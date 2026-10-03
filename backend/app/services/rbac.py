"""Club-scoped role resolution, assignment, and atomic handover."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.permissions import RoleCode, permissions_for_roles
from app.models import ClubMember, ClubRoleAssignment, Role, User
from app.services.audit import record_audit


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _assignment_active_clause(at: datetime):
    return and_(
        ClubRoleAssignment.starts_at <= at,
        or_(ClubRoleAssignment.ends_at.is_(None), ClubRoleAssignment.ends_at > at),
    )


def effective_role_codes(
    db: Session,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    at: datetime | None = None,
) -> set[str]:
    moment = at or utcnow()
    rows = db.execute(
        select(Role.code)
        .join(ClubRoleAssignment, ClubRoleAssignment.role_id == Role.id)
        .where(
            ClubRoleAssignment.club_id == club_id,
            ClubRoleAssignment.user_id == user_id,
            _assignment_active_clause(moment),
        )
    ).scalars().all()
    return set(rows)


def effective_permissions(
    db: Session,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[str]:
    return permissions_for_roles(effective_role_codes(db, club_id=club_id, user_id=user_id))


def require_permission(
    db: Session,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    permission: str,
) -> None:
    perms = effective_permissions(db, club_id=club_id, user_id=user_id)
    if permission not in perms:
        raise ForbiddenError("You do not have permission for this action.")


def list_active_assignments(db: Session, *, club_id: uuid.UUID) -> list[ClubRoleAssignment]:
    return list(
        db.scalars(
            select(ClubRoleAssignment)
            .where(ClubRoleAssignment.club_id == club_id, _assignment_active_clause(utcnow()))
            .order_by(ClubRoleAssignment.starts_at.desc())
        ).all()
    )


def _has_overlapping_assignment(
    db: Session,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    starts_at: datetime,
    ends_at: datetime | None,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    rows = db.scalars(
        select(ClubRoleAssignment).where(
            ClubRoleAssignment.club_id == club_id,
            ClubRoleAssignment.user_id == user_id,
            ClubRoleAssignment.role_id == role_id,
        )
    ).all()
    for row in rows:
        if exclude_id and row.id == exclude_id:
            continue
        row_end = row.ends_at
        # Overlap if ranges intersect on the timeline.
        if row_end is None:
            if ends_at is None or ends_at > row.starts_at:
                if starts_at < (ends_at or datetime.max.replace(tzinfo=timezone.utc)):
                    if starts_at < (row_end or datetime.max.replace(tzinfo=timezone.utc)) and (
                        ends_at is None or ends_at > row.starts_at
                    ):
                        return True
        else:
            open_end = ends_at is None
            if starts_at < row_end and (open_end or ends_at > row.starts_at):
                return True
    return False


def count_active_admins(db: Session, *, club_id: uuid.UUID, at: datetime | None = None) -> int:
    moment = at or utcnow()
    admin_role = db.scalar(select(Role).where(Role.code == RoleCode.CLUB_ADMIN.value))
    if admin_role is None:
        return 0
    return len(
        db.scalars(
            select(ClubRoleAssignment).where(
                ClubRoleAssignment.club_id == club_id,
                ClubRoleAssignment.role_id == admin_role.id,
                _assignment_active_clause(moment),
            )
        ).all()
    )


def assign_role(
    db: Session,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    role_code: str,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> ClubRoleAssignment:
    if actor_user_id == target_user_id:
        # Prevent privilege self-escalation via the assignment API.
        raise ForbiddenError("You cannot assign privileged roles to yourself.")
    require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_roles")
    role = db.scalar(select(Role).where(Role.code == role_code))
    if role is None:
        raise NotFoundError("Role not found.")
    target = db.get(User, target_user_id)
    if target is None:
        raise NotFoundError("User not found.")
    if db.scalar(select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == target_user_id)) is None:
        raise AppError("User must belong to the club before receiving a role.", code="not_club_member")

    start = starts_at or utcnow()
    if ends_at is not None and ends_at <= start:
        raise AppError("Role end must be after start.")
    if _has_overlapping_assignment(
        db,
        club_id=club_id,
        user_id=target_user_id,
        role_id=role.id,
        starts_at=start,
        ends_at=ends_at,
    ):
        raise ConflictError("An overlapping assignment already exists for this person and role.")

    assignment = ClubRoleAssignment(
        club_id=club_id,
        user_id=target_user_id,
        role_id=role.id,
        starts_at=start,
        ends_at=ends_at,
        assigned_by_user_id=actor_user_id,
    )
    db.add(assignment)
    db.flush()
    record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="role.assigned",
        entity_type="club_role_assignment",
        entity_id=assignment.id,
        details={"role": role_code, "user_id": str(target_user_id)},
    )
    return assignment


def end_assignment(
    db: Session,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    assignment_id: uuid.UUID,
    ends_at: datetime | None = None,
) -> ClubRoleAssignment:
    require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_roles")
    assignment = db.get(ClubRoleAssignment, assignment_id)
    if assignment is None or assignment.club_id != club_id:
        raise NotFoundError("Assignment not found.")
    role = db.get(Role, assignment.role_id)
    end = ends_at or utcnow()
    if assignment.ends_at is not None and assignment.ends_at <= utcnow():
        raise AppError("Assignment already ended.")
    if role and role.code == RoleCode.CLUB_ADMIN.value:
        # Keep at least one effective administrator for the club.
        if count_active_admins(db, club_id=club_id) <= 1:
            raise ConflictError("Cannot remove the club's last effective administrator.")
    assignment.ends_at = end
    record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="role.ended",
        entity_type="club_role_assignment",
        entity_id=assignment.id,
        details={"role": role.code if role else None},
    )
    return assignment


def handover_role(
    db: Session,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    outgoing_assignment_id: uuid.UUID,
    incoming_user_id: uuid.UUID,
) -> tuple[ClubRoleAssignment, ClubRoleAssignment]:
    """Atomically end outgoing assignment and start incoming assignment."""
    require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_roles")
    outgoing = db.get(ClubRoleAssignment, outgoing_assignment_id)
    if outgoing is None or outgoing.club_id != club_id:
        raise NotFoundError("Outgoing assignment not found.")
    role = db.get(Role, outgoing.role_id)
    if role is None:
        raise NotFoundError("Role not found.")
    if actor_user_id == incoming_user_id:
        raise ForbiddenError("You cannot assign privileged roles to yourself.")

    now = utcnow()
    if outgoing.ends_at is not None and outgoing.ends_at <= now:
        raise AppError("Outgoing assignment is not active.")

    outgoing.ends_at = now
    if _has_overlapping_assignment(
        db,
        club_id=club_id,
        user_id=incoming_user_id,
        role_id=role.id,
        starts_at=now,
        ends_at=None,
        exclude_id=outgoing.id,
    ):
        raise ConflictError("Incoming user already has an overlapping assignment for this role.")

    incoming = ClubRoleAssignment(
        club_id=club_id,
        user_id=incoming_user_id,
        role_id=role.id,
        starts_at=now,
        ends_at=None,
        assigned_by_user_id=actor_user_id,
    )
    db.add(incoming)
    db.flush()
    record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="role.handover",
        entity_type="club_role_assignment",
        entity_id=incoming.id,
        details={
            "role": role.code,
            "from_assignment_id": str(outgoing.id),
            "from_user_id": str(outgoing.user_id),
            "to_user_id": str(incoming_user_id),
        },
    )
    return outgoing, incoming
