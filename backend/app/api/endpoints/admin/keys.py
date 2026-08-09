import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.schemas.admin import (
    HealthCheckResponse,
    HealthProbeInfo,
    KeyCreateRequest,
    KeyListResponse,
    KeyResponse,
    KeyUpdateRequest,
)
from app.services.audit import write_audit_log
from app.services.crypto import decrypt_secret, encrypt_secret
from app.services.health import probe_key

from ._shared import require_admin

router = APIRouter()

ALLOWED_CONFIG_KEYS = [
    "gemini_api_key",
    "speechmatics_api_key",
]


# ── API Key Vault Endpoints ───────────────────────────────────────────────


@router.get("/keys", response_model=KeyListResponse)
async def list_keys(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    List all encrypted operational API keys (masked, never returned in plaintext).
    """
    sql = text("""
        SELECT id, created_at, updated_at, config_key, label, last4, status, disabled_reason,
               last_used_at, health_status, health_checked_at, health_detail
        FROM public.admin_config
        WHERE config_key IN :keys
        ORDER BY config_key ASC, created_at ASC
    """).bindparams(bindparam("keys", expanding=True))
    res = await db.execute(sql, {"keys": ALLOWED_CONFIG_KEYS})
    rows = res.fetchall()

    keys = []
    for r in rows:
        keys.append(
            KeyResponse(
                id=r[0],
                created_at=r[1],
                updated_at=r[2],
                config_key=r[3],
                label=r[4],
                last4=r[5],
                status=r[6],
                disabled_reason=r[7],
                last_used_at=r[8],
                health_status=r[9] or "unknown",
                health_checked_at=r[10].isoformat() if r[10] else None,
                health_detail=r[11],
            )
        )

    return KeyListResponse(keys=keys)


@router.post("/keys", response_model=KeyResponse, status_code=201)
async def add_key(
    payload: KeyCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Save new api key, encrypting it using master key.
    """
    if payload.configKey not in ALLOWED_CONFIG_KEYS:
        raise HTTPException(
            status_code=422,
            detail=f"configKey must be one of: {', '.join(ALLOWED_CONFIG_KEYS)}",
        )

    raw_key = payload.key.strip()
    if len(raw_key) < 8:
        raise HTTPException(
            status_code=422, detail="Key must be at least 8 characters."
        )

    # Encrypt
    enc = encrypt_secret(raw_key)

    new_id = uuid.uuid4()
    last4 = raw_key[-4:]

    sql = text("""
        INSERT INTO public.admin_config (
            id, created_at, updated_at, config_key, label, value_ciphertext, value_iv, value_auth_tag, last4, status, created_by
        ) VALUES (
            :id, NOW(), NOW(), :config_key, :label, :ciphertext, :iv, :auth_tag, :last4, 'active', :created_by
        )
    """)
    await db.execute(
        sql,
        {
            "id": new_id,
            "config_key": payload.configKey,
            "label": payload.label.strip(),
            "ciphertext": enc["ciphertext"],
            "iv": enc["iv"],
            "auth_tag": enc["authTag"],
            "last4": last4,
            "created_by": admin.id,
        },
    )
    await db.commit()

    # Log audit
    ip = request.client.host if request.client else None
    agent = request.headers.get("user-agent")
    await write_audit_log(
        db,
        actor_id=admin.id,
        actor_email=admin.email,
        action="admin_config.create",
        target_type="admin_config",
        target_id=str(new_id),
        metadata={"configKey": payload.configKey, "label": payload.label},
        ip_address=ip,
        user_agent=agent,
    )
    await db.commit()

    # Return key info
    return KeyResponse(
        id=new_id,
        created_at=datetime.utcnow(),
        config_key=payload.configKey,
        label=payload.label,
        last4=last4,
        status="active",
    )


@router.patch("/keys/{id}", response_model=KeyResponse)
async def update_key(
    id: uuid.UUID,
    payload: KeyUpdateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Toggle key active / disabled status. Block disabling if it is last active key.
    """
    # Fetch key
    res_find = await db.execute(
        text(
            "SELECT id, config_key, label, status FROM public.admin_config WHERE id = :id"
        ),
        {"id": id},
    )
    key_row = res_find.fetchone()
    if not key_row:
        raise HTTPException(status_code=404, detail="Key not found.")

    config_key = key_row[1]
    label = key_row[2]
    old_status = key_row[3]

    new_status = payload.status
    if new_status not in ["active", "disabled"]:
        raise HTTPException(
            status_code=422, detail="status must be 'active' or 'disabled'."
        )

    # Guard: prevent disabling last active key
    if new_status == "disabled" and old_status == "active":
        count_res = await db.execute(
            text(
                "SELECT COUNT(*) FROM public.admin_config WHERE config_key = :ck AND status = 'active'"
            ),
            {"ck": config_key},
        )
        active_count = count_res.scalar() or 0
        if active_count <= 1:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot disable the last active key for '{config_key}'. Add another first.",
            )

    sql_update = text("""
        UPDATE public.admin_config
        SET status = :status, disabled_reason = :reason, updated_at = NOW()
        WHERE id = :id
    """)
    await db.execute(
        sql_update,
        {"status": new_status, "reason": payload.disabled_reason, "id": id},
    )
    await db.commit()

    # Log audit
    ip = request.client.host if request.client else None
    agent = request.headers.get("user-agent")
    action = "admin_config.enable" if new_status == "active" else "admin_config.disable"
    await write_audit_log(
        db,
        actor_id=admin.id,
        actor_email=admin.email,
        action=action,
        target_type="admin_config",
        target_id=str(id),
        metadata={"configKey": config_key, "label": label},
        ip_address=ip,
        user_agent=agent,
    )
    await db.commit()

    # Return key response
    res_refreshed = await db.execute(
        text(
            "SELECT id, created_at, updated_at, config_key, label, last4, status, disabled_reason, last_used_at FROM public.admin_config WHERE id = :id"
        ),
        {"id": id},
    )
    r = res_refreshed.fetchone()

    return KeyResponse(
        id=r[0],
        created_at=r[1],
        updated_at=r[2],
        config_key=r[3],
        label=r[4],
        last4=r[5],
        status=r[6],
        disabled_reason=r[7],
        last_used_at=r[8],
    )


@router.delete("/keys/{id}")
async def delete_key(
    id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Permanently delete API key. Block if it is last active.
    """
    res_find = await db.execute(
        text(
            "SELECT id, config_key, label, status FROM public.admin_config WHERE id = :id"
        ),
        {"id": id},
    )
    key_row = res_find.fetchone()
    if not key_row:
        raise HTTPException(status_code=404, detail="Key not found.")

    config_key = key_row[1]
    label = key_row[2]
    status_val = key_row[3]

    # Prevent deleting last active
    if status_val == "active":
        count_res = await db.execute(
            text(
                "SELECT COUNT(*) FROM public.admin_config WHERE config_key = :ck AND status = 'active'"
            ),
            {"ck": config_key},
        )
        active_count = count_res.scalar() or 0
        if active_count <= 1:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot delete the last active key for '{config_key}'. Disable it or add another first.",
            )

    await db.execute(text("DELETE FROM public.admin_config WHERE id = :id"), {"id": id})
    await db.commit()

    # Log audit
    ip = request.client.host if request.client else None
    agent = request.headers.get("user-agent")
    await write_audit_log(
        db,
        actor_id=admin.id,
        actor_email=admin.email,
        action="admin_config.delete",
        target_type="admin_config",
        target_id=str(id),
        metadata={"configKey": config_key, "label": label},
        ip_address=ip,
        user_agent=agent,
    )
    await db.commit()

    return {"ok": True}


@router.post("/keys/healthcheck", response_model=HealthCheckResponse)
async def trigger_healthcheck(
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Decrypts each stored key in-memory, probes provider, and returns health results.
    """
    sql_load = text("""
        SELECT id, config_key, label, value_ciphertext, value_iv, value_auth_tag, status
        FROM public.admin_config
        WHERE config_key IN :keys
    """).bindparams(bindparam("keys", expanding=True))
    res = await db.execute(sql_load, {"keys": ALLOWED_CONFIG_KEYS})
    rows = res.fetchall()

    checked_keys = []
    ran_at = datetime.utcnow().isoformat() + "Z"

    healthy_count = 0
    unhealthy_count = 0
    unknown_count = 0

    for r_id, config_key, label, ciphertext, iv, auth_tag, status_val in rows:
        try:
            # Decrypt
            plaintext = decrypt_secret(ciphertext, iv, auth_tag)
            probe = await probe_key(config_key, plaintext)
        except Exception as e:
            probe = {"status": "unhealthy", "detail": f"Decryption failed: {str(e)}"}

        if probe["status"] == "healthy":
            healthy_count += 1
        elif probe["status"] == "unhealthy":
            unhealthy_count += 1
        else:
            unknown_count += 1

        # Persist so GET /keys reflects the latest result instead of always
        # reporting "unknown" — plaintext/ciphertext are never written back here,
        # only the verdict.
        await db.execute(
            text("""
                UPDATE public.admin_config
                SET health_status = :status, health_checked_at = NOW(), health_detail = :detail
                WHERE id = :id
            """),
            {"status": probe["status"], "detail": probe["detail"][:500], "id": r_id},
        )

        checked_keys.append(
            HealthProbeInfo(
                id=r_id,
                config_key=config_key,
                label=label,
                status=probe["status"],
                detail=probe["detail"],
            )
        )

    summary = {
        "total": len(rows),
        "healthy": healthy_count,
        "unhealthy": unhealthy_count,
        "unknown": unknown_count,
    }

    # Log audit
    ip = request.client.host if request.client else None
    agent = request.headers.get("user-agent")
    await write_audit_log(
        db,
        actor_id=admin.id,
        actor_email=admin.email,
        action="admin_config.healthcheck",
        target_type="admin_config",
        target_id="",
        metadata={"summary": summary},
        ip_address=ip,
        user_agent=agent,
    )
    await db.commit()

    return HealthCheckResponse(
        ranAt=ran_at,
        summary=summary,
        keys=checked_keys,
    )
