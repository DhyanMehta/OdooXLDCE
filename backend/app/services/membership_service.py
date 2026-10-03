"""Membership plans, purchase dates, and renewals."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFoundError
from app.models import Membership, MembershipPlan, OrderItem
from app.services.audit import record_audit
from app.services.membership_eligibility import (
    continuous_entitlement_chain_end,
    fixed_period_exclusive_end,
    lock_user_club_memberships,
    utcnow,
)
from app.services.rbac import require_permission


async def create_plan(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    name: str,
    description: str,
    dues_amount: Decimal,
    duration_days: int | None,
    fixed_expires_on: date | None,
    is_active: bool = True,
) -> MembershipPlan:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_plans")
    if (duration_days is None) == (fixed_expires_on is None):
        raise AppError("Provide either duration_days or fixed_expires_on, not both.")
    if duration_days is not None and duration_days < 1:
        raise AppError("duration_days must be positive.")
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
    await db.flush()
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="membership_plan.created",
        entity_type="membership_plan",
        entity_id=plan.id,
        details={"name": plan.name},
    )
    return plan


async def update_plan(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    plan_id: uuid.UUID,
    fields: dict[str, Any],
) -> MembershipPlan:
    """Apply an explicit field set.

    Keys present in ``fields`` are written even when the value is ``None``,
    so clients can clear ``duration_days`` or ``fixed_expires_on`` when
    switching XOR sides. Keys omitted from ``fields`` are left unchanged.
    """
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_plans")
    plan = await db.get(MembershipPlan, plan_id)
    if plan is None or plan.club_id != club_id:
        raise NotFoundError("Membership plan not found.")

    # Translate UI "archived" flag into archived_at timestamp.
    if "archived" in fields:
        archived = fields.pop("archived")
        if archived is True and plan.archived_at is None:
            fields["archived_at"] = utcnow()
        elif archived is False:
            fields["archived_at"] = None

    allowed = {
        "name",
        "description",
        "dues_amount",
        "duration_days",
        "fixed_expires_on",
        "is_active",
        "archived_at",
    }
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "name" and value is not None:
            setattr(plan, key, str(value).strip())
        elif key == "description" and value is not None:
            setattr(plan, key, str(value).strip())
        else:
            setattr(plan, key, value)

    if (plan.duration_days is None) == (plan.fixed_expires_on is None):
        raise AppError("Provide either duration_days or fixed_expires_on, not both.")
    if plan.duration_days is not None and plan.duration_days < 1:
        raise AppError("duration_days must be positive.")
    if plan.dues_amount is not None and plan.dues_amount < 0:
        raise AppError("Dues amount cannot be negative.")

    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="membership_plan.updated",
        entity_type="membership_plan",
        entity_id=plan.id,
    )
    await db.flush()
    return plan


async def compute_entitlement_window(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    plan: MembershipPlan,
    now: datetime | None = None,
    order_item: OrderItem | None = None,
    lock: bool = True,
) -> tuple[datetime, datetime]:
    """Calculate entitlement dates for purchase / fulfillment.

    Duration renewals extend the continuous entitlement chain (active + future
    periods). Fixed-period purchases cannot duplicate an existing active row
    with the same exclusive end. Unsupported overlaps raise validation errors.

    When ``order_item`` is provided, term snapshots on the item are used and
    must not fall back to the live plan (plan edits after order creation).
    """
    moment = now or utcnow()
    if lock:
        await lock_user_club_memberships(db, club_id=club_id, user_id=user_id)

    if order_item is not None:
        dur = order_item.duration_days_snapshot
        fixed = order_item.fixed_expires_on_snapshot
    else:
        dur = plan.duration_days
        fixed = plan.fixed_expires_on

    if fixed is not None:
        if dur is not None:
            raise AppError("Plan terms must be duration XOR fixed-period.")
        start = moment
        end = fixed_period_exclusive_end(fixed)
        if end <= moment:
            raise AppError("This fixed-period plan has already expired and cannot be purchased.")
        existing = (
            await db.scalars(
                select(Membership).where(
                    Membership.club_id == club_id,
                    Membership.user_id == user_id,
                    Membership.plan_id == plan.id,
                    Membership.status == "active",
                    Membership.ends_at == end,
                )
            )
        ).first()
        if existing:
            raise AppError(
                "You already hold this fixed-period membership entitlement.",
                code="duplicate_fixed_membership",
            )
        overlap = (
            await db.scalars(
                select(Membership).where(
                    Membership.club_id == club_id,
                    Membership.user_id == user_id,
                    Membership.status == "active",
                    Membership.starts_at < end,
                    Membership.ends_at > start,
                )
            )
        ).first()
        if overlap:
            raise AppError(
                "This fixed-period purchase overlaps an existing entitlement.",
                code="membership_overlap",
            )
        return start, end

    if dur is None:
        raise AppError("Membership plan is missing duration terms.")
    if dur < 1:
        raise AppError("duration_days must be positive.")

    chain_end = await continuous_entitlement_chain_end(
        db, club_id=club_id, user_id=user_id, at=moment
    )
    # Renew from the end of the continuous chain so stacked future periods are respected.
    start = chain_end if chain_end is not None else moment
    end = start + timedelta(days=dur)
    return start, end


async def issue_membership_from_order_item(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    plan: MembershipPlan,
    order_item: OrderItem,
) -> Membership:
    """Fulfill using order-item term snapshots so mid-flight plan edits cannot change the purchase."""
    if order_item.membership_plan_id != plan.id:
        raise AppError("Order item plan mismatch during fulfillment.")
    if plan.club_id != club_id:
        raise AppError("Membership plan club mismatch.", code="cross_club_violation")

    starts_at, ends_at = await compute_entitlement_window(
        db,
        club_id=club_id,
        user_id=user_id,
        plan=plan,
        order_item=order_item,
        lock=True,
    )
    membership = Membership(
        club_id=club_id,
        user_id=user_id,
        plan_id=plan.id,
        order_item_id=order_item.id,
        starts_at=starts_at,
        ends_at=ends_at,
        status="active",
    )
    db.add(membership)
    await db.flush()
    return membership
