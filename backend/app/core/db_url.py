"""Normalize PostgreSQL URLs for SQLAlchemy asyncpg without unsafe string surgery.

Distinguishes:
- SQLAlchemy asyncpg dialect arg ``prepared_statement_cache_size`` (SQLAlchemy LRU
  around asyncpg.prepare).
- asyncpg connect arg ``statement_cache_size`` (asyncpg's own prepared-statement LRU).

Disabling caches reduces prepared-statement conflicts behind transaction poolers
(e.g. PgBouncer transaction mode) but does not guarantee compatibility with every
pooler or version. Prefer session pooling or a pooler that tracks prepared
statements (PgBouncer >= 1.21 with max_prepared_statements) when possible.
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from sqlalchemy.engine.url import URL, make_url

# Query keys we intentionally support / map. Anything else is rejected.
_SUPPORTED_QUERY_KEYS = frozenset(
    {
        "sslmode",
        "ssl",
        "channel_binding",
        "application_name",
        "options",
        # SQLAlchemy asyncpg dialect (passed as connect arg via URL query).
        "prepared_statement_cache_size",
        # Hint consumed by our settings layer (not forwarded to the driver).
        "disable_prepared_statement_cache",
    }
)

_SSLMODE_REQUIRE = frozenset({"require", "verify-ca", "verify-full"})
_SSLMODE_DISABLE = frozenset({"disable", "allow", "prefer"})


class DatabaseURLError(ValueError):
    """Raised when a DATABASE_URL cannot be normalized for asyncpg."""


@dataclass(frozen=True)
class NormalizedDatabaseURL:
    """Driver URL plus connect_args for create_async_engine."""

    url: str
    connect_args: dict[str, Any]
    # True when caller asked for transaction-pooler-friendly cache disabling.
    prepared_statement_cache_disabled: bool


def _pop_query(url: URL, key: str) -> tuple[URL, str | None]:
    q = dict(url.query)
    value = q.pop(key, None)
    if value is None:
        return url, None
    # SQLAlchemy may give list values for repeated keys.
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    # update_query_dict({}) does not clear existing keys; set(query="") does.
    if not q:
        return url.set(query=""), None if value is None else str(value)
    return url.update_query_dict(q, append=False), None if value is None else str(value)


def normalize_async_database_url(
    raw: str,
    *,
    disable_prepared_statement_cache: bool = False,
) -> NormalizedDatabaseURL:
    """Accept provider-style postgres URLs; return postgresql+asyncpg URL + connect_args."""
    if not raw or not raw.strip():
        raise DatabaseURLError("DATABASE_URL is empty.")

    try:
        url = make_url(raw.strip())
    except Exception as exc:  # noqa: BLE001 — surface as configuration error
        raise DatabaseURLError(f"Invalid DATABASE_URL: {exc}") from exc

    driver = (url.drivername or "").lower()
    if driver in {"postgres", "postgresql", "postgresql+psycopg", "postgresql+psycopg2"}:
        url = url.set(drivername="postgresql+asyncpg")
    elif driver == "postgresql+asyncpg":
        pass
    else:
        raise DatabaseURLError(
            f"Unsupported database driver {url.drivername!r}. "
            "Use a PostgreSQL URL (postgresql:// or postgresql+asyncpg://)."
        )

    # Reject unknown query keys early (preserve credentials; do not log URL).
    unknown = sorted(k for k in url.query if k not in _SUPPORTED_QUERY_KEYS)
    if unknown:
        raise DatabaseURLError(
            "Unsupported DATABASE_URL query parameter(s): "
            + ", ".join(unknown)
            + ". Supported: "
            + ", ".join(sorted(_SUPPORTED_QUERY_KEYS))
            + "."
        )

    connect_args: dict[str, Any] = {}
    prepared_disabled = disable_prepared_statement_cache

    url, disable_flag = _pop_query(url, "disable_prepared_statement_cache")
    if disable_flag is not None and disable_flag.lower() in {"1", "true", "yes"}:
        prepared_disabled = True

    url, sslmode = _pop_query(url, "sslmode")
    url, ssl_flag = _pop_query(url, "ssl")
    # channel_binding is libpq-specific; drop rather than forward unsupported.
    url, _channel = _pop_query(url, "channel_binding")

    mode = (sslmode or "").lower()
    if ssl_flag is not None and ssl_flag.lower() in {"1", "true", "require"}:
        mode = mode or "require"

    if mode in _SSLMODE_REQUIRE:
        # verify-full needs a custom context + hostname checks; require uses TLS
        # without forcing CA verification (common for managed providers).
        if mode == "verify-full":
            ctx = ssl.create_default_context()
            connect_args["ssl"] = ctx
        elif mode == "verify-ca":
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            connect_args["ssl"] = ctx
        else:
            connect_args["ssl"] = True
    elif mode in _SSLMODE_DISABLE or mode == "":
        pass
    else:
        raise DatabaseURLError(
            f"Unsupported sslmode={mode!r}. "
            "Use disable, allow, prefer, require, verify-ca, or verify-full."
        )

    url, prep_cache = _pop_query(url, "prepared_statement_cache_size")
    if prepared_disabled:
        # SQLAlchemy dialect cache (connect arg name used by the asyncpg dialect).
        connect_args["prepared_statement_cache_size"] = 0
        # asyncpg's own statement cache — distinct from SQLAlchemy's setting.
        connect_args["statement_cache_size"] = 0
    elif prep_cache is not None:
        try:
            connect_args["prepared_statement_cache_size"] = int(prep_cache)
        except ValueError as exc:
            raise DatabaseURLError("prepared_statement_cache_size must be an integer.") from exc

    # Rebuild query string for remaining supported keys (application_name, options).
    remaining = {k: v for k, v in url.query.items() if k in {"application_name", "options"}}
    if remaining:
        # Flatten list values for urlencode.
        flat: list[tuple[str, str]] = []
        for key, value in remaining.items():
            if isinstance(value, (list, tuple)):
                for item in value:
                    flat.append((key, str(item)))
            else:
                flat.append((key, str(value)))
        url = url.set(query=urlencode(flat))
    else:
        # query=None is a no-op in SQLAlchemy URL; empty string clears query.
        url = url.set(query="")

    return NormalizedDatabaseURL(
        url=url.render_as_string(hide_password=False),
        connect_args=connect_args,
        prepared_statement_cache_disabled=prepared_disabled,
    )


def redacted_database_url(raw: str) -> str:
    """Safe for logs: never include password."""
    try:
        return make_url(raw).render_as_string(hide_password=True)
    except Exception:  # noqa: BLE001
        return "<unparseable DATABASE_URL>"
