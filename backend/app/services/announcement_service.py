"""Announcements, mailing list (double opt-in), and delivery queueing."""

from __future__ import annotations

import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.core.security import generate_token, hash_token
from app.core.time import utcnow
from app.models import Announcement, Club, MailingListSubscription, Membership, NotificationDelivery, User
from app.services.audit import record_audit
from app.services.membership_eligibility import (
    continuous_entitlement_chain_end,
    has_active_membership,
)
from app.services.rbac import require_permission

CONFIRM_TTL_HOURS = 48
OPAQUE_SUBSCRIBE_MSG = (
    "If this address can be subscribed, a confirmation message has been prepared."
)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _public_base_url() -> str:
    # Prefer first CORS origin as the public site base for confirm/unsubscribe links.
    origins = get_settings().cors_origins
    return (origins[0] if origins else "http://127.0.0.1:5173").rstrip("/")


def _write_dev_preview(*, kind: str, to_email: str, subject: str, body: str) -> Path:
    outbox = Path(__file__).resolve().parents[1] / "var" / "email_outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    path = outbox / f"{kind}-{uuid.uuid4().hex[:12]}.txt"
    path.write_text(f"To: {to_email}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
    return path


async def create_announcement(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    title: str,
    body: str,
    visibility: str,
) -> Announcement:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_announcements")
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
    await db.flush()
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="announcement.created",
        entity_type="announcement",
        entity_id=row.id,
        details={"visibility": visibility},
    )
    return row


async def update_announcement(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    announcement_id: uuid.UUID,
    title: str | None = None,
    body: str | None = None,
    visibility: str | None = None,
) -> Announcement:
    """Edit website content only — does not queue or resend notifications."""
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_announcements")
    row = await db.get(Announcement, announcement_id)
    if row is None or row.club_id != club_id:
        raise NotFoundError("Announcement not found.")
    before = {"title": row.title, "body": row.body, "visibility": row.visibility}
    if title is not None:
        row.title = title.strip()
    if body is not None:
        row.body = body.strip()
    if visibility is not None:
        if visibility not in {"public", "members"}:
            raise AppError("Visibility must be public or members.")
        row.visibility = visibility
    after = {"title": row.title, "body": row.body, "visibility": row.visibility}
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="announcement.updated",
        entity_type="announcement",
        entity_id=row.id,
        details={"before": before, "after": after, "content_only": True},
    )
    return row


async def _eligible_subscriber_emails(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    visibility: str,
) -> list[tuple[str, str]]:
    """Return (email, unsubscribe_token_placeholder_hash) for active confirmed subscribers."""
    subs = (
        await db.scalars(
            select(MailingListSubscription).where(
                MailingListSubscription.club_id == club_id,
                MailingListSubscription.status == "active",
            )
        )
    ).all()
    out: list[tuple[str, str]] = []
    for sub in subs:
        if visibility == "members":
            user = await db.scalar(select(User).where(User.email == sub.email))
            if user is None or not await has_active_membership(db, club_id=club_id, user_id=user.id):
                continue
        out.append((sub.email, sub.unsubscribe_token_hash))
    return out


async def _queue_announcement_emails(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    announcement: Announcement,
    kind: str,
    idempotency_prefix: str,
    subject: str,
    body: str,
) -> int:
    queued = 0
    base = _public_base_url()
    for email, _token_hash in sorted(
        await _eligible_subscriber_emails(db, club_id=club_id, visibility=announcement.visibility)
    ):
        # Resolve raw unsubscribe token is impossible from hash — store link using a
        # per-delivery opaque reference looked up by email at send time via hash re-read.
        key = f"{idempotency_prefix}:{announcement.id}:{email}"
        if await db.scalar(select(NotificationDelivery).where(NotificationDelivery.idempotency_key == key)):
            continue
        # Placeholder; worker injects unsubscribe URL from current subscription token...
        # We cannot reverse the hash, so store email in meta and append link at send using
        # a purpose-built one-time link path that looks up by delivery id.
        db.add(
            NotificationDelivery(
                club_id=club_id,
                kind=kind,
                announcement_id=announcement.id,
                membership_id=None,
                recipient_email=email,
                subject=subject,
                body=body,
                status="queued",
                idempotency_key=key,
                meta={"unsubscribe_base": base, "needs_unsubscribe_link": True},
            )
        )
        queued += 1
    return queued


async def publish_announcement(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    announcement_id: uuid.UUID,
) -> Announcement:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_announcements")
    row = await db.scalar(
        select(Announcement).where(Announcement.id == announcement_id, Announcement.club_id == club_id).with_for_update()
    )
    if row is None:
        raise NotFoundError("Announcement not found.")
    if row.status == "published":
        return row
    row.status = "published"
    row.published_at = utcnow()
    n = await _queue_announcement_emails(
        db,
        club_id=club_id,
        announcement=row,
        kind="announcement",
        idempotency_prefix="announcement",
        subject=row.title,
        body=row.body,
    )
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="announcement.published",
        entity_type="announcement",
        entity_id=row.id,
        details={"recipients_queued": n},
    )
    return row


