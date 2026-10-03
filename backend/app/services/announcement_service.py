"""Announcements, mailing list, and delivery queueing."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.core.security import generate_token, hash_token
from app.models import Announcement, MailingListSubscription, NotificationDelivery, User
from app.services.audit import record_audit
from app.services.membership_eligibility import has_active_membership, utcnow
from app.services.rbac import require_permission


def normalize_email(email: str) -> str:
    return email.strip().lower()


def create_announcement(
    db: Session,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    title: str,
    body: str,
    visibility: str,
) -> Announcement:
    require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_announcements")
    if visibility not in {"public", "members"}:
        raise AppError("Visibility must be public or members.")
    row = Announcement(
        club_id=club_id,
        title=title.strip(),
        body=body.strip(),
        visibility=visibility,
        status="draft",
        author_user_id=actor_user_id,
    )
    db.add(row)
    db.flush()
    record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="announcement.created",
        entity_type="announcement",
        entity_id=row.id,
    )
    return row


def update_announcement(
    db: Session,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    announcement_id: uuid.UUID,
    title: str | None = None,
    body: str | None = None,
    visibility: str | None = None,
) -> Announcement:
    require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_announcements")
    row = db.get(Announcement, announcement_id)
    if row is None or row.club_id != club_id:
        raise NotFoundError("Announcement not found.")
    if title is not None:
        row.title = title.strip()
    if body is not None:
        row.body = body.strip()
    if visibility is not None:
        if visibility not in {"public", "members"}:
            raise AppError("Visibility must be public or members.")
        row.visibility = visibility
    record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="announcement.updated",
        entity_type="announcement",
        entity_id=row.id,
    )
    return row


def publish_announcement(
    db: Session,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    announcement_id: uuid.UUID,
) -> Announcement:
    """Save published state and queue deliveries in the same transaction."""
    require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_announcements")
    row = db.get(Announcement, announcement_id)
    if row is None or row.club_id != club_id:
        raise NotFoundError("Announcement not found.")
    if row.status == "published":
        return row
    row.status = "published"
    row.published_at = utcnow()

    recipients: set[str] = set()
    subs = db.scalars(
        select(MailingListSubscription).where(
            MailingListSubscription.club_id == club_id,
            MailingListSubscription.status == "active",
        )
    ).all()
    for sub in subs:
        recipients.add(sub.email)

    if row.visibility == "members":
        # Members-only announcements notify only active paid members among subscribers.
        filtered: set[str] = set()
        for email in recipients:
            user = db.scalar(select(User).where(User.email == email))
            if user and has_active_membership(db, club_id=club_id, user_id=user.id):
                filtered.add(email)
        recipients = filtered

    for email in sorted(recipients):
        key = f"announcement:{row.id}:{email}"
        exists = db.scalar(
            select(NotificationDelivery).where(NotificationDelivery.idempotency_key == key)
        )
        if exists:
            continue
        db.add(
            NotificationDelivery(
                club_id=club_id,
                kind="announcement",
                announcement_id=row.id,
                membership_id=None,
                recipient_email=email,
                subject=row.title,
                body=row.body,
                status="queued",
                idempotency_key=key,
            )
        )
    record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="announcement.published",
        entity_type="announcement",
        entity_id=row.id,
        details={"recipients_queued": len(recipients)},
    )
    return row


def list_announcements(
    db: Session,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID | None,
    q: str | None,
    include_drafts: bool,
    limit: int = 20,
    offset: int = 0,
) -> list[Announcement]:
    stmt = select(Announcement).where(Announcement.club_id == club_id)
    if include_drafts:
        pass
    else:
        stmt = stmt.where(Announcement.status == "published")
        if user_id is None or not has_active_membership(db, club_id=club_id, user_id=user_id):
            stmt = stmt.where(Announcement.visibility == "public")
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(Announcement.title.ilike(pattern), Announcement.body.ilike(pattern)))
    stmt = stmt.order_by(Announcement.published_at.desc().nullslast(), Announcement.created_at.desc())
    stmt = stmt.limit(min(limit, 100)).offset(max(offset, 0))
    return list(db.scalars(stmt).all())


def get_announcement(
    db: Session,
    *,
    club_id: uuid.UUID,
    announcement_id: uuid.UUID,
    user_id: uuid.UUID | None,
) -> Announcement:
    row = db.get(Announcement, announcement_id)
    if row is None or row.club_id != club_id:
        raise NotFoundError("Announcement not found.")
    if row.status != "published":
        raise NotFoundError("Announcement not found.")
    if row.visibility == "members":
        if user_id is None or not has_active_membership(db, club_id=club_id, user_id=user_id):
            raise NotFoundError("Announcement not found.")
    return row


def subscribe_mailing_list(
    db: Session,
    *,
    club_id: uuid.UUID,
    email: str,
) -> tuple[MailingListSubscription, str | None]:
    """Subscribe without revealing whether an email was already on the list."""
    require_permission_not_needed = True  # public action
    del require_permission_not_needed
    normalized = normalize_email(email)
    existing = db.scalar(
        select(MailingListSubscription).where(
            MailingListSubscription.club_id == club_id,
            MailingListSubscription.email == normalized,
        )
    )
    raw_token = generate_token(24)
    if existing:
        if existing.status != "active":
            existing.status = "active"
            existing.consent_at = utcnow()
            existing.unsubscribe_token_hash = hash_token(raw_token)
            existing.unsubscribed_at = None
            return existing, raw_token
        # Do not disclose existing subscription; return no fresh token.
        return existing, None
    row = MailingListSubscription(
        club_id=club_id,
        email=normalized,
        status="active",
        consent_at=utcnow(),
        unsubscribe_token_hash=hash_token(raw_token),
    )
    db.add(row)
    db.flush()
    return row, raw_token


def unsubscribe_mailing_list(db: Session, *, token: str) -> None:
    row = db.scalar(
        select(MailingListSubscription).where(
            MailingListSubscription.unsubscribe_token_hash == hash_token(token)
        )
    )
    # Always succeed outwardly to avoid token/email oracle behavior.
    if row and row.status == "active":
        row.status = "unsubscribed"
        row.unsubscribed_at = utcnow()


def list_mailing_subscriptions(
    db: Session,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    status: str | None = None,
) -> list[MailingListSubscription]:
    """Staff-only subscriber roster. Not exposed on public pages."""
    require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_mailing_list")
    stmt = select(MailingListSubscription).where(MailingListSubscription.club_id == club_id)
    if status:
        stmt = stmt.where(MailingListSubscription.status == status)
    stmt = stmt.order_by(MailingListSubscription.created_at.desc())
    return list(db.scalars(stmt).all())


def staff_unsubscribe(
    db: Session,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    subscription_id: uuid.UUID,
) -> MailingListSubscription:
    require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_mailing_list")
    row = db.get(MailingListSubscription, subscription_id)
    if row is None or row.club_id != club_id:
        raise NotFoundError("Subscription not found.")
    if row.status == "active":
        row.status = "unsubscribed"
        row.unsubscribed_at = utcnow()
        record_audit(
            db,
            club_id=club_id,
            actor_user_id=actor_user_id,
            action="mailing_list.unsubscribed",
            entity_type="mailing_list_subscription",
            entity_id=row.id,
            details={"email": row.email},
        )
    return row


def queue_renewal_reminders(db: Session, *, within_days: int) -> int:
    from datetime import timedelta

    from app.models import Membership

    now = utcnow()
    horizon = now + timedelta(days=within_days)
    memberships = db.scalars(
        select(Membership).where(
            Membership.status == "active",
            Membership.ends_at > now,
            Membership.ends_at <= horizon,
        )
    ).all()
    created = 0
    for membership in memberships:
        user = db.get(User, membership.user_id)
        if user is None:
            continue
        key = f"renewal:{membership.id}:{membership.ends_at.date().isoformat()}"
        if db.scalar(select(NotificationDelivery).where(NotificationDelivery.idempotency_key == key)):
            continue
        db.add(
            NotificationDelivery(
                club_id=membership.club_id,
                kind="renewal_reminder",
                announcement_id=None,
                membership_id=membership.id,
                recipient_email=user.email,
                subject="Membership renewal reminder",
                body=(
                    f"Your membership ends on {membership.ends_at.isoformat()}. "
                    "Renew to keep member ticket pricing and members-only updates."
                ),
                status="queued",
                idempotency_key=key,
            )
        )
        created += 1
    return created
