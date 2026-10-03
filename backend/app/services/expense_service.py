"""Expense submission, approval, and reimbursement recording (no ledger on approve)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core import receipt_storage
from app.core.db_errors import is_unique_violation
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.models import ClubMember, Expense, ExpenseApproval, ExpenseAttachment, Reimbursement
from app.services.audit import record_audit
from app.services.ledger_service import post_reimbursement
from app.services.membership_eligibility import utcnow
from app.services.rbac import effective_permissions, require_permission

EDITABLE_STATUSES = frozenset({"draft", "rejected"})
FROZEN_AFTER_SUBMIT = frozenset({"submitted", "approved", "reimbursed"})
ATTACHABLE_STATUSES = frozenset({"draft", "rejected", "submitted"})
EXPENSE_VIEW_PERMISSIONS = frozenset({"review_expenses", "record_reimbursement", "view_finance"})
MAX_ATTACHMENTS_PER_EXPENSE = 10
EXPENSE_STATUSES = frozenset({"draft", "submitted", "approved", "rejected", "reimbursed"})

# Leading bytes that must match the declared content type (cheap spoof guard).
_MAGIC_PREFIXES: dict[str, tuple[bytes, ...]] = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "application/pdf": (b"%PDF-",),
}


def _expense_load_options():
    return (
        joinedload(Expense.attachments),
        joinedload(Expense.approvals),
        joinedload(Expense.reimbursement),
    )


async def _require_affiliation(db: AsyncSession, *, club_id: uuid.UUID, user_id: uuid.UUID) -> None:
    row = await db.scalar(
        select(ClubMember).where(ClubMember.club_id == club_id, ClubMember.user_id == user_id)
    )
    if row is None:
        raise ForbiddenError("Club affiliation required.")


async def get_expense(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    expense_id: uuid.UUID,
    refresh: bool = False,
) -> Expense:
    """Load an expense with children. ``refresh`` re-reads rows (use only on a clean session)."""
    stmt = (
        select(Expense)
        .options(*_expense_load_options())
        .where(Expense.id == expense_id, Expense.club_id == club_id)
    )
    if refresh:
        stmt = stmt.execution_options(populate_existing=True)
    expense = (await db.scalars(stmt)).unique().first()
    if expense is None:
        raise NotFoundError("Expense not found.")
    return expense


async def _lock_expense(db: AsyncSession, *, club_id: uuid.UUID, expense_id: uuid.UUID) -> None:
    """Row lock so concurrent submit/decide/reimburse calls serialize on one expense."""
    locked = await db.scalar(
        select(Expense.id)
        .where(Expense.id == expense_id, Expense.club_id == club_id)
        .with_for_update()
    )
    if locked is None:
        raise NotFoundError("Expense not found.")


async def get_expense_for_actor(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    expense_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    refresh: bool = False,
) -> Expense:
    """Submitter or finance reviewers may view; everyone else is forbidden."""
    expense = await get_expense(db, club_id=club_id, expense_id=expense_id, refresh=refresh)
    if expense.submitter_user_id != actor_user_id:
        perms = set(await effective_permissions(db, club_id=club_id, user_id=actor_user_id))
        if not perms & EXPENSE_VIEW_PERMISSIONS:
            raise ForbiddenError("You cannot view this expense.")
    return expense


async def create_expense(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    submitter_user_id: uuid.UUID,
    amount: Decimal,
    currency: str,
    expense_date: date,
    category: str,
    description: str,
) -> Expense:
    await _require_affiliation(db, club_id=club_id, user_id=submitter_user_id)
    if amount <= 0:
        raise AppError("Amount must be positive.", code="invalid_amount")
    expense = Expense(
        club_id=club_id,
        submitter_user_id=submitter_user_id,
        amount=amount,
        currency=currency.upper(),
        expense_date=expense_date,
        category=category.strip().lower() or "general",
        description=description.strip(),
        status="draft",
    )
    db.add(expense)
    await db.flush()
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=submitter_user_id,
        action="expense.created",
        entity_type="expense",
        entity_id=expense.id,
        details={"status": "draft"},
    )
    return expense


async def patch_expense(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    expense_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    amount: Decimal | None = None,
    currency: str | None = None,
    expense_date: date | None = None,
    category: str | None = None,
    description: str | None = None,
) -> Expense:
    expense = await get_expense(db, club_id=club_id, expense_id=expense_id)
    if expense.submitter_user_id != actor_user_id:
        raise ForbiddenError("Only the submitter can edit this expense.")
    if expense.status not in EDITABLE_STATUSES:
        raise ConflictError("Financial fields are frozen after submission.")
    if amount is not None:
        if amount <= 0:
            raise AppError("Amount must be positive.", code="invalid_amount")
        expense.amount = amount
    if currency is not None:
        expense.currency = currency.upper()
    if expense_date is not None:
        expense.expense_date = expense_date
    if category is not None:
        expense.category = category.strip().lower() or "general"
    if description is not None:
        expense.description = description.strip()
    if expense.status == "rejected":
        expense.status = "draft"
        expense.decided_at = None
    await db.flush()
    return expense


async def submit_expense(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    expense_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> Expense:
    await _lock_expense(db, club_id=club_id, expense_id=expense_id)
    expense = await get_expense(db, club_id=club_id, expense_id=expense_id)
    if expense.submitter_user_id != actor_user_id:
        raise ForbiddenError("Only the submitter can submit this expense.")
    if expense.status not in {"draft", "rejected"}:
        raise ConflictError("Expense cannot be submitted from its current status.")
    expense.status = "submitted"
    expense.submitted_at = utcnow()
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="expense.submitted",
        entity_type="expense",
        entity_id=expense.id,
        details={},
    )
    await db.flush()
    return expense


async def decide_expense(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    expense_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    decision: str,
    reason: str = "",
) -> Expense:
    """Approve or reject. Approval does not move cash or post a journal."""
    await require_permission(
        db, club_id=club_id, user_id=actor_user_id, permission="review_expenses"
    )
    await _lock_expense(db, club_id=club_id, expense_id=expense_id)
    expense = await get_expense(db, club_id=club_id, expense_id=expense_id)
    if expense.status != "submitted":
        raise ConflictError("Only submitted expenses can be reviewed.")
    if expense.submitter_user_id == actor_user_id:
        raise ForbiddenError("Self-approval is not allowed.")
    if decision not in {"approved", "rejected"}:
        raise AppError("Invalid decision.", code="invalid_decision")
    if decision == "rejected" and not reason.strip():
        raise AppError("Rejection requires a reason.", code="reason_required")

    expense.status = decision
    expense.decided_at = utcnow()
    db.add(
        ExpenseApproval(
            expense_id=expense.id,
            actor_user_id=actor_user_id,
            decision=decision,
            reason=reason.strip(),
        )
    )
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action=f"expense.{decision}",
        entity_type="expense",
        entity_id=expense.id,
        details={"reason": reason.strip()},
    )
    await db.flush()
    return expense


async def record_reimbursement(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    expense_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    payment_reference: str,
    paid_at: datetime | None = None,
) -> Reimbursement:
    await require_permission(
        db, club_id=club_id, user_id=actor_user_id, permission="record_reimbursement"
    )
    await _lock_expense(db, club_id=club_id, expense_id=expense_id)
    expense = await get_expense(db, club_id=club_id, expense_id=expense_id)
    if expense.status != "approved":
        raise ConflictError("Only approved expenses can be reimbursed.")
    if expense.reimbursement is not None:
        raise ConflictError("Expense already reimbursed.", code="duplicate_reimbursement")
    if not payment_reference.strip():
        raise AppError("Payment reference is required.", code="reference_required")

    reimb = Reimbursement(
        expense_id=expense.id,
        club_id=club_id,
        amount=expense.amount,
        currency=expense.currency,
        payment_reference=payment_reference.strip(),
        paid_at=paid_at or utcnow(),
        recorded_by_user_id=actor_user_id,
    )
    db.add(reimb)
    try:
        await db.flush()
    except IntegrityError as exc:
        if is_unique_violation(exc):
            raise ConflictError("Expense already reimbursed.", code="duplicate_reimbursement") from exc
        raise

    expense.status = "reimbursed"
    await post_reimbursement(
        db,
        club_id=club_id,
        currency=expense.currency,
        amount=expense.amount,
        category=expense.category,
        reimbursement_id=reimb.id,
        memo=f"Reimburse expense {expense.id} ({expense.category})",
    )
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="reimbursement.recorded",
        entity_type="reimbursement",
        entity_id=reimb.id,
        details={"expense_id": str(expense.id), "reference": reimb.payment_reference},
    )
    await db.flush()
    return reimb


async def list_my_expenses(
    db: AsyncSession, *, club_id: uuid.UUID, user_id: uuid.UUID
) -> list[Expense]:
    await _require_affiliation(db, club_id=club_id, user_id=user_id)
    rows = await db.scalars(
        select(Expense)
        .options(*_expense_load_options())
        .where(Expense.club_id == club_id, Expense.submitter_user_id == user_id)
        .order_by(Expense.created_at.desc())
    )
    return list(rows.unique().all())


async def list_review_queue(db: AsyncSession, *, club_id: uuid.UUID, actor_user_id: uuid.UUID) -> list[Expense]:
    await require_permission(
        db, club_id=club_id, user_id=actor_user_id, permission="review_expenses"
    )
    rows = await db.scalars(
        select(Expense)
        .options(*_expense_load_options())
        .where(Expense.club_id == club_id, Expense.status == "submitted")
        .order_by(Expense.submitted_at.asc().nulls_last())
    )
    return list(rows.unique().all())


async def list_club_expenses(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Expense]:
    """Club-wide expenses for finance reviewers (review / reimburse / view_finance)."""
    perms = set(await effective_permissions(db, club_id=club_id, user_id=actor_user_id))
    if not perms & EXPENSE_VIEW_PERMISSIONS:
        raise ForbiddenError("You do not have permission for this action.")
    # Drafts are private to their submitter until submitted.
    conditions = [Expense.club_id == club_id, Expense.status != "draft"]
    if status is not None:
        if status not in EXPENSE_STATUSES:
            raise AppError("Invalid expense status filter.", code="invalid_status")
        conditions.append(Expense.status == status)
    order = (Expense.submitted_at.desc().nulls_last(), Expense.created_at.desc())
    # Paging a joined-eager collection needs the id window in a subquery.
    ids = select(Expense.id).where(*conditions).order_by(*order).limit(limit).offset(offset)
    rows = await db.scalars(
        select(Expense)
        .options(*_expense_load_options())
        .where(Expense.id.in_(ids))
        .order_by(*order)
    )
    return list(rows.unique().all())


async def add_attachment(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    expense_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    filename: str,
    content_type: str | None,
    data: bytes,
) -> ExpenseAttachment:
    """Store a receipt on local disk, then insert the DB row (file removed if the row fails)."""
    expense = await get_expense(db, club_id=club_id, expense_id=expense_id)
    if expense.submitter_user_id != actor_user_id:
        raise ForbiddenError("Only the submitter can attach receipts.")
    if expense.status not in ATTACHABLE_STATUSES:
        raise ConflictError("Receipts cannot be added after approval.")
    normalized = receipt_storage.validate_upload(content_type, len(data))
    if not any(data.startswith(prefix) for prefix in _MAGIC_PREFIXES[normalized]):
        raise AppError(
            "File contents do not match the declared type.", code="receipt_bad_type", status_code=415
        )
    existing = await db.scalar(
        select(func.count())
        .select_from(ExpenseAttachment)
        .where(ExpenseAttachment.expense_id == expense.id)
    )
    if int(existing or 0) >= MAX_ATTACHMENTS_PER_EXPENSE:
        raise ConflictError("Too many receipts on this expense.", code="receipt_limit")

    key = receipt_storage.build_storage_key(
        club_id, expense.id, receipt_storage.extension_for(normalized)
    )
    clean_name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()[:255] or "receipt"
    receipt_storage.write_receipt(key, data)
    try:
        attachment = ExpenseAttachment(
            expense_id=expense.id,
            storage_key=key,
            original_filename=clean_name,
            content_type=normalized,
            byte_size=len(data),
            uploaded_by_user_id=actor_user_id,
        )
        db.add(attachment)
        await db.flush()
        await record_audit(
            db,
            club_id=club_id,
            actor_user_id=actor_user_id,
            action="expense.attachment_added",
            entity_type="expense",
            entity_id=expense.id,
            details={"attachment_id": str(attachment.id), "bytes": len(data)},
        )
        await db.flush()
    except Exception:
        receipt_storage.delete_receipt(key)
        raise
    return attachment


async def get_attachment_for_download(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    attachment_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> ExpenseAttachment:
    """Submitter, reviewers, reimbursement recorders, or finance viewers only."""
    row = (
        await db.execute(
            select(ExpenseAttachment, Expense.submitter_user_id)
            .join(Expense, Expense.id == ExpenseAttachment.expense_id)
            .where(ExpenseAttachment.id == attachment_id, Expense.club_id == club_id)
        )
    ).first()
    if row is None:
        raise NotFoundError("Receipt not found.")
    attachment, submitter_id = row
    if submitter_id != actor_user_id:
        perms = set(await effective_permissions(db, club_id=club_id, user_id=actor_user_id))
        if not perms & EXPENSE_VIEW_PERMISSIONS:
            raise ForbiddenError("You cannot view this receipt.")
    return attachment


def assert_fields_frozen(expense: Expense) -> None:
    if expense.status in FROZEN_AFTER_SUBMIT:
        raise ConflictError("Submitted financial fields cannot be changed.")
