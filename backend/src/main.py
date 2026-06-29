from fastapi import Depends, FastAPI, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db

app = FastAPI(title="Platform Migration Backend")


@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check_endpoint(db: AsyncSession = Depends(get_db)) -> JSONResponse:

    try:
        result = await db.execute(text("SELECT 1"))
        result.scalar()

        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "healthy",
                "database_connection": "connected",
                "provider": "Supabase Cloud PostgreSQL",
            },
        )

    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "unhealthy",
                "database_connection": "disconnected",
                "error_detail": str(e),
            },
        )
