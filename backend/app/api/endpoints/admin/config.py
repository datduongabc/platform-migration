import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.services.ai.registry import list_registered_ai_models
from app.services.ai.resolve import is_model_allowed, load_generation_config
from app.services.audit import write_audit_log

from ._shared import require_admin

router = APIRouter()


# ── System & Generation Config Endpoints ─────────────────────────────────────


@router.get("/config")
async def get_app_config(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    res = await db.execute(
        text(
            "SELECT key, value, description, updated_at FROM public.app_config ORDER BY key ASC"
        )
    )
    rows = res.fetchall()
    return {
        "configs": [
            {
                "key": r[0],
                "value": r[1],
                "description": r[2],
                "updated_at": r[3].isoformat() if r[3] else None,
            }
            for r in rows
        ]
    }


def _is_valid_config_value(value) -> bool:
    """Primitives only (bool/int/float/str/None) — objects/arrays are rejected so
    app_config stays a flat key-value store, matching what the admin UI can render
    as a single input field."""
    return value is None or isinstance(value, (bool, int, float, str))


@router.patch("/config")
async def update_app_config(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    key = payload.get("key")
    value = payload.get("value")
    if not key or value is None:
        raise HTTPException(status_code=422, detail="key and value are required.")
    if not _is_valid_config_value(value):
        raise HTTPException(
            status_code=422, detail="value must be a boolean, number, string, or null."
        )

    # Unlike provider keys / generation-config, nothing in this codebase reads
    # app_config yet and no migration seeds any keys into it — it's a general
    # admin-managed key/value store, so upsert-by-key (rather than requiring the
    # key to pre-exist) is the correct behavior here, not a validation gap.
    sql = text("""
        INSERT INTO public.app_config (key, value, updated_at, updated_by)
        VALUES (:key, :value, NOW(), :user_id)
        ON CONFLICT (key) DO UPDATE SET value = :value, updated_at = NOW(), updated_by = :user_id
    """)
    await db.execute(sql, {"key": key, "value": json.dumps(value), "user_id": admin.id})
    await db.commit()

    ip = request.client.host if request.client else None
    agent = request.headers.get("user-agent")
    await write_audit_log(
        db,
        actor_id=admin.id,
        actor_email=admin.email,
        action="config.update",
        target_type="app_config",
        target_id=key,
        metadata={"value": value},
        ip_address=ip,
        user_agent=agent,
    )
    await db.commit()

    return {"ok": True}


@router.get("/generation-config")
async def get_generation_config(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    # load_generation_config is the single source of truth for the fallback
    # shown when app_settings has no seeded row yet — kept in app/services/ai
    # so this admin view and the AIP-06 resolver (services/ai/resolve.py) can
    # never drift out of sync with each other again.
    system_default, allowed_models = await load_generation_config(db)
    registered_models = [
        {"provider": e.provider, "model": e.model} for e in list_registered_ai_models()
    ]
    return {
        "systemDefault": system_default,
        "allowedModels": allowed_models,
        "registeredModels": registered_models,
    }


@router.patch("/generation-config")
async def update_generation_config(
    payload: dict,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    registered = {(e.provider, e.model) for e in list_registered_ai_models()}
    new_allowed_models = payload.get("allowedModels")

    if "allowedModels" in payload:
        if not isinstance(new_allowed_models, list) or not new_allowed_models:
            raise HTTPException(
                status_code=400, detail="allowedModels must be a non-empty array."
            )
        for m in new_allowed_models:
            if (m.get("provider"), m.get("model")) not in registered:
                raise HTTPException(
                    status_code=400,
                    detail=f"{m.get('provider')}:{m.get('model')} is not in the provider registry.",
                )

    if "systemDefault" in payload:
        system_default = payload["systemDefault"]
        # Validate against the EFFECTIVE allow-list: the new one from this same
        # request if provided, else whatever is currently persisted — so an admin
        # can atomically replace the allow-list and set a default that's only
        # valid under the new list, in one call.
        effective_allowed = new_allowed_models
        if effective_allowed is None:
            _, effective_allowed = await load_generation_config(db)
        if not is_model_allowed(
            system_default.get("provider"), system_default.get("model"), effective_allowed
        ):
            raise HTTPException(
                status_code=400,
                detail="systemDefault must be one of the (new or current) allowed models.",
            )
        sql = text(
            "INSERT INTO public.app_settings (key, value, updated_at, updated_by) VALUES ('generation.system_default', :val, NOW(), :uid) ON CONFLICT (key) DO UPDATE SET value = :val, updated_at = NOW(), updated_by = :uid"
        )
        await db.execute(sql, {"val": json.dumps(system_default), "uid": admin.id})

    if "allowedModels" in payload:
        sql = text(
            "INSERT INTO public.app_settings (key, value, updated_at, updated_by) VALUES ('generation.allowed_models', :val, NOW(), :uid) ON CONFLICT (key) DO UPDATE SET value = :val, updated_at = NOW(), updated_by = :uid"
        )
        await db.execute(
            sql, {"val": json.dumps(new_allowed_models), "uid": admin.id}
        )

    await db.commit()

    ip = request.client.host if request.client else None
    agent = request.headers.get("user-agent")
    await write_audit_log(
        db,
        actor_id=admin.id,
        actor_email=admin.email,
        action="generation_config.update",
        target_type="app_settings",
        target_id="generation",
        metadata={k: payload[k] for k in ("systemDefault", "allowedModels") if k in payload},
        ip_address=ip,
        user_agent=agent,
    )
    await db.commit()

    return await get_generation_config(db=db, admin=admin)
