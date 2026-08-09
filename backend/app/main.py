import asyncio
import logging
import ssl
import urllib.error
import urllib.request
from contextlib import asynccontextmanager

from app.api.deps import get_current_admin
from app.core.config import settings
from app.core.database import async_session_factory
from app.core.limiter import limiter
from app.services.jobs import run_worker_loop
from fastapi import Depends, FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text


import uuid
import app.models  # Ensures all SQLAlchemy models are registered
from app.core.database import Base, engine
from app.core.security import get_password_hash
from app.models.user import User

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize DB schema and create tables if they do not exist. Real
    # failures here (unreachable DB, bad credentials) must not be swallowed —
    # a backend that "starts" without a schema just 500s on every request
    # instead of failing visibly where docker-compose/orchestration can restart
    # or alert on it.
    async with engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS auth;"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto;"))
        await conn.run_sync(Base.metadata.create_all)

    # 2. Seed a default admin only if BOTH env vars are explicitly set — no
    # fixed default account. See Settings.SEED_DEFAULT_ADMIN_EMAIL.
    if settings.SEED_DEFAULT_ADMIN_EMAIL and settings.SEED_DEFAULT_ADMIN_PASSWORD:
        async with async_session_factory() as db:
            result = await db.execute(text("SELECT COUNT(*) FROM auth.users"))
            count = result.scalar()
            if count == 0:
                admin_id = uuid.uuid4()
                hashed_pw = get_password_hash(settings.SEED_DEFAULT_ADMIN_PASSWORD)
                db_user = User(
                    id=admin_id,
                    email=settings.SEED_DEFAULT_ADMIN_EMAIL,
                    encrypted_password=hashed_pw,
                )
                db.add(db_user)
                await db.commit()
                # handle_new_user() (migrations/003) fires on this insert and
                # creates the matching profiles row with role='user' — flip it
                # to admin so the seeded account is actually usable as one.
                await db.execute(
                    text("UPDATE public.profiles SET role = 'admin' WHERE id = :id"),
                    {"id": admin_id},
                )
                await db.commit()
                logger.warning(
                    f"Seeded initial admin user {settings.SEED_DEFAULT_ADMIN_EMAIL} "
                    "from SEED_DEFAULT_ADMIN_EMAIL/PASSWORD — unset these env vars "
                    "now that the account exists."
                )

    # 3. Start background job worker loop
    worker_task = asyncio.create_task(run_worker_loop())
    yield
    worker_task.cancel()


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    lifespan=lifespan,
)

# Set up rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Set up CORS middleware to allow requests from frontend SPA. Origins come from
# settings.ALLOWED_ORIGINS (env-configurable) — defaults to local dev hosts, but
# a real deploy sets ALLOWED_ORIGINS in .env to its actual frontend domain(s)
# rather than needing a code change here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Compress JSON responses over the wire — admin list endpoints (audit logs,
# pipeline jobs, transcripts) can return large payloads uncompressed otherwise.
app.add_middleware(GZipMiddleware, minimum_size=1000)

from app.api.endpoints import (
    admin,
    auth,
    chat,
    folders,
    profile,
    projects,
    quota,
    rag,
    users,
)
from fastapi.staticfiles import StaticFiles
import os

# Include endpoint routers under /api (for direct legacy client calls) and /api/v1
routers = [
    (auth.router, "/auth", "Authentication"),
    (users.router, "", "User Management"),
    (admin.router, "/admin", "Admin Control Center"),
    (projects.router, "", "Meetings & Projects"),
    (folders.router, "", "Folder Management & Sharing"),
    (chat.router, "", "Interactive Chat & RAG"),
    (profile.router, "", "Profile & Preferences"),
    (quota.router, "", "Quota Management"),
    (rag.router, "", "RAG & Meeting Q&A"),
]

for router_obj, sub_prefix, tag in routers:
    # 1. Mount under /api/v1 (Primary API prefix used by frontend and client)
    app.include_router(router_obj, prefix=f"/api/v1{sub_prefix}", tags=[f"{tag} (v1)"])
    # 2. Mount under /api (Legacy /api prefix)
    app.include_router(router_obj, prefix=f"/api{sub_prefix}", tags=[tag])
    # 3. Mount under root / (Direct endpoint prefix)
    app.include_router(router_obj, prefix=sub_prefix, tags=[tag])

# Mount local uploads static files
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/api/v1/uploads", StaticFiles(directory="uploads"), name="api_v1_uploads")
app.mount("/api/uploads", StaticFiles(directory="uploads"), name="api_uploads")


@app.get("/")
def read_root():
    return {"status": "ok", "message": "Welcome to the Platform Migration API"}


@app.get("/healthz")
async def liveness_check(response: Response):
    """
    Unauthenticated liveness/readiness probe for docker HEALTHCHECK and
    orchestration — deliberately separate from /health (admin-gated, returns
    diagnostic detail). This only confirms the process is up and the DB is
    reachable; it returns no sensitive information.
    """
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "error"}


@app.get("/health")
async def health_check(response: Response, admin: User = Depends(get_current_admin)):
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))

        return {
            "status": "ok",
            "message": "Database connection successful",
        }
    except Exception as e:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {
            "status": "error",
            "message": f"Database connection failed: {str(e)}",
        }


@app.get("/gemini")
async def gemini_check(response: Response, admin: User = Depends(get_current_admin)):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={settings.GEMINI_API_KEY}&pageSize=1"

        def probe():
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(url, timeout=8, context=context) as res:
                return res.status

        status_code = await asyncio.to_thread(probe)

        if status_code == 200:
            return {"status": "ok", "message": "Gemini connection successful"}
    except Exception as e:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {"status": "error", "message": f"Gemini connection failed: {str(e)}"}


@app.get("/speechmatics")
async def speechmatics_check(
    response: Response, admin: User = Depends(get_current_admin)
):
    try:
        url = "https://asr.api.speechmatics.com/v2/jobs?limit=1"

        def probe():
            req = urllib.request.Request(url)
            req.add_header("Authorization", f"Bearer {settings.SPEECHMATICS_API_KEY}")
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=8, context=context) as res:
                return res.status

        status_code = await asyncio.to_thread(probe)

        if status_code == 200:
            return {"status": "ok", "message": "Speechmatics connection successful"}
    except Exception as e:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return {
            "status": "error",
            "message": f"Speechmatics connection failed: {str(e)}",
        }
