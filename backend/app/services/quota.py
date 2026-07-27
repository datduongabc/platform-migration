import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

QuotaMovementStatus = Literal['applied', 'already_applied', 'insufficient']
QuotaMovementReason = Literal['topup', 'admin_grant', 'generate', 'agent_query', 'refund', 'adjustment']

STUCK_TIMEOUT_MINUTES = 30
RECLAIMED_MESSAGE = "QUOTA_BLOCKED: Reservation reclaimed — processing job was stuck in processing and exceeded the timeout."


@dataclass
class QuotaMovementParams:
    user_id: UUID | str
    delta_audio_seconds: int
    delta_agent_queries: int
    reason: QuotaMovementReason
    dedup_key: Optional[str] = None
    allow_overdraw: bool = False
    meeting_id: Optional[UUID | str] = None
    created_by: Optional[UUID | str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class QuotaMovementResult:
    status: QuotaMovementStatus
    audio_remaining: float
    agent_remaining: int


async def apply_quota_movement(
    db: AsyncSession, params: QuotaMovementParams
) -> QuotaMovementResult:
    """
    Atomically moves quota balances for a user via the `quota_apply_movement`
    Postgres RPC function.
    """
    sql = text("""
        SELECT * FROM public.quota_apply_movement(
            p_user_id := :p_user_id,
            p_delta_audio_seconds := :p_delta_audio_seconds,
            p_delta_agent_queries := :p_delta_agent_queries,
            p_reason := :p_reason,
            p_dedup_key := :p_dedup_key,
            p_allow_overdraw := :p_allow_overdraw,
            p_meeting_id := :p_meeting_id,
            p_created_by := :p_created_by,
            p_metadata := :p_metadata
        )
    """)

    result = await db.execute(
        sql,
        {
            "p_user_id": str(params.user_id),
            "p_delta_audio_seconds": params.delta_audio_seconds,
            "p_delta_agent_queries": params.delta_agent_queries,
            "p_reason": params.reason,
            "p_dedup_key": params.dedup_key,
            "p_allow_overdraw": params.allow_overdraw,
            "p_meeting_id": str(params.meeting_id) if params.meeting_id else None,
            "p_created_by": str(params.created_by) if params.created_by else None,
            "p_metadata": json.dumps(params.metadata or {}),
        },
    )

    row = result.mappings().first()
    if not row:
        raise RuntimeError("quota_apply_movement RPC returned no result")

    return QuotaMovementResult(
        status=row["status"],
        audio_remaining=float(row["audio_remaining"]),
        agent_remaining=int(row["agent_remaining"]),
    )


async def reconcile_stuck_reservations(db: AsyncSession) -> dict[str, int]:
    """
    Find meetings stuck in 'processing' past STUCK_TIMEOUT_MINUTES holding an unredeemed
    quota reservation, refund each one, and mark them failed.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_TIMEOUT_MINUTES)

    # Fetch stuck meetings
    query_stuck = text("""
        SELECT id, user_id FROM public.meetings
        WHERE status = 'processing' AND updated_at < :cutoff
    """)
    res_stuck = await db.execute(query_stuck, {"cutoff": cutoff})
    stuck_meetings = res_stuck.mappings().all()

    reconciled_count = 0

    for meeting in stuck_meetings:
        meeting_id = str(meeting["id"])
        user_id = str(meeting["user_id"]) if meeting["user_id"] else None

        try:
            # Check reservation entry
            res_reserve = await db.execute(
                text("SELECT delta_audio_seconds FROM public.quota_ledger WHERE dedup_key = :key LIMIT 1"),
                {"key": f"gen:{meeting_id}:reserve"},
            )
            reserve_row = res_reserve.mappings().first()
            if not reserve_row:
                continue

            # Skip if already settled
            res_settle = await db.execute(
                text("SELECT id FROM public.quota_ledger WHERE dedup_key = :key LIMIT 1"),
                {"key": f"gen:{meeting_id}:settle"},
            )
            if res_settle.mappings().first():
                continue

            # Check if already refunded
            res_refund = await db.execute(
                text("SELECT id FROM public.quota_ledger WHERE dedup_key = :key LIMIT 1"),
                {"key": f"gen:{meeting_id}:refund"},
            )
            if res_refund.mappings().first():
                await db.execute(
                    text("UPDATE public.meetings SET status = 'failed', error_message = :msg WHERE id = :id AND status = 'processing'"),
                    {"msg": RECLAIMED_MESSAGE, "id": meeting_id},
                )
                await db.commit()
                continue

            # Issue refund
            estimate_secs = abs(int(reserve_row["delta_audio_seconds"]))
            if estimate_secs > 0 and user_id:
                await apply_quota_movement(
                    db,
                    QuotaMovementParams(
                        user_id=user_id,
                        delta_audio_seconds=estimate_secs,
                        delta_agent_queries=0,
                        reason="refund",
                        dedup_key=f"gen:{meeting_id}:refund",
                        allow_overdraw=False,
                        meeting_id=meeting_id,
                        metadata={
                            "reason": "stuck_reclaimed",
                            "stuck_timeout_minutes": STUCK_TIMEOUT_MINUTES,
                        },
                    ),
                )

            # Update meeting status to failed
            await db.execute(
                text("UPDATE public.meetings SET status = 'failed', error_message = :msg WHERE id = :id AND status = 'processing'"),
                {"msg": RECLAIMED_MESSAGE, "id": meeting_id},
            )
            await db.commit()
            reconciled_count += 1
        except Exception:
            await db.rollback()

    return {"reconciled": reconciled_count}
