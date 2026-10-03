from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import AuthContext, get_club, get_current_auth, require_csrf
from app.models import Club, Membership, MembershipPlan, User
from app.schemas.membership import MembershipOut, PlanIn, PlanOut
from app.services.membership_service import create_plan, update_plan
from app.services.rbac import require_permission
from app.core.errors import ForbiddenError, NotFoundError

router = APIRouter(tags=["memberships"])


@router.get("/clubs/{club_id}/plans", response_model=list[PlanOut])
def list_plans(club: Club = Depends(get_club), db: Session = Depends(get_db)) -> list[MembershipPlan]:
    return list(
        db.scalars(
            select(MembershipPlan)
            .where(
                MembershipPlan.club_id == club.id,
                MembershipPlan.is_active.is_(True),
                MembershipPlan.archived_at.is_(None),
            )
            .order_by(MembershipPlan.name)
        ).all()
    )


@router.post("/clubs/{club_id}/plans", response_model=PlanOut)
def create_plan_endpoint(
    payload: PlanIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> MembershipPlan:
    plan = create_plan(
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
    db.commit()
    db.refresh(plan)
    return plan


@router.patch("/clubs/{club_id}/plans/{plan_id}", response_model=PlanOut)
def patch_plan(
    plan_id: uuid.UUID,
    payload: PlanIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> MembershipPlan:
    plan = update_plan(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        plan_id=plan_id,
        name=payload.name,
        description=payload.description,
        dues_amount=payload.dues_amount,
        duration_days=payload.duration_days,
        fixed_expires_on=payload.fixed_expires_on,
        is_active=payload.is_active,
    )
    db.commit()
    db.refresh(plan)
    return plan


@router.get("/clubs/{club_id}/me/memberships", response_model=list[MembershipOut])
def my_memberships(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> list[Membership]:
    return list(
        db.scalars(
            select(Membership)
            .where(Membership.club_id == club.id, Membership.user_id == auth.user.id)
            .order_by(Membership.ends_at.desc())
        ).all()
    )


@router.get("/clubs/{club_id}/members", response_model=list[dict])
def list_members(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> list[dict]:
    require_permission(db, club_id=club.id, user_id=auth.user.id, permission="manage_members")
    rows = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.club_id == club.id)
        .order_by(Membership.ends_at.desc())
    ).all()
    return [
        {
            "membership_id": str(m.id),
            "user_id": str(u.id),
            "email": u.email,
            "full_name": u.full_name,
            "starts_at": m.starts_at.isoformat(),
            "ends_at": m.ends_at.isoformat(),
            "status": m.status,
            "plan_id": str(m.plan_id),
        }
        for m, u in rows
    ]


@router.get("/clubs/{club_id}/directory", response_model=list[dict])
def club_directory(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Club affiliation directory for role assignment UIs (names/emails only in the client)."""
    require_permission(db, club_id=club.id, user_id=auth.user.id, permission="manage_roles")
    from app.models import ClubMember

    rows = db.execute(
        select(User)
        .join(ClubMember, ClubMember.user_id == User.id)
        .where(ClubMember.club_id == club.id)
        .order_by(User.full_name)
    ).scalars().all()
    return [
        {"user_id": str(u.id), "full_name": u.full_name, "email": u.email}
        for u in rows
    ]
