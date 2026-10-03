"""Registration, login, logout, and session cookies."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, UnauthorizedError
from app.core.security import generate_token, hash_password, hash_token, verify_password
from app.core.time import utcnow
from app.models import AuthSession, ClubMember, User
from app.services.audit import record_audit


async def register_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str,
) -> User:
    normalized = email.strip().lower()
    existing = await db.scalar(select(User).where(User.email == normalized))
    if existing:
        raise AppError("An account with this email already exists.", code="email_taken", status_code=409)
    password_hash = await asyncio.to_thread(hash_password, password)
    user = User(
        email=normalized,
        password_hash=password_hash,
        full_name=full_name.strip(),
    )
    db.add(user)
    await db.flush()
    return user


async def authenticate_user(db: AsyncSession, *, email: str, password: str) -> User:
    user = await db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not user.is_active:
        raise UnauthorizedError("Invalid email or password.")
    ok = await asyncio.to_thread(verify_password, password, user.password_hash)
    if not ok:
        raise UnauthorizedError("Invalid email or password.")
    return user


async def create_session(db: AsyncSession, *, user: User, settings: Settings) -> tuple[AuthSession, str]:
    raw_token = generate_token(32)
    csrf = generate_token(24)
    session = AuthSession(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        csrf_token=csrf,
        expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(session)
    await db.flush()
    return session, raw_token


async def get_session_user(db: AsyncSession, *, raw_token: str | None) -> tuple[AuthSession, User] | None:
    if not raw_token:
        return None
    session = await db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == hash_token(raw_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > utcnow(),
        )
    )
    if session is None:
        return None
    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        return None
    return session, user


async def revoke_session(db: AsyncSession, *, session: AuthSession) -> None:
    session.revoked_at = utcnow()


async def update_profile(
    db: AsyncSession,
    *,
    user: User,
    full_name: str | None = None,
    email: str | None = None,
    current_password: str | None = None,
    new_password: str | None = None,
) -> User:
    if full_name is not None:
        user.full_name = full_name.strip()
    if email is not None and email.lower() != user.email:
        conflict = await db.scalar(select(User).where(User.email == email.lower()))
        if conflict and conflict.id != user.id:
            raise ConflictError("Email already in use.")
        user.email = email.lower()
    if new_password is not None:
        if not current_password:
            raise AppError("Current password is incorrect.", code="bad_password")
        ok = await asyncio.to_thread(verify_password, current_password, user.password_hash)
        if not ok:
            raise AppError("Current password is incorrect.", code="bad_password")
        user.password_hash = await asyncio.to_thread(hash_password, new_password)
    await db.flush()
    return user


async def ensure_club_member(db: AsyncSession, *, club_id: uuid.UUID, user_id: uuid.UUID) -> ClubMember:
    member = await db.scalar(
        select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == user_id)
    )
    if member:
        return member
    member = ClubMember(club_id=club_id, user_id=user_id)
    db.add(member)
    await db.flush()
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=user_id,
        action="club_member.joined",
        entity_type="club_member",
        entity_id=member.id,
    )
    return member
