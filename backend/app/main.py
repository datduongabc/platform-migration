import asyncio
import ssl
import urllib.error
import urllib.request

from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.api.endpoints import auth, projects, users
from app.core.config import settings
from app.core.database import async_session_factory
from app.core.limiter import limiter

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
)

# Set up rate limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Set up CORS middleware to allow requests from frontend SPA
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4200",
        "http://localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include endpoint routers
app.include_router(
    auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["Authentication"]
)
app.include_router(users.router, prefix=settings.API_V1_STR, tags=["User Management"])
app.include_router(
    projects.router, prefix=settings.API_V1_STR, tags=["Projects by User"]
)


@app.get("/")
def read_root():
    return {"status": "ok", "message": "Welcome to the Platform Migration API"}


@app.get("/health")
async def health_check(response: Response):
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
async def gemini_check(response: Response):
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
async def speechmatics_check(response: Response):
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
