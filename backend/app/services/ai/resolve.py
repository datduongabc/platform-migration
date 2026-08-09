import json
from typing import Optional

from app.services.ai.registry import list_registered_ai_models
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_SYSTEM_MODEL = {"provider": "gemini", "model": "gemini-3.5-flash-lite"}
# Single source of truth for the "app_settings has no seeded row yet" fallback —
# previously admin.py's GET /generation-config carried its own separate inline
# fallback list here, which drifted out of sync with this one (this file only
# offered the single system-default model, so the preferences dropdown showed
# just one choice until an admin explicitly saved a wider allow-list).
DEFAULT_ALLOWED_MODELS = [
    DEFAULT_SYSTEM_MODEL,
    {"provider": "gemini", "model": "gemini-3.5-flash"},
]


def is_model_allowed(provider: str, model: str, allowed_models: list[dict]) -> bool:
    in_allow_list = any(
        m.get("provider") == provider and m.get("model") == model
        for m in allowed_models
    )
    if not in_allow_list:
        return False
    registered = {(e.provider, e.model) for e in list_registered_ai_models()}
    return (provider, model) in registered


async def load_generation_config(db: AsyncSession) -> tuple[dict, list[dict]]:
    res = await db.execute(
        text(
            "SELECT key, value FROM public.app_settings WHERE key IN "
            "('generation.system_default', 'generation.allowed_models')"
        )
    )
    rows = {r[0]: r[1] for r in res.fetchall()}
    system_default = rows.get("generation.system_default") or DEFAULT_SYSTEM_MODEL
    allowed_models = rows.get("generation.allowed_models") or DEFAULT_ALLOWED_MODELS
    if isinstance(system_default, str):
        system_default = json.loads(system_default)
    if isinstance(allowed_models, str):
        allowed_models = json.loads(allowed_models)
    return system_default, allowed_models


async def resolve_generation_model(
    db: AsyncSession,
    user_id: Optional[str] = None,
    pick_provider: Optional[str] = None,
    pick_model: Optional[str] = None,
) -> tuple[str, str]:
    """
    3-tier fallback (ricotdin AIP-06 parity): explicit pick -> user's stored
    preference -> system default. Each tier is independently re-validated against
    the CURRENT allow-list — a stale pick or stale preference silently falls
    through to the next tier rather than erroring.
    """
    system_default, allowed_models = await load_generation_config(db)

    if pick_provider and pick_model and is_model_allowed(
        pick_provider, pick_model, allowed_models
    ):
        return pick_provider, pick_model

    if user_id:
        res = await db.execute(
            text(
                "SELECT default_provider, default_model FROM public.profiles WHERE id = :id"
            ),
            {"id": user_id},
        )
        row = res.mappings().first()
        if row and row["default_provider"] and row["default_model"]:
            if is_model_allowed(
                row["default_provider"], row["default_model"], allowed_models
            ):
                return row["default_provider"], row["default_model"]

    return system_default["provider"], system_default["model"]
