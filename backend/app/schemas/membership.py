from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
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


class PlanOut(ORMModel):
    id: UUID
    club_id: UUID
    name: str
    description: str
    dues_amount: Decimal
    duration_days: int | None
    fixed_expires_on: date | None
    is_active: bool


class MembershipOut(ORMModel):
    id: UUID
    club_id: UUID
    user_id: UUID
    plan_id: UUID
    starts_at: datetime
    ends_at: datetime
    status: str
