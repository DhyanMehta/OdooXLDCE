from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ProjectIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    status: str = "draft"


class ProjectPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    status: str | None = None


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    deadline: datetime | None = None
    capacity: int | None = Field(default=None, ge=0)
    status: str = "open"


class TaskPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    deadline: datetime | None = None
    capacity: int | None = Field(default=None, ge=0)
    clear_deadline: bool = False
    clear_capacity: bool = False
    status: str | None = None


class AssignIn(BaseModel):
    user_id: UUID


class AssignmentStatusIn(BaseModel):
    status: str


class TaskOut(ORMModel):
    id: UUID
    project_id: UUID
    title: str
    description: str
    deadline: datetime | None
    status: str
    capacity: int | None
    active_count: int | None = None
    created_at: datetime
    updated_at: datetime


class ProjectOut(ORMModel):
    id: UUID
    club_id: UUID
    title: str
    description: str
    status: str
    created_at: datetime
    updated_at: datetime
    tasks: list[TaskOut] = []


class AssignmentOut(ORMModel):
    id: UUID
    task_id: UUID
    user_id: UUID
    status: str
    signed_up_at: datetime
    completed_at: datetime | None
    assigned_by_user_id: UUID | None
    task_title: str | None = None
    project_id: UUID | None = None
    project_title: str | None = None
    club_id: UUID | None = None
    user_email: str | None = None
    user_name: str | None = None
