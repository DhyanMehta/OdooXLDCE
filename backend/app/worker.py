"""Long-running notification worker (asyncpg).

Production entrypoint (separate process; not supervised by this script):
  campusos-worker --loop
  python -m app.worker --loop

One-shot (dev / cron-style):
  campusos-worker --once
  python -m app.worker --once

The console script only standardizes startup. It does not provide process
supervision, clustering, or health checks — run it under your OS service
manager or process supervisor in production.

Delivery semantics (honest):
- Concurrent workers must not process the same *active* claim (SKIP LOCKED).
- Crash after adapter send but before DB success can still redeliver
  (at-least-once). The dev outbox recovers via provider_message_id + file.
- Exactly-once external delivery needs provider idempotency; locks alone do not.

States: queued → processing → sent_simulated | failed | suppressed
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import socket
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.security import generate_token, hash_token
from app.core.time import utcnow
from app.db.session import create_async_engine_from_settings, dispose_engine
from app.models import MailingListSubscription, NotificationDelivery
from app.services.announcement_service import delivery_still_eligible, queue_renewal_reminders

_shutdown = False
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = (15, 60, 180, 600, 1800)


def _request_shutdown(*_args: object) -> None:
    global _shutdown
    _shutdown = True


def reset_shutdown_flag() -> None:
    """Test helper — clear the process shutdown latch."""
    global _shutdown
    _shutdown = False


def _worker_id() -> str:
    return f"{socket.gethostname()}:{uuid.uuid4().hex[:8]}"


def _outbox_dir() -> Path:
    # Unchanged development adapter location.
    path = Path(__file__).resolve().parents[1] / "var" / "email_outbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _claim_seconds() -> int:
    return int(getattr(get_settings(), "worker_claim_seconds", 120))


def _install_signal_handlers() -> None:
    """Windows-safe Ctrl+C: use signal.signal; optionally add loop handlers on Unix.

    Do not depend exclusively on loop.add_signal_handler (unsupported on Windows).
    """
    signal.signal(signal.SIGINT, _request_shutdown)
    if hasattr(signal, "SIGTERM"):
        try:
            signal.signal(signal.SIGTERM, _request_shutdown)
        except (ValueError, OSError):
            pass
    if sys.platform == "win32":
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_shutdown)
        except (NotImplementedError, RuntimeError, ValueError):
            pass


async def interruptible_sleep(seconds: float) -> None:
    """Sleep in short slices so shutdown is noticed promptly."""
    deadline = time.monotonic() + max(seconds, 0)
    while not _shutdown and time.monotonic() < deadline:
        await asyncio.sleep(min(0.25, deadline - time.monotonic()))


async def reclaim_abandoned(db: AsyncSession) -> int:
    cutoff = utcnow() - timedelta(seconds=_claim_seconds())
    result = await db.execute(
        update(NotificationDelivery)
        .where(
            NotificationDelivery.status == "processing",
            NotificationDelivery.claimed_at.is_not(None),
            NotificationDelivery.claimed_at < cutoff,
        )
        .values(status="queued", claimed_at=None, claimed_by=None)
    )
    return int(result.rowcount or 0)


async def claim_deliveries(
    db: AsyncSession, *, limit: int, worker_id: str
) -> list[NotificationDelivery]:
    await reclaim_abandoned(db)
    now = utcnow()
    # SKIP LOCKED so multiple workers do not claim the same row.
    rows = (
        await db.scalars(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.status == "queued",
                NotificationDelivery.attempts < MAX_ATTEMPTS,
                or_(
                    NotificationDelivery.next_attempt_at.is_(None),
                    NotificationDelivery.next_attempt_at <= now,
                ),
            )
            .order_by(NotificationDelivery.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    ).all()
    claimed: list[NotificationDelivery] = []
    for row in rows:
        # Provider uncertainty recovery: preview already written but DB not updated.
        if row.provider_message_id:
            preview = _outbox_dir() / row.provider_message_id
            if preview.is_file():
                row.status = "sent_simulated"
                row.processed_at = now
                row.last_error = None
                row.claimed_at = None
                row.claimed_by = None
                row.meta = {
                    **(row.meta or {}),
                    "recovered_from_provider_file": True,
                    "adapter": "dev",
                }
                continue
        row.status = "processing"
        row.claimed_at = now
        row.claimed_by = worker_id
        claimed.append(row)
    await db.flush()
    return claimed


async def _append_unsubscribe_link(db: AsyncSession, row: NotificationDelivery, body: str) -> str:
    meta = row.meta or {}
    if not meta.get("needs_unsubscribe_link"):
        return body
    sub = await db.scalar(
        select(MailingListSubscription).where(
            MailingListSubscription.club_id == row.club_id,
            MailingListSubscription.email == row.recipient_email,
            MailingListSubscription.status == "active",
        )
    )
    if sub is None:
        return body
    raw = generate_token(32)
    sub.unsubscribe_token_hash = hash_token(raw)
    base = meta.get("unsubscribe_base") or "http://127.0.0.1:5173"
    return (
        f"{body.rstrip()}\n\n---\n"
        f"Unsubscribe from optional announcements: {base}/mailing/unsubscribe?token={raw}\n"
    )


async def process_one(db: AsyncSession, row: NotificationDelivery) -> None:
    """Process one delivery. Caller commits. Email IO happens after claim commit."""
    settings = get_settings()
    row.attempts += 1
    ok, reason = await delivery_still_eligible(db, row)
    if not ok:
        row.status = "suppressed"
        row.processed_at = utcnow()
        row.last_error = reason
        row.claimed_at = None
        row.claimed_by = None
        return

    if settings.email_adapter != "dev":
        raise RuntimeError("Only the development email adapter is enabled in this build.")

    body = await _append_unsubscribe_link(db, row, row.body)
    # Stable per-delivery id doubles as the simulated provider idempotency key.
    provider_id = f"delivery-{row.id}.txt"
    preview = _outbox_dir() / provider_id
    # Persist provider id before write so a crash after write can recover.
    row.provider_message_id = provider_id
    await db.flush()
    preview.write_text(
        f"To: {row.recipient_email}\nSubject: {row.subject}\n\n{body}\n",
        encoding="utf-8",
    )
    row.status = "sent_simulated"
    row.processed_at = utcnow()
    row.last_error = None
    row.claimed_at = None
    row.claimed_by = None
    row.meta = {
        **(row.meta or {}),
        "adapter": "dev",
        "preview_path": str(preview),
        "provider_idempotency_key": provider_id,
    }


async def process_deliveries(
    session_factory: async_sessionmaker[AsyncSession],
    limit: int = 100,
) -> int:
    """Claim a batch (if not shutting down), then finish each claimed row independently."""
    if _shutdown:
        return 0
    worker_id = _worker_id()
    processed = 0
    async with session_factory() as db:
        claimed = await claim_deliveries(db, limit=limit, worker_id=worker_id)
        await db.commit()
        claimed_ids = [r.id for r in claimed]
    # Finish the bounded claimed batch even if shutdown was signaled mid-batch.
    for row_id in claimed_ids:
        async with session_factory() as row_db:
            row = await row_db.get(NotificationDelivery, row_id)
            if row is None or row.status != "processing":
                continue
            try:
                await process_one(row_db, row)
                processed += 1
            except Exception as exc:  # noqa: BLE001 — isolate per-row failures
                row.last_error = str(exc)[:2000]
                row.claimed_at = None
                row.claimed_by = None
                if row.attempts >= MAX_ATTEMPTS:
                    row.status = "failed"
                    row.processed_at = utcnow()
                else:
                    delay = BACKOFF_SECONDS[min(row.attempts - 1, len(BACKOFF_SECONDS) - 1)]
                    row.status = "queued"
                    row.next_attempt_at = utcnow() + timedelta(seconds=delay)
            await row_db.commit()
    return processed


async def run_reminders(session_factory: async_sessionmaker[AsyncSession]) -> int:
    settings = get_settings()
    async with session_factory() as db:
        created = await queue_renewal_reminders(db, within_days=settings.renewal_reminder_days)
        await db.commit()
    return created


async def run_once(
    *,
    reminders: bool,
    deliveries: bool,
    limit: int,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    if reminders and not _shutdown:
        created = await run_reminders(session_factory)
        print(f"Queued renewal reminders: {created}")
    if deliveries and not _shutdown:
        processed = await process_deliveries(session_factory, limit=limit)
        print(f"Processed deliveries: {processed}")


async def run_loop(
    *,
    do_reminders: bool,
    do_deliveries: bool,
    limit: int,
    delivery_interval: int,
    reminder_interval: int,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Poll deliveries on delivery_interval; scan reminders on reminder_interval."""
    print(
        f"Worker looping: deliveries every {delivery_interval}s, "
        f"reminders every {reminder_interval}s (Ctrl+C to stop)"
    )
    # Run reminders on the first tick, then on their own cadence.
    last_reminder = 0.0
    while not _shutdown:
        now = time.monotonic()
        if do_reminders and (now - last_reminder) >= reminder_interval:
            if not _shutdown:
                created = await run_reminders(session_factory)
                print(f"Queued renewal reminders: {created}")
                last_reminder = time.monotonic()
        if do_deliveries and not _shutdown:
            processed = await process_deliveries(session_factory, limit=limit)
            print(f"Processed deliveries: {processed}")
        if _shutdown:
            break
        await interruptible_sleep(delivery_interval)
    print("Worker stopped (finished current batch; no new claims).")


