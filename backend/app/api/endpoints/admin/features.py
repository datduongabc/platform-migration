from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.services.audit import write_audit_log

from ._shared import require_admin

router = APIRouter()


# ── Feature Registry Endpoints ───────────────────────────────────────────────


@router.get("/features")
async def list_features(
    modulePrefix: Optional[str] = Query(None),
    status_val: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    where_clauses = []
    params = {}

    if modulePrefix:
        where_clauses.append("module_prefix = :modulePrefix")
        params["modulePrefix"] = modulePrefix
    if status_val:
        where_clauses.append("status = :status_val")
        params["status_val"] = status_val
    if search:
        where_clauses.append(
            "(key ILIKE :search OR title ILIKE :search OR description ILIKE :search)"
        )
        params["search"] = f"%{search}%"

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    sql = text(f"""
        SELECT id, key, source_path, module_prefix, module_name, title, user_story, description, content, status, priority, note_tags, depends_on, blocks, key_files, metadata, updated_by, change_note, updated_at
        FROM public.features
        {where_sql}
        ORDER BY module_prefix ASC, key ASC
    """)
    res = await db.execute(sql, params)
    rows = res.fetchall()

    features_list = []
    for r in rows:
        features_list.append(
            {
                "id": str(r[0]),
                "key": r[1],
                "source_path": r[2],
                "module_prefix": r[3],
                "module_name": r[4],
                "title": r[5],
                "user_story": r[6],
                "description": r[7],
                "content": r[8],
                "status": r[9],
                "priority": r[10],
                "note_tags": r[11] or [],
                "depends_on": r[12] or [],
                "blocks": r[13] or [],
                "key_files": r[14] or [],
                "metadata": r[15] or {},
                "updated_by": r[16],
                "change_note": r[17],
                "updated_at": r[18].isoformat() if r[18] else None,
            }
        )

    return {"features": features_list}


@router.patch("/features/{id}")
async def update_feature(
    id: str,
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    sql_find = text(
        "SELECT id, key FROM public.features WHERE id::text = :id OR key = :id"
    )
    res_find = await db.execute(sql_find, {"id": id})
    row_find = res_find.fetchone()
    if not row_find:
        raise HTTPException(status_code=404, detail="Feature not found.")

    feature_id = row_find[0]
    feature_key = row_find[1]

    updatable_fields = [
        "title",
        "description",
        "content",
        "status",
        "priority",
        "change_note",
        "note_tags",
        "depends_on",
        "key_files",
    ]
    set_clauses = ["updated_at = NOW()", "updated_by = :updated_by"]
    params = {"id": feature_id, "updated_by": admin.email}

    for f in updatable_fields:
        if f in payload:
            set_clauses.append(f"{f} = :{f}")
            params[f] = payload[f]

    sql_update = text(
        f"UPDATE public.features SET {', '.join(set_clauses)} WHERE id = :id"
    )
    await db.execute(sql_update, params)
    await db.commit()

    ip = request.client.host if request.client else None
    agent = request.headers.get("user-agent")
    await write_audit_log(
        db,
        actor_id=admin.id,
        actor_email=admin.email,
        action="feature.update",
        target_type="feature",
        target_id=feature_key,
        metadata={"changed_fields": list(payload.keys())},
        ip_address=ip,
        user_agent=agent,
    )
    await db.commit()

    return {"ok": True, "id": str(feature_id), "key": feature_key}
