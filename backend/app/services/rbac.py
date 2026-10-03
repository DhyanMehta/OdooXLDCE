"""Club-scoped role resolution, assignment, and atomic handover.

Mutations serialize on a club-scoped advisory lock so concurrent end/handover
cannot bypass last-administrator or overlap rules.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.permissions import RoleCode, permissions_for_roles
from app.core.time import utcnow
from app.models import ClubMember, ClubRoleAssignment, Role, User
from app.services.audit import record_audit


def _assignment_active_clause(at: datetime):
    return and_(
        ClubRoleAssignment.starts_at <= at,
        or_(ClubRoleAssignment.ends_at.is_(None), ClubRoleAssignment.ends_at > at),
    )


async def lock_club_roles(db: AsyncSession, club_id: uuid.UUID) -> None:
    """Serialize role mutations for one club (transaction-scoped advisory lock)."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:k1, :k2)"),
        {"k1": 904201, "k2": club_id.int % (2**31 - 1)},
    )


async def effective_role_codes(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    at: datetime | None = None,
) -> set[str]:
    moment = at or utcnow()
    result = await db.execute(
        select(Role.code)
        .join(ClubRoleAssignment, ClubRoleAssignment.role_id == Role.id)
        .where(
            ClubRoleAssignment.club_id == club_id,
            ClubRoleAssignment.user_id == user_id,
            _assignment_active_clause(moment),
        )
    )
    return set(result.scalars().all())


async def effective_permissions(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
) -> list[str]:
    return permissions_for_roles(await effective_role_codes(db, club_id=club_id, user_id=user_id))


async def require_permission(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    permission: str,
) -> None:
    perms = await effective_permissions(db, club_id=club_id, user_id=user_id)
    if permission not in perms:
        raise ForbiddenError("You do not have permission for this action.")


async def list_active_assignments(db: AsyncSession, *, club_id: uuid.UUID) -> list[ClubRoleAssignment]:
    return list(
        (
            await db.scalars(
                select(ClubRoleAssignment)
                .where(ClubRoleAssignment.club_id == club_id, _assignment_active_clause(utcnow()))
                .order_by(ClubRoleAssignment.starts_at.desc())
            )
        ).all()
    )


