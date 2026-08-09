import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.endpoints.projects import enqueue_job
from app.core.database import get_db
from app.models.project import Project
from app.models.user import Profile, User
from app.schemas.admin import (
    PipelineCounts,
    PipelineJob,
    PipelineJobsResponse,
    PipelineOverviewResponse,
)
from app.services.audit import write_audit_log

from ._shared import require_admin

router = APIRouter()

STUCK_THRESHOLD_MINUTES = 15


# ── Pipeline Monitoring Endpoints ───────────────────────────────────────────


@router.get("/pipeline/overview", response_model=PipelineOverviewResponse)
async def get_pipeline_overview(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Get aggregate pipeline statistics across all users using SQL aggregation.
    """
    now = datetime.utcnow()
    stuck_cutoff = now - timedelta(minutes=STUCK_THRESHOLD_MINUTES)

    # 1. Count by status at DB level
    res_counts = await db.execute(
        text("SELECT status, COUNT(*) FROM public.meetings GROUP BY status")
    )
    counts = {"pending": 0, "processing": 0, "done": 0, "failed": 0, "stuck": 0}
    total = 0
    for status_val, cnt in res_counts.fetchall():
        if status_val in counts:
            counts[status_val] = cnt
        total += cnt

    # 2. Count stuck processing jobs at DB level
    res_stuck = await db.execute(
        text(
            "SELECT COUNT(*) FROM public.meetings WHERE status = 'processing' AND updated_at < :stuck_cutoff"
        ),
        {"stuck_cutoff": stuck_cutoff},
    )
    counts["stuck"] = res_stuck.scalar() or 0

    # 3. Calculate average processing time for done jobs at DB level
    res_avg = await db.execute(
        text("""
            SELECT AVG(EXTRACT(EPOCH FROM (updated_at - created_at)))
            FROM public.meetings
            WHERE status = 'done' AND updated_at > created_at
        """)
    )
    avg_raw = res_avg.scalar()
    avg_secs = int(avg_raw) if avg_raw is not None else None

    return PipelineOverviewResponse(
        counts=PipelineCounts(**counts),
        avg_processing_secs=avg_secs,
        stuck_threshold_minutes=STUCK_THRESHOLD_MINUTES,
        total=total,
    )


@router.get("/pipeline/jobs", response_model=PipelineJobsResponse)
async def get_pipeline_jobs(
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    perPage: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    List paginated pipeline jobs with user email and username details.
    """
    stuck_cutoff = datetime.utcnow() - timedelta(minutes=STUCK_THRESHOLD_MINUTES)

    base_query = (
        select(Project, User.email, Profile.username)
        .outerjoin(User, Project.user_id == User.id)
        .outerjoin(Profile, Project.user_id == Profile.id)
    )

    if status_filter:
        status_clean = status_filter.strip().lower()
        if status_clean == "stuck":
            base_query = base_query.where(
                Project.status == "processing", Project.updated_at < stuck_cutoff
            )
        else:
            base_query = base_query.where(Project.status == status_clean)

    # Total count query at DB level
    count_query = select(func.count()).select_from(base_query.subquery())
    total_res = await db.execute(count_query)
    total = total_res.scalar() or 0

    # Paginated query at DB level
    offset = (page - 1) * perPage
    paginated_query = (
        base_query.order_by(Project.created_at.desc()).offset(offset).limit(perPage)
    )

    result = await db.execute(paginated_query)
    rows = result.all()

    jobs_list = []
    for project, email, username in rows:
        proj_updated_naive = (
            project.updated_at.replace(tzinfo=None)
            if project.updated_at
            else datetime.utcnow()
        )
        is_stuck = project.status == "processing" and proj_updated_naive < stuck_cutoff

        jobs_list.append(
            PipelineJob(
                id=project.id,
                title=project.title,
                status=project.status,
                created_at=project.created_at,
                updated_at=project.updated_at,
                duration_seconds=project.duration_seconds,
                error_message=project.error_message,
                owner_email=email,
                owner_username=username,
                is_stuck=is_stuck,
            )
        )

    return PipelineJobsResponse(
        jobs=jobs_list,
        total=total,
        page=page,
        perPage=perPage,
    )


@router.post("/pipeline/{id}/requeue")
async def requeue_pipeline_job(
    id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Admin command to clear and requeue any meeting job.
    """
    # Fetch meeting
    project = await db.get(Project, id)
    if not project:
        raise HTTPException(status_code=404, detail="Meeting not found.")

    prev_status = project.status
    if prev_status not in ("failed", "processing"):
        raise HTTPException(
            status_code=422,
            detail="Only failed or stuck (processing) meetings can be requeued.",
        )

    # Clear children
    await db.execute(
        text("DELETE FROM public.transcript_chunks WHERE meeting_id = :id"), {"id": id}
    )
    await db.execute(
        text("DELETE FROM public.transcript_segments WHERE meeting_id = :id"),
        {"id": id},
    )
    await db.execute(
        text("DELETE FROM public.todos WHERE meeting_id = :id"), {"id": id}
    )
    await db.execute(
        text("DELETE FROM public.calendar_suggestions WHERE meeting_id = :id"),
        {"id": id},
    )
    await db.execute(text("DELETE FROM public.jobs WHERE meeting_id = :id"), {"id": id})

    # Reset
    project.status = "pending"
    project.error_message = None
    project.summary = None
    project.notes = None
    project.language = None
    project.updated_at = datetime.utcnow()

    await db.commit()

    # Log audit trail
    ip = request.client.host if request.client else None
    agent = request.headers.get("user-agent")
    await write_audit_log(
        db,
        actor_id=admin.id,
        actor_email=admin.email,
        action="meeting.requeue",
        target_type="meeting",
        target_id=str(id),
        metadata={
            "previous_status": prev_status,
            "meeting_owner_id": str(project.user_id),
        },
        ip_address=ip,
        user_agent=agent,
    )
    await db.commit()

    # Trigger async processing background thread task
    await enqueue_job(db, id)
    return {"ok": True, "meetingId": id}
