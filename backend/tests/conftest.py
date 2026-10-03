"""PostgreSQL-backed pytest fixtures."""

from __future__ import annotations

import uuid
from collections.abc import Generator
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.permissions import RoleCode
from app.core.security import hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Club, ClubMember, ClubRoleAssignment, Role, User
from app.services.membership_eligibility import utcnow

TEST_PASSWORD = "Password123!"


@pytest.fixture(scope="session")
def engine():
    settings = get_settings()
    # Use a dedicated schema/database suffix via search_path alternate DB name if available.
    url = settings.database_url
    if url.endswith("/campusos"):
        url = url[:-len("campusos")] + "campusos_test"
    eng = create_engine(url, pool_pre_ping=True)
    # Create DB if missing.
    admin = create_engine(settings.database_url.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname='campusos_test'")).scalar()
        if not exists:
            conn.execute(text("CREATE DATABASE campusos_test"))
    admin.dispose()
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture
def db(engine) -> Generator[Session, None, None]:
    connection = engine.connect()
    transaction = connection.begin()
    SessionTesting = sessionmaker(bind=connection, autoflush=False, autocommit=False)
    session = SessionTesting()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db: Session) -> Generator[TestClient, None, None]:
    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def world(db: Session):
    now = utcnow()
    roles = {}
    for code, name in [
        (RoleCode.CLUB_ADMIN.value, "Admin"),
        (RoleCode.MEMBERSHIP_MANAGER.value, "Membership"),
        (RoleCode.EVENT_ORGANIZER.value, "Events"),
        (RoleCode.COMMUNICATIONS_OFFICER.value, "Comms"),
    ]:
        role = Role(code=code, name=name)
        db.add(role)
        roles[code] = role
    db.flush()

    club_a = Club(slug=f"club-a-{uuid.uuid4().hex[:8]}", name="Club A", description="A")
    club_b = Club(slug=f"club-b-{uuid.uuid4().hex[:8]}", name="Club B", description="B")
    db.add_all([club_a, club_b])
    db.flush()

    def make_user(email: str, name: str) -> User:
        user = User(email=email, full_name=name, password_hash=hash_password(TEST_PASSWORD))
        db.add(user)
        db.flush()
        return user

    admin = make_user(f"admin-{uuid.uuid4().hex[:6]}@test.edu", "Admin")
    member = make_user(f"member-{uuid.uuid4().hex[:6]}@test.edu", "Member")
    other = make_user(f"other-{uuid.uuid4().hex[:6]}@test.edu", "Other")

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
    db.flush()
    return {
        "club_a": club_a,
        "club_b": club_b,
        "admin": admin,
        "member": member,
        "other": other,
        "roles": roles,
        "password": TEST_PASSWORD,
    }


def login(client: TestClient, email: str, password: str = TEST_PASSWORD):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    csrf = response.json()["csrf_token"]
    return {"X-CSRF-Token": csrf}
