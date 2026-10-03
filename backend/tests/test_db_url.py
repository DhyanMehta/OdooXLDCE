"""Unit tests for async DATABASE_URL normalization."""

from __future__ import annotations

import pytest

from app.core.db_url import DatabaseURLError, normalize_async_database_url, redacted_database_url


def test_postgresql_scheme_becomes_asyncpg():
    result = normalize_async_database_url("postgresql://user:pass@localhost:5432/campusos")
    assert result.url.startswith("postgresql+asyncpg://")
    assert "localhost:5432/campusos" in result.url


def test_sslmode_require_sets_ssl_true():
    result = normalize_async_database_url(
        "postgresql://user:pass@localhost:5432/campusos?sslmode=require"
    )
    assert result.connect_args.get("ssl") is True
    assert "sslmode" not in result.url


def test_disable_prepared_statement_cache_flag():
    result = normalize_async_database_url(
        "postgresql+asyncpg://user:pass@localhost:5432/campusos"
        "?disable_prepared_statement_cache=true"
    )
    assert result.connect_args["statement_cache_size"] == 0
    assert result.connect_args["prepared_statement_cache_size"] == 0
    assert result.prepared_statement_cache_disabled is True


def test_disable_prepared_statement_cache_kwarg():
    result = normalize_async_database_url(
        "postgresql://user:pass@localhost:5432/campusos",
        disable_prepared_statement_cache=True,
    )
    assert result.connect_args["statement_cache_size"] == 0
    assert result.connect_args["prepared_statement_cache_size"] == 0


def test_unsupported_query_param_raises():
    with pytest.raises(DatabaseURLError, match="Unsupported DATABASE_URL query parameter"):
        normalize_async_database_url(
            "postgresql://user:pass@localhost:5432/campusos?connect_timeout=10"
        )


def test_password_not_in_redacted_database_url():
    raw = "postgresql://myuser:s3cret-pass@db.example:5432/campusos"
    redacted = redacted_database_url(raw)
    assert "s3cret-pass" not in redacted
    assert "myuser" in redacted