async def main_async(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="CampusOS notification worker (campusos-worker)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously until SIGINT/SIGTERM (production mode)",
    )
    mode.add_argument(
        "--once",
        action="store_true",
        help="Single pass then exit (default if neither --loop nor --once)",
    )
    parser.add_argument("--reminders-only", action="store_true")
    parser.add_argument("--deliveries-only", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help="Seconds between delivery polls (default: WORKER_INTERVAL_SECONDS)",
    )
    parser.add_argument(
        "--reminder-interval",
        type=int,
        default=None,
        help="Seconds between reminder scans (default: WORKER_REMINDER_INTERVAL_SECONDS)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    delivery_interval = (
        args.interval if args.interval is not None else settings.worker_interval_seconds
    )
    reminder_interval = (
        args.reminder_interval
        if args.reminder_interval is not None
        else settings.worker_reminder_interval_seconds
    )
    do_reminders = not args.deliveries_only
    do_deliveries = not args.reminders_only
    use_loop = bool(args.loop)

    # One long-lived engine for this process; smaller worker pool from settings.
    engine = create_async_engine_from_settings(settings, worker=True)
    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )

    reset_shutdown_flag()
    _install_signal_handlers()

    try:
        if not use_loop:
            await run_once(
                reminders=do_reminders,
                deliveries=do_deliveries,
                limit=args.limit,
                session_factory=session_factory,
            )
            return
        await run_loop(
            do_reminders=do_reminders,
            do_deliveries=do_deliveries,
            limit=args.limit,
            delivery_interval=delivery_interval,
            reminder_interval=reminder_interval,
            session_factory=session_factory,
        )
    finally:
        await engine.dispose()
        await dispose_engine()


def main(argv: list[str] | None = None) -> None:
    asyncio.run(main_async(argv))


if __name__ == "__main__":
    main()
