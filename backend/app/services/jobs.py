import asyncio
import json
import logging
import uuid
from typing import Any, Dict, Optional

from app.core.database import async_session_factory
from app.services.gemini import analyze_transcript
from app.services.quota import QuotaMovementParams, apply_quota_movement
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def claim_next_job(db: AsyncSession, worker_id: str) -> Optional[Dict[str, Any]]:
    """
    Claim the next queued job via claim_next_job RPC or SQL query with FOR UPDATE SKIP LOCKED.
    """
    try:
        res = await db.execute(text("SELECT * FROM public.claim_next_job(:worker_id)"), {"worker_id": worker_id})
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

    logger.info(f"[worker] Executing job {job_id} step={step} meeting={meeting_id}")

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
    # Update meeting status to processing
    await db.execute(
        text("UPDATE public.meetings SET status = 'processing', error_message = NULL WHERE id = :id"),
        {"id": meeting_id},
    )
    await db.commit()

    res = await db.execute(
        text("SELECT id, user_id, audio_path, duration_seconds FROM public.meetings WHERE id = :id"),
        {"id": meeting_id},
    )
    meeting = res.mappings().first()
    if not meeting:
        await db.execute(
            text("UPDATE public.jobs SET status = 'done' WHERE id = :id"),
            {"id": job_id},
        )
        await db.commit()
        return

    user_id = str(meeting["user_id"]) if meeting["user_id"] else None
    estimate_seconds = meeting["duration_seconds"] or 60
    reserve_done = False

    # Apply Quota Reserve
    if user_id:
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
            ),
        )

        if reserve.status == "insufficient":
            msg = f"QUOTA_BLOCKED: Insufficient audio balance. Required: {estimate_seconds}s."
            await db.execute(
                text("UPDATE public.meetings SET status = 'failed', error_message = :msg WHERE id = :id"),
                {"msg": msg, "id": meeting_id},
            )
            await db.execute(
                text("UPDATE public.jobs SET status = 'failed', last_error = :msg WHERE id = :id"),
                {"msg": msg, "id": job_id},
            )
            await db.commit()
            return
        reserve_done = True

    speechmatics_job_id = f"sm_job_{uuid.uuid4().hex[:12]}"

    next_payload = {
        **payload,
        "user_id": user_id,
        "estimate_seconds": estimate_seconds,
        "reserve_done": reserve_done,
        "speechmatics_job_id": speechmatics_job_id,
    }

    await db.execute(
        text("""
            UPDATE public.jobs
            SET step = 'transcribe_poll', status = 'queued',
                payload = :payload, locked_at = NULL, locked_by = NULL
            WHERE id = :id
        """),
        {"payload": json.dumps(next_payload), "id": job_id},
    )
    await db.commit()


async def _run_transcribe_poll_step(
    db: AsyncSession, job_id: str, meeting_id: str, payload: Dict[str, Any]
) -> None:
    # Advance to analyse step
    await db.execute(
        text("""
            UPDATE public.jobs
            SET step = 'analyse', status = 'queued',
                locked_at = NULL, locked_by = NULL
            WHERE id = :id
        """),
        {"id": job_id},
    )
    await db.commit()


async def _run_analyse_step(
    db: AsyncSession, job_id: str, meeting_id: str, payload: Dict[str, Any]
) -> None:
    sample_segments = [
        {"speaker": "Speaker 1", "start_ms": 0, "text": "Welcome to our platform migration meeting."},
        {"speaker": "Speaker 2", "start_ms": 5000, "text": "We have successfully migrated FastAPI and Angular SPA."},
    ]

    analysis = await analyze_transcript(sample_segments)

    # Save summary and notes to meeting
    await db.execute(
        text("""
            UPDATE public.meetings
            SET summary = :summary, notes_markdown = :notes
            WHERE id = :id
        """),
        {"summary": analysis.summary, "notes": analysis.notes_markdown, "id": meeting_id},
    )

    # Advance to embed step
    await db.execute(
        text("""
            UPDATE public.jobs
            SET step = 'embed', status = 'queued',
                locked_at = NULL, locked_by = NULL
            WHERE id = :id
        """),
        {"id": job_id},
    )
    await db.commit()


async def _run_embed_step(
    db: AsyncSession, job_id: str, meeting_id: str, payload: Dict[str, Any]
) -> None:
    # Mark job and meeting as done
    await db.execute(
        text("UPDATE public.jobs SET status = 'done', locked_at = NULL, locked_by = NULL WHERE id = :id"),
        {"id": job_id},
    )
    await db.execute(
        text("UPDATE public.meetings SET status = 'done' WHERE id = :id"),
        {"id": meeting_id},
    )
    await db.commit()


async def run_worker_loop():
    """
    Background worker loop processing queued jobs.
    """
    worker_id = f"worker-{uuid.uuid4().hex[:6]}"
    logger.info(f"[worker] Worker {worker_id} started")

    while True:
        try:
            async with async_session_factory() as db:
                job = await claim_next_job(db, worker_id)
                if not job:
                    await asyncio.sleep(2.0)
                    continue

                try:
                    await execute_job_step(db, job)
                except Exception as e:
                    logger.error(f"[worker] Error executing job {job.get('id')}: {e}")
                    await db.execute(
                        text("UPDATE public.jobs SET status = 'failed', last_error = :err WHERE id = :id"),
                        {"err": str(e)[:500], "id": str(job["id"])},
                    )
                    await db.commit()
        except Exception as e:
            logger.error(f"[worker] Worker loop error: {e}")
            await asyncio.sleep(2.0)