async def send_correction_notification(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    announcement_id: uuid.UUID,
) -> Announcement:
    """Explicit correction email — never fired automatically by content edit."""
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_announcements")
    row = await db.scalar(
        select(Announcement).where(Announcement.id == announcement_id, Announcement.club_id == club_id).with_for_update()
    )
    if row is None:
        raise NotFoundError("Announcement not found.")
    if row.status != "published":
        raise AppError("Only published announcements can send correction notifications.")
    row.correction_seq = int(row.correction_seq or 0) + 1
    subject = f"[Correction] {row.title}"
    body = f"Correction to a previous announcement:\n\n{row.body}"
    n = await _queue_announcement_emails(
        db,
        club_id=club_id,
        announcement=row,
        kind="announcement_correction",
        idempotency_prefix=f"announcement_correction:{row.correction_seq}",
        subject=subject,
        body=body,
    )
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="announcement.correction_queued",
        entity_type="announcement",
        entity_id=row.id,
        details={"correction_seq": row.correction_seq, "recipients_queued": n},
    )
    return row


async def list_announcements(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID | None,
    q: str | None,
    include_drafts: bool,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Announcement], int]:
    stmt = select(Announcement).where(Announcement.club_id == club_id)
    if not include_drafts:
        stmt = stmt.where(Announcement.status == "published")
        if user_id is None or not await has_active_membership(db, club_id=club_id, user_id=user_id):
            stmt = stmt.where(Announcement.visibility == "public")
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(Announcement.title.ilike(pattern), Announcement.body.ilike(pattern)))
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    stmt = stmt.order_by(Announcement.published_at.desc().nullslast(), Announcement.created_at.desc())
    stmt = stmt.limit(min(limit, 100)).offset(max(offset, 0))
    return list((await db.scalars(stmt)).all()), int(total)


async def get_announcement(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    announcement_id: uuid.UUID,
    user_id: uuid.UUID | None,
    staff_preview: bool = False,
) -> Announcement:
    row = await db.get(Announcement, announcement_id)
    if row is None or row.club_id != club_id:
        raise NotFoundError("Announcement not found.")
    if staff_preview and user_id is not None:
        try:
            await require_permission(db, club_id=club_id, user_id=user_id, permission="manage_announcements")
            return row
        except ForbiddenError:
            pass
    if row.status != "published":
        raise NotFoundError("Announcement not found.")
    if row.visibility == "members":
        if user_id is None or not await has_active_membership(db, club_id=club_id, user_id=user_id):
            raise NotFoundError("Announcement not found.")
    return row


async def subscribe_mailing_list(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    email: str,
    consent: bool,
) -> None:
    """Consent-based subscribe. Always opaque; never returns tokens."""
    if not consent:
        raise AppError("Consent is required to subscribe to optional announcements.")
    club = await db.get(Club, club_id)
    if club is None or not club.is_active:
        raise NotFoundError("Club not found.")
    normalized = normalize_email(email)
    existing = await db.scalar(
        select(MailingListSubscription).where(
            MailingListSubscription.club_id == club_id,
            MailingListSubscription.email == normalized,
        )
    )
    # Already confirmed or waiting — do not disclose; do not change state.
    if existing and existing.status in {"active", "pending"}:
        return

    raw_confirm = generate_token(32)
    # Placeholder unsubscribe hash until confirmation (required NOT NULL).
    raw_unsub = generate_token(32)
    now = utcnow()
    if existing and existing.status == "unsubscribed":
        # Do not silently reactivate — require a new confirmation.
        existing.status = "pending"
        existing.consent_at = now
        existing.confirm_token_hash = hash_token(raw_confirm)
        existing.confirm_expires_at = now + timedelta(hours=CONFIRM_TTL_HOURS)
        existing.unsubscribe_token_hash = hash_token(raw_unsub)
        existing.unsubscribed_at = None
    else:
        row = MailingListSubscription(
            club_id=club_id,
            email=normalized,
            status="pending",
            consent_at=now,
            confirm_token_hash=hash_token(raw_confirm),
            confirm_expires_at=now + timedelta(hours=CONFIRM_TTL_HOURS),
            unsubscribe_token_hash=hash_token(raw_unsub),
        )
        db.add(row)
        await db.flush()

    confirm_url = f"{_public_base_url()}/mailing/confirm?token={raw_confirm}"
    _write_dev_preview(
        kind="confirm",
        to_email=normalized,
        subject=f"Confirm subscription — {club.name}",
        body=(
            f"Confirm your optional announcement subscription for {club.name}.\n\n"
            f"Confirm: {confirm_url}\n\n"
            f"This link expires in {CONFIRM_TTL_HOURS} hours.\n"
            "This is separate from transactional account messages."
        ),
    )


