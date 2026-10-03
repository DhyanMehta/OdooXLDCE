"""Cash-basis finance reports and budgets.

Every figure is derived from posted journal entries (income, cash balances) or
recorded reimbursements (spending). Nothing is accrual-based: an approved but
unpaid expense does not count as spending until a reimbursement is recorded.
Demo payments post to ``demo_clearing`` (simulated money) and are excluded from
income unless the caller opts in with ``include_demo``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.db_errors import is_unique_violation
from app.core.errors import AppError, ConflictError
from app.models import (
    Account,
    Budget,
    Expense,
    JournalEntry,
    JournalLine,
    Reimbursement,
    User,
)
from app.services.audit import record_audit

BASIS = "cash"
DEMO_ACCOUNT_CODE = "demo_clearing"
_LEDGER_STATUSES = ("posted", "reversed")


@dataclass(frozen=True)
class CategoryTotal:
    category: str
    name: str
    currency: str
    amount: Decimal


@dataclass(frozen=True)
class CashBalance:
    code: str
    name: str
    currency: str
    balance: Decimal
    simulated: bool


@dataclass(frozen=True)
class PendingReimbursement:
    expense_id: uuid.UUID
    submitter_user_id: uuid.UUID
    submitter_name: str
    amount: Decimal
    currency: str
    category: str
    description: str
    approved_at: datetime | None


@dataclass(frozen=True)
class BudgetActual:
    budget_id: uuid.UUID
    category: str
    currency: str
    period_start: date
    period_end: date
    limit_amount: Decimal
    actual_amount: Decimal
    remaining_amount: Decimal
    percent_used: Decimal


def _money(value: Decimal | int | None) -> Decimal:
    return Decimal(value if value is not None else 0).quantize(Decimal("0.01"))


def _normalize_category(category: str) -> str:
    return category.strip().lower() or "general"


def _start_dt(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=timezone.utc)


def _end_dt_exclusive(day: date) -> datetime:
    return datetime.combine(day + timedelta(days=1), time.min, tzinfo=timezone.utc)


def _demo_entry_exists():
    """Correlated EXISTS: the journal entry touches the simulated demo clearing account."""
    demo_line = aliased(JournalLine)
    demo_acc = aliased(Account)
    return exists(
        select(demo_line.id)
        .join(demo_acc, demo_acc.id == demo_line.account_id)
        .where(demo_line.entry_id == JournalEntry.id, demo_acc.code == DEMO_ACCOUNT_CODE)
    )


def _entry_window(start: date | None, end: date | None) -> list:
    clauses = [JournalEntry.status.in_(_LEDGER_STATUSES)]
    if start:
        clauses.append(JournalEntry.posted_at >= _start_dt(start))
    if end:
        clauses.append(JournalEntry.posted_at < _end_dt_exclusive(end))
    return clauses


async def income_by_category(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    include_demo: bool = False,
) -> list[CategoryTotal]:
    """Net income (credits less debits, so refunds subtract) per income account."""
    net = func.coalesce(func.sum(JournalLine.credit - JournalLine.debit), 0)
    stmt = (
        select(Account.code, Account.name, JournalEntry.currency, net)
        .join(JournalLine, JournalLine.account_id == Account.id)
        .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
        .where(
            Account.club_id == club_id,
            Account.account_type == "income",
            JournalEntry.club_id == club_id,
            *_entry_window(start, end),
        )
        .group_by(Account.code, Account.name, JournalEntry.currency)
        .order_by(Account.code)
    )
    if not include_demo:
        stmt = stmt.where(~_demo_entry_exists())
    rows = (await db.execute(stmt)).all()
    return [
        CategoryTotal(category=code, name=name, currency=cur, amount=_money(total))
        for code, name, cur, total in rows
    ]


async def spending_by_category(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
) -> list[CategoryTotal]:
    """Reimbursements actually paid (cash basis), grouped by the expense category."""
    stmt = (
        select(Expense.category, Reimbursement.currency, func.sum(Reimbursement.amount))
        .join(Expense, Expense.id == Reimbursement.expense_id)
        .where(Reimbursement.club_id == club_id)
        .group_by(Expense.category, Reimbursement.currency)
        .order_by(Expense.category)
    )
    if start:
        stmt = stmt.where(Reimbursement.paid_at >= _start_dt(start))
    if end:
        stmt = stmt.where(Reimbursement.paid_at < _end_dt_exclusive(end))
    rows = (await db.execute(stmt)).all()
    return [
        CategoryTotal(category=cat, name=cat.title(), currency=cur, amount=_money(total))
        for cat, cur, total in rows
    ]


async def cash_balances(
    db: AsyncSession, *, club_id: uuid.UUID, as_of: date | None = None
) -> list[CashBalance]:
    """Recorded cash vs simulated demo clearing, kept strictly separate."""
    accounts = (
        await db.scalars(
            select(Account)
            .where(Account.club_id == club_id, Account.code.in_(("cash", DEMO_ACCOUNT_CODE)))
            .order_by(Account.code)
        )
    ).all()
    out: list[CashBalance] = []
    for acc in accounts:
        clauses = [
            JournalLine.account_id == acc.id,
            JournalEntry.status.in_(_LEDGER_STATUSES),
        ]
        if as_of:
            clauses.append(JournalEntry.posted_at < _end_dt_exclusive(as_of))
        total = await db.scalar(
            select(func.coalesce(func.sum(JournalLine.debit - JournalLine.credit), 0))
            .select_from(JournalLine)
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .where(and_(*clauses))
        )
        out.append(
            CashBalance(
                code=acc.code,
                name=acc.name,
                currency=acc.currency,
                balance=_money(total),
                simulated=acc.code == DEMO_ACCOUNT_CODE,
            )
        )
    return out


async def pending_reimbursements(
    db: AsyncSession, *, club_id: uuid.UUID
) -> list[PendingReimbursement]:
    """Approved expenses not yet paid out."""
    rows = (
        await db.execute(
            select(Expense, User.full_name)
            .join(User, User.id == Expense.submitter_user_id)
            .outerjoin(Reimbursement, Reimbursement.expense_id == Expense.id)
            .where(
                Expense.club_id == club_id,
                Expense.status == "approved",
                Reimbursement.id.is_(None),
            )
            .order_by(Expense.decided_at.asc().nulls_last(), Expense.id)
        )
    ).all()
    return [
        PendingReimbursement(
            expense_id=e.id,
            submitter_user_id=e.submitter_user_id,
            submitter_name=name,
            amount=e.amount,
            currency=e.currency,
            category=e.category,
            description=e.description,
            approved_at=e.decided_at,
        )
        for e, name in rows
    ]


async def list_budgets(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
) -> list[Budget]:
    """Budgets overlapping [start, end] (either bound optional)."""
    stmt = select(Budget).where(Budget.club_id == club_id)
    if start:
        stmt = stmt.where(Budget.period_end >= start)
    if end:
        stmt = stmt.where(Budget.period_start <= end)
    stmt = stmt.order_by(Budget.period_start.desc(), Budget.category)
    return list((await db.scalars(stmt)).all())


async def upsert_budget(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    category: str,
    period_start: date,
    period_end: date,
    currency: str,
    limit_amount: Decimal,
) -> Budget:
    if limit_amount <= 0:
        raise AppError("Budget limit must be positive.", code="invalid_amount")
    if period_end < period_start:
        raise AppError("Budget period end must not precede its start.", code="invalid_period")
    cat = _normalize_category(category)
    cur = currency.upper()

    budget = await db.scalar(
        select(Budget)
        .where(
            Budget.club_id == club_id,
            Budget.category == cat,
            Budget.period_start == period_start,
            Budget.period_end == period_end,
            Budget.currency == cur,
        )
        .with_for_update()
    )
    created = budget is None
    if budget is None:
        budget = Budget(
            club_id=club_id,
            category=cat,
            period_start=period_start,
            period_end=period_end,
            currency=cur,
            limit_amount=limit_amount,
        )
        db.add(budget)
    else:
        budget.limit_amount = limit_amount
    try:
        await db.flush()
    except IntegrityError as exc:
        if is_unique_violation(exc):
            raise ConflictError(
                "Budget was changed concurrently; retry.", code="budget_conflict"
            ) from exc
        raise
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="budget.created" if created else "budget.updated",
        entity_type="budget",
        entity_id=budget.id,
        details={"category": cat, "limit_amount": str(limit_amount)},
    )
    return budget


async def budget_vs_actual(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
) -> list[BudgetActual]:
    """Compare each budget to reimbursements paid in its period for the same category."""
    out: list[BudgetActual] = []
    for budget in await list_budgets(db, club_id=club_id, start=start, end=end):
        actual = await db.scalar(
            select(func.coalesce(func.sum(Reimbursement.amount), 0))
            .join(Expense, Expense.id == Reimbursement.expense_id)
            .where(
                Reimbursement.club_id == club_id,
                Reimbursement.currency == budget.currency,
                Expense.category == budget.category,
                Reimbursement.paid_at >= _start_dt(budget.period_start),
                Reimbursement.paid_at < _end_dt_exclusive(budget.period_end),
            )
        )
        actual_amt = _money(actual)
        limit = budget.limit_amount
        out.append(
            BudgetActual(
                budget_id=budget.id,
                category=budget.category,
                currency=budget.currency,
                period_start=budget.period_start,
                period_end=budget.period_end,
                limit_amount=limit,
                actual_amount=actual_amt,
                remaining_amount=limit - actual_amt,
                percent_used=(actual_amt * 100 / limit).quantize(Decimal("0.01")),
            )
        )
    return out
