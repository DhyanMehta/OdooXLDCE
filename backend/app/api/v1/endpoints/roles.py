from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.db.session import get_db
from app.dependencies.auth import AuthContext, get_club, require_csrf
from app.models import AuditLog, Club, ClubRoleAssignment, Role, User
from app.schemas.roles import (
    AssignRoleIn,
    AuditLogOut,
    HandoverIn,
    RoleAssignmentEndOut,
    RoleAssignmentIdOut,
    RoleAssignmentOut,
    RoleHandoverOut,
    RoleOut,
)
from app.services.rbac import assign_role, end_assignment, handover_role, list_active_assignments
from app.services.rbac import require_permission

router = APIRouter(tags=["roles"])


@router.get("/clubs/{club_id}/roles", response_model=list[RoleOut])
async def list_roles(
    club_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[RoleOut]:
    """Role catalog is global; club_id is retained for stable club-scoped URLs."""
    del club_id
    roles = (await db.scalars(select(Role).order_by(Role.code))).all()
    return [RoleOut(id=str(r.id), code=r.code, name=r.name) for r in roles]


@router.get("/clubs/{club_id}/role-assignments", response_model=list[RoleAssignmentOut])
async def list_assignments(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
    include_history: bool = False,
) -> list[RoleAssignmentOut]:
    await require_permission(db, club_id=club.id, user_id=auth.user.id, permission="manage_roles")
    if include_history:
        rows = (
            await db.scalars(
                select(ClubRoleAssignment)
                .where(ClubRoleAssignment.club_id == club.id)
                .order_by(ClubRoleAssignment.starts_at.desc())
            )
        ).all()
    else:
        rows = await list_active_assignments(db, club_id=club.id)
    now = utcnow()
    out: list[RoleAssignmentOut] = []
    for row in rows:
        role = await db.get(Role, row.role_id)
        user = await db.get(User, row.user_id)
        if row.ends_at is not None and row.ends_at <= now:
            state = "ended"
        elif row.starts_at > now:
            state = "scheduled"
        else:
            state = "active"
        out.append(
            RoleAssignmentOut(
                id=str(row.id),
                user_id=str(row.user_id),
                user_email=user.email if user else None,
                user_name=user.full_name if user else None,
                role_code=role.code if role else None,
                starts_at=row.starts_at.isoformat(),
                ends_at=row.ends_at.isoformat() if row.ends_at else None,
                state=state,  # type: ignore[arg-type]
            )
        )
    return out


@router.post("/clubs/{club_id}/role-assignments", response_model=RoleAssignmentIdOut)
async def create_assignment(
    payload: AssignRoleIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> RoleAssignmentIdOut:
    row = await assign_role(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        target_user_id=payload.user_id,
        role_code=payload.role_code,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
    )
    await db.commit()
    return RoleAssignmentIdOut(id=str(row.id))


@router.post(
    "/clubs/{club_id}/role-assignments/{assignment_id}/end",
    response_model=RoleAssignmentEndOut,
)
async def end_one(
    assignment_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> RoleAssignmentEndOut:
    row = await end_assignment(
        db, club_id=club.id, actor_user_id=auth.user.id, assignment_id=assignment_id
    )
    await db.commit()
    return RoleAssignmentEndOut(
        id=str(row.id),
        ends_at=row.ends_at.isoformat() if row.ends_at else None,
    )


@router.post("/clubs/{club_id}/role-assignments/handover", response_model=RoleHandoverOut)
async def handover(
    payload: HandoverIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> RoleHandoverOut:
    outgoing, incoming = await handover_role(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        outgoing_assignment_id=payload.outgoing_assignment_id,
        incoming_user_id=payload.incoming_user_id,
    )
    await db.commit()
    return RoleHandoverOut(
        outgoing_id=str(outgoing.id),
        incoming_id=str(incoming.id),
    )


@router.get("/clubs/{club_id}/audit-logs", response_model=list[AuditLogOut])
async def audit_logs(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
) -> list[AuditLogOut]:
    await require_permission(db, club_id=club.id, user_id=auth.user.id, permission="view_audit")
    rows = (
        await db.scalars(
            select(AuditLog)
            .where(AuditLog.club_id == club.id)
            .order_by(AuditLog.created_at.desc())
            .limit(min(limit, 200))
        )
    ).all()
    out: list[AuditLogOut] = []
    for r in rows:
        actor = await db.get(User, r.actor_user_id) if r.actor_user_id else None
        # Never surface secrets; scrub known sensitive detail keys.
        details = dict(r.details or {})
        for key in list(details):
            if any(s in key.lower() for s in ("password", "token", "secret", "qr", "csrf")):
                details.pop(key, None)
        entity_label = f"{r.entity_type}"
        if r.entity_id:
            entity_label = f"{r.entity_type} {str(r.entity_id)[:8]}"
        out.append(
            AuditLogOut(
                id=str(r.id),
                action=r.action,
                entity_type=r.entity_type,
                entity_id=str(r.entity_id) if r.entity_id else None,
                entity_label=entity_label,
                actor_user_id=str(r.actor_user_id) if r.actor_user_id else None,
                actor_name=actor.full_name if actor else None,
                actor_email=actor.email if actor else None,
                details=details,
                created_at=r.created_at.isoformat(),
            )
        )
    return out
