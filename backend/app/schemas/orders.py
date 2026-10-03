from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class MembershipOrderIn(BaseModel):
    plan_id: UUID


class TicketOrderIn(BaseModel):
    ticket_price_id: UUID
    quantity: int = Field(default=1, ge=1, le=10)


class DemoPayIn(BaseModel):
    success: bool = True


class ManualPayIn(BaseModel):
    provider_ref: str = Field(min_length=1, max_length=120)


class OrderItemOut(ORMModel):
    id: UUID
    item_kind: str
    quantity: int
    unit_price_snapshot: Decimal
    title_snapshot: str
    membership_plan_id: UUID | None
    ticket_price_id: UUID | None


class PaymentOut(ORMModel):
    id: UUID
    amount: Decimal
    method: str
    status: str
    provider_ref: str | None
    confirmed_at: datetime | None


class OrderOut(ORMModel):
    id: UUID
    club_id: UUID
    user_id: UUID
    status: str
    total_amount: Decimal
    currency: str
    expires_at: datetime | None
    created_at: datetime
    items: list[OrderItemOut] = []
    payments: list[PaymentOut] = []
