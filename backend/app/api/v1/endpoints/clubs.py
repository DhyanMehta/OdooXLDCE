from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.db.session import get_db
from app.dependencies.auth import AuthContext, club_permissions, get_optional_auth
from app.models import Club, ClubMember
from app.schemas.common import ClubContextOut, ClubOut
from app.services.membership_eligibility import has_active_membership

router = APIRouter(tags=["clubs"])


@router.get("/clubs", response_model=list[ClubOut])
def list_clubs(db: Session = Depends(get_db)) -> list[Club]:
    return list(db.scalars(select(Club).where(Club.is_active.is_(True)).order_by(Club.name)).all())


@router.get("/clubs/by-slug/{slug}", response_model=ClubContextOut)
def get_club_by_slug(
    slug: str,
    db: Session = Depends(get_db),
    auth: AuthContext | None = Depends(get_optional_auth),
) -> ClubContextOut:
    club = db.scalar(select(Club).where(Club.slug == slug, Club.is_active.is_(True)))
    if club is None:
        raise NotFoundError("Club not found.")
    user_id = auth.user.id if auth else None
    is_member = False
    if user_id:
        is_member = (
            db.scalar(
                select(ClubMember).where(
                    ClubMember.club_id == club.id, ClubMember.user_id == user_id
                )
            )
            is not None
        )
    return ClubContextOut(
        club=ClubOut.model_validate(club),
        permissions=club_permissions(db, club.id, user_id) if user_id else [],
        is_member=is_member,
        has_active_membership=bool(user_id)
        and has_active_membership(db, club_id=club.id, user_id=user_id),
    )
