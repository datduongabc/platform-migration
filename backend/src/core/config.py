import os
from typing import List

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

TARGET_ENV = os.getenv("FASTAPI_ENV", "development")
ENV_FILE_NAME = ".env.production" if TARGET_ENV == "production" else ".env.local"
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
RESOLVED_ENV_PATH = os.path.join(BASE_DIR, ENV_FILE_NAME)


class Settings(BaseSettings):
    PROJECT_NAME: str = "Platform Migration"
    ENVIRONMENT: str = TARGET_ENV
    API_V1_STR: str = ""

    JWT_SECRET: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    CORS_ORIGINS: List[str] = ["http://localhost:4200"]

    DATABASE_URL: str

    model_config = SettingsConfigDict(
        env_file=RESOLVED_ENV_PATH,
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
