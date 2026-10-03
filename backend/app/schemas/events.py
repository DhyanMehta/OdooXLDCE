from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

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


class TicketTypeIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    member_price: Decimal = Field(ge=0)
    public_price: Decimal = Field(ge=0)


class EventCreateIn(EventIn):
    """Atomic create: event + optional ticket types + optional publish."""

    ticket_types: list[TicketTypeIn] = Field(default_factory=list)
    publish: bool = False


class EventStatusIn(BaseModel):
    status: str


class TicketTypePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    is_active: bool | None = None
    member_price: Decimal | None = Field(default=None, ge=0)
    public_price: Decimal | None = Field(default=None, ge=0)
    member_price_active: bool | None = None
    public_price_active: bool | None = None


class TicketPriceOut(ORMModel):
    id: UUID
    audience: str
    amount: Decimal
    is_active: bool


class TicketTypeOut(ORMModel):
    id: UUID
    name: str
    description: str
    is_active: bool = True
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


class AffectedBookingOut(BaseModel):
    order_id: UUID
    user_id: UUID
    user_email: str | None = None
    user_name: str | None = None
    order_status: str
    ticket_count: int = 0
    reason: str


class EventStatusOut(BaseModel):
    event: EventOut
    affected_bookings: list[AffectedBookingOut] = []


class CheckInIn(BaseModel):
    qr_token: str | None = Field(default=None, min_length=8)
    override_window: bool = False
    # Explicit ticket id for attendee-lookup path (still validated server-side).
    ticket_id: UUID | None = None

    @model_validator(mode="after")
    def _require_credential(self) -> CheckInIn:
        if not self.ticket_id and not self.qr_token:
            raise ValueError("Provide qr_token or ticket_id.")
        return self


class CheckInOut(BaseModel):
    status: str
    duplicate: bool = False
    ticket_id: UUID
    event_id: UUID
    attendee_name: str | None = None
    attendee_email: str | None = None
    ticket_type_name: str | None = None
    ticket_status: str
    checked_in_at: datetime
    checked_in_by_name: str | None = None
    original_checked_in_at: datetime | None = None


class CheckInListItem(BaseModel):
    id: UUID
    ticket_id: UUID
    attendee_name: str | None
    attendee_email: str | None
    ticket_type_name: str | None
    checked_in_at: datetime
    checked_in_by_name: str | None


class AttendeeTicketOut(BaseModel):
    ticket_id: UUID
    user_id: UUID
    attendee_name: str
    attendee_email: str
    ticket_type_name: str
    ticket_status: str
    checked_in: bool
    checked_in_at: datetime | None = None


class TicketOut(ORMModel):
    id: UUID
    event_id: UUID
    club_id: UUID
    status: str
    issued_at: datetime
    qr_token: str | None = None
    event_title: str | None = None


class AttendanceOut(BaseModel):
    """Exact attendance-report JSON (string event_id, float percentage)."""

    event_id: str
    tickets_issued: int
    unique_checkins: int
    attendance_percentage: float
    denominator: str
