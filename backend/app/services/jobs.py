import asyncio
import json
import logging
import math
import os
import random
import shutil
import tempfile
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_factory
from app.services.audio import get_audio_duration_seconds, transcode_to_mp3
from app.services.gemini import analyze_transcript, generate_embeddings
from app.services.quota import (
    QuotaMovementParams,
    apply_quota_movement,
    reconcile_wallets,
)
from app.services.rag import chunk_segments
from app.services.speechmatics import (
    fetch_speechmatics_transcript,
    get_speechmatics_job_status,
    submit_speechmatics_job,
)

logger = logging.getLogger(__name__)


async def _download_audio(audio_path: str) -> bytes:
    """
    Download audio file from storage (HTTP URL, local file, or Supabase Storage).
    """
    # 1. If it's a full URL
    if audio_path.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.get(audio_path)
            res.raise_for_status()
            return res.content

    # 2. If it's a local file path
    if os.path.exists(audio_path):

        def _read_local():
            with open(audio_path, "rb") as f:
                return f.read()

        return await asyncio.to_thread(_read_local)

    # 3. Try to construct Supabase Storage URL from DATABASE_URL
    project_ref = None
    if (
        "supabase.com" in settings.DATABASE_URL
        or "supabase.co" in settings.DATABASE_URL
    ):
        try:
            parsed = urllib.parse.urlparse(settings.DATABASE_URL)
            username = parsed.username
            if username and "postgres." in username:
                project_ref = username.split("postgres.")[1]
        except Exception:
            pass

    if project_ref:
        path_clean = audio_path
        if path_clean.startswith("recordings/"):
            path_clean = path_clean[len("recordings/") :]

        encoded_path = urllib.parse.quote(path_clean)
        supabase_url = f"https://{project_ref}.supabase.co/storage/v1/object/public/recordings/{encoded_path}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.get(supabase_url)
            if res.status_code == 200:
                return res.content

    raise FileNotFoundError(
        f"Audio file not found or could not be downloaded: {audio_path}"
    )


def jittered_backoff(attempts: int) -> float:
    """
    Retry backoff: 2s, 4s, 8s ... capped at 5 min; ±25% jitter.
    """
    BASE_BACKOFF_SECONDS = 2.0
    MAX_BACKOFF_SECONDS = 300.0
    exp = min(BASE_BACKOFF_SECONDS * (2 ** (attempts - 1)), MAX_BACKOFF_SECONDS)
    return exp * (0.75 + random.random() * 0.5)


def is_terminal_error(err: Exception) -> bool:
    """
    Terminal errors should NOT be retried — they indicate bad configuration or data issues.
    """
    err_msg = str(err)
    if "401" in err_msg or "API_KEY_INVALID" in err_msg:
        return True
    if isinstance(
        err, (ValueError, KeyError, TypeError, AttributeError, AssertionError)
    ):
        return True
    return False


async def claim_next_job(db: AsyncSession, worker_id: str) -> Optional[Dict[str, Any]]:
    """
    Claim the next queued job via claim_next_job RPC or SQL query with FOR UPDATE SKIP LOCKED.
    """
    try:
        res = await db.execute(
            text("SELECT * FROM public.claim_next_job(:worker_id)"),
            {"worker_id": worker_id},
        )
        row = res.mappings().first()
        if row:
            return dict(row)
    except Exception:
        pass

    # Fallback SQL FOR UPDATE SKIP LOCKED
    sql_fallback = text("""
        UPDATE public.jobs
        SET status = 'running', locked_at = NOW(), locked_by = :worker_id
        WHERE id = (
            SELECT id FROM public.jobs
            WHERE status = 'queued' AND run_after <= NOW()
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        RETURNING *
    """)
    res = await db.execute(sql_fallback, {"worker_id": worker_id})
    row = res.mappings().first()
    if row:
        await db.commit()
        return dict(row)

    return None


async def execute_job_step(db: AsyncSession, job: Dict[str, Any]) -> None:
    job_id = str(job["id"])
    meeting_id = str(job["meeting_id"])
    step = job["step"]
    payload = job.get("payload") or {}

    if step == "start":
        await _run_start_step(db, job_id, meeting_id, payload)
    elif step == "transcribe_poll":
        await _run_transcribe_poll_step(db, job_id, meeting_id, payload)
    elif step == "analyse":
        await _run_analyse_step(db, job_id, meeting_id, payload)
    elif step == "embed":
        await _run_embed_step(db, job_id, meeting_id, payload)
    else:
        raise ValueError(f"Unknown job step: {step}")


