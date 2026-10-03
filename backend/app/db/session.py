"""Async SQLAlchemy engine and session factory (asyncpg).

Engine creation is lazy so schema-export and import-time tooling do not open
database connections. One AsyncSession per request or independent task — never
share a session across concurrent tasks.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_async_engine_from_settings(
    settings: Settings | None = None,
    *,
    worker: bool = False,
) -> AsyncEngine:
    """Build a new AsyncEngine from settings (caller owns lifecycle)."""
    cfg = settings or get_settings()
    normalized = cfg.async_database_url()
    return create_async_engine(normalized.url, **cfg.engine_kwargs(worker=worker))


def get_engine(*, settings: Settings | None = None) -> AsyncEngine:
    """Return the process-wide API async engine, creating it on first use."""
    global _engine, _session_factory
    if _engine is not None:
        return _engine
    _engine = create_async_engine_from_settings(settings, worker=False)
    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )
    return _engine


def get_session_factory(*, settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        get_engine(settings=settings)
    assert _session_factory is not None
    return _session_factory


async def dispose_engine() -> None:
    """Dispose the process-wide engine (API shutdown / tests)."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped session; rollback on error; always close."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()
