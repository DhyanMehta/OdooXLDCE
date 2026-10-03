from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    dues_amount: Decimal = Field(ge=0)
    duration_days: int | None = Field(default=None, ge=1)
    fixed_expires_on: date | None = None
    is_active: bool = True


class PlanPatch(BaseModel):
    """Partial update: omitted fields unchanged; explicit null clears XOR sides."""

    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    dues_amount: Decimal | None = Field(default=None, ge=0)
    duration_days: int | None = Field(default=None, ge=1)
    fixed_expires_on: date | None = None
    is_active: bool | None = None
    archived: bool | None = None


class PlanOut(ORMModel):
    id: UUID
    club_id: UUID
    name: str
    description: str
    dues_amount: Decimal
    duration_days: int | None
    fixed_expires_on: date | None
    is_active: bool
    archived_at: datetime | None = None


class MembershipOut(ORMModel):
    id: UUID
    club_id: UUID
    user_id: UUID
    plan_id: UUID
    starts_at: datetime
    ends_at: datetime
    status: str
    effective_state: Literal["upcoming", "active", "expired", "revoked"] | None = None
    plan_name: str | None = None


class MemberPersonOut(BaseModel):
    user_id: UUID
    email: str
    full_name: str
    is_affiliated: bool
    effective_state: Literal["upcoming", "active", "expired", "revoked", "none"]
    current_membership_id: UUID | None = None
    current_plan_name: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    pending_dues_count: int = 0


class MemberPageOut(BaseModel):
    items: list[MemberPersonOut]
    total: int
    limit: int
    offset: int


class DirectoryPersonOut(BaseModel):
    """Club affiliation row for role-assignment UIs (string ids)."""

    user_id: str
    full_name: str
    email: str
