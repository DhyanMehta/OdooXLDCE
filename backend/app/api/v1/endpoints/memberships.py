from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError
from app.core.time import utcnow
from app.db.session import get_db
from app.dependencies.auth import AuthContext, get_club, get_current_auth, get_optional_auth, require_csrf
from app.models import Club, ClubMember, Membership, MembershipPlan, Order, OrderItem, User
from app.schemas.membership import (
    DirectoryPersonOut,
    MemberPageOut,
    MemberPersonOut,
    MembershipOut,
    PlanIn,
    PlanOut,
    PlanPatch,
)
from app.services.membership_eligibility import effective_membership_state
from app.services.membership_service import create_plan, update_plan
from app.services.rbac import require_permission

router = APIRouter(tags=["memberships"])


@router.get("/clubs/{club_id}/plans", response_model=list[PlanOut])
async def list_plans(
    club: Club = Depends(get_club),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext | None = Depends(get_optional_auth),
    include_inactive: bool = False,
) -> list[MembershipPlan]:
    """Public list is active plans only. Staff may request inactive/archived."""
    staff = False
    if include_inactive and auth is not None:
        try:
            await require_permission(db, club_id=club.id, user_id=auth.user.id, permission="manage_plans")
            staff = True
        except ForbiddenError:
            staff = False
    stmt = select(MembershipPlan).where(MembershipPlan.club_id == club.id)
    if not staff:
        stmt = stmt.where(
            MembershipPlan.is_active.is_(True),
            MembershipPlan.archived_at.is_(None),
        )
    return list((await db.scalars(stmt.order_by(MembershipPlan.name))).all())


@router.post("/clubs/{club_id}/plans", response_model=PlanOut)
async def create_plan_endpoint(
    payload: PlanIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> MembershipPlan:
    plan = await create_plan(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        name=payload.name,
        description=payload.description,
        dues_amount=payload.dues_amount,
        duration_days=payload.duration_days,
        fixed_expires_on=payload.fixed_expires_on,
        is_active=payload.is_active,
    )
    await db.commit()
    await db.refresh(plan)
    return plan


@router.patch("/clubs/{club_id}/plans/{plan_id}", response_model=PlanOut)
async def patch_plan(
    plan_id: uuid.UUID,
    payload: PlanPatch,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> MembershipPlan:
    plan = await update_plan(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        plan_id=plan_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await db.commit()
    await db.refresh(plan)
    return plan


@router.get("/clubs/{club_id}/me/memberships", response_model=list[MembershipOut])
async def my_memberships(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> list[MembershipOut]:
    rows = list(
        (
            await db.scalars(
                select(Membership)
                .where(Membership.club_id == club.id, Membership.user_id == auth.user.id)
                .order_by(Membership.ends_at.desc())
            )
        ).all()
    )
    out: list[MembershipOut] = []
    for row in rows:
        item = MembershipOut.model_validate(row)
        item.effective_state = effective_membership_state(row)
        plan = await db.get(MembershipPlan, row.plan_id)
        item.plan_name = plan.name if plan else None
        out.append(item)
    return out


def _latest_membership_state(rows: list[Membership], *, at: datetime) -> tuple[str, Membership | None]:
    if not rows:
        return "none", None
    # Prefer currently active, then upcoming, then most recently ended.
    active = [m for m in rows if effective_membership_state(m, at=at) == "active"]
    if active:
        best = max(active, key=lambda m: m.ends_at)
        return "active", best
    upcoming = [m for m in rows if effective_membership_state(m, at=at) == "upcoming"]
    if upcoming:
        best = min(upcoming, key=lambda m: m.starts_at)
        return "upcoming", best
    best = max(rows, key=lambda m: m.ends_at)
    return effective_membership_state(best, at=at), best


@router.get("/clubs/{club_id}/members", response_model=MemberPageOut)
async def list_members(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
    q: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> MemberPageOut:
    """Person-centric directory: affiliation + derived paid membership state."""
    await require_permission(db, club_id=club.id, user_id=auth.user.id, permission="manage_members")
    now = utcnow()
    stmt = (
        select(User)
        .join(ClubMember, ClubMember.user_id == User.id)
        .where(ClubMember.club_id == club.id)
    )
    if q:
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.full_name.ilike(term), User.email.ilike(term)))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    users = (await db.scalars(stmt.order_by(User.full_name).limit(limit).offset(offset))).all()

    items: list[MemberPersonOut] = []
    for user in users:
        memberships = list(
            (
                await db.scalars(
                    select(Membership).where(
                        Membership.club_id == club.id,
                        Membership.user_id == user.id,
                    )
                )
            ).all()
        )
        state, current = _latest_membership_state(memberships, at=now)
        plan_name = None
        if current:
            plan = await db.get(MembershipPlan, current.plan_id)
            plan_name = plan.name if plan else None
        pending = await db.scalar(
            select(func.count())
            .select_from(Order)
            .join(OrderItem, OrderItem.order_id == Order.id)
            .where(
                Order.club_id == club.id,
                Order.user_id == user.id,
                Order.status == "pending",
                OrderItem.item_kind == "membership",
            )
        ) or 0
        items.append(
            MemberPersonOut(
                user_id=user.id,
                email=user.email,
                full_name=user.full_name,
                is_affiliated=True,
                effective_state=state,  # type: ignore[arg-type]
                current_membership_id=current.id if current else None,
                current_plan_name=plan_name,
                starts_at=current.starts_at if current else None,
                ends_at=current.ends_at if current else None,
                pending_dues_count=int(pending),
            )
        )
    return MemberPageOut(items=items, total=int(total), limit=limit, offset=offset)


@router.get("/clubs/{club_id}/members/{user_id}/memberships", response_model=list[MembershipOut])
async def member_history(
    user_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> list[MembershipOut]:
    await require_permission(db, club_id=club.id, user_id=auth.user.id, permission="manage_members")
    affiliated = await db.scalar(
        select(ClubMember).where(ClubMember.club_id == club.id, ClubMember.user_id == user_id)
    )
    if affiliated is None:
        raise NotFoundError("Member not found in this club.")
    rows = list(
        (
            await db.scalars(
                select(Membership)
                .where(Membership.club_id == club.id, Membership.user_id == user_id)
                .order_by(Membership.starts_at.desc())
            )
        ).all()
    )
    out: list[MembershipOut] = []
    for row in rows:
        item = MembershipOut.model_validate(row)
        item.effective_state = effective_membership_state(row)
        plan = await db.get(MembershipPlan, row.plan_id)
        item.plan_name = plan.name if plan else None
        out.append(item)
    return out


@router.get("/clubs/{club_id}/directory", response_model=list[DirectoryPersonOut])
async def club_directory(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> list[DirectoryPersonOut]:
    """Club affiliation directory for role assignment UIs."""
    await require_permission(db, club_id=club.id, user_id=auth.user.id, permission="manage_roles")
    rows = (
        await db.execute(
            select(User)
            .join(ClubMember, ClubMember.user_id == User.id)
            .where(ClubMember.club_id == club.id)
            .order_by(User.full_name)
        )
    ).scalars().all()
    return [
        DirectoryPersonOut(user_id=str(u.id), full_name=u.full_name, email=u.email)
        for u in rows
    ]
