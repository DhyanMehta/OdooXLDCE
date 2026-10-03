"""Async PostgreSQL pytest fixtures.

Safety rules
------------
- Require an explicit ``TEST_DATABASE_URL`` (env or settings).
- Refuse to run if the test DB name equals the application DB name.
- Allow only known test database names.
- Never auto-create databases (provider-safe).
- Apply schema via Alembic migrations.
- Per-test rollback via outer transaction + nested savepoints so endpoint
  commits do not leak across tests.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncGenerator
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.orm import Session

# Force non-production before settings are cached for demo-payment gating.
os.environ.setdefault("APP_ENV", "test")

from app.core.config import get_settings
from app.core.db_url import normalize_async_database_url
from app.core.permissions import RoleCode
from app.core.security import hash_password
from app.core.time import utcnow
from app.db.session import dispose_engine, get_db
from app.main import app
from app.models import Club, ClubMember, ClubRoleAssignment, Role, User

TEST_PASSWORD = "Password123!"
ALLOWED_TEST_DB_NAMES = frozenset({"campusos_test", "campusos_ci_test"})
REPO_ROOT = Path(__file__).resolve().parents[2]


def _database_name(url: str) -> str:
    normalized = normalize_async_database_url(url).url
    parsed = urlparse(normalized.replace("postgresql+asyncpg://", "postgresql://", 1))
    name = (parsed.path or "").lstrip("/")
    return name.split("?", 1)[0]


def resolve_test_database_url() -> tuple[str, str]:
    get_settings.cache_clear()
    settings = get_settings()
    test_url = os.environ.get("TEST_DATABASE_URL") or settings.test_database_url
    if not test_url:
        raise RuntimeError(
            "TEST_DATABASE_URL must be set explicitly to a dedicated test database "
            f"(allowed names: {sorted(ALLOWED_TEST_DB_NAMES)})."
        )
    app_name = _database_name(settings.database_url or "")
    test_name = _database_name(test_url)
    if not test_name or test_name in {"postgres", "template0", "template1"}:
        raise RuntimeError(f"Refusing unsafe test database name: {test_name!r}")
    if test_name == app_name:
        raise RuntimeError(
            f"TEST_DATABASE_URL database ({test_name!r}) must differ from DATABASE_URL ({app_name!r})."
        )
    if test_name not in ALLOWED_TEST_DB_NAMES:
        raise RuntimeError(
            f"Test database {test_name!r} is not in the allowlist {sorted(ALLOWED_TEST_DB_NAMES)}."
        )
    return test_url, test_name


def _normalized_test_url(raw: str) -> str:
    return normalize_async_database_url(raw).url


def _run_migrations(test_url: str) -> None:
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = test_url
    get_settings.cache_clear()
    try:
        cfg = Config(str(REPO_ROOT / "database" / "alembic.ini"))
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        get_settings.cache_clear()


@pytest.fixture(scope="session")
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    """Session-scoped async engine on the pytest-asyncio session loop (no asyncio.run)."""
    test_url, test_name = resolve_test_database_url()
    async_url = _normalized_test_url(test_url)
    assert _database_name(async_url) == test_name
    assert test_name in ALLOWED_TEST_DB_NAMES

    # Fail closed if the dedicated DB is missing — never CREATE DATABASE.
    probe = create_async_engine(async_url, pool_pre_ping=True)
    try:
        async with probe.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        await probe.dispose()
        raise RuntimeError(
            f"Cannot connect to test database {test_name!r}. "
            "Create it manually before running pytest; tests never auto-create databases."
        ) from exc
    await probe.dispose()

    # Alembic env uses asyncio.run; run it in a worker thread so it does not
    # collide with the pytest-asyncio session loop.
    await asyncio.to_thread(_run_migrations, test_url)
    eng = create_async_engine(async_url, pool_pre_ping=True)
    yield eng
    await eng.dispose()
    await dispose_engine()


@pytest.fixture
async def db(engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """Outer transaction + nested savepoint so request commits stay isolated."""
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.begin_nested()
        session = AsyncSession(bind=connection, expire_on_commit=False, autoflush=False)

        @event.listens_for(session.sync_session, "after_transaction_end")
        def _restart_savepoint(sync_session: Session, sync_transaction) -> None:
            if sync_transaction.nested and not sync_transaction._parent.nested:
                sync_session.begin_nested()

        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """httpx AsyncClient shares the pytest-asyncio loop with ``db`` (TestClient does not)."""

    async def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
async def world(db: AsyncSession):
    now = utcnow()
    roles = {}
    for code, name in [
        (RoleCode.CLUB_ADMIN.value, "Admin"),
        (RoleCode.MEMBERSHIP_MANAGER.value, "Membership"),
        (RoleCode.EVENT_ORGANIZER.value, "Events"),
        (RoleCode.COMMUNICATIONS_OFFICER.value, "Comms"),
    ]:
        role = await db.scalar(select(Role).where(Role.code == code))
        if role is None:
            role = Role(code=code, name=name)
            db.add(role)
            await db.flush()
        roles[code] = role

    club_a = Club(slug=f"club-a-{uuid.uuid4().hex[:8]}", name="Club A", description="A")
    club_b = Club(slug=f"club-b-{uuid.uuid4().hex[:8]}", name="Club B", description="B")
    db.add_all([club_a, club_b])
    await db.flush()

    async def make_user(email: str, name: str) -> User:
        user = User(email=email, full_name=name, password_hash=hash_password(TEST_PASSWORD))
        db.add(user)
        await db.flush()
        return user

    admin = await make_user(f"admin-{uuid.uuid4().hex[:6]}@test.edu", "Admin")
    member = await make_user(f"member-{uuid.uuid4().hex[:6]}@test.edu", "Member")
    other = await make_user(f"other-{uuid.uuid4().hex[:6]}@test.edu", "Other")

    for user in (admin, member, other):
        db.add(ClubMember(club_id=club_a.id, user_id=user.id))
    db.add(ClubMember(club_id=club_b.id, user_id=other.id))
    db.add(
        ClubRoleAssignment(
            club_id=club_a.id,
            user_id=admin.id,
            role_id=roles[RoleCode.CLUB_ADMIN.value].id,
            starts_at=now - timedelta(days=1),
        )
    )
    await db.flush()
    return {
        "club_a": club_a,
        "club_b": club_b,
        "admin": admin,
        "member": member,
        "other": other,
        "roles": roles,
        "password": TEST_PASSWORD,
    }


async def login(client: AsyncClient, email: str, password: str = TEST_PASSWORD):
    response = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    csrf = response.json()["csrf_token"]
    return {"X-CSRF-Token": csrf}