async def confirm_mailing_list(db: AsyncSession, *, token: str) -> bool:
    """Confirm pending subscription. Returns whether a pending row was activated."""
    row = await db.scalar(
        select(MailingListSubscription).where(
            MailingListSubscription.confirm_token_hash == hash_token(token)
        )
    )
    if row is None or row.status != "pending":
        return False
    if row.confirm_expires_at and row.confirm_expires_at <= utcnow():
        return False
    raw_unsub = generate_token(32)
    row.status = "active"
    row.unsubscribe_token_hash = hash_token(raw_unsub)
    row.confirm_token_hash = None
    row.confirm_expires_at = None
    row.unsubscribed_at = None
    # Dev preview of unsubscribe URL (not returned in API).
    unsub_url = f"{_public_base_url()}/mailing/unsubscribe?token={raw_unsub}"
    club = await db.get(Club, row.club_id)
    _write_dev_preview(
        kind="welcome",
        to_email=row.email,
        subject=f"Subscribed — {club.name if club else 'CampusOS'}",
        body=f"You are confirmed.\n\nUnsubscribe anytime: {unsub_url}\n",
    )
    return True


async def unsubscribe_mailing_list(db: AsyncSession, *, token: str) -> bool:
    row = await db.scalar(
        select(MailingListSubscription).where(
            MailingListSubscription.unsubscribe_token_hash == hash_token(token)
        )
    )
    if row and row.status == "active":
        row.status = "unsubscribed"
        row.unsubscribed_at = utcnow()
        return True
    return False


async def resolve_unsubscribe_token_for_email(
    db: AsyncSession, *, club_id: uuid.UUID, email: str
) -> str | None:
    """Worker cannot reverse hashes — unsubscribe links use delivery-scoped tokens in meta at claim time.

    At queue time we only know the hash. At send time we generate a short-lived delivery
    unsubscribe path using the delivery id (see worker).
    """
    del db, club_id, email
    return None


async def list_mailing_subscriptions(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    status: str | None = None,
    q: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[MailingListSubscription], int]:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_mailing_list")
    stmt = select(MailingListSubscription).where(MailingListSubscription.club_id == club_id)
    if status:
        stmt = stmt.where(MailingListSubscription.status == status)
    if q:
        stmt = stmt.where(MailingListSubscription.email.ilike(f"%{q.strip()}%"))
    total = await db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    rows = (
        await db.scalars(
            stmt.order_by(MailingListSubscription.created_at.desc()).limit(min(limit, 100)).offset(max(offset, 0))
        )
    ).all()
    return list(rows), int(total)


async def staff_unsubscribe(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    subscription_id: uuid.UUID,
) -> MailingListSubscription:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_mailing_list")
    row = await db.get(MailingListSubscription, subscription_id)
    if row is None or row.club_id != club_id:
        raise NotFoundError("Subscription not found.")
    if row.status in {"active", "pending"}:
        row.status = "unsubscribed"
        row.unsubscribed_at = utcnow()
        row.confirm_token_hash = None
        await record_audit(
            db,
            club_id=club_id,
            actor_user_id=actor_user_id,
            action="mailing_list.unsubscribed",
            entity_type="mailing_list_subscription",
            entity_id=row.id,
            details={"email": row.email},
        )
    return row


async def queue_renewal_reminders(db: AsyncSession, *, within_days: int) -> int:
    """Queue renewal reminders; concurrent scanners are safe via unique idempotency_key."""
    now = utcnow()
    horizon = now + timedelta(days=within_days)
    memberships = (
        await db.scalars(
            select(Membership).where(
                Membership.status == "active",
                Membership.ends_at > now,
                Membership.ends_at <= horizon,
            )
        )
    ).all()
    created = 0
    for membership in memberships:
        # Suppress when a later continuous entitlement already covers beyond this end.
        chain_end = await continuous_entitlement_chain_end(
            db, club_id=membership.club_id, user_id=membership.user_id, at=now
        )
        if chain_end is not None and chain_end > membership.ends_at:
            continue
        user = await db.get(User, membership.user_id)
        if user is None:
            continue
        # Reuses uq_notification_deliveries_idempotency — no duplicate constraint.
        key = f"renewal:{membership.id}:{membership.ends_at.date().isoformat()}"
        if await db.scalar(
            select(NotificationDelivery).where(NotificationDelivery.idempotency_key == key)
        ):
            continue
        try:
            # Savepoint so a unique violation does not abort the whole scan.
            async with db.begin_nested():
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
                        meta={"transactional": True},
                    )
                )
                await db.flush()
            created += 1
        except IntegrityError:
            continue
    return created


async def delivery_still_eligible(db: AsyncSession, row: NotificationDelivery) -> tuple[bool, str | None]:
    """Recheck unsubscribe / member-only rules immediately before send."""
    if row.kind in {"announcement", "announcement_correction"} and row.announcement_id:
        ann = await db.get(Announcement, row.announcement_id)
        if ann is None:
            return False, "announcement_missing"
        sub = await db.scalar(
            select(MailingListSubscription).where(
                MailingListSubscription.club_id == row.club_id,
                MailingListSubscription.email == row.recipient_email,
            )
        )
        if sub is None or sub.status != "active":
            return False, "unsubscribed_or_inactive"
        if ann.visibility == "members":
            user = await db.scalar(select(User).where(User.email == row.recipient_email))
            if user is None or not await has_active_membership(db, club_id=row.club_id, user_id=user.id):
                return False, "not_active_member"
    return True, None
