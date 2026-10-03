from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    venue: str = ""
    starts_at: datetime
    ends_at: datetime
    capacity: int = Field(ge=0)
    sales_opens_at: datetime | None = None
    sales_closes_at: datetime | None = None


class EventStatusIn(BaseModel):
    status: str


class TicketTypeIn(BaseModel):
    name: str
    description: str = ""
    member_price: Decimal = Field(ge=0)
    public_price: Decimal = Field(ge=0)


class TicketPriceOut(ORMModel):
    id: UUID
    audience: str
    amount: Decimal
    is_active: bool


class TicketTypeOut(ORMModel):
    id: UUID
    name: str
    description: str
    prices: list[TicketPriceOut] = []


class EventOut(ORMModel):
    id: UUID
    club_id: UUID
    title: str
    description: str
    venue: str
    starts_at: datetime
    ends_at: datetime
    capacity: int
    status: str
    sales_opens_at: datetime | None
    sales_closes_at: datetime | None
    ticket_types: list[TicketTypeOut] = []
    seats_remaining: int | None = None


class CheckInIn(BaseModel):
    qr_token: str = Field(min_length=8)


class TicketOut(ORMModel):
    id: UUID
    event_id: UUID
    club_id: UUID
    status: str
    issued_at: datetime
    qr_token: str | None = None
    event_title: str | None = None
