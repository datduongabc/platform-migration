from fastapi import APIRouter

from . import audit, config, features, keys, pipeline, storage
from ._shared import require_admin

router = APIRouter()
router.include_router(pipeline.router)
router.include_router(keys.router)
router.include_router(storage.router)
router.include_router(config.router)
router.include_router(audit.router)
router.include_router(features.router)

__all__ = ["router", "require_admin"]
