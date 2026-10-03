from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import AuthContext, get_club, require_csrf
from app.models import AuditLog, Club, ClubRoleAssignment, Role, User
from app.services.rbac import assign_role, end_assignment, handover_role, list_active_assignments
from app.services.rbac import require_permission

router = APIRouter(tags=["roles"])


class AssignRoleIn(BaseModel):
    user_id: uuid.UUID
    role_code: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class HandoverIn(BaseModel):
    outgoing_assignment_id: uuid.UUID
    incoming_user_id: uuid.UUID


@router.get("/clubs/{club_id}/roles")
def list_roles(db: Session = Depends(get_db)) -> list[dict]:
    roles = db.scalars(select(Role).order_by(Role.code)).all()
    return [{"id": str(r.id), "code": r.code, "name": r.name} for r in roles]


@router.get("/clubs/{club_id}/role-assignments")
def list_assignments(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    include_history: bool = False,
) -> list[dict]:
    require_permission(db, club_id=club.id, user_id=auth.user.id, permission="manage_roles")
    if include_history:
        rows = db.scalars(
            select(ClubRoleAssignment)
            .where(ClubRoleAssignment.club_id == club.id)
            .order_by(ClubRoleAssignment.starts_at.desc())
        ).all()
    else:
        rows = list_active_assignments(db, club_id=club.id)
    out = []
    for row in rows:
        role = db.get(Role, row.role_id)
        user = db.get(User, row.user_id)
        out.append(
            {
                "id": str(row.id),
                "user_id": str(row.user_id),
                "user_email": user.email if user else None,
                "user_name": user.full_name if user else None,
                "role_code": role.code if role else None,
                "starts_at": row.starts_at.isoformat(),
                "ends_at": row.ends_at.isoformat() if row.ends_at else None,
            }
        )
    return out


@router.post("/clubs/{club_id}/role-assignments")
def create_assignment(
    payload: AssignRoleIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    row = assign_role(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        target_user_id=payload.user_id,
        role_code=payload.role_code,
        starts_at=payload.starts_at,
        ends_at=payload.ends_at,
    )
    db.commit()
    return {"id": str(row.id)}


@router.post("/clubs/{club_id}/role-assignments/{assignment_id}/end")
def end_one(
    assignment_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    row = end_assignment(
        db, club_id=club.id, actor_user_id=auth.user.id, assignment_id=assignment_id
    )
    db.commit()
    return {"id": str(row.id), "ends_at": row.ends_at.isoformat() if row.ends_at else None}


@router.post("/clubs/{club_id}/role-assignments/handover")
def handover(
    payload: HandoverIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    outgoing, incoming = handover_role(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        outgoing_assignment_id=payload.outgoing_assignment_id,
        incoming_user_id=payload.incoming_user_id,
    )
    db.commit()
    return {
        "outgoing_id": str(outgoing.id),
        "incoming_id": str(incoming.id),
    }


@router.get("/clubs/{club_id}/audit-logs")
def audit_logs(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
    limit: int = 50,
) -> list[dict]:
    require_permission(db, club_id=club.id, user_id=auth.user.id, permission="view_audit")
    rows = db.scalars(
        select(AuditLog)
        .where(AuditLog.club_id == club.id)
        .order_by(AuditLog.created_at.desc())
        .limit(min(limit, 200))
    ).all()
    return [
        {
            "id": str(r.id),
            "action": r.action,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "actor_user_id": str(r.actor_user_id) if r.actor_user_id else None,
            "details": r.details,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
