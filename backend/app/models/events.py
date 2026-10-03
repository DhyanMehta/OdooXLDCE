"""Events, ticket types/prices, issued tickets, check-ins.

Denormalized ticket.event_id / club_id / user_id are kept for query performance
and attendance reports. Consistency with ticket_type → event → club and
order → user is enforced by DB triggers (see integrity migration) rather than
removing the columns.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Event(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("capacity >= 0", name="ck_events_capacity_nonneg"),
        CheckConstraint("ends_at > starts_at", name="ck_events_end_after_start"),
        CheckConstraint(
            "status IN ('draft', 'published', 'cancelled')",
            name="ck_events_status",
        ),
        CheckConstraint(
            "sales_opens_at IS NULL OR sales_closes_at IS NULL OR sales_closes_at > sales_opens_at",
            name="ck_events_sales_window",
        ),
    )

    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    venue: Mapped[str] = mapped_column(String(240), nullable=False, default="")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    sales_opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sales_closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    ticket_types: Mapped[list[TicketType]] = relationship(back_populates="event")


class TicketType(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "ticket_types"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    event: Mapped[Event] = relationship(back_populates="ticket_types")
    prices: Mapped[list[TicketPrice]] = relationship(back_populates="ticket_type")


class TicketPrice(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "ticket_prices"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_ticket_prices_amount_nonneg"),
        CheckConstraint("audience IN ('member', 'public')", name="ck_ticket_prices_audience"),
        UniqueConstraint("ticket_type_id", "audience", name="uq_ticket_prices_type_audience"),
    )

    ticket_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ticket_types.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    audience: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    ticket_type: Mapped[TicketType] = relationship(back_populates="prices")


class Ticket(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "tickets"
    __table_args__ = (
        CheckConstraint(
            "status IN ('valid', 'cancelled', 'refund_required', 'used')",
            name="ck_tickets_status",
        ),
        CheckConstraint("unit_index >= 0", name="ck_tickets_unit_index_nonneg"),
        UniqueConstraint("order_item_id", "unit_index", name="uq_tickets_item_unit"),
    )

    order_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # 0..quantity-1 within the order line — together with order_item_id uniquely identifies a seat.
    unit_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ticket_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ticket_types.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="valid", index=True)
    # Hash for check-in; AEAD (or legacy signed) blob for owner re-display only.
    qr_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    qr_token_sealed: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    checkin: Mapped[TicketCheckin | None] = relationship(back_populates="ticket", uselist=False)


class TicketCheckin(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "ticket_checkins"
    __table_args__ = (UniqueConstraint("ticket_id", name="uq_ticket_checkins_ticket"),)

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="RESTRICT"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    checked_in_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    checked_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    ticket: Mapped[Ticket] = relationship(back_populates="checkin")
