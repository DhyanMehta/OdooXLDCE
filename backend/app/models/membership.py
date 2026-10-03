"""Membership plans and paid entitlements."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class MembershipPlan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "membership_plans"
    __table_args__ = (
        CheckConstraint(
            "(duration_days IS NOT NULL AND fixed_expires_on IS NULL) OR "
            "(duration_days IS NULL AND fixed_expires_on IS NOT NULL)",
            name="ck_membership_plans_duration_xor_fixed",
        ),
        CheckConstraint("dues_amount >= 0", name="ck_membership_plans_dues_nonneg"),
        CheckConstraint(
            "duration_days IS NULL OR duration_days > 0",
            name="ck_membership_plans_duration_positive",
        ),
    )

    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dues_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    duration_days: Mapped[int | None] = mapped_column(Integer)
    fixed_expires_on: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Membership(Base, UUIDPrimaryKeyMixin):
    """Paid entitlement dates are snapshotted at purchase confirmation."""

    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_memberships_end_after_start"),
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_memberships_status",
        ),
    )

    # RESTRICT keeps paid history when clubs/users are archived rather than hard-deleted.
    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("membership_plans.id", ondelete="RESTRICT"), nullable=False
    )
    order_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order_items.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
