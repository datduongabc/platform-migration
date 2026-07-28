from typing import Any, Dict, Optional
from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.core.database import get_db
from app.models.user import User
from app.services.quota import (
    apply_quota_movement,
    reconcile_stuck_reservations,
    QuotaMovementParams,
    QuotaMovementReason,
)

router = APIRouter()


class QuotaMovementRequest(BaseModel):
    user_id: UUID
    delta_audio_seconds: int = 0
    delta_agent_queries: int = 0
    reason: QuotaMovementReason
    dedup_key: Optional[str] = None
    allow_overdraw: bool = False
    meeting_id: Optional[UUID] = None
    metadata: Optional[Dict[str, Any]] = None


@router.post("/quota/movement")
async def move_quota(
    payload: QuotaMovementRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """
    Admin endpoint to manually adjust user quota balances.
    """
    res = await apply_quota_movement(
        db,
        QuotaMovementParams(
            user_id=payload.user_id,
            delta_audio_seconds=payload.delta_audio_seconds,
            delta_agent_queries=payload.delta_agent_queries,
            reason=payload.reason,
            dedup_key=payload.dedup_key,
            allow_overdraw=payload.allow_overdraw,
            meeting_id=payload.meeting_id,
            created_by=admin.id,
            metadata=payload.metadata,
        ),
    )
    return {
        "status": res.status,
        "audio_remaining": res.audio_remaining,
        "agent_remaining": res.agent_remaining,
    }


@router.post(
    "/admin/pipeline/reconcile-quota",
    dependencies=[Depends(get_current_admin)],
)
async def reconcile_quota(
    db: AsyncSession = Depends(get_db),
):
    """
    Admin trigger for quota reconciliation sweep on stuck processing meetings.
    """
    result = await reconcile_stuck_reservations(db)
    return result
