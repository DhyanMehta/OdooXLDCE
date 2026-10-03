"""Membership plans, purchase dates, and renewals."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.models import Membership, MembershipPlan
from app.services.audit import record_audit
from app.services.membership_eligibility import get_active_membership, utcnow
from app.services.rbac import require_permission


def create_plan(
    db: Session,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    name: str,
    description: str,
    dues_amount: Decimal,
    duration_days: int | None,
    fixed_expires_on,
    is_active: bool = True,
) -> MembershipPlan:
    require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_plans")
    if (duration_days is None) == (fixed_expires_on is None):
        raise AppError("Provide either duration_days or fixed_expires_on, not both.")
    if dues_amount < 0:
        raise AppError("Dues amount cannot be negative.")
    plan = MembershipPlan(
        club_id=club_id,
        name=name.strip(),
        description=description.strip(),
        dues_amount=dues_amount,
        duration_days=duration_days,
        fixed_expires_on=fixed_expires_on,
        is_active=is_active,
    )
    db.add(plan)
    db.flush()
    record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="membership_plan.created",
        entity_type="membership_plan",
        entity_id=plan.id,
        details={"name": plan.name},
    )
    return plan


def update_plan(
    db: Session,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    plan_id: uuid.UUID,
    **fields,
) -> MembershipPlan:
    require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_plans")
    plan = db.get(MembershipPlan, plan_id)
    if plan is None or plan.club_id != club_id:
        raise NotFoundError("Membership plan not found.")
    for key, value in fields.items():
        if value is not None and hasattr(plan, key):
            setattr(plan, key, value)
    if (plan.duration_days is None) == (plan.fixed_expires_on is None):
        raise AppError("Provide either duration_days or fixed_expires_on, not both.")
    record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="membership_plan.updated",
        entity_type="membership_plan",
        entity_id=plan.id,
    )
    return plan


def compute_entitlement_window(
    db: Session,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    plan: MembershipPlan,
    now: datetime | None = None,
) -> tuple[datetime, datetime]:
    """Calculate entitlement dates at purchase confirmation.

    Duration renewal starts at the current entitlement end while still valid;
    otherwise it starts now. Fixed-period plans cannot be duplicated or bought
    after they would already be expired.
    """
    moment = now or utcnow()
    if plan.fixed_expires_on is not None:
        start = moment
        end = datetime(
            plan.fixed_expires_on.year,
            plan.fixed_expires_on.month,
            plan.fixed_expires_on.day,
            tzinfo=timezone.utc,
        )
        if end <= moment:
            raise AppError("This fixed-period plan has already expired and cannot be purchased.")
        existing = db.scalars(
            select(Membership).where(
                Membership.club_id == club_id,
                Membership.user_id == user_id,
                Membership.plan_id == plan.id,
                Membership.status == "active",
                Membership.ends_at == end,
            )
        ).first()
        if existing:
            raise AppError(
                "You already hold this fixed-period membership entitlement.",
                code="duplicate_fixed_membership",
            )
        return start, end

    assert plan.duration_days is not None
    current = get_active_membership(db, club_id=club_id, user_id=user_id, at=moment)
    # Renew from current end while valid so members are not penalized for early renewal.
    start = current.ends_at if current is not None else moment
    end = start + timedelta(days=plan.duration_days)
    return start, end


def issue_membership_from_order_item(
    db: Session,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    plan: MembershipPlan,
    order_item_id: uuid.UUID,
) -> Membership:
    starts_at, ends_at = compute_entitlement_window(
        db, club_id=club_id, user_id=user_id, plan=plan
    )
    membership = Membership(
        club_id=club_id,
        user_id=user_id,
        plan_id=plan.id,
        order_item_id=order_item_id,
        starts_at=starts_at,
        ends_at=ends_at,
        status="active",
    )
    db.add(membership)
    db.flush()
    return membership
