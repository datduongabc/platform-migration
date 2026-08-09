import logging
import secrets

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    PROJECT_NAME: str = "Platform Migration API"
    API_V1_STR: str = "/api/v1"

    # Local PostgreSQL by default (this project targets a local DB, not Supabase).
    # Matches docker-compose.yml's POSTGRES_DB — only used if DATABASE_URL is unset.
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/postgres",
        validation_alias="DATABASE_URL",
    )

    # Comma-separated list of browser origins allowed by CORS. Defaults to the
    # local dev hosts so nothing breaks out of the box; set this in .env to the
    # real frontend domain(s) for a production deploy.
    ALLOWED_ORIGINS: str = Field(
        default="http://localhost:4200,http://localhost,http://127.0.0.1:4200,http://127.0.0.1,http://localhost:3000,http://localhost:80",
        validation_alias="ALLOWED_ORIGINS",
    )

    # Both must be explicitly set for the startup admin-seed to run — there is no
    # fixed default account. A known email/password pair auto-created on every
    # fresh deploy is a standing credential any scanner can try; bootstrapping an
    # admin should be a deliberate one-time choice, not automatic.
    SEED_DEFAULT_ADMIN_EMAIL: str = Field(
        default="", validation_alias="SEED_DEFAULT_ADMIN_EMAIL"
    )
    SEED_DEFAULT_ADMIN_PASSWORD: str = Field(
        default="", validation_alias="SEED_DEFAULT_ADMIN_PASSWORD"
    )

    # No hardcoded default: a known, committed-to-source signing secret lets anyone
    # who has read this repo mint a valid access token for any user id. If unset,
    # _ensure_secret_key below generates a random per-process value instead.
    SECRET_KEY: str = Field(default="", validation_alias="SECRET_KEY")

    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_WEEKS: int = 1

    # Rate Limiting Settings
    RATELIMIT_DEFAULT: str = "100/minute"

    GEMINI_API_KEY: str = Field(default="", validation_alias="GEMINI_API_KEY")

    SPEECHMATICS_API_KEY: str = Field(
        default="", validation_alias="SPEECHMATICS_API_KEY"
    )

    # No hardcoded default here either: this key encrypts provider API keys and R2
    # secrets at rest (app/services/crypto.py). Unlike SECRET_KEY it must NOT be
    # auto-generated per process — anything already encrypted under a previous value
    # would become permanently undecryptable. Leave empty and let crypto.py fail
    # loudly the first time it's actually needed.
    KEY_ENCRYPTION_SECRET: str = Field(
        default="", validation_alias="KEY_ENCRYPTION_SECRET"
    )

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )

    @model_validator(mode="after")
    def _ensure_secret_key(self) -> "Settings":
        if not self.SECRET_KEY:
            logger.warning(
                "SECRET_KEY is not set in the environment — generating a random "
                "ephemeral secret for this process. Every issued token becomes "
                "invalid on restart, and this value MUST NOT be relied on across "
                "multiple instances or in production. Set SECRET_KEY in your .env."
            )
            self.SECRET_KEY = secrets.token_urlsafe(48)
        return self

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]


settings = Settings()
