"""Single eligibility function for paid membership validity.

Reused for member ticket pricing and members-only announcement access.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import Membership


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def active_membership_query(
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    at: datetime | None = None,
) -> Select[tuple[Membership]]:
    moment = at or utcnow()
    return (
        select(Membership)
        .where(
            Membership.club_id == club_id,
            Membership.user_id == user_id,
            Membership.status == "active",
            Membership.starts_at <= moment,
            Membership.ends_at > moment,
        )
        .order_by(Membership.ends_at.desc())
    )


def has_active_membership(
    db: Session,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    at: datetime | None = None,
) -> bool:
    row = db.scalars(active_membership_query(club_id, user_id, at=at).limit(1)).first()
    return row is not None


def get_active_membership(
    db: Session,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    at: datetime | None = None,
) -> Membership | None:
    return db.scalars(active_membership_query(club_id, user_id, at=at).limit(1)).first()
