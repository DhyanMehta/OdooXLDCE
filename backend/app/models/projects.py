"""Club projects, volunteer tasks, and assignment history."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Project(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'open', 'closed', 'archived')",
            name="ck_projects_status",
        ),
    )

    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)

    tasks: Mapped[list[Task]] = relationship(back_populates="project")


class Task(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'in_progress', 'done', 'cancelled')",
            name="ck_tasks_status",
        ),
        CheckConstraint("capacity IS NULL OR capacity >= 0", name="ck_tasks_capacity_nonneg"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", index=True)
    # Null capacity = unlimited volunteer slots.
    capacity: Mapped[int | None] = mapped_column(Integer)

    project: Mapped[Project] = relationship(back_populates="tasks")
    assignments: Mapped[list[TaskAssignment]] = relationship(back_populates="task")


class TaskAssignment(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "task_assignments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'withdrawn', 'cancelled', 'completed')",
            name="ck_task_assignments_status",
        ),
        Index(
            "uq_task_assignments_active_task_user",
            "task_id",
            "user_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tasks.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    signed_up_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    task: Mapped[Task] = relationship(back_populates="assignments")
