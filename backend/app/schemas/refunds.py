from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class RefundRequestIn(BaseModel):
    order_id: UUID
    reason: str = Field(default="", max_length=1000)


class RefundDecideIn(BaseModel):
    decision: Literal["approved", "rejected"]
    reason: str = Field(default="", max_length=1000)


class RefundCompleteIn(BaseModel):
    """Operator confirms they returned the money outside CampusOS."""

    manual_reference: str = Field(min_length=1, max_length=200)
    acknowledge_used: bool = False
    physical_return: bool = False
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=160)


class RefundOut(ORMModel):
    id: UUID
    club_id: UUID
    order_id: UUID
    payment_id: UUID
    amount: Decimal
    currency: str
    status: str
    reason: str
    manual_reference: str | None = None
    acknowledge_used: bool
    physical_return: bool
    requested_by_user_id: UUID
    decided_by_user_id: UUID | None = None
    completed_by_user_id: UUID | None = None
    requested_at: datetime
    decided_at: datetime | None = None
    completed_at: datetime | None = None