async def _run_start_step(
    db: AsyncSession, job_id: str, meeting_id: str, payload: Dict[str, Any]
) -> None:
    # 1. Update meeting status to processing (atomic claim)
    await db.execute(
        text("""
            UPDATE public.meetings
            SET status = 'processing', error_message = NULL
            WHERE id = :id AND status IN ('pending', 'failed')
        """),
        {"id": meeting_id},
    )
    await db.commit()

    res = await db.execute(
        text(
            "SELECT id, user_id, audio_path, storage_provider, duration_seconds FROM public.meetings WHERE id = :id"
        ),
        {"id": meeting_id},
    )
    meeting = res.mappings().first()
    if not meeting:
        # Restart case: meeting is already processing
        res = await db.execute(
            text(
                "SELECT id, user_id, audio_path, storage_provider, duration_seconds FROM public.meetings WHERE id = :id AND status = 'processing'"
            ),
            {"id": meeting_id},
        )
        meeting = res.mappings().first()
        if not meeting:
            logger.info(
                f"[jobs/start] {meeting_id}: meeting not claimable, marking job done"
            )
            await db.execute(
                text(
                    "UPDATE public.jobs SET status = 'done', locked_at = NULL, locked_by = NULL WHERE id = :id"
                ),
                {"id": job_id},
            )
            await db.commit()
            return
        logger.info(
            f"[jobs/start] {meeting_id}: restart detected — meeting already in processing, continuing"
        )

    audio_path = meeting["audio_path"]
    user_id = str(meeting["user_id"]) if meeting["user_id"] else None
    if not audio_path:
        raise ValueError("Meeting has no audio_path — cannot process")

    tmp_audio_path = None
    tmp_transcode_dir = None

    try:
        # Download audio
        logger.info(f"[jobs/start] {meeting_id}: downloading audio from storage")
        audio_bytes = await _download_audio(audio_path)
        ext = os.path.splitext(audio_path)[1] or ".webm"

        fd, tmp_audio_path = tempfile.mkstemp(suffix=ext)
        os.close(fd)

        def _write_temp():
            with open(tmp_audio_path, "wb") as f:
                f.write(audio_bytes)

        await asyncio.to_thread(_write_temp)
        logger.info(
            f"[jobs/start] {meeting_id}: wrote {len(audio_bytes)} bytes to {tmp_audio_path}"
        )

        # Quota Pre-flight
        estimate_seconds = 0
        reserve_done = False

        if user_id:
            try:
                probed = await get_audio_duration_seconds(tmp_audio_path)
            except Exception:
                probed = 0
            estimate_seconds = math.ceil(
                probed if probed > 0 else (meeting["duration_seconds"] or 0)
            )

            if estimate_seconds > 0:
                reserve = await apply_quota_movement(
                    db,
                    QuotaMovementParams(
                        user_id=user_id,
                        delta_audio_seconds=-estimate_seconds,
                        delta_agent_queries=0,
                        reason="generate",
                        dedup_key=f"gen:{meeting_id}:reserve",
                        allow_overdraw=False,
                        meeting_id=meeting_id,
                        metadata={"estimate_seconds": estimate_seconds},
                    ),
                )

                if reserve.status == "insufficient":
                    msg = (
                        f"QUOTA_BLOCKED: Insufficient audio balance. "
                        f"Required: {estimate_seconds}s, remaining: {reserve.audio_remaining}s."
                    )
                    await db.execute(
                        text(
                            "UPDATE public.meetings SET status = 'failed', error_message = :msg WHERE id = :id"
                        ),
                        {"msg": msg, "id": meeting_id},
                    )
                    await db.execute(
                        text(
                            "UPDATE public.jobs SET status = 'failed', last_error = :msg, locked_at = NULL, locked_by = NULL WHERE id = :id"
                        ),
                        {"msg": msg, "id": job_id},
                    )
                    await db.commit()

                    # Log activity
                    await db.execute(
                        text("""
                            INSERT INTO public.activity_logs (id, user_id, event_type, meeting_id, metadata, created_at)
                            VALUES (:id, :user_id, 'processing_failed', :meeting_id, :metadata, NOW())
                        """),
                        {
                            "id": str(uuid.uuid4()),
                            "user_id": user_id,
                            "meeting_id": meeting_id,
                            "metadata": json.dumps(
                                {
                                    "reason": "quota_blocked",
                                    "required_seconds": estimate_seconds,
                                    "remaining_seconds": reserve.audio_remaining,
                                }
                            ),
                        },
                    )
                    await db.commit()
                    return
                reserve_done = True

        # Transcode to MP3
        job_audio_path = tmp_audio_path
        if not tmp_audio_path.lower().endswith(".mp3"):
            tmp_transcode_dir = tempfile.mkdtemp(prefix="sm-transcode-")
            try:
                job_audio_path = await transcode_to_mp3(
                    tmp_audio_path, tmp_transcode_dir
                )
                logger.info(f"[jobs/start] {meeting_id}: transcoded to MP3")
            except Exception as e:
                logger.warning(
                    f"[jobs/start] {meeting_id}: ffmpeg transcode failed, using original — {e}"
                )
                job_audio_path = tmp_audio_path
                if os.path.exists(tmp_transcode_dir):
                    shutil.rmtree(tmp_transcode_dir, ignore_errors=True)
                tmp_transcode_dir = None

        # Submit to Speechmatics
        speaker_count = payload.get("speaker_count")
        speechmatics_job_id = await asyncio.to_thread(
            submit_speechmatics_job, job_audio_path, speaker_count
        )
        logger.info(
            f"[jobs/start] {meeting_id}: Speechmatics job submitted: {speechmatics_job_id}"
        )

        # Advance to transcribe_poll
        next_payload = {
            **payload,
            "user_id": user_id,
            "estimate_seconds": estimate_seconds,
            "reserve_done": reserve_done,
            "transcription_settled": False,
            "speechmatics_job_id": speechmatics_job_id,
        }

        run_after = datetime.now(timezone.utc) + timedelta(seconds=5)

        await db.execute(
            text("""
                UPDATE public.jobs
                SET step = 'transcribe_poll', status = 'queued',
                    run_after = :run_after, payload = :payload,
                    locked_at = NULL, locked_by = NULL
                WHERE id = :id
            """),
            {
                "run_after": run_after,
                "payload": json.dumps(next_payload),
                "id": job_id,
            },
        )
        await db.commit()

    finally:
        if tmp_transcode_dir and os.path.exists(tmp_transcode_dir):
            try:
                shutil.rmtree(tmp_transcode_dir, ignore_errors=True)
            except Exception:
                pass
        if tmp_audio_path and os.path.exists(tmp_audio_path):
            try:
                os.unlink(tmp_audio_path)
            except Exception:
                pass


