"""Background worker for notification delivery and renewal reminders.

Run from repo (venv active):
  campusos-worker
  # or
  python -m app.worker
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import NotificationDelivery
from app.services.announcement_service import queue_renewal_reminders
from app.services.membership_eligibility import utcnow


def process_deliveries(limit: int = 100) -> int:
    settings = get_settings()
    processed = 0
    with SessionLocal() as db:
        rows = db.scalars(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.status == "queued",
                NotificationDelivery.attempts < 5,
            )
            .order_by(NotificationDelivery.created_at.asc())
            .limit(limit)
        ).all()
        outbox = Path(__file__).resolve().parents[1] / "var" / "email_outbox"
        outbox.mkdir(parents=True, exist_ok=True)
        for row in rows:
            row.attempts += 1
            try:
                if settings.email_adapter != "dev":
                    raise RuntimeError("Only the development email adapter is enabled in this build.")
                # Simulated delivery: write preview file and mark sent_simulated.
                preview = outbox / f"{row.id}.txt"
                preview.write_text(
                    f"To: {row.recipient_email}\nSubject: {row.subject}\n\n{row.body}\n",
                    encoding="utf-8",
                )
                row.status = "sent_simulated"
                row.processed_at = utcnow()
                row.last_error = None
                row.meta = {**(row.meta or {}), "adapter": "dev", "preview_path": str(preview)}
                processed += 1
            except Exception as exc:  # noqa: BLE001 - worker must isolate per-row failures
                row.last_error = str(exc)
                if row.attempts >= 5:
                    row.status = "failed"
                    row.processed_at = utcnow()
        db.commit()
    return processed


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="CampusOS notification worker")
    parser.add_argument("--reminders-only", action="store_true")
    parser.add_argument("--deliveries-only", action="store_true")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args(argv)

    settings = get_settings()
    if not args.deliveries_only:
        with SessionLocal() as db:
            created = queue_renewal_reminders(db, within_days=settings.renewal_reminder_days)
            db.commit()
            print(f"Queued renewal reminders: {created}")
    if not args.reminders_only:
        processed = process_deliveries(limit=args.limit)
        print(f"Processed deliveries: {processed}")


if __name__ == "__main__":
    main()