async def _has_overlapping_assignment(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    starts_at: datetime,
    ends_at: datetime | None,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    rows = (
        await db.scalars(
            select(ClubRoleAssignment).where(
                ClubRoleAssignment.club_id == club_id,
                ClubRoleAssignment.user_id == user_id,
                ClubRoleAssignment.role_id == role_id,
            )
        )
    ).all()
    for row in rows:
        if exclude_id and row.id == exclude_id:
            continue
        row_end = row.ends_at
        open_end = ends_at is None
        if starts_at < (row_end or datetime.max.replace(tzinfo=timezone.utc)) and (
            open_end or (ends_at is not None and ends_at > row.starts_at)
        ):
            return True
    return False


async def count_active_admins(db: AsyncSession, *, club_id: uuid.UUID, at: datetime | None = None) -> int:
    moment = at or utcnow()
    admin_role = await db.scalar(select(Role).where(Role.code == RoleCode.CLUB_ADMIN.value))
    if admin_role is None:
        return 0
    return len(
        (
            await db.scalars(
                select(ClubRoleAssignment).where(
                    ClubRoleAssignment.club_id == club_id,
                    ClubRoleAssignment.role_id == admin_role.id,
                    _assignment_active_clause(moment),
                )
            )
        ).all()
    )


async def _require_eligible_assignee(db: AsyncSession, *, club_id: uuid.UUID, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise NotFoundError("User not found.")
    if await db.scalar(select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == user_id)) is None:
        raise AppError("User must belong to the club before receiving a role.", code="not_club_member")
    return user


async def assign_role(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    role_code: str,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
) -> ClubRoleAssignment:
    if actor_user_id == target_user_id:
        raise ForbiddenError("You cannot assign privileged roles to yourself.")
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_roles")
    await lock_club_roles(db, club_id)

    role = await db.scalar(select(Role).where(Role.code == role_code))
    if role is None:
        raise NotFoundError("Role not found.")
    await _require_eligible_assignee(db, club_id=club_id, user_id=target_user_id)

    start = starts_at or utcnow()
    if ends_at is not None and ends_at <= start:
        raise AppError("Role end must be after start.")
    if await _has_overlapping_assignment(
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
    await db.flush()
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="role.assigned",
        entity_type="club_role_assignment",
        entity_id=assignment.id,
        details={"role": role_code, "user_id": str(target_user_id)},
    )
    return assignment


async def end_assignment(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    assignment_id: uuid.UUID,
    ends_at: datetime | None = None,
) -> ClubRoleAssignment:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_roles")
    await lock_club_roles(db, club_id)

    assignment = await db.scalar(
        select(ClubRoleAssignment)
        .where(ClubRoleAssignment.id == assignment_id, ClubRoleAssignment.club_id == club_id)
        .with_for_update()
    )
    if assignment is None:
        raise NotFoundError("Assignment not found.")
    role = await db.get(Role, assignment.role_id)
    now = utcnow()
    if assignment.ends_at is not None and assignment.ends_at <= now:
        raise AppError("Assignment already ended.")
    if assignment.starts_at > now:
        # Ending a scheduled assignment is allowed; last-admin only applies when currently effective.
        pass
    elif role and role.code == RoleCode.CLUB_ADMIN.value:
        if await count_active_admins(db, club_id=club_id) <= 1:
            raise ConflictError("Cannot remove the club's last effective administrator.")
    end = ends_at or now
    if end <= assignment.starts_at:
        raise AppError("Role end must be after start.")
    assignment.ends_at = end
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="role.ended",
        entity_type="club_role_assignment",
        entity_id=assignment.id,
        details={"role": role.code if role else None},
    )
    return assignment


async def handover_role(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    outgoing_assignment_id: uuid.UUID,
    incoming_user_id: uuid.UUID,
) -> tuple[ClubRoleAssignment, ClubRoleAssignment]:
    """Atomically end outgoing assignment and start incoming assignment."""
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_roles")
    await lock_club_roles(db, club_id)

    outgoing = await db.scalar(
        select(ClubRoleAssignment)
        .where(ClubRoleAssignment.id == outgoing_assignment_id, ClubRoleAssignment.club_id == club_id)
        .with_for_update()
    )
    if outgoing is None:
        raise NotFoundError("Outgoing assignment not found.")
    role = await db.get(Role, outgoing.role_id)
    if role is None:
        raise NotFoundError("Role not found.")
    if actor_user_id == incoming_user_id:
        raise ForbiddenError("You cannot assign privileged roles to yourself.")
    await _require_eligible_assignee(db, club_id=club_id, user_id=incoming_user_id)

    now = utcnow()
    if not (outgoing.starts_at <= now and (outgoing.ends_at is None or outgoing.ends_at > now)):
        raise AppError("Outgoing assignment is not currently effective.")

    outgoing.ends_at = now
    if await _has_overlapping_assignment(
        db,
        club_id=club_id,
        user_id=incoming_user_id,
        role_id=role.id,
        starts_at=now,
        ends_at=None,
        exclude_id=outgoing.id,
    ):
        raise ConflictError("Incoming user already has an overlapping assignment for this role.")

    # After ending outgoing admin, ensure we still have an admin once incoming is created.
    incoming = ClubRoleAssignment(
        club_id=club_id,
        user_id=incoming_user_id,
        role_id=role.id,
        starts_at=now,
        ends_at=None,
        assigned_by_user_id=actor_user_id,
    )
    db.add(incoming)
    await db.flush()
    if role.code == RoleCode.CLUB_ADMIN.value and await count_active_admins(db, club_id=club_id) < 1:
        raise ConflictError("Club must retain an effective administrator.")

    await record_audit(
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
