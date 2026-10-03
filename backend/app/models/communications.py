"""Announcements, mailing list, notification deliveries.

Search uses ILIKE '%q%' on title/body; pg_trgm GIN indexes support that pattern
(see migration b2c3d4e5f6a7). There is no tsvector/FTS index.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class Announcement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "announcements"
    __table_args__ = (
        CheckConstraint("visibility IN ('public', 'members')", name="ck_announcements_visibility"),
        CheckConstraint("status IN ('draft', 'published')", name="ck_announcements_status"),
    )

    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="public")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    author_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    # Bumped only when staff explicitly sends a correction notification.
    correction_seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class MailingListSubscription(Base, UUIDPrimaryKeyMixin):
    """Optional announcement mailing list (not transactional account email).

    Status lifecycle: pending → active → unsubscribed.
    Re-submitting an unsubscribed email starts a new pending confirmation;
    it does not silently reactivate.
    """

    __tablename__ = "mailing_list_subscriptions"
    __table_args__ = (
        UniqueConstraint("club_id", "email", name="uq_mailing_list_club_email"),
        CheckConstraint(
            "status IN ('pending', 'active', 'unsubscribed')",
            name="ck_mailing_list_status",
        ),
    )

    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirm_token_hash: Mapped[str | None] = mapped_column(String(64))
    confirm_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unsubscribe_token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    unsubscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationDelivery(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_notification_deliveries_idempotency"),
        CheckConstraint(
            "status IN ('queued', 'processing', 'sent_simulated', 'sent', 'failed', 'suppressed')",
            name="ck_notification_deliveries_status",
        ),
    )

    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    announcement_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("announcements.id", ondelete="CASCADE")
    )
    membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memberships.id", ondelete="CASCADE")
    )
    recipient_email: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by: Mapped[str | None] = mapped_column(String(80))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
