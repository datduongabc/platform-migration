from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

app = FastAPI(title="Platform Migration Backend")


@app.get("/api/health", status_code=status.HTTP_200_OK)
async def health_check_endpoint() -> JSONResponse:
    return JSONResponse(
        content={
            "status": "healthy",
        }
    )
