// SERVER ONLY
//
// Job step: 'transcribe_poll'
// Checks Speechmatics job status ONCE and returns immediately — no loop.
// The worker reschedules this step via run_after until the job is done.
//
// Outcomes:
//   'running'  → reschedule (status='queued', run_after += 5s). No attempt consumed.
//   'done'     → fetch transcript, settle quota, delete old segments (idempotency),
//                insert new segments, advance to 'analyse'.
//   'rejected' with LANG_DETECT_FAIL (first time) → re-download audio, resubmit
//                with language='en', reschedule. No attempt consumed.
//   'rejected' (other) | 'deleted' → throw; worker handles retry/failure.

import { writeFile, unlink, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join, extname } from 'node:path'
import { randomUUID } from 'node:crypto'

import { log } from '@/lib/logger'
import { logActivity } from '@/lib/activity/logActivity'
import { createServerClient } from '@/lib/supabase/server'
import { getObjectBytes } from '@/lib/storage'
import { isFfmpegAvailable, transcodeForGemini } from '@/lib/audio/transcode'
import {
  submitJob,
  checkSpeechmaticsJob,
  fetchSpeechmaticsTranscript,
} from '@/lib/speechmatics/transcribe'
import { applyQuotaMovement } from '@/lib/quota/applyQuotaMovement'
import type { JobRow, JobPayload } from '../types'

const POLL_INTERVAL_MS = 5_000

// Speechmatics error text for auto-detect failure — same constant as transcribe.ts.
const LANG_DETECT_FAIL = 'Language identification could not identify'

