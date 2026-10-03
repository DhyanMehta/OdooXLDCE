"""Authentication endpoints with HttpOnly session cookies."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.dependencies.auth import AuthContext, club_permissions, get_current_auth, require_csrf
from app.models import Club, ClubMember
from app.schemas.auth import LoginIn, MeOut, ProfilePatch, RegisterIn
from app.schemas.common import ClubContextOut, ClubOut, MessageOut, UserOut
from app.services.auth_service import (
    authenticate_user,
    create_session,
    register_user,
    revoke_session,
    update_profile,
)
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


async def build_me(db: AsyncSession, auth: AuthContext) -> MeOut:
    memberships = (await db.scalars(select(ClubMember).where(ClubMember.user_id == auth.user.id))).all()
    clubs_out: list[ClubContextOut] = []
    for membership in memberships:
        club = await db.get(Club, membership.club_id)
        if club is None or not club.is_active:
            continue
        clubs_out.append(
            ClubContextOut(
                club=ClubOut.model_validate(club),
                permissions=await club_permissions(db, club.id, auth.user.id),
                is_member=True,
                has_active_membership=await has_active_membership(
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
async def register(
    payload: RegisterIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MeOut:
    user = await register_user(
        db, email=payload.email, password=payload.password, full_name=payload.full_name
    )
    session, raw = await create_session(db, user=user, settings=settings)
    await db.commit()
    _set_auth_cookies(response, raw_token=raw, csrf=session.csrf_token, settings=settings)
    auth = AuthContext(user=user, session=session, settings=settings)
    return await build_me(db, auth)


@router.post("/login", response_model=MeOut)
async def login(
    payload: LoginIn,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MeOut:
    user = await authenticate_user(db, email=payload.email, password=payload.password)
    session, raw = await create_session(db, user=user, settings=settings)
    await db.commit()
    _set_auth_cookies(response, raw_token=raw, csrf=session.csrf_token, settings=settings)
    return await build_me(db, AuthContext(user=user, session=session, settings=settings))


@router.post("/logout", response_model=MessageOut)
async def logout(
    response: Response,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> MessageOut:
    await revoke_session(db, session=auth.session)
    await db.commit()
    _clear_auth_cookies(response, settings)
    return MessageOut(message="Logged out.")


@router.get("/me", response_model=MeOut)
async def me(auth: AuthContext = Depends(get_current_auth), db: AsyncSession = Depends(get_db)) -> MeOut:
    return await build_me(db, auth)


@router.patch("/me", response_model=MeOut)
async def patch_me(
    payload: ProfilePatch,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> MeOut:
    await update_profile(
        db,
        user=auth.user,
        full_name=payload.full_name,
        email=str(payload.email) if payload.email else None,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    await db.commit()
    await db.refresh(auth.user)
    return await build_me(db, auth)
