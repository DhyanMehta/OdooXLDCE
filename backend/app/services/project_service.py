"""Club projects, volunteer tasks, and assignment lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.db_errors import is_unique_violation
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.models import ClubMember, Project, Task, TaskAssignment
from app.services.audit import record_audit
from app.services.membership_eligibility import utcnow
from app.services.rbac import require_permission

_OPEN_TASK = frozenset({"open", "in_progress"})
_PROJECT_STATUSES = frozenset({"draft", "open", "closed", "archived"})
_TASK_STATUSES = frozenset({"open", "in_progress", "done", "cancelled"})


async def _require_club_affiliate(db: AsyncSession, *, club_id: uuid.UUID, user_id: uuid.UUID) -> None:
    row = await db.scalar(
        select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == user_id)
    )
    if row is None:
        raise ForbiddenError("Club affiliation is required.")


async def _get_project(db: AsyncSession, *, club_id: uuid.UUID, project_id: uuid.UUID) -> Project:
    project = await db.scalar(
        select(Project).where(Project.id == project_id, Project.club_id == club_id)
    )
    if project is None:
        raise NotFoundError("Project not found.")
    return project


async def _get_task_for_club(
    db: AsyncSession, *, club_id: uuid.UUID, task_id: uuid.UUID, for_update: bool = False
) -> Task:
    stmt = (
        select(Task)
        .join(Project, Project.id == Task.project_id)
        .options(joinedload(Task.project))
        .where(Task.id == task_id, Project.club_id == club_id)
    )
    if for_update:
        stmt = stmt.with_for_update(of=Task)
    task = (await db.scalars(stmt)).unique().first()
    if task is None:
        raise NotFoundError("Task not found.")
    return task


async def create_project(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    title: str,
    description: str = "",
    status: str = "draft",
) -> Project:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_projects")
    if status not in _PROJECT_STATUSES:
        raise AppError("Invalid project status.")
    project = Project(
        club_id=club_id,
        title=title.strip(),
        description=description or "",
        status=status,
    )
    db.add(project)
    await db.flush()
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="project.created",
        entity_type="project",
        entity_id=project.id,
    )
    return project


async def patch_project(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    project_id: uuid.UUID,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
) -> Project:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_projects")
    project = await db.scalar(
        select(Project).where(Project.id == project_id, Project.club_id == club_id).with_for_update()
    )
    if project is None:
        raise NotFoundError("Project not found.")
    if title is not None:
        project.title = title.strip()
    if description is not None:
        project.description = description
    if status is not None:
        if status not in _PROJECT_STATUSES:
            raise AppError("Invalid project status.")
        project.status = status
    await db.flush()
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="project.updated",
        entity_type="project",
        entity_id=project.id,
        details={"status": project.status},
    )
    return project


async def list_projects(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    staff: bool = False,
) -> list[Project]:
    stmt = (
        select(Project)
        .options(joinedload(Project.tasks))
        .where(Project.club_id == club_id)
        .order_by(Project.title.asc())
    )
    if not staff:
        stmt = stmt.where(Project.status == "open")
    return list((await db.scalars(stmt)).unique().all())


async def create_task(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    project_id: uuid.UUID,
    title: str,
    description: str = "",
    deadline: datetime | None = None,
    capacity: int | None = None,
    status: str = "open",
) -> Task:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_projects")
    project = await _get_project(db, club_id=club_id, project_id=project_id)
    if status not in _TASK_STATUSES:
        raise AppError("Invalid task status.")
    if capacity is not None and capacity < 0:
        raise AppError("Capacity must be non-negative.")
    task = Task(
        project_id=project.id,
        title=title.strip(),
        description=description or "",
        deadline=deadline,
        capacity=capacity,
        status=status,
    )
    db.add(task)
    await db.flush()
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="task.created",
        entity_type="task",
        entity_id=task.id,
    )
    return task


async def patch_task(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    task_id: uuid.UUID,
    title: str | None = None,
    description: str | None = None,
    deadline: datetime | None | object = ...,
    capacity: int | None | object = ...,
    status: str | None = None,
) -> Task:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_projects")
    task = await _get_task_for_club(db, club_id=club_id, task_id=task_id, for_update=True)
    if title is not None:
        task.title = title.strip()
    if description is not None:
        task.description = description
    if deadline is not ...:
        task.deadline = deadline  # type: ignore[assignment]
    if capacity is not ...:
        if capacity is not None and int(capacity) < 0:  # type: ignore[arg-type]
            raise AppError("Capacity must be non-negative.")
        task.capacity = capacity  # type: ignore[assignment]
    if status is not None:
        if status not in _TASK_STATUSES:
            raise AppError("Invalid task status.")
        task.status = status
    await db.flush()
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="task.updated",
        entity_type="task",
        entity_id=task.id,
    )
    return task


async def count_active_assignments(db: AsyncSession, *, task_id: uuid.UUID) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(TaskAssignment)
            .where(TaskAssignment.task_id == task_id, TaskAssignment.status == "active")
        )
        or 0
    )


async def _create_active_assignment(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    task: Task,
    user_id: uuid.UUID,
    assigned_by_user_id: uuid.UUID | None,
) -> TaskAssignment:
    if task.status not in _OPEN_TASK:
        raise AppError("Task is not open for signup.", code="task_not_open")
    project = task.project if task.project else await db.get(Project, task.project_id)
    if project is None or project.club_id != club_id:
        raise ForbiddenError("Task does not belong to this club.")
    if project.status != "open":
        raise AppError("Project is not open for volunteers.", code="project_not_open")

    active = await count_active_assignments(db, task_id=task.id)
    if task.capacity is not None and active >= task.capacity:
        raise ConflictError("Task volunteer capacity is full.", code="capacity_exhausted")

    existing_active = await db.scalar(
        select(TaskAssignment).where(
            TaskAssignment.task_id == task.id,
            TaskAssignment.user_id == user_id,
            TaskAssignment.status == "active",
        )
    )
    if existing_active is not None:
        raise ConflictError("Already signed up for this task.", code="already_assigned")

    assignment = TaskAssignment(
        task_id=task.id,
        user_id=user_id,
        status="active",
        signed_up_at=utcnow(),
        assigned_by_user_id=assigned_by_user_id,
    )
    db.add(assignment)
    try:
        await db.flush()
    except Exception as exc:
        if is_unique_violation(exc):
            raise ConflictError("Already signed up for this task.", code="already_assigned") from exc
        raise
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=assigned_by_user_id or user_id,
        action="task_assignment.created",
        entity_type="task_assignment",
        entity_id=assignment.id,
        details={"task_id": str(task.id), "user_id": str(user_id)},
    )
    return assignment


async def signup_for_task(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    task_id: uuid.UUID,
) -> TaskAssignment:
    await _require_club_affiliate(db, club_id=club_id, user_id=user_id)
    # Lock task row so concurrent signups serialize on capacity.
    task = await _get_task_for_club(db, club_id=club_id, task_id=task_id, for_update=True)
    return await _create_active_assignment(
        db, club_id=club_id, task=task, user_id=user_id, assigned_by_user_id=None
    )


async def withdraw_assignment(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    assignment_id: uuid.UUID,
) -> TaskAssignment:
    assignment = await db.scalar(
        select(TaskAssignment).where(TaskAssignment.id == assignment_id).with_for_update()
    )
    if assignment is None:
        raise NotFoundError("Assignment not found.")
    if assignment.user_id != user_id:
        raise ForbiddenError("You can only withdraw your own assignment.")
    task = await _get_task_for_club(db, club_id=club_id, task_id=assignment.task_id)
    if assignment.status != "active":
        raise AppError("Only active assignments can be withdrawn.", code="assignment_not_active")
    assignment.status = "withdrawn"
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=user_id,
        action="task_assignment.withdrawn",
        entity_type="task_assignment",
        entity_id=assignment.id,
        details={"task_id": str(task.id)},
    )
    return assignment


async def organizer_assign(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    task_id: uuid.UUID,
    user_id: uuid.UUID,
) -> TaskAssignment:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_projects")
    await _require_club_affiliate(db, club_id=club_id, user_id=user_id)
    task = await _get_task_for_club(db, club_id=club_id, task_id=task_id, for_update=True)
    return await _create_active_assignment(
        db, club_id=club_id, task=task, user_id=user_id, assigned_by_user_id=actor_user_id
    )


async def organizer_set_assignment_status(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    assignment_id: uuid.UUID,
    status: str,
) -> TaskAssignment:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_projects")
    if status not in {"cancelled", "completed"}:
        raise AppError("Organizers may only cancel or complete assignments.")
    assignment = await db.scalar(
        select(TaskAssignment).where(TaskAssignment.id == assignment_id).with_for_update()
    )
    if assignment is None:
        raise NotFoundError("Assignment not found.")
    await _get_task_for_club(db, club_id=club_id, task_id=assignment.task_id)
    if assignment.status != "active":
        raise AppError("Only active assignments can be updated.", code="assignment_not_active")
    assignment.status = status
    if status == "completed":
        assignment.completed_at = utcnow()
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action=f"task_assignment.{status}",
        entity_type="task_assignment",
        entity_id=assignment.id,
    )
    return assignment


async def list_my_assignments(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    club_id: uuid.UUID | None = None,
) -> list[TaskAssignment]:
    stmt = (
        select(TaskAssignment)
        .join(Task, Task.id == TaskAssignment.task_id)
        .join(Project, Project.id == Task.project_id)
        .options(joinedload(TaskAssignment.task).joinedload(Task.project))
        .where(TaskAssignment.user_id == user_id)
        .order_by(TaskAssignment.signed_up_at.desc())
    )
    if club_id is not None:
        stmt = stmt.where(Project.club_id == club_id)
    return list((await db.scalars(stmt)).unique().all())


async def list_task_roster(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    task_id: uuid.UUID,
) -> list[TaskAssignment]:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_projects")
    await _get_task_for_club(db, club_id=club_id, task_id=task_id)
    return list(
        (
            await db.scalars(
                select(TaskAssignment)
                .where(TaskAssignment.task_id == task_id)
                .order_by(TaskAssignment.signed_up_at.asc())
            )
        ).all()
    )
