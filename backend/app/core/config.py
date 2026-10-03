"""Environment-based application settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
BACKEND_ENV = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    """Runtime configuration loaded from environment / backend/.env file."""

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ENV),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field(default="CampusOS API", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
        alias="CORS_ORIGINS",
    )
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/campusos",
        alias="DATABASE_URL",
    )
    secret_key: str = Field(
        default="campusos-dev-secret-change-me",
        alias="SECRET_KEY",
    )
    session_cookie_name: str = Field(default="campusos_session", alias="SESSION_COOKIE_NAME")
    csrf_cookie_name: str = Field(default="campusos_csrf", alias="CSRF_COOKIE_NAME")
    session_ttl_hours: int = Field(default=72, alias="SESSION_TTL_HOURS")
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")
    cookie_samesite: str = Field(default="lax", alias="COOKIE_SAMESITE")
    demo_payments_enabled: bool = Field(default=True, alias="DEMO_PAYMENTS_ENABLED")
    reservation_minutes: int = Field(default=15, alias="RESERVATION_MINUTES")
    renewal_reminder_days: int = Field(default=14, alias="RENEWAL_REMINDER_DAYS")
    email_adapter: str = Field(default="dev", alias="EMAIL_ADAPTER")
    currency_code: str = Field(default="INR", alias="CURRENCY_CODE")


@lru_cache
def get_settings() -> Settings:
    return Settings()
