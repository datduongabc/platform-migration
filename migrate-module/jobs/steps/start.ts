// SERVER ONLY
//
// Job step: 'start'
// 1. Atomically claim the meeting (pending/failed → processing).
//    On restart (meeting already 'processing'): detect and continue.
// 2. Download audio from storage → temp file.
// 3. ffprobe → estimate audio duration for quota pre-flight.
// 4. QUO-02 quota reserve (dedup: gen:<id>:reserve — idempotent on restart).
//    'insufficient' → terminal failure; no retry makes sense.
// 5. Transcode to MP3 via ffmpeg if available (better Speechmatics compat).
// 6. Submit to Speechmatics Batch API → jobId.
// 7. Update job payload and advance to 'transcribe_poll'.
// 8. Cleanup temp files (always, even on error).

import { writeFile, unlink, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, extname } from 'node:path'
import { randomUUID } from 'node:crypto'

import { log } from '@/lib/logger'
import { logActivity } from '@/lib/activity/logActivity'
import { createServerClient } from '@/lib/supabase/server'
import { getObjectBytes } from '@/lib/storage'
import { isFfmpegAvailable, transcodeForGemini } from '@/lib/audio/transcode'
import { getAudioDurationSeconds } from '@/lib/audio/ffprobe'
import { submitJob } from '@/lib/speechmatics/transcribe'
import { applyQuotaMovement } from '@/lib/quota/applyQuotaMovement'
import type { JobRow, JobPayload } from '../types'

const FIRST_POLL_DELAY_MS = 5_000

export async function runStart(job: JobRow): Promise<void> {
  const db = createServerClient()
  const meetingId = job.meeting_id

  // ── Atomic claim ────────────────────────────────────────────────────────────
  // Same guard as the old processMeeting() — only runs on pending/failed.
  const { data: claimed } = await db
    .from('meetings')
    .update({ status: 'processing', error_message: null })
    .in('status', ['pending', 'failed'])
    .eq('id', meetingId)
    .select('id, audio_path, storage_provider, duration_seconds, started_at, user_id')
    .maybeSingle()

  let meeting = claimed

  if (!meeting) {
    // Restart case: sweeper reset the job to 'queued' but the meeting is already
    // 'processing' from the previous attempt. Detect and continue from it.
    const { data: processing } = await db
      .from('meetings')
      .select('id, audio_path, storage_provider, duration_seconds, started_at, user_id')
      .eq('id', meetingId)
      .eq('status', 'processing')
      .maybeSingle()

    if (!processing) {
      // Meeting finished (done/missing) while this job was queued — nothing to do.
      log(`[jobs/start] ${meetingId}: meeting not claimable (done or missing), marking job done`)
      await db.from('jobs')
        .update({ status: 'done', locked_at: null, locked_by: null })
        .eq('id', job.id)
      return
    }
    meeting = processing
    log(`[jobs/start] ${meetingId}: restart detected — meeting already in processing, continuing`)
  }

  const userId = meeting.user_id
  const audioPath = meeting.audio_path
  if (!audioPath) throw new Error('Meeting has no audio_path — cannot process')

  let tmpAudioPath: string | null = null
  let tmpTranscodeDir: string | null = null

  try {
    // ── Download audio ───────────────────────────────────────────────────────
    log(`[jobs/start] ${meetingId}: downloading audio from storage`)
    const audioBuffer = await getObjectBytes({
      key: audioPath,
      provider: meeting.storage_provider,
    })
    const ext = extname(audioPath) || '.webm'
    tmpAudioPath = join(tmpdir(), `job-${randomUUID()}${ext}`)
    await writeFile(tmpAudioPath, audioBuffer)
    log(`[jobs/start] ${meetingId}: wrote ${audioBuffer.length} bytes to ${tmpAudioPath}`)

    // ── QUO-02: quota reserve ────────────────────────────────────────────────
    let estimateSeconds = 0
    let reserveDone = false

    if (userId) {
      const probed = await getAudioDurationSeconds(tmpAudioPath).catch(() => 0)
      estimateSeconds = Math.ceil(probed > 0 ? probed : (meeting.duration_seconds ?? 0))

      if (estimateSeconds > 0) {
        const reserve = await applyQuotaMovement({
          userId,
          deltaAudioSeconds: -estimateSeconds,
          deltaAgentQueries: 0,
          reason: 'generate',
          dedupKey: `gen:${meetingId}:reserve`,
          allowOverdraw: false,
          meetingId,
          metadata: { estimate_seconds: estimateSeconds },
        })

        if (reserve.status === 'insufficient') {
          const msg =
            `QUOTA_BLOCKED: Insufficient audio balance. ` +
            `Required: ${estimateSeconds}s, remaining: ${reserve.audioRemaining}s.`
          await db.from('meetings')
            .update({ status: 'failed', error_message: msg })
            .eq('id', meetingId)
          await db.from('jobs')
            .update({ status: 'failed', last_error: msg, locked_at: null, locked_by: null })
            .eq('id', job.id)
          logActivity({
            userId,
            eventType: 'processing_failed',
            meetingId,
            metadata: { reason: 'quota_blocked', required_seconds: estimateSeconds, remaining_seconds: reserve.audioRemaining },
          })
          return
        }
        // 'applied' or 'already_applied' (idempotent on restart) — proceed.
        reserveDone = true
      }
    }

    // ── Transcode ────────────────────────────────────────────────────────────
    let jobAudioPath = tmpAudioPath
    const ffmpegAvailable = await isFfmpegAvailable()
    if (ffmpegAvailable && !tmpAudioPath.endsWith('.mp3')) {
      tmpTranscodeDir = join(tmpdir(), `sm-transcode-${randomUUID()}`)
      try {
        jobAudioPath = await transcodeForGemini(tmpAudioPath, tmpTranscodeDir)
        log(`[jobs/start] ${meetingId}: transcoded to MP3`)
      } catch (e) {
        log(`[jobs/start] ${meetingId}: ffmpeg transcode failed, using original — ${e}`)
        jobAudioPath = tmpAudioPath
        tmpTranscodeDir = null
      }
    }

    // ── Submit to Speechmatics ───────────────────────────────────────────────
    const speakerCount = job.payload.speaker_count
    const speechmaticsJobId = await submitJob(jobAudioPath, speakerCount)
    log(`[jobs/start] ${meetingId}: Speechmatics job submitted: ${speechmaticsJobId}`)

    // ── Advance to transcribe_poll ───────────────────────────────────────────
    // Store all durable state needed by later steps in the payload.
    const nextPayload: JobPayload = {
      ...job.payload,
      user_id: userId,
      estimate_seconds: estimateSeconds,
      reserve_done: reserveDone,
      transcription_settled: false,
      speechmatics_job_id: speechmaticsJobId,
    }
    await db.from('jobs').update({
      step: 'transcribe_poll',
      status: 'queued',
      run_after: new Date(Date.now() + FIRST_POLL_DELAY_MS).toISOString(),
      payload: nextPayload as Record<string, unknown>,
      locked_at: null,
      locked_by: null,
    }).eq('id', job.id)

  } finally {
    if (tmpTranscodeDir) rm(tmpTranscodeDir, { recursive: true }).catch(() => {})
    if (tmpAudioPath) unlink(tmpAudioPath).catch(() => {})
  }
}
