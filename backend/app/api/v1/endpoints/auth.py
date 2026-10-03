"""Authentication endpoints with HttpOnly session cookies."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.dependencies.auth import AuthContext, club_permissions, get_current_auth, get_optional_auth, require_csrf
from app.models import Club, ClubMember
from app.schemas.auth import LoginIn, MeOut, RegisterIn
from app.schemas.common import ClubContextOut, ClubOut, MessageOut, UserOut
from app.services.auth_service import authenticate_user, create_session, register_user, revoke_session
from app.services.membership_eligibility import has_active_membership

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_auth_cookies(response: Response, *, raw_token: str, csrf: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf,
        httponly=False,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=settings.session_ttl_hours * 3600,
        path="/",
    )


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


def build_me(db: Session, auth: AuthContext) -> MeOut:
    memberships = db.scalars(select(ClubMember).where(ClubMember.user_id == auth.user.id)).all()
    clubs_out: list[ClubContextOut] = []
    for membership in memberships:
        club = db.get(Club, membership.club_id)
        if club is None or not club.is_active:
            continue
        clubs_out.append(
            ClubContextOut(
                club=ClubOut.model_validate(club),
                permissions=club_permissions(db, club.id, auth.user.id),
                is_member=True,
                has_active_membership=has_active_membership(
                    db, club_id=club.id, user_id=auth.user.id
                ),
            )
        )
    return MeOut(
        user=UserOut.model_validate(auth.user),
        csrf_token=auth.session.csrf_token,
        clubs=clubs_out,
    )


@router.post("/register", response_model=MeOut)
def register(
    payload: RegisterIn,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MeOut:
    user = register_user(
        db, email=payload.email, password=payload.password, full_name=payload.full_name
    )
    session, raw = create_session(db, user=user, settings=settings)
    db.commit()
    _set_auth_cookies(response, raw_token=raw, csrf=session.csrf_token, settings=settings)
    auth = AuthContext(user=user, session=session, settings=settings)
    return build_me(db, auth)


@router.post("/login", response_model=MeOut)
def login(
    payload: LoginIn,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MeOut:
    user = authenticate_user(db, email=payload.email, password=payload.password)
    session, raw = create_session(db, user=user, settings=settings)
    db.commit()
    _set_auth_cookies(response, raw_token=raw, csrf=session.csrf_token, settings=settings)
    return build_me(db, AuthContext(user=user, session=session, settings=settings))


@router.post("/logout", response_model=MessageOut)
def logout(
    response: Response,
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageOut:
    revoke_session(db, session=auth.session)
    db.commit()
    _clear_auth_cookies(response, settings)
    return MessageOut(message="Logged out.")


@router.get("/me", response_model=MeOut)
def me(auth: AuthContext = Depends(get_current_auth), db: Session = Depends(get_db)) -> MeOut:
    return build_me(db, auth)
