from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Platform Migration API"
    API_V1_STR: str = ""

    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://postgres.rqwemtphjjjpiiyqktco:[YOUR_PASSOWRD]@aws-1-ap-southeast-2.pooler.supabase.com:6543/postgres",
        validation_alias="DATABASE_URL",
    )

    SECRET_KEY: str = Field(
        default="1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
        validation_alias="SECRET_KEY",
    )

    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_WEEKS: int = 1

    # Cookie Settings
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"

    # Rate Limiting Settings
    RATELIMIT_DEFAULT: str = "100/minute"

    GEMINI_API_KEY: str = Field(
        default="1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
        validation_alias="GEMINI_API_KEY",
    )

    SPEECHMATICS_API_KEY: str = Field(
        default="1234567890abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
        validation_alias="SPEECHMATICS_API_KEY",
    )

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=True, extra="ignore"
    )


settings = Settings()
