"""Single eligibility function for paid membership validity.

Reused for member ticket pricing and members-only announcement access.

Effective (derived) states exposed to API clients:
- upcoming: status=active and starts_at > now
- active: status=active and starts_at <= now < ends_at
- expired: status=active and ends_at <= now (row kept; entitlement ended)
- revoked: status=revoked

Timezone: all membership timestamps are timezone-aware UTC.
Fixed-period plans advertised as valid through calendar date D (UTC) use an
exclusive end of D+1 00:00:00 UTC so the full day D remains valid.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import Select, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.models import Membership

EffectiveMembershipState = Literal["upcoming", "active", "expired", "revoked"]

__all__ = [
    "utcnow",
    "fixed_period_exclusive_end",
    "effective_membership_state",
    "active_membership_query",
    "has_active_membership",
    "get_active_membership",
    "lock_user_club_memberships",
    "continuous_entitlement_chain_end",
    "EffectiveMembershipState",
]


def fixed_period_exclusive_end(fixed_expires_on: date) -> datetime:
    """End of the advertised calendar day D in UTC (exclusive)."""
    start_of_day = datetime(
        fixed_expires_on.year,
        fixed_expires_on.month,
        fixed_expires_on.day,
        tzinfo=timezone.utc,
    )
    return start_of_day + timedelta(days=1)


def effective_membership_state(membership: Membership, *, at: datetime | None = None) -> EffectiveMembershipState:
    moment = at or utcnow()
    if membership.status == "revoked":
        return "revoked"
    if membership.starts_at > moment:
        return "upcoming"
    if membership.ends_at > moment:
        return "active"
    return "expired"


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


async def has_active_membership(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    at: datetime | None = None,
) -> bool:
    row = (await db.scalars(active_membership_query(club_id, user_id, at=at).limit(1))).first()
    return row is not None


async def get_active_membership(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    at: datetime | None = None,
) -> Membership | None:
    return (await db.scalars(active_membership_query(club_id, user_id, at=at).limit(1))).first()


async def lock_user_club_memberships(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[Membership]:
    """Serialize entitlement writes for one club member (renewal / issue).

    An advisory transaction lock is required because ``SELECT … FOR UPDATE`` on an
    empty membership set does not block concurrent first inserts.
    """
    # Stable 64-bit key from club/user UUIDs (two-int advisory lock).
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:k1, :k2)"),
        {"k1": club_id.int % (2**31 - 1), "k2": user_id.int % (2**31 - 1)},
    )
    return list(
        (
            await db.scalars(
                select(Membership)
                .where(Membership.club_id == club_id, Membership.user_id == user_id)
                .order_by(Membership.starts_at.asc())
                .with_for_update()
            )
        ).all()
    )


async def continuous_entitlement_chain_end(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    at: datetime | None = None,
) -> datetime | None:
    """Latest ends_at among non-revoked entitlements that still cover the future.

    Includes currently active *and* already-purchased future periods so early
    renewals stack after the whole continuous chain, not only "active today".
    """
    moment = at or utcnow()
    return await db.scalar(
        select(func.max(Membership.ends_at)).where(
            Membership.club_id == club_id,
            Membership.user_id == user_id,
            Membership.status == "active",
            Membership.ends_at > moment,
        )
    )