export async function runTranscribePoll(job: JobRow): Promise<void> {
  const db = createServerClient()
  const meetingId = job.meeting_id
  const payload = job.payload

  const speechmaticsJobId = payload.speechmatics_job_id
  if (!speechmaticsJobId) throw new Error('transcribe_poll: missing speechmatics_job_id in payload')

  log(`[jobs/transcribe_poll] ${meetingId}: checking job ${speechmaticsJobId}`)
  const { status, errors } = await checkSpeechmaticsJob(speechmaticsJobId)
  log(`[jobs/transcribe_poll] ${meetingId}: Speechmatics status=${status}`)

  // ── Case A: Still running ─────────────────────────────────────────────────
  if (status === 'running') {
    // Normal polling wait — reschedule without consuming an attempt.
    await db.from('jobs').update({
      status: 'queued',
      run_after: new Date(Date.now() + POLL_INTERVAL_MS).toISOString(),
      locked_at: null,
      locked_by: null,
    }).eq('id', job.id)
    return
  }

  // ── Case B: Done ──────────────────────────────────────────────────────────
  if (status === 'done') {
    const ctx = {
      meetingId,
      userId: payload.user_id ?? undefined,
      speakerCount: payload.speaker_count,
    }
    const { transcript, audioSeconds } = await fetchSpeechmaticsTranscript(speechmaticsJobId, ctx)
    log(`[jobs/transcribe_poll] ${meetingId}: transcript done — ${transcript.segments.length} segments, language=${transcript.language}`)

    // QUO-02: settle reservation (estimate - real = refund or overage).
    // Dedup key ensures this runs at most once even on retries.
    const userId = payload.user_id
    const estimateSeconds = payload.estimate_seconds ?? 0
    if (userId && estimateSeconds > 0) {
      await applyQuotaMovement({
        userId,
        deltaAudioSeconds: estimateSeconds - audioSeconds,
        deltaAgentQueries: 0,
        reason: 'generate',
        dedupKey: `gen:${meetingId}:settle`,
        allowOverdraw: true,
        meetingId,
        metadata: { estimate_seconds: estimateSeconds, real_seconds: audioSeconds },
      })
    }

    // Mark quota as settled in payload before any DB write that could fail.
    const settledPayload: JobPayload = { ...payload, transcription_settled: true }

    // REL-03: delete any segments from a prior run before inserting.
    // transcript_chunks FK to meeting_id directly — also delete explicitly.
    await Promise.all([
      db.from('transcript_chunks').delete().eq('meeting_id', meetingId),
      db.from('transcript_segments').delete().eq('meeting_id', meetingId),
    ])

    // Empty transcript: audio was silent or unrecognised.
    if (transcript.segments.length === 0) {
      await db.from('meetings').update({
        status: 'done',
        summary: 'No speech detected in this recording.',
        notes: '',
        language: transcript.language,
      }).eq('id', meetingId)
      await db.from('jobs').update({
        status: 'done',
        payload: settledPayload as Record<string, unknown>,
        locked_at: null,
        locked_by: null,
      }).eq('id', job.id)
      log(`[jobs/transcribe_poll] ${meetingId}: done (empty transcript — no speech detected)`)
      if (userId) {
        logActivity({ userId, eventType: 'processing_done', meetingId, metadata: { empty_transcript: true } })
      }
      return
    }

    // Insert transcript segments.
    const segmentRows = transcript.segments.map((s, idx) => ({
      meeting_id: meetingId,
      segment_index: idx,
      speaker: s.speaker,
      start_ms: s.start_ms,
      end_ms: s.end_ms,
      text: s.text,
      confidence: s.confidence ?? null,
    }))
    const { error: segErr } = await db.from('transcript_segments').insert(segmentRows)
    if (segErr) throw new Error(`transcript_segments insert: ${segErr.message}`)

    await db.from('meetings').update({ language: transcript.language }).eq('id', meetingId)

    // Advance to 'analyse'.
    await db.from('jobs').update({
      step: 'analyse',
      status: 'queued',
      run_after: new Date().toISOString(),
      payload: settledPayload as Record<string, unknown>,
      locked_at: null,
      locked_by: null,
    }).eq('id', job.id)
    return
  }

  // ── Case C: Rejected — language auto-detect failure → retry with 'en' ────
  if (status === 'rejected') {
    const errMsg = JSON.stringify(errors ?? [])
    const isLangFail = errMsg.includes(LANG_DETECT_FAIL)

    if (isLangFail && !payload.lang_retry) {
      log(`[jobs/transcribe_poll] ${meetingId}: language auto-detect rejected — retrying with language=en`)

      // Re-download the audio from storage and resubmit with explicit language.
      const { data: mtg } = await db
        .from('meetings')
        .select('audio_path, storage_provider')
        .eq('id', meetingId)
        .maybeSingle()

      if (!mtg?.audio_path) throw new Error('transcribe_poll: cannot retry lang — missing audio_path')

      let tmpAudioPath: string | null = null
      let tmpTranscodeDir: string | null = null

      try {
        const audioBuffer = await getObjectBytes({ key: mtg.audio_path, provider: mtg.storage_provider })
        const ext = extname(mtg.audio_path) || '.webm'
        tmpAudioPath = join(tmpdir(), `job-lang-${randomUUID()}${ext}`)
        await writeFile(tmpAudioPath, audioBuffer)

        let jobAudioPath = tmpAudioPath
        const ffmpegAvailable = await isFfmpegAvailable()
        if (ffmpegAvailable && !tmpAudioPath.endsWith('.mp3')) {
          tmpTranscodeDir = join(tmpdir(), `sm-lang-${randomUUID()}`)
          try {
            jobAudioPath = await transcodeForGemini(tmpAudioPath, tmpTranscodeDir)
          } catch {
            jobAudioPath = tmpAudioPath
            tmpTranscodeDir = null
          }
        }

        const newJobId = await submitJob(jobAudioPath, payload.speaker_count, 'en')
        log(`[jobs/transcribe_poll] ${meetingId}: resubmitted with language=en: ${newJobId}`)

        const retryPayload: JobPayload = {
          ...payload,
          speechmatics_job_id: newJobId,
          lang_retry: true,
        }
        // Reschedule — no attempt consumed (this is an expected recovery path).
        await db.from('jobs').update({
          status: 'queued',
          run_after: new Date(Date.now() + POLL_INTERVAL_MS).toISOString(),
          payload: retryPayload as Record<string, unknown>,
          locked_at: null,
          locked_by: null,
        }).eq('id', job.id)
        return
      } finally {
        if (tmpTranscodeDir) rm(tmpTranscodeDir, { recursive: true }).catch(() => {})
        if (tmpAudioPath) unlink(tmpAudioPath).catch(() => {})
      }
    }

    // Non-recoverable rejection.
    throw new Error(`Speechmatics job ${speechmaticsJobId} rejected: ${errMsg}`)
  }

  // ── Case D: Deleted ───────────────────────────────────────────────────────
  throw new Error(`Speechmatics job ${speechmaticsJobId} was unexpectedly deleted`)
}
