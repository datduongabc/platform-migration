import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User

from ._shared import require_admin

router = APIRouter()


# ── Audit Logs Endpoints ──────────────────────────────────────────────────────


@router.get("/audit-logs")
async def list_audit_logs(
    action: Optional[str] = Query(None),
    targetType: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    perPage: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    where_clauses = []
    params = {}

    if action:
        where_clauses.append("action = :action")
        params["action"] = action
    if targetType:
        where_clauses.append("target_type = :targetType")
        params["targetType"] = targetType

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    res_count = await db.execute(
        text(f"SELECT COUNT(*) FROM public.audit_logs{where_sql}"), params
    )
    total = res_count.scalar() or 0

    offset = (page - 1) * perPage
    params["offset"] = offset
    params["perPage"] = perPage

    sql_rows = text(f"""
        SELECT id, created_at, actor_id, actor_email, action, target_type, target_id, metadata, ip_address, user_agent
        FROM public.audit_logs{where_sql}
        ORDER BY created_at DESC
        OFFSET :offset LIMIT :perPage
    """)
    res = await db.execute(sql_rows, params)
    rows = res.fetchall()

    logs = []
    for r in rows:
        logs.append(
            {
                "id": str(r[0]),
                "created_at": r[1].isoformat() if r[1] else None,
                "actor_id": str(r[2]) if r[2] else None,
                "actor_email": r[3],
                "action": r[4],
                "target_type": r[5],
                "target_id": r[6],
                "metadata": r[7],
                "ip_address": r[8],
                "user_agent": r[9],
            }
        )

    return {"rows": logs, "total": total, "page": page, "perPage": perPage}


# ── User Activity Logs Endpoints ─────────────────────────────────────────────


@router.get("/activity")
async def list_activity_logs(
    userId: Optional[str] = Query(None),
    eventType: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    perPage: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    where_clauses = []
    params = {}

    if userId:
        where_clauses.append("a.user_id = :userId")
        params["userId"] = uuid.UUID(userId)
    if eventType:
        where_clauses.append("a.event_type = :eventType")
        params["eventType"] = eventType

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    res_count = await db.execute(
        text(f"SELECT COUNT(*) FROM public.activity_log a{where_sql}"), params
    )
    total = res_count.scalar() or 0

    offset = (page - 1) * perPage
    params["offset"] = offset
    params["perPage"] = perPage

    sql_rows = text(f"""
        SELECT a.id, a.created_at, a.user_id, a.event_type, a.meeting_id, m.title as meeting_title, a.metadata, a.ip, a.user_agent, u.email as user_email
        FROM public.activity_log a
        LEFT JOIN public.meetings m ON a.meeting_id = m.id
        LEFT JOIN auth.users u ON a.user_id = u.id
        {where_sql}
        ORDER BY a.created_at DESC
        OFFSET :offset LIMIT :perPage
    """)
    res = await db.execute(sql_rows, params)
    rows = res.fetchall()

    activities = []
    for r in rows:
        activities.append(
            {
                "id": str(r[0]),
                "created_at": r[1].isoformat() if r[1] else None,
                "user_id": str(r[2]) if r[2] else None,
                "event_type": r[3],
                "meeting_id": str(r[4]) if r[4] else None,
                "meeting_title": r[5],
                "metadata": r[6],
                "ip": r[7],
                "user_agent": r[8],
                "user_email": r[9],
            }
        )

    return {"rows": activities, "total": total, "page": page, "perPage": perPage}


# ── AI Usage Telemetry Endpoints ──────────────────────────────────────────────


@router.get("/ai-usage")
async def get_ai_usage_telemetry(
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    groupBy: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    where_clauses = []
    params = {}

    if from_date:
        where_clauses.append("created_at >= :from_date")
        params["from_date"] = datetime.fromisoformat(from_date.replace("Z", "+00:00"))
    if to_date:
        where_clauses.append("created_at <= :to_date")
        params["to_date"] = datetime.fromisoformat(to_date.replace("Z", "+00:00"))

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    group_cols = "provider, model, unit"
    if groupBy == "operation":
        group_cols = "provider, model, operation, unit"

    sql = text(f"""
        SELECT {group_cols},
               COUNT(*) as calls,
               SUM(COALESCE(total_tokens, 0)) as total_tokens,
               SUM(COALESCE(input_tokens, 0)) as input_tokens,
               SUM(COALESCE(output_tokens, 0)) as output_tokens,
               SUM(COALESCE(audio_seconds, 0)) as total_audio_seconds,
               SUM(CASE WHEN status = 'rate_limited' THEN 1 ELSE 0 END) as rate_limited_count,
               SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as error_count
        FROM public.usage_log
        {where_sql}
        GROUP BY {group_cols}
        ORDER BY calls DESC
    """)
    res = await db.execute(sql, params)
    rows = res.fetchall()

    rows_list = []
    for r in rows:
        if groupBy == "operation":
            rows_list.append(
                {
                    "provider": r[0],
                    "model": r[1],
                    "operation": r[2],
                    "unit": r[3],
                    "calls": r[4],
                    "total_tokens": int(r[5]),
                    "input_tokens": int(r[6]),
                    "output_tokens": int(r[7]),
                    "total_audio_seconds": float(r[8]),
                    "rate_limited_count": int(r[9]),
                    "error_count": int(r[10]),
                }
            )
        else:
            rows_list.append(
                {
                    "provider": r[0],
                    "model": r[1],
                    "unit": r[2],
                    "calls": r[3],
                    "total_tokens": int(r[4]),
                    "input_tokens": int(r[5]),
                    "output_tokens": int(r[6]),
                    "total_audio_seconds": float(r[7]),
                    "rate_limited_count": int(r[8]),
                    "error_count": int(r[9]),
                }
            )

    # Daily totals for trend chart
    sql_daily = text(f"""
        SELECT DATE(created_at) as date, provider, unit, SUM(quantity) as quantity
        FROM public.usage_log
        {where_sql}
        GROUP BY DATE(created_at), provider, unit
        ORDER BY date ASC
    """)
    res_daily = await db.execute(sql_daily, params)
    daily_rows = res_daily.fetchall()
    daily_totals = [
        {
            "date": r[0].strftime("%Y-%m-%d"),
            "provider": r[1],
            "unit": r[2],
            "quantity": float(r[3]),
        }
        for r in daily_rows
    ]

    return {
        "from": from_date,
        "to": to_date,
        "rows": rows_list,
        "dailyTotals": daily_totals,
    }
