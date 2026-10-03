"""FastAPI auth and CSRF dependencies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import ForbiddenError, NotFoundError, UnauthorizedError
from app.db.session import get_db
from app.models import AuthSession, Club, User
from app.services.auth_service import get_session_user
from app.services.rbac import effective_permissions, require_permission


@dataclass
class AuthContext:
    user: User
    session: AuthSession
    settings: Settings


def get_optional_auth(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthContext | None:
    raw = request.cookies.get(settings.session_cookie_name)
    result = get_session_user(db, raw_token=raw)
    if result is None:
        return None
    session, user = result
    return AuthContext(user=user, session=session, settings=settings)


def get_current_auth(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    raw = request.cookies.get(settings.session_cookie_name)
    result = get_session_user(db, raw_token=raw)
    if result is None:
        raise UnauthorizedError()
    session, user = result
    return AuthContext(user=user, session=session, settings=settings)


def require_csrf(
    request: Request,
    auth: AuthContext = Depends(get_current_auth),
    csrf_header: str | None = Header(default=None, alias="X-CSRF-Token"),
) -> AuthContext:
    """Double-submit CSRF: header must match session csrf token for mutating requests."""
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return auth
    if not csrf_header or csrf_header != auth.session.csrf_token:
        raise ForbiddenError("CSRF token missing or invalid.")
    return auth


def get_club(club_id: uuid.UUID, db: Session = Depends(get_db)) -> Club:
    club = db.get(Club, club_id)
    if club is None or not club.is_active:
        raise NotFoundError("Club not found.")
    return club


def require_club_permission(permission: str):
    def _dep(
        club: Club = Depends(get_club),
        auth: AuthContext = Depends(require_csrf),
        db: Session = Depends(get_db),
    ) -> tuple[Club, AuthContext]:
        require_permission(db, club_id=club.id, user_id=auth.user.id, permission=permission)
        return club, auth

    return _dep


def club_permissions(db: Session, club_id: uuid.UUID, user_id: uuid.UUID) -> list[str]:
    return effective_permissions(db, club_id=club_id, user_id=user_id)
