from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError
from app.db.session import get_db
from app.dependencies.auth import AuthContext, get_club, get_current_auth, get_optional_auth, require_csrf
from app.models import Club, Task, User
from app.schemas.projects import (
    AssignIn,
    AssignmentOut,
    AssignmentStatusIn,
    ProjectIn,
    ProjectOut,
    ProjectPatch,
    TaskIn,
    TaskOut,
    TaskPatch,
)
from app.services.project_service import (
    count_active_assignments,
    create_project,
    create_task,
    list_my_assignments,
    list_projects,
    list_task_roster,
    organizer_assign,
    organizer_set_assignment_status,
    patch_project,
    patch_task,
    signup_for_task,
    withdraw_assignment,
)
from app.services.rbac import require_permission

router = APIRouter(tags=["projects"])


async def _can_manage_projects(db: AsyncSession, club_id: uuid.UUID, auth: AuthContext | None) -> bool:
    if auth is None:
        return False
    try:
        await require_permission(db, club_id=club_id, user_id=auth.user.id, permission="manage_projects")
        return True
    except ForbiddenError:
        return False


async def _task_out(db: AsyncSession, task: Task) -> TaskOut:
    data = TaskOut.model_validate(task)
    data.active_count = await count_active_assignments(db, task_id=task.id)
    return data


async def _project_out(db: AsyncSession, project) -> ProjectOut:
    data = ProjectOut.model_validate(project)
    data.tasks = [await _task_out(db, t) for t in project.tasks]
    return data


def _assignment_out(assignment, *, user: User | None = None) -> AssignmentOut:
    data = AssignmentOut.model_validate(assignment)
    task = assignment.task
    if task is not None:
        data.task_title = task.title
        data.project_id = task.project_id
        if task.project is not None:
            data.project_title = task.project.title
            data.club_id = task.project.club_id
    if user is not None:
        data.user_email = user.email
        data.user_name = user.full_name
    return data


@router.get("/clubs/{club_id}/projects", response_model=list[ProjectOut])
async def get_projects(
    club: Club = Depends(get_club),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext | None = Depends(get_optional_auth),
) -> list[ProjectOut]:
    staff = await _can_manage_projects(db, club.id, auth)
    projects = await list_projects(db, club_id=club.id, staff=staff)
    return [await _project_out(db, p) for p in projects]


@router.post("/clubs/{club_id}/projects", response_model=ProjectOut)
async def post_project(
    payload: ProjectIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    project = await create_project(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        title=payload.title,
        description=payload.description,
        status=payload.status,
    )
    await db.commit()
    projects = await list_projects(db, club_id=club.id, staff=True)
    loaded = next(p for p in projects if p.id == project.id)
    return await _project_out(db, loaded)


@router.patch("/clubs/{club_id}/projects/{project_id}", response_model=ProjectOut)
async def patch_project_endpoint(
    project_id: uuid.UUID,
    payload: ProjectPatch,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> ProjectOut:
    await patch_project(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        project_id=project_id,
        **payload.model_dump(exclude_unset=True),
    )
    await db.commit()
    projects = await list_projects(db, club_id=club.id, staff=True)
    loaded = next(p for p in projects if p.id == project_id)
    return await _project_out(db, loaded)


@router.post("/clubs/{club_id}/projects/{project_id}/tasks", response_model=TaskOut)
async def post_task(
    project_id: uuid.UUID,
    payload: TaskIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    task = await create_task(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        project_id=project_id,
        title=payload.title,
        description=payload.description,
        deadline=payload.deadline,
        capacity=payload.capacity,
        status=payload.status,
    )
    await db.commit()
    await db.refresh(task)
    return await _task_out(db, task)


@router.patch("/clubs/{club_id}/tasks/{task_id}", response_model=TaskOut)
async def patch_task_endpoint(
    task_id: uuid.UUID,
    payload: TaskPatch,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> TaskOut:
    data = payload.model_dump(exclude_unset=True)
    clear_deadline = bool(data.pop("clear_deadline", False))
    clear_capacity = bool(data.pop("clear_capacity", False))
    deadline = data["deadline"] if "deadline" in data or clear_deadline else ...
    if clear_deadline:
        deadline = None
    capacity = data["capacity"] if "capacity" in data or clear_capacity else ...
    if clear_capacity:
        capacity = None
    task = await patch_task(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        task_id=task_id,
        title=data.get("title"),
        description=data.get("description"),
        status=data.get("status"),
        deadline=deadline,
        capacity=capacity,
    )
    await db.commit()
    await db.refresh(task)
    return await _task_out(db, task)


@router.post("/clubs/{club_id}/tasks/{task_id}/signup", response_model=AssignmentOut)
async def signup(
    task_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> AssignmentOut:
    assignment = await signup_for_task(
        db, club_id=club.id, user_id=auth.user.id, task_id=task_id
    )
    await db.commit()
    rows = await list_my_assignments(db, user_id=auth.user.id, club_id=club.id)
    loaded = next(a for a in rows if a.id == assignment.id)
    return _assignment_out(loaded)


@router.post("/clubs/{club_id}/assignments/{assignment_id}/withdraw", response_model=AssignmentOut)
async def withdraw(
    assignment_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> AssignmentOut:
    assignment = await withdraw_assignment(
        db, club_id=club.id, user_id=auth.user.id, assignment_id=assignment_id
    )
    await db.commit()
    rows = await list_my_assignments(db, user_id=auth.user.id, club_id=club.id)
    loaded = next((a for a in rows if a.id == assignment.id), None)
    if loaded is None:
        return AssignmentOut.model_validate(assignment)
    return _assignment_out(loaded)


@router.get("/me/assignments", response_model=list[AssignmentOut])
async def my_assignments(
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
    club_id: uuid.UUID | None = None,
) -> list[AssignmentOut]:
    rows = await list_my_assignments(db, user_id=auth.user.id, club_id=club_id)
    return [_assignment_out(a) for a in rows]


@router.post("/clubs/{club_id}/tasks/{task_id}/assign", response_model=AssignmentOut)
async def assign(
    task_id: uuid.UUID,
    payload: AssignIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> AssignmentOut:
    assignment = await organizer_assign(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        task_id=task_id,
        user_id=payload.user_id,
    )
    await db.commit()
    roster = await list_task_roster(
        db, club_id=club.id, actor_user_id=auth.user.id, task_id=task_id
    )
    loaded = next(a for a in roster if a.id == assignment.id)
    user = await db.get(User, loaded.user_id)
    return _assignment_out(loaded, user=user)


@router.post("/clubs/{club_id}/assignments/{assignment_id}/status", response_model=AssignmentOut)
async def set_status(
    assignment_id: uuid.UUID,
    payload: AssignmentStatusIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> AssignmentOut:
    assignment = await organizer_set_assignment_status(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        assignment_id=assignment_id,
        status=payload.status,
    )
    await db.commit()
    user = await db.get(User, assignment.user_id)
    return _assignment_out(assignment, user=user)


@router.get("/clubs/{club_id}/tasks/{task_id}/roster", response_model=list[AssignmentOut])
async def roster(
    task_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> list[AssignmentOut]:
    rows = await list_task_roster(
        db, club_id=club.id, actor_user_id=auth.user.id, task_id=task_id
    )
    out: list[AssignmentOut] = []
    for row in rows:
        user = await db.get(User, row.user_id)
        out.append(_assignment_out(row, user=user))
    return out
