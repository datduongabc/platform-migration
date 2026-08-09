import asyncio
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.services.audit import write_audit_log
from app.services.crypto import encrypt_secret
from app.services.storage import invalidate_storage_config_cache, test_r2_connection

from ._shared import require_admin

router = APIRouter()


# ── Storage Configuration Endpoints ──────────────────────────────────────────


@router.get("/storage")
async def list_storage_configs(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    sql = text("""
        SELECT id, created_at, updated_at, provider, label, account_id, access_key_id, bucket, secret_last4, status, disabled_reason, last_used_at
        FROM public.storage_config
        ORDER BY created_at DESC
    """)
    res = await db.execute(sql)
    rows = res.fetchall()

    configs = []
    for r in rows:
        configs.append(
            {
                "id": str(r[0]),
                "created_at": r[1].isoformat() if r[1] else None,
                "updated_at": r[2].isoformat() if r[2] else None,
                "provider": r[3],
                "label": r[4],
                "account_id": r[5],
                "access_key_id": r[6],
                "bucket": r[7],
                "secret_last4": r[8],
                "status": r[9],
                "disabled_reason": r[10],
                "last_used_at": r[11].isoformat() if r[11] else None,
            }
        )
    return {"storage_configs": configs}


@router.post("/storage", status_code=201)
async def create_storage_config(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    provider = payload.get("provider", "r2")
    label = payload.get("label", "").strip()
    account_id = payload.get("account_id", "").strip()
    access_key_id = payload.get("access_key_id", "").strip()
    secret_access_key = payload.get("secret_access_key", "").strip()
    bucket = payload.get("bucket", "").strip()

    if (
        not label
        or not account_id
        or not access_key_id
        or not secret_access_key
        or not bucket
    ):
        raise HTTPException(
            status_code=422, detail="All storage configuration fields are required."
        )

    if len(secret_access_key) < 8:
        raise HTTPException(
            status_code=422, detail="Secret access key must be at least 8 characters."
        )

    # Always test the connection before persisting — a bad config must never be
    # saved as 'active' only to break every subsequent upload silently. boto3 is
    # synchronous, so run it off the event loop — otherwise this blocks every
    # other in-flight request for the duration of the network round-trip to R2.
    ok, detail = await asyncio.to_thread(
        test_r2_connection, account_id, access_key_id, secret_access_key, bucket
    )
    if not ok:
        raise HTTPException(
            status_code=422, detail=f"Connection test failed: {detail}"
        )

    enc = encrypt_secret(secret_access_key)
    new_id = uuid.uuid4()
    secret_last4 = secret_access_key[-4:]

    sql = text("""
        INSERT INTO public.storage_config (
            id, created_at, updated_at, provider, label, account_id, access_key_id, bucket,
            secret_ciphertext, secret_iv, secret_auth_tag, secret_last4, status, created_by
        ) VALUES (
            :id, NOW(), NOW(), :provider, :label, :account_id, :access_key_id, :bucket,
            :ciphertext, :iv, :auth_tag, :secret_last4, 'active', :created_by
        )
    """)
    await db.execute(
        sql,
        {
            "id": new_id,
            "provider": provider,
            "label": label,
            "account_id": account_id,
            "access_key_id": access_key_id,
            "bucket": bucket,
            "ciphertext": enc["ciphertext"],
            "iv": enc["iv"],
            "auth_tag": enc["authTag"],
            "secret_last4": secret_last4,
            "created_by": admin.id,
        },
    )
    await db.commit()
    invalidate_storage_config_cache()

    ip = request.client.host if request.client else None
    agent = request.headers.get("user-agent")
    await write_audit_log(
        db,
        actor_id=admin.id,
        actor_email=admin.email,
        action="storage_config.create",
        target_type="storage_config",
        target_id=str(new_id),
        metadata={"provider": provider, "bucket": bucket},
        ip_address=ip,
        user_agent=agent,
    )
    await db.commit()

    return {"id": str(new_id), "status": "active", "secret_last4": secret_last4}


@router.patch("/storage/{id}")
async def update_storage_config(
    id: uuid.UUID,
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    status_val = payload.get("status")
    if status_val not in ["active", "disabled"]:
        raise HTTPException(
            status_code=422, detail="status must be 'active' or 'disabled'."
        )

    sql = text(
        "UPDATE public.storage_config SET status = :status, disabled_reason = :reason, updated_at = NOW() WHERE id = :id"
    )
    await db.execute(
        sql, {"status": status_val, "reason": payload.get("disabled_reason"), "id": id}
    )
    await db.commit()
    invalidate_storage_config_cache()

    ip = request.client.host if request.client else None
    agent = request.headers.get("user-agent")
    await write_audit_log(
        db,
        actor_id=admin.id,
        actor_email=admin.email,
        action=f"storage_config.{status_val}",
        target_type="storage_config",
        target_id=str(id),
        metadata={"status": status_val},
        ip_address=ip,
        user_agent=agent,
    )
    await db.commit()

    return {"ok": True}


@router.delete("/storage/{id}")
async def delete_storage_config(
    id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    await db.execute(
        text("DELETE FROM public.storage_config WHERE id = :id"), {"id": id}
    )
    await db.commit()
    invalidate_storage_config_cache()

    ip = request.client.host if request.client else None
    agent = request.headers.get("user-agent")
    await write_audit_log(
        db,
        actor_id=admin.id,
        actor_email=admin.email,
        action="storage_config.delete",
        target_type="storage_config",
        target_id=str(id),
        metadata={},
        ip_address=ip,
        user_agent=agent,
    )
    await db.commit()

    return {"ok": True}


# ── Storage Orphan Scan & Cleanup ─────────────────────────────────────────────
# Local-disk primary: files live under uploads/<user_id>/<file>. R2 orphan
# scanning isn't implemented here since this deployment defaults to local disk
# (see services/storage.py) — only local files are covered.

UPLOADS_ROOT = "uploads"
ORPHAN_SCAN_CAP = 10000


@router.get("/storage/orphans")
async def list_storage_orphans(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    disk_paths = []
    if os.path.isdir(UPLOADS_ROOT):
        for root, _dirs, files in os.walk(UPLOADS_ROOT):
            for fname in files:
                disk_paths.append(os.path.relpath(os.path.join(root, fname)).replace("\\", "/"))
                if len(disk_paths) >= ORPHAN_SCAN_CAP:
                    break
            if len(disk_paths) >= ORPHAN_SCAN_CAP:
                break

    res = await db.execute(text("SELECT audio_path FROM public.meetings WHERE audio_path IS NOT NULL"))
    db_paths = {row[0].replace("\\", "/") for row in res.fetchall() if row[0]}
    # Also match by basename, in case audio_path was stored without the "uploads/" prefix
    db_basenames = {p.rsplit("/", 1)[-1] for p in db_paths}

    orphans = [
        p for p in disk_paths
        if p not in db_paths and p.rsplit("/", 1)[-1] not in db_basenames
    ]

    return {"orphans": orphans, "count": len(orphans), "scanCapped": len(disk_paths) >= ORPHAN_SCAN_CAP}


class StorageCleanupRequest(BaseModel):
    paths: list[str]


@router.post("/storage/cleanup")
async def cleanup_storage_orphans(
    payload: StorageCleanupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if not payload.paths:
        raise HTTPException(status_code=422, detail="paths must be a non-empty list.")
    if len(payload.paths) > 500:
        raise HTTPException(
            status_code=422, detail="Cannot clean up more than 500 paths per request."
        )

    root_abs = os.path.abspath(UPLOADS_ROOT)
    deleted = 0
    errors = []
    for rel_path in payload.paths:
        # Reject anything that would escape the uploads root (path traversal).
        candidate_abs = os.path.abspath(os.path.join(".", rel_path))
        if not candidate_abs.startswith(root_abs):
            errors.append(f"{rel_path}: outside uploads root, skipped")
            continue
        try:
            if os.path.isfile(candidate_abs):
                os.remove(candidate_abs)
                deleted += 1
        except Exception as e:
            errors.append(f"{rel_path}: {e}")

    ip = request.client.host if request.client else None
    agent = request.headers.get("user-agent")
    await write_audit_log(
        db,
        actor_id=admin.id,
        actor_email=admin.email,
        action="storage.cleanup",
        target_type="storage",
        target_id="",
        metadata={"deletedCount": deleted, "requestedCount": len(payload.paths)},
        ip_address=ip,
        user_agent=agent,
    )
    await db.commit()

    return {"deleted": deleted, "errors": errors or None}