async def _run_transcribe_poll_step(
    db: AsyncSession, job_id: str, meeting_id: str, payload: Dict[str, Any]
) -> None:
    speechmatics_job_id = payload.get("speechmatics_job_id")
    if not speechmatics_job_id:
        raise ValueError("transcribe_poll: missing speechmatics_job_id in payload")

    logger.info(
        f"[jobs/transcribe_poll] {meeting_id}: checking job {speechmatics_job_id}"
    )

    status_data = await asyncio.to_thread(
        get_speechmatics_job_status, speechmatics_job_id
    )
    status = status_data.get("job", {}).get("status")
    errors = status_data.get("job", {}).get("errors", [])
    logger.info(f"[jobs/transcribe_poll] {meeting_id}: Speechmatics status={status}")

    # Case A: Still running
    if status == "running":
        run_after = datetime.now(timezone.utc) + timedelta(seconds=5)
        await db.execute(
            text("""
                UPDATE public.jobs
                SET status = 'queued', run_after = :run_after,
                    locked_at = NULL, locked_by = NULL
                WHERE id = :id
            """),
            {"run_after": run_after, "id": job_id},
        )
        await db.commit()
        return

    # Case B: Done
    if status == "done":
        transcript_data = await asyncio.to_thread(
            fetch_speechmatics_transcript, speechmatics_job_id
        )
        transcript = transcript_data["transcript"]
        audio_seconds = transcript_data["audio_seconds"]
        logger.info(
            f"[jobs/transcribe_poll] {meeting_id}: transcript done — {len(transcript['segments'])} segments, language={transcript['language']}"
        )

        # Settle quota
        user_id = payload.get("user_id")
        estimate_seconds = payload.get("estimate_seconds") or 0
        if user_id and estimate_seconds > 0:
            await apply_quota_movement(
                db,
                QuotaMovementParams(
                    user_id=user_id,
                    delta_audio_seconds=estimate_seconds - audio_seconds,
                    delta_agent_queries=0,
                    reason="generate",
                    dedup_key=f"gen:{meeting_id}:settle",
                    allow_overdraw=True,
                    meeting_id=meeting_id,
                    metadata={
                        "estimate_seconds": estimate_seconds,
                        "real_seconds": audio_seconds,
                    },
                ),
            )

        settled_payload = {**payload, "transcription_settled": True}

        # Clear prior segments & chunks to avoid duplicates (REL-03)
        await db.execute(
            text("DELETE FROM public.transcript_chunks WHERE meeting_id = :id"),
            {"id": meeting_id},
        )
        await db.execute(
            text("DELETE FROM public.transcript_segments WHERE meeting_id = :id"),
            {"id": meeting_id},
        )
        await db.commit()

        # Empty transcript: audio was silent
        if not transcript["segments"]:
            await db.execute(
                text("""
                    UPDATE public.meetings
                    SET status = 'done', summary = 'No speech detected in this recording.',
                        notes_markdown = '', language = :lang
                    WHERE id = :id
                """),
                {"lang": transcript["language"], "id": meeting_id},
            )
            await db.execute(
                text("""
                    UPDATE public.jobs
                    SET status = 'done', payload = :payload,
                        locked_at = NULL, locked_by = NULL
                    WHERE id = :id
                """),
                {"payload": json.dumps(settled_payload), "id": job_id},
            )
            await db.commit()

            if user_id:
                await db.execute(
                    text("""
                        INSERT INTO public.activity_logs (id, user_id, event_type, meeting_id, metadata, created_at)
                        VALUES (:id, :user_id, 'processing_done', :meeting_id, :metadata, NOW())
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "user_id": user_id,
                        "meeting_id": meeting_id,
                        "metadata": json.dumps({"empty_transcript": True}),
                    },
                )
                await db.commit()
            return

        # Insert segments
        for idx, s in enumerate(transcript["segments"]):
            await db.execute(
                text("""
                    INSERT INTO public.transcript_segments
                    (id, meeting_id, segment_index, speaker, start_ms, end_ms, text, confidence)
                    VALUES (:id, :meeting_id, :segment_index, :speaker, :start_ms, :end_ms, :text, :confidence)
                """),
                {
                    "id": str(uuid.uuid4()),
                    "meeting_id": meeting_id,
                    "segment_index": idx,
                    "speaker": s["speaker"],
                    "start_ms": s["start_ms"],
                    "end_ms": s["end_ms"],
                    "text": s["text"],
                    "confidence": s["confidence"],
                },
            )

        # Update language
        await db.execute(
            text("UPDATE public.meetings SET language = :lang WHERE id = :id"),
            {"lang": transcript["language"], "id": meeting_id},
        )

        # Advance to analyse
        await db.execute(
            text("""
                UPDATE public.jobs
                SET step = 'analyse', status = 'queued', run_after = NOW(),
                    payload = :payload, locked_at = NULL, locked_by = NULL
                WHERE id = :id
            """),
            {"payload": json.dumps(settled_payload), "id": job_id},
        )
        await db.commit()
        return

    # Case C: Rejected
    if status == "rejected":
        err_msg = json.dumps(errors or [])
        LANG_DETECT_FAIL = "Language identification could not identify"
        is_lang_fail = LANG_DETECT_FAIL in err_msg

        if is_lang_fail and not payload.get("lang_retry"):
            logger.info(
                f"[jobs/transcribe_poll] {meeting_id}: language auto-detect rejected — retrying with language=en"
            )

            # Re-download and resubmit
            res = await db.execute(
                text("SELECT audio_path FROM public.meetings WHERE id = :id"),
                {"id": meeting_id},
            )
            mtg = res.mappings().first()
            if not mtg or not mtg["audio_path"]:
                raise ValueError(
                    "transcribe_poll: cannot retry lang — missing audio_path"
                )

            tmp_audio_path = None
            tmp_transcode_dir = None

            try:
                audio_bytes = await _download_audio(mtg["audio_path"])
                ext = os.path.splitext(mtg["audio_path"])[1] or ".webm"

                fd, tmp_audio_path = tempfile.mkstemp(suffix=ext)
                os.close(fd)

                def _write_temp():
                    with open(tmp_audio_path, "wb") as f:
                        f.write(audio_bytes)

                await asyncio.to_thread(_write_temp)

                job_audio_path = tmp_audio_path
                if not tmp_audio_path.lower().endswith(".mp3"):
                    tmp_transcode_dir = tempfile.mkdtemp(prefix="sm-lang-")
                    try:
                        job_audio_path = await transcode_to_mp3(
                            tmp_audio_path, tmp_transcode_dir
                        )
                    except Exception:
                        job_audio_path = tmp_audio_path
                        if os.path.exists(tmp_transcode_dir):
                            shutil.rmtree(tmp_transcode_dir, ignore_errors=True)
                        tmp_transcode_dir = None

                new_job_id = await asyncio.to_thread(
                    submit_speechmatics_job,
                    job_audio_path,
                    payload.get("speaker_count"),
                    "en",
                )
                logger.info(
                    f"[jobs/transcribe_poll] {meeting_id}: resubmitted with language=en: {new_job_id}"
                )

                retry_payload = {
                    **payload,
                    "speechmatics_job_id": new_job_id,
                    "lang_retry": True,
                }

                run_after = datetime.now(timezone.utc) + timedelta(seconds=5)
                await db.execute(
                    text("""
                        UPDATE public.jobs
                        SET status = 'queued', run_after = :run_after,
                            payload = :payload, locked_at = NULL, locked_by = NULL
                        WHERE id = :id
                    """),
                    {
                        "run_after": run_after,
                        "payload": json.dumps(retry_payload),
                        "id": job_id,
                    },
                )
                await db.commit()
                return

            finally:
                if tmp_transcode_dir and os.path.exists(tmp_transcode_dir):
                    try:
                        shutil.rmtree(tmp_transcode_dir, ignore_errors=True)
                    except Exception:
                        pass
                if tmp_audio_path and os.path.exists(tmp_audio_path):
                    try:
                        os.unlink(tmp_audio_path)
                    except Exception:
                        pass

        raise RuntimeError(
            f"Speechmatics job {speechmatics_job_id} rejected: {err_msg}"
        )

    # Case D: Deleted / Other
    raise RuntimeError(
        f"Speechmatics job {speechmatics_job_id} was unexpectedly in status: {status}"
    )


async def _run_analyse_step(
    db: AsyncSession, job_id: str, meeting_id: str, payload: Dict[str, Any]
) -> None:
    # 1. Load segments from DB
    res = await db.execute(
        text("""
            SELECT id, segment_index, speaker, start_ms, end_ms, text, confidence
            FROM public.transcript_segments
            WHERE meeting_id = :meeting_id
            ORDER BY segment_index ASC
        """),
        {"meeting_id": meeting_id},
    )
    seg_rows = res.mappings().all()
    if not seg_rows:
        raise ValueError(
            f"analyse: no transcript_segments found for meeting {meeting_id}"
        )

    segment_id_by_index = {r["segment_index"]: str(r["id"]) for r in seg_rows}

    # Rebuild segments list for analyze_transcript
    segments = [
        {
            "speaker": r["speaker"] or "",
            "start_ms": r["start_ms"],
            "end_ms": r["end_ms"],
            "text": r["text"],
            "confidence": r["confidence"],
        }
        for r in seg_rows
    ]

    # Fetch meeting metadata (started_at)
    res_mtg = await db.execute(
        text("SELECT started_at FROM public.meetings WHERE id = :id"),
        {"id": meeting_id},
    )
    meeting = res_mtg.mappings().first()
    started_at = (
        meeting["started_at"].isoformat() if meeting and meeting["started_at"] else None
    )

    # Call Gemini Flash analysis
    logger.info(
        f"[jobs/analyse] {meeting_id}: calling Gemini with {len(seg_rows)} segments"
    )
    analysis = await analyze_transcript(segments, meeting_date=started_at)
    logger.info(
        f"[jobs/analyse] {meeting_id}: done — {len(analysis.todos)} todos, {len(analysis.calendar_suggestions)} suggestions"
    )

    if not analysis.summary and not analysis.notes_markdown:
        raise ValueError("Gemini analysis returned empty summary and notes.")

    # Write summary + notes to meeting
    await db.execute(
        text("""
            UPDATE public.meetings
            SET summary = :summary, notes_markdown = :notes
            WHERE id = :id
        """),
        {
            "summary": analysis.summary,
            "notes": analysis.notes_markdown,
            "id": meeting_id,
        },
    )

    # REL-03: clear prior todos & calendar suggestions to prevent duplicates
    await db.execute(
        text("DELETE FROM public.todos WHERE meeting_id = :id"), {"id": meeting_id}
    )
    await db.execute(
        text("DELETE FROM public.calendar_suggestions WHERE meeting_id = :id"),
        {"id": meeting_id},
    )
    await db.commit()

    # Insert todos
    for t in analysis.todos:
        source_segment_id = None
        if t.source_segment_index is not None:
            source_segment_id = segment_id_by_index.get(t.source_segment_index)

        await db.execute(
            text("""
                INSERT INTO public.todos
                (id, meeting_id, content, assignee, due_date, status, source_segment_id)
                VALUES (:id, :meeting_id, :content, :assignee, :due_date, 'open', :source_segment_id)
            """),
            {
                "id": str(uuid.uuid4()),
                "meeting_id": meeting_id,
                "content": t.content,
                "assignee": t.assignee,
                "due_date": t.due_date,
                "source_segment_id": source_segment_id,
            },
        )

    # Insert calendar suggestions
    for c in analysis.calendar_suggestions:
        source_segment_id = None
        if c.source_segment_index is not None:
            source_segment_id = segment_id_by_index.get(c.source_segment_index)

        await db.execute(
            text("""
                INSERT INTO public.calendar_suggestions
                (id, meeting_id, title, proposed_at, raw_mention, dismissed, source_segment_id)
                VALUES (:id, :meeting_id, :title, :proposed_at, :raw_mention, FALSE, :source_segment_id)
            """),
            {
                "id": str(uuid.uuid4()),
                "meeting_id": meeting_id,
                "title": c.title,
                "proposed_at": c.proposed_at,
                "raw_mention": c.raw_mention,
                "source_segment_id": source_segment_id,
            },
        )

    # Advance to embed
    await db.execute(
        text("""
            UPDATE public.jobs
            SET step = 'embed', status = 'queued', run_after = NOW(),
                locked_at = NULL, locked_by = NULL
            WHERE id = :id
        """),
        {"id": job_id},
    )
    await db.commit()


async def _run_embed_step(
    db: AsyncSession, job_id: str, meeting_id: str, payload: Dict[str, Any]
) -> None:
    # 1. Load segments
    res = await db.execute(
        text("""
            SELECT speaker, start_ms, end_ms, text, confidence
            FROM public.transcript_segments
            WHERE meeting_id = :meeting_id
            ORDER BY segment_index ASC
        """),
        {"meeting_id": meeting_id},
    )
    seg_rows = res.mappings().all()
    if not seg_rows:
        raise ValueError(
            f"embed: no transcript_segments found for meeting {meeting_id}"
        )

    segments = [
        {
            "speaker": r["speaker"] or "",
            "start_ms": r["start_ms"],
            "end_ms": r["end_ms"],
            "text": r["text"],
            "confidence": r["confidence"],
        }
        for r in seg_rows
    ]

    # Chunk segments
    chunks = chunk_segments(segments)
    logger.info(f"[jobs/embed] {meeting_id}: {len(chunks)} RAG chunks, embedding…")

    if chunks:
        # Call Gemini embeddings
        vectors = await generate_embeddings([c["content"] for c in chunks])

        # REL-03: delete prior chunks before inserting
        await db.execute(
            text("DELETE FROM public.transcript_chunks WHERE meeting_id = :id"),
            {"id": meeting_id},
        )
        await db.commit()

        # Insert chunks
        for idx, c in enumerate(chunks):
            await db.execute(
                text("""
                    INSERT INTO public.transcript_chunks
                    (id, meeting_id, chunk_index, content, embedding, start_ms, end_ms, token_count)
                    VALUES (:id, :meeting_id, :chunk_index, :content, :embedding::vector, :start_ms, :end_ms, :token_count)
                """),
                {
                    "id": str(uuid.uuid4()),
                    "meeting_id": meeting_id,
                    "chunk_index": c["chunk_index"],
                    "content": c["content"],
                    "embedding": str(vectors[idx]),
                    "start_ms": c["start_ms"],
                    "end_ms": c["end_ms"],
                    "token_count": c["token_count"],
                },
            )

    # Mark meeting done
    await db.execute(
        text("UPDATE public.meetings SET status = 'done' WHERE id = :id"),
        {"id": meeting_id},
    )
    logger.info(f"[jobs/embed] {meeting_id}: done ✓")

    user_id = payload.get("user_id")
    if user_id:
        await db.execute(
            text("""
                INSERT INTO public.activity_logs (id, user_id, event_type, meeting_id, created_at)
                VALUES (:id, :user_id, 'processing_done', :meeting_id, NOW())
            """),
            {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "meeting_id": meeting_id,
            },
        )

    # Close job
    await db.execute(
        text(
            "UPDATE public.jobs SET status = 'done', locked_at = NULL, locked_by = NULL WHERE id = :id"
        ),
        {"id": job_id},
    )
    await db.commit()


async def handle_job_error(
    db: AsyncSession, job: Dict[str, Any], err: Exception
) -> None:
    job_id = str(job["id"])
    meeting_id = str(job["meeting_id"])
    payload = job.get("payload") or {}

    message = str(err)
    terminal = is_terminal_error(err)
    new_attempts = (job.get("attempts") or 0) + 1
    max_attempts = job.get("max_attempts") or 8

    if not terminal and new_attempts < max_attempts:
        delay = jittered_backoff(new_attempts)
        logger.warning(
            f"[worker] job {job_id} step={job['step']} transient error, retry in {delay:.1f}s: {message}"
        )
        run_after = datetime.now(timezone.utc) + timedelta(seconds=delay)
        await db.execute(
            text("""
                UPDATE public.jobs
                SET status = 'queued', attempts = :attempts, last_error = :err,
                    run_after = :run_after, locked_at = NULL, locked_by = NULL
                WHERE id = :id
            """),
            {
                "attempts": new_attempts,
                "err": message[:500],
                "run_after": run_after,
                "id": job_id,
            },
        )
        await db.commit()
        return

    # Terminal or exhausted
    logger.error(
        f"[worker] job {job_id} step={job['step']} FAILED ({new_attempts}/{max_attempts}): {message}"
    )

    await db.execute(
        text("""
            UPDATE public.jobs
            SET status = 'failed', attempts = :attempts, last_error = :err,
                locked_at = NULL, locked_by = NULL
            WHERE id = :id
        """),
        {
            "attempts": new_attempts,
            "err": message[:500],
            "id": job_id,
        },
    )

    # QUO-02: refund reserved quota if transcription never settled
    user_id = payload.get("user_id")
    estimate_seconds = payload.get("estimate_seconds") or 0
    if (
        payload.get("reserve_done")
        and not payload.get("transcription_settled")
        and user_id
        and estimate_seconds > 0
    ):
        try:
            await apply_quota_movement(
                db,
                QuotaMovementParams(
                    user_id=user_id,
                    delta_audio_seconds=estimate_seconds,
                    delta_agent_queries=0,
                    reason="refund",
                    dedup_key=f"gen:{meeting_id}:refund",
                    allow_overdraw=False,
                    meeting_id=meeting_id,
                    metadata={"reason": "pipeline_failure", "error": message[:200]},
                ),
            )
        except Exception as e:
            logger.error(f"[worker] quota refund failed (non-fatal): {e}")

    # Mark meeting as failed
    await db.execute(
        text(
            "UPDATE public.meetings SET status = 'failed', error_message = :err WHERE id = :id"
        ),
        {"err": message[:500], "id": meeting_id},
    )
    await db.commit()

    if user_id:
        await db.execute(
            text("""
                INSERT INTO public.activity_logs (id, user_id, event_type, meeting_id, metadata, created_at)
                VALUES (:id, :user_id, 'processing_failed', :meeting_id, :metadata, NOW())
            """),
            {
                "id": str(uuid.uuid4()),
                "user_id": user_id,
                "meeting_id": meeting_id,
                "metadata": json.dumps({"error": message[:200]}),
            },
        )
        await db.commit()


async def sweep_stuck_jobs(db: AsyncSession) -> None:
    """
    Find 'running' jobs stuck for > 15 minutes and requeue or fail them. (REL-02)
    """
    STUCK_THRESHOLD_SECONDS = 15 * 60
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=STUCK_THRESHOLD_SECONDS)

    res = await db.execute(
        text(
            "SELECT * FROM public.jobs WHERE status = 'running' AND locked_at < :cutoff"
        ),
        {"cutoff": cutoff},
    )
    stuck = res.mappings().all()

    for raw in stuck:
        job = dict(raw)
        job_id = str(job["id"])
        meeting_id = str(job["meeting_id"])
        new_attempts = (job.get("attempts") or 0) + 1
        max_attempts = job.get("max_attempts") or 8
        logger.warning(
            f"[worker] sweeper found stuck job {job_id} step={job['step']} locked_at={job['locked_at']}"
        )

        if new_attempts >= max_attempts:
            err_msg = "Job timed out (stuck in running state — server may have restarted mid-step)"
            await db.execute(
                text("""
                    UPDATE public.jobs
                    SET status = 'failed', attempts = :attempts, last_error = :err,
                        locked_at = NULL, locked_by = NULL
                    WHERE id = :id
                """),
                {"attempts": new_attempts, "err": err_msg, "id": job_id},
            )
            await db.execute(
                text("""
                    UPDATE public.meetings
                    SET status = 'failed', error_message = 'Processing timed out. Use the Requeue button to retry.'
                    WHERE id = :id
                """),
                {"id": meeting_id},
            )
            logger.error(
                f"[worker] sweeper: terminated job {job_id} (max attempts reached)"
            )
        else:
            if job["step"] == "start":
                await db.execute(
                    text(
                        "UPDATE public.meetings SET status = 'pending' WHERE id = :id"
                    ),
                    {"id": meeting_id},
                )
            await db.execute(
                text("""
                    UPDATE public.jobs
                    SET status = 'queued', attempts = :attempts,
                        last_error = :err, locked_at = NULL, locked_by = NULL,
                        run_after = NOW()
                    WHERE id = :id
                """),
                {
                    "attempts": new_attempts,
                    "err": f"Requeued after stuck timeout (attempt {new_attempts}/{max_attempts})",
                    "id": job_id,
                },
            )
            logger.info(
                f"[worker] sweeper: requeued job {job_id} step={job['step']} (attempt {new_attempts}/{max_attempts})"
            )
    await db.commit()


async def run_worker_loop():
    """
    Background worker loop processing queued jobs.
    """
    worker_id = f"worker-{uuid.uuid4().hex[:6]}"
    logger.info(f"[worker] Worker {worker_id} started")

    STUCK_SWEEP_SECONDS = 60
    RECONCILE_INTERVAL_SECONDS = 5 * 60

    next_sweep_at = datetime.now(timezone.utc) + timedelta(seconds=STUCK_SWEEP_SECONDS)
    next_reconcile_at = datetime.now(timezone.utc) + timedelta(
        seconds=RECONCILE_INTERVAL_SECONDS
    )

    while True:
        now = datetime.now(timezone.utc)

        # 1. Periodic stuck-job sweep (REL-02)
        if now >= next_sweep_at:
            try:
                async with async_session_factory() as db:
                    await sweep_stuck_jobs(db)
            except Exception as e:
                logger.error(f"[worker] sweeper error: {e}")
            next_sweep_at = datetime.now(timezone.utc) + timedelta(
                seconds=STUCK_SWEEP_SECONDS
            )

        # 2. QUO-04: ledger-wallet reconciliation
        if now >= next_reconcile_at:
            try:
                async with async_session_factory() as db:
                    await reconcile_wallets(db)
            except Exception as e:
                logger.error(f"[wallet-reconcile] loop error: {e}")
            next_reconcile_at = datetime.now(timezone.utc) + timedelta(
                seconds=RECONCILE_INTERVAL_SECONDS
            )

        # 3. Claim and execute next job
        job = None
        try:
            async with async_session_factory() as db:
                job = await claim_next_job(db, worker_id)
                if job:
                    try:
                        logger.info(
                            f"[worker] executing job {job['id']} step={job['step']} attempt={job.get('attempts', 0)} meeting={job['meeting_id']}"
                        )
                        await execute_job_step(db, job)
                    except Exception as err:
                        await handle_job_error(db, job, err)
        except Exception as e:
            logger.error(f"[worker] loop error: {e}")

        # Sleep OUTSIDE the database session context block to prevent connection leak/holding!
        if not job:
            await asyncio.sleep(2.0)
        else:
            await asyncio.sleep(0.1)
