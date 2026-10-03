from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db.session import get_db
from app.dependencies.auth import AuthContext, club_permissions, get_club, get_optional_auth, require_csrf
from app.models import Club, ClubMember
from app.schemas.common import ClubContextOut, ClubOut
from app.services.auth_service import ensure_club_member
from app.services.membership_eligibility import has_active_membership

router = APIRouter(tags=["clubs"])


async def _club_context(db: AsyncSession, club: Club, auth: AuthContext | None) -> ClubContextOut:
    user_id = auth.user.id if auth else None
    is_member = False
    if user_id:
        is_member = (
            await db.scalar(
                select(ClubMember).where(
                    ClubMember.club_id == club.id, ClubMember.user_id == user_id
                )
            )
            is not None
        )
    return ClubContextOut(
        club=ClubOut.model_validate(club),
        permissions=await club_permissions(db, club.id, user_id) if user_id else [],
        is_member=is_member,
        has_active_membership=bool(user_id)
        and await has_active_membership(db, club_id=club.id, user_id=user_id),
    )


@router.get("/clubs", response_model=list[ClubOut])
async def list_clubs(db: AsyncSession = Depends(get_db)) -> list[Club]:
    return list(
        (await db.scalars(select(Club).where(Club.is_active.is_(True)).order_by(Club.name))).all()
    )


@router.get("/clubs/by-slug/{slug}", response_model=ClubContextOut)
async def get_club_by_slug(
    slug: str,
    db: AsyncSession = Depends(get_db),
    auth: AuthContext | None = Depends(get_optional_auth),
) -> ClubContextOut:
    club = await db.scalar(select(Club).where(Club.slug == slug, Club.is_active.is_(True)))
    if club is None:
        raise NotFoundError("Club not found.")
    return await _club_context(db, club, auth)


@router.post("/clubs/{club_id}/join", response_model=ClubContextOut)
async def join_club(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> ClubContextOut:
    """Affiliate the authenticated user with the club (unpaid affiliation)."""
    await ensure_club_member(db, club_id=club.id, user_id=auth.user.id)
    await db.commit()
    return await _club_context(db, club, auth)
