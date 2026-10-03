"""Translate common DB integrity errors into AppError without leaking internals."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.core.errors import AppError, ConflictError


def is_unique_violation(exc: BaseException) -> bool:
    """True when the underlying DB error is a unique constraint violation."""
    if isinstance(exc, IntegrityError):
        exc = exc.orig if getattr(exc, "orig", None) is not None else exc
    sqlstate = getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None)
    if sqlstate == "23505":
        return True
    msg = str(exc).lower()
    return "unique" in msg or "duplicate key" in msg


def translate_integrity_error(exc: IntegrityError) -> AppError:
    msg = str(getattr(exc, "orig", exc)).lower()
    if "uq_mailing_list_club_email" in msg or "mailing_list" in msg and "email" in msg:
        return ConflictError("Subscription conflict.", code="subscription_conflict")
    if "uq_notification_deliveries_idempotency" in msg:
        return ConflictError("Notification already queued.", code="delivery_exists")
    if "uq_club_members" in msg or "club_members" in msg:
        return ConflictError("Already a club affiliate.", code="already_member")
    if "users_email" in msg or "ix_users_email" in msg:
        return ConflictError("Email already in use.", code="email_taken")
    return AppError("Could not save changes due to a data conflict.", code="integrity_error", status_code=409)
