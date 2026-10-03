"""Cash-basis club ledger posting.

Payment rows remain the collection activity record. Journal entries record the
accounting effect only. Demo payments post to ``demo_clearing`` (simulated),
never labeled as real bank cash.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.db_errors import is_unique_violation
from app.core.errors import AppError, ConflictError, NotFoundError
from app.models import Account, JournalEntry, JournalLine, Order, OrderItem, Payment
from app.services.membership_eligibility import utcnow

# System chart seeded per club (currency matches club operations; default INR).
SYSTEM_ACCOUNTS: tuple[tuple[str, str, str], ...] = (
    ("cash", "Cash / bank (recorded)", "asset"),
    ("demo_clearing", "Demo clearing (simulated collections)", "asset"),
    ("membership_income", "Membership dues income", "income"),
    ("ticket_income", "Ticket sales income", "income"),
    ("merch_income", "Merchandise sales income", "income"),
    ("expense_general", "General expenses", "expense"),
)

INCOME_BY_ITEM_KIND = {
    "membership": "membership_income",
    "ticket": "ticket_income",
    "merchandise": "merch_income",
}

EXPENSE_ACCOUNT_BY_CATEGORY = {
    "general": "expense_general",
    "supplies": "expense_general",
    "travel": "expense_general",
    "food": "expense_general",
    "equipment": "expense_general",
    "other": "expense_general",
}


async def ensure_chart_of_accounts(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    currency: str,
) -> dict[str, Account]:
    """Idempotently create system accounts for a club/currency pair codes."""
    cur = currency.upper()
    existing = (
        await db.scalars(select(Account).where(Account.club_id == club_id))
    ).all()
    by_code = {a.code: a for a in existing}
    for code, name, account_type in SYSTEM_ACCOUNTS:
        if code in by_code:
            continue
        acc = Account(
            club_id=club_id,
            code=code,
            name=name,
            account_type=account_type,
            currency=cur,
            is_system=True,
        )
        db.add(acc)
        by_code[code] = acc
    await db.flush()
    return by_code


def _money(value: Decimal | int | str) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


async def _get_entry_by_source_key(
    db: AsyncSession, source_event_key: str
) -> JournalEntry | None:
    return await db.scalar(
        select(JournalEntry)
        .options(joinedload(JournalEntry.lines))
        .where(JournalEntry.source_event_key == source_event_key)
    )


async def post_balanced_entry(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    currency: str,
    source_type: str,
    source_id: uuid.UUID | None,
    source_event_key: str,
    memo: str,
    lines: Iterable[tuple[uuid.UUID, Decimal, Decimal]],
    reverses_entry_id: uuid.UUID | None = None,
) -> JournalEntry:
    """Insert draft lines then mark posted (DB deferred trigger enforces balance).

    Duplicate ``source_event_key`` returns the existing posted entry (idempotent).
    """
    existing = await _get_entry_by_source_key(db, source_event_key)
    if existing is not None:
        return existing

    cur = currency.upper()
    line_rows = list(lines)
    if not line_rows:
        raise AppError("Journal entry requires lines.", code="journal_empty")

    debit_total = sum((d for _, d, _ in line_rows), Decimal("0"))
    credit_total = sum((c for _, _, c in line_rows), Decimal("0"))
    if debit_total != credit_total or debit_total <= 0:
        raise AppError(
            f"Unbalanced journal: debit={debit_total} credit={credit_total}",
            code="journal_unbalanced",
        )

    # Validate accounts belong to club and share currency.
    account_ids = {aid for aid, _, _ in line_rows}
    accounts = (
        await db.scalars(select(Account).where(Account.id.in_(account_ids)))
    ).all()
    if len(accounts) != len(account_ids):
        raise NotFoundError("Account not found.")
    for acc in accounts:
        if acc.club_id != club_id:
            raise AppError("Account club mismatch.", code="account_club_mismatch")
        if acc.currency.upper() != cur:
            raise AppError("Account currency mismatch.", code="account_currency_mismatch")

    entry = JournalEntry(
        club_id=club_id,
        currency=cur,
        status="draft",
        source_type=source_type,
        source_id=source_id,
        source_event_key=source_event_key,
        memo=memo,
        reverses_entry_id=reverses_entry_id,
    )
    db.add(entry)
    try:
        await db.flush()
    except IntegrityError as exc:
        if is_unique_violation(exc):
            raise ConflictError("Duplicate journal source event.", code="journal_duplicate") from exc
        raise

    for account_id, debit, credit in line_rows:
        db.add(
            JournalLine(
                entry_id=entry.id,
                account_id=account_id,
                debit=_money(debit),
                credit=_money(credit),
            )
        )
    await db.flush()

    entry.status = "posted"
    entry.posted_at = utcnow()
    if reverses_entry_id is not None:
        original = await db.get(JournalEntry, reverses_entry_id)
        if original is None:
            raise NotFoundError("Original journal entry not found.")
        if original.club_id != club_id:
            raise AppError("Reversal club mismatch.", code="reversal_club_mismatch")
        if original.status != "posted":
            raise ConflictError("Only posted entries can be reversed.")
        original.status = "reversed"
    await db.flush()
    return entry


async def post_payment_confirmation(
    db: AsyncSession,
    *,
    order: Order,
    payment: Payment,
) -> JournalEntry | None:
    """Post cash-basis income for a confirmed payment. Idempotent per payment id."""
    # May run mid-confirm while order is still pending; payment status is authoritative.
    if payment.status not in {"confirmed", "refund_required"}:
        return None

    charts = await ensure_chart_of_accounts(db, club_id=order.club_id, currency=order.currency)
    asset_code = "demo_clearing" if payment.method == "demo" else "cash"
    asset = charts[asset_code]

    # Eager-load items (async session — no lazy IO).
    items = (
        await db.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()

    # Allocate income by order line snapshots (single currency).
    income_totals: dict[str, Decimal] = {}
    for item in items:
        code = INCOME_BY_ITEM_KIND.get(item.item_kind, "membership_income")
        line_total = _money(item.unit_price_snapshot) * item.quantity
        income_totals[code] = income_totals.get(code, Decimal("0")) + line_total

    amount = _money(payment.amount)
    allocated = sum(income_totals.values(), Decimal("0"))
    if allocated != amount:
        # Prefer payment amount as source of truth; park remainder in membership_income.
        drift = amount - allocated
        income_totals["membership_income"] = income_totals.get("membership_income", Decimal("0")) + drift

    lines: list[tuple[uuid.UUID, Decimal, Decimal]] = [
        (asset.id, amount, Decimal("0")),
    ]
    for code, total in income_totals.items():
        if total == 0:
            continue
        if total < 0:
            raise AppError("Negative income allocation.", code="journal_negative")
        lines.append((charts[code].id, Decimal("0"), _money(total)))

    label = "simulated demo collection" if payment.method == "demo" else "recorded manual collection"
    return await post_balanced_entry(
        db,
        club_id=order.club_id,
        currency=order.currency,
        source_type="payment_confirmed",
        source_id=payment.id,
        source_event_key=f"payment_confirmed:{payment.id}",
        memo=f"Payment {payment.id} ({label})",
        lines=lines,
    )


async def post_reimbursement(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    currency: str,
    amount: Decimal,
    category: str,
    reimbursement_id: uuid.UUID,
    memo: str = "",
) -> JournalEntry:
    charts = await ensure_chart_of_accounts(db, club_id=club_id, currency=currency)
    expense_code = EXPENSE_ACCOUNT_BY_CATEGORY.get(category, "expense_general")
    expense_acc = charts[expense_code]
    cash = charts["cash"]
    amt = _money(amount)
    return await post_balanced_entry(
        db,
        club_id=club_id,
        currency=currency,
        source_type="reimbursement",
        source_id=reimbursement_id,
        source_event_key=f"reimbursement:{reimbursement_id}",
        memo=memo or f"Reimbursement {reimbursement_id}",
        lines=[
            (expense_acc.id, amt, Decimal("0")),
            (cash.id, Decimal("0"), amt),
        ],
    )


async def post_refund_reversal(
    db: AsyncSession,
    *,
    order: Order,
    payment: Payment,
    refund_id: uuid.UUID,
) -> JournalEntry:
    """Reverse the original payment_confirmed entry for a completed full refund."""
    original_key = f"payment_confirmed:{payment.id}"
    original = await _get_entry_by_source_key(db, original_key)
    if original is None:
        # Payment may predate ledger; synthesize a balanced reverse from payment amount.
        charts = await ensure_chart_of_accounts(db, club_id=order.club_id, currency=order.currency)
        asset_code = "demo_clearing" if payment.method == "demo" else "cash"
        income_code = "membership_income"
        if order.items:
            income_code = INCOME_BY_ITEM_KIND.get(order.items[0].item_kind, income_code)
        amt = _money(payment.amount)
        return await post_balanced_entry(
            db,
            club_id=order.club_id,
            currency=order.currency,
            source_type="refund_completed",
            source_id=refund_id,
            source_event_key=f"refund_completed:{refund_id}",
            memo=f"Refund {refund_id} (no prior journal; synthetic reverse)",
            lines=[
                (charts[income_code].id, amt, Decimal("0")),
                (charts[asset_code].id, Decimal("0"), amt),
            ],
        )

    if original.status == "reversed":
        existing = await _get_entry_by_source_key(db, f"refund_completed:{refund_id}")
        if existing:
            return existing
        raise ConflictError("Original payment journal already reversed.")

    # Swap debit/credit of original lines.
    rev_lines: list[tuple[uuid.UUID, Decimal, Decimal]] = []
    for line in original.lines:
        rev_lines.append((line.account_id, _money(line.credit), _money(line.debit)))

    return await post_balanced_entry(
        db,
        club_id=order.club_id,
        currency=order.currency,
        source_type="refund_completed",
        source_id=refund_id,
        source_event_key=f"refund_completed:{refund_id}",
        memo=f"Refund {refund_id} reversing {original.source_event_key}",
        lines=rev_lines,
        reverses_entry_id=original.id,
    )

