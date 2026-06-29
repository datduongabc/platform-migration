import os
from typing import List

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

FASTAPI_ENV = os.getenv("FASTAPI_ENV", "development")
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
ENV_FILE_NAME = ".env.production" if FASTAPI_ENV == "production" else ".env.local"


class Settings(BaseSettings):
    PROJECT_NAME: str = "Platform Migration"
    ENVIRONMENT: str = FASTAPI_ENV
    API_V1_STR: str = ""

    JWT_SECRET: str = os.getenv("JWT_SECRET", "your_jwt_secret_key")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 15)
    REFRESH_TOKEN_EXPIRE_DAYS: int = os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", 7)

    CORS_ORIGINS: List[str] = os.getenv("CORS_ORIGINS", ["http://localhost:4200"])

    DATABASE_URL: str = os.getenv("DATABASE_URL", "your_database_url")

    model_config = SettingsConfigDict(
        env_file=os.path.join(BASE_DIR, ENV_FILE_NAME),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()


@field_validator("DATABASE_URL", mode="before")
@classmethod
def validate_database_url(cls, v: str, info: ValidationInfo) -> str:
    if not v:
        raise ValueError("DATABASE_URL has not been configured in the .env file")

    if v.startswith("postgresql://"):
        return v.replace("postgresql://", "postgresql+asyncpg://", 1)

    return v


__all__ = ["settings"]
