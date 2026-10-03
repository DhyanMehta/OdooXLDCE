"""Shared checkout: orders, items, payments."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import UUIDPrimaryKeyMixin


class Order(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="ck_orders_total_nonneg"),
        CheckConstraint(
            "status IN ('pending', 'paid', 'cancelled', 'refund_required', 'refunded')",
            name="ck_orders_status",
        ),
    )

    # RESTRICT: purchase history must not vanish if a club/user row is removed.
    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    # Reservation window for ticket/merch holds; null for membership-only orders.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    items: Mapped[list[OrderItem]] = relationship(back_populates="order")
    payments: Mapped[list[Payment]] = relationship(back_populates="order")


class OrderItem(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint(
            "("
            "item_kind = 'membership' AND membership_plan_id IS NOT NULL AND ticket_price_id IS NULL "
            "AND product_variant_id IS NULL AND quantity = 1 AND fulfillment_status IS NULL"
            ") OR ("
            "item_kind = 'ticket' AND ticket_price_id IS NOT NULL AND membership_plan_id IS NULL "
            "AND product_variant_id IS NULL AND quantity >= 1 AND fulfillment_status IS NULL"
            ") OR ("
            "item_kind = 'merchandise' AND product_variant_id IS NOT NULL AND membership_plan_id IS NULL "
            "AND ticket_price_id IS NULL AND quantity >= 1 "
            "AND fulfillment_status IN ('reserved', 'awaiting_collection', 'collected', 'cancelled')"
            ")",
            name="ck_order_items_kind_refs",
        ),
        CheckConstraint("unit_price_snapshot >= 0", name="ck_order_items_price_nonneg"),
        CheckConstraint("quantity >= 1", name="ck_order_items_quantity_positive"),
        CheckConstraint(
            "item_kind IN ('membership', 'ticket', 'merchandise')",
            name="ck_order_items_kind",
        ),
        CheckConstraint(
            "("
            "item_kind IN ('ticket', 'merchandise') AND duration_days_snapshot IS NULL "
            "AND fixed_expires_on_snapshot IS NULL"
            ") OR ("
            "item_kind = 'membership' AND ("
            "(duration_days_snapshot IS NOT NULL AND fixed_expires_on_snapshot IS NULL) OR "
            "(duration_days_snapshot IS NULL AND fixed_expires_on_snapshot IS NOT NULL)"
            ")"
            ")",
            name="ck_order_items_membership_term_snapshot",
        ),
        CheckConstraint(
            "duration_days_snapshot IS NULL OR duration_days_snapshot > 0",
            name="ck_order_items_duration_positive",
        ),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    item_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    membership_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("membership_plans.id", ondelete="RESTRICT")
    )
    ticket_price_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ticket_prices.id", ondelete="RESTRICT")
    )
    product_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_variants.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Snapshot so later plan/price edits cannot rewrite historical purchases.
    unit_price_snapshot: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    title_snapshot: Mapped[str] = mapped_column(String(240), nullable=False)
    # Plan terms frozen at order creation for consistent fulfillment.
    duration_days_snapshot: Mapped[int | None] = mapped_column(Integer)
    fixed_expires_on_snapshot: Mapped[date | None] = mapped_column(Date)
    # Merch-only lifecycle: reserved → awaiting_collection → collected | cancelled.
    fulfillment_status: Mapped[str | None] = mapped_column(String(32))

    order: Mapped[Order] = relationship(back_populates="items")


class Payment(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount >= 0", name="ck_payments_amount_nonneg"),
        CheckConstraint(
            "status IN ('pending', 'confirmed', 'failed', 'refund_required', 'refunded')",
            name="ck_payments_status",
        ),
    )

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    method: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    provider_ref: Mapped[str | None] = mapped_column(String(120))
    confirmed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    order: Mapped[Order] = relationship(back_populates="payments")
    events: Mapped[list[PaymentEvent]] = relationship(back_populates="payment")


class PaymentEvent(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "payment_events"

    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Never store raw QR tokens or credential secrets in payload.
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    payment: Mapped[Payment] = relationship(back_populates="events")
