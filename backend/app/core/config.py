"""Environment-based application settings."""

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.db_url import DatabaseURLError, NormalizedDatabaseURL, normalize_async_database_url

BACKEND_DIR = Path(__file__).resolve().parents[2]
BACKEND_ENV = BACKEND_DIR / ".env"

# Environments that may enable the labeled demo payment adapter.
_DEMO_ALLOWED_ENVS = frozenset({"development", "dev", "test", "testing", "local"})
_DEV_DEFAULT_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/campusos"


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
    # Canonical URL for app, worker, seed, and Alembic. No default outside development.
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    # Explicit test target only — never derived by mutating DATABASE_URL in fixtures.
    test_database_url: str | None = Field(default=None, alias="TEST_DATABASE_URL")
    secret_key: str = Field(
        default="campusos-dev-secret-change-me",
        alias="SECRET_KEY",
    )
    # Optional dedicated key for QR AEAD. When unset, derived from SECRET_KEY.
    qr_credential_key: str | None = Field(default=None, alias="QR_CREDENTIAL_KEY")
    session_cookie_name: str = Field(default="campusos_session", alias="SESSION_COOKIE_NAME")
    csrf_cookie_name: str = Field(default="campusos_csrf", alias="CSRF_COOKIE_NAME")
    session_ttl_hours: int = Field(default=72, alias="SESSION_TTL_HOURS")
    cookie_secure: bool = Field(default=False, alias="COOKIE_SECURE")
    cookie_samesite: str = Field(default="lax", alias="COOKIE_SAMESITE")
    # Demo payments require a non-production APP_ENV AND this flag (see demo_payments_allowed).
    demo_payments_enabled: bool = Field(default=True, alias="DEMO_PAYMENTS_ENABLED")
    reservation_minutes: int = Field(default=15, alias="RESERVATION_MINUTES")
    renewal_reminder_days: int = Field(default=14, alias="RENEWAL_REMINDER_DAYS")
    # Check-in allowed from (starts_at - before) through (ends_at + after), unless overridden.
    check_in_open_minutes_before: int = Field(default=60, alias="CHECK_IN_OPEN_MINUTES_BEFORE")
    check_in_close_minutes_after: int = Field(default=120, alias="CHECK_IN_CLOSE_MINUTES_AFTER")
    email_adapter: str = Field(default="dev", alias="EMAIL_ADAPTER")
    # Delivery polling interval when running with --loop.
    worker_interval_seconds: int = Field(default=30, alias="WORKER_INTERVAL_SECONDS")
    # Renewal reminder scan interval (independent of delivery polling).
    worker_reminder_interval_seconds: int = Field(
        default=300, alias="WORKER_REMINDER_INTERVAL_SECONDS"
    )
    # Abandoned processing claims older than this are requeued.
    worker_claim_seconds: int = Field(default=120, alias="WORKER_CLAIM_SECONDS")
    currency_code: str = Field(default="INR", alias="CURRENCY_CODE")

    # Expense receipt files live on local disk (operator must back this directory up).
    receipt_storage_dir: Path = Field(
        default=BACKEND_DIR / "app" / "var" / "receipts", alias="RECEIPT_STORAGE_DIR"
    )
    receipt_max_bytes: int = Field(default=5_000_000, alias="RECEIPT_MAX_BYTES")

    # Connection pool (SQLAlchemy QueuePool around asyncpg).
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")
    db_pool_recycle: int = Field(default=1800, alias="DB_POOL_RECYCLE")
    # When true, set both SQLAlchemy prepared_statement_cache_size=0 and
    # asyncpg statement_cache_size=0 (transaction-pooler-friendly).
    db_disable_prepared_statement_cache: bool = Field(
        default=False, alias="DB_DISABLE_PREPARED_STATEMENT_CACHE"
    )
    # Optional smaller pool for the notification worker process.
    worker_db_pool_size: int = Field(default=2, alias="WORKER_DB_POOL_SIZE")
    worker_db_max_overflow: int = Field(default=2, alias="WORKER_DB_MAX_OVERFLOW")

    @field_validator("app_env")
    @classmethod
    def _normalize_env(cls, value: str) -> str:
        return value.strip().lower()

    @model_validator(mode="after")
    def _resolve_database_url(self) -> "Settings":
        if self.database_url:
            return self
        if self.app_env in {"development", "dev", "local"}:
            self.database_url = _DEV_DEFAULT_URL
            return self
        raise ValueError(
            "DATABASE_URL is required when APP_ENV is not development/dev/local."
        )

    def is_production(self) -> bool:
        return self.app_env in {"production", "prod"}

    def demo_payments_allowed(self) -> bool:
        """Hard-disable demo adapter outside non-production environments."""
        if self.is_production() or self.app_env not in _DEMO_ALLOWED_ENVS:
            return False
        return self.demo_payments_enabled

    def async_database_url(self, raw: str | None = None) -> NormalizedDatabaseURL:
        """Normalize a URL (default: canonical DATABASE_URL) for asyncpg."""
        source = raw if raw is not None else self.database_url
        if not source:
            raise DatabaseURLError("DATABASE_URL is not configured.")
        return normalize_async_database_url(
            source,
            disable_prepared_statement_cache=self.db_disable_prepared_statement_cache,
        )

    def engine_kwargs(self, *, worker: bool = False) -> dict[str, Any]:
        """Keyword args for create_async_engine (excluding the URL)."""
        normalized = self.async_database_url()
        pool_size = self.worker_db_pool_size if worker else self.db_pool_size
        max_overflow = self.worker_db_max_overflow if worker else self.db_max_overflow
        return {
            "pool_pre_ping": True,
            "pool_size": pool_size,
            "max_overflow": max_overflow,
            "pool_timeout": self.db_pool_timeout,
            "pool_recycle": self.db_pool_recycle,
            "connect_args": normalized.connect_args,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
