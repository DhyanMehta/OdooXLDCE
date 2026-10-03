"""Role catalog, assignments, handover, and audit-log response contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class AssignRoleIn(BaseModel):
    user_id: UUID
    role_code: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class HandoverIn(BaseModel):
    outgoing_assignment_id: UUID
    incoming_user_id: UUID


class RoleOut(BaseModel):
    id: str
    code: str
    name: str


class RoleAssignmentOut(BaseModel):
    id: str
    user_id: str
    user_email: str | None = None
    user_name: str | None = None
    role_code: str | None = None
    starts_at: str
    ends_at: str | None = None
    state: Literal["active", "scheduled", "ended"]


class RoleAssignmentIdOut(BaseModel):
    id: str


class RoleAssignmentEndOut(BaseModel):
    id: str
    ends_at: str | None = None


class RoleHandoverOut(BaseModel):
    outgoing_id: str
    incoming_id: str


class AuditLogOut(BaseModel):
    id: str
    action: str
    entity_type: str
    entity_id: str | None = None
    entity_label: str
    actor_user_id: str | None = None
    actor_name: str | None = None
    actor_email: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: str
