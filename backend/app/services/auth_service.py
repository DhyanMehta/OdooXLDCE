"""Registration, login, logout, and session cookies."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, UnauthorizedError
from app.core.security import generate_token, hash_password, hash_token, verify_password
from app.models import AuthSession, ClubMember, User
from app.services.audit import record_audit


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def register_user(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str,
) -> User:
    normalized = email.strip().lower()
    existing = db.scalar(select(User).where(User.email == normalized))
    if existing:
        raise AppError("An account with this email already exists.", code="email_taken", status_code=409)
    user = User(
        email=normalized,
        password_hash=hash_password(password),
        full_name=full_name.strip(),
    )
    db.add(user)
    db.flush()
    return user


def authenticate_user(db: Session, *, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise UnauthorizedError("Invalid email or password.")
    return user


def create_session(db: Session, *, user: User, settings: Settings) -> tuple[AuthSession, str]:
    raw_token = generate_token(32)
    csrf = generate_token(24)
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        csrf_token=csrf,
        expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(session)
    db.flush()
    return session, raw_token


def get_session_user(db: Session, *, raw_token: str | None) -> tuple[AuthSession, User] | None:
    if not raw_token:
        return None
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == hash_token(raw_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        )
    )
    if session is None:
        return None
    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    return session, user


def revoke_session(db: Session, *, session: AuthSession) -> None:
    session.revoked_at = utcnow()


def ensure_club_member(db: Session, *, club_id: uuid.UUID, user_id: uuid.UUID) -> ClubMember:
    member = db.scalar(
        select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == user_id)
    )
    if member:
        return member
    member = ClubMember(club_id=club_id, user_id=user_id)
    db.add(member)
    db.flush()
    record_audit(
        db,
        club_id=club_id,
        actor_user_id=user_id,
        action="club_member.joined",
        entity_type="club_member",
        entity_id=member.id,
    )
    return member
