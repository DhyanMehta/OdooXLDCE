"""Checkpoint 1: ledger posting, reversals, expense state machine."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.permissions import RoleCode
from app.core.security import hash_password
from app.models import (
    Club,
    ClubMember,
    ClubRoleAssignment,
    JournalEntry,
    JournalLine,
    Order,
    Payment,
    Role,
    User,
)
from app.services.expense_service import (
    create_expense,
    decide_expense,
    get_expense,
    patch_expense,
    record_reimbursement,
    submit_expense,
)
from app.services.ledger_service import (
    ensure_chart_of_accounts,
    post_balanced_entry,
    post_payment_confirmation,
    post_refund_reversal,
)
from app.services.membership_eligibility import utcnow
from tests.conftest import TEST_PASSWORD


async def _role(db: AsyncSession, code: str) -> Role:
    role = await db.scalar(select(Role).where(Role.code == code))
    if role is None:
        role = Role(code=code, name=code)
        db.add(role)
        await db.flush()
    return role


async def _world(db: AsyncSession):
    club = Club(slug=f"fin-{uuid.uuid4().hex[:8]}", name="Finance Club", description="")
    other = Club(slug=f"fin-o-{uuid.uuid4().hex[:8]}", name="Other", description="")
    db.add_all([club, other])
    await db.flush()
    admin = User(
        email=f"admin-{uuid.uuid4().hex[:8]}@fin.test",
        full_name="Admin",
        password_hash=hash_password(TEST_PASSWORD),
    )
    member = User(
        email=f"mem-{uuid.uuid4().hex[:8]}@fin.test",
        full_name="Member",
        password_hash=hash_password(TEST_PASSWORD),
    )
    db.add_all([admin, member])
    await db.flush()
    for u in (admin, member):
        db.add(ClubMember(club_id=club.id, user_id=u.id))
    admin_role = await _role(db, RoleCode.CLUB_ADMIN.value)
    db.add(
        ClubRoleAssignment(
            club_id=club.id,
            user_id=admin.id,
            role_id=admin_role.id,
            starts_at=utcnow() - timedelta(days=1),
            ends_at=None,
            assigned_by_user_id=admin.id,
        )
    )
    await db.flush()
    return {"club": club, "other": other, "admin": admin, "member": member}


@pytest.mark.asyncio
async def test_balanced_posting_and_duplicate_source(db: AsyncSession):
    w = await _world(db)
    charts = await ensure_chart_of_accounts(db, club_id=w["club"].id, currency="INR")
    key = f"test_payment:{uuid.uuid4()}"
    entry = await post_balanced_entry(
        db,
        club_id=w["club"].id,
        currency="INR",
        source_type="test",
        source_id=None,
        source_event_key=key,
        memo="balanced",
        lines=[
            (charts["cash"].id, Decimal("100.00"), Decimal("0")),
            (charts["membership_income"].id, Decimal("0"), Decimal("100.00")),
        ],
    )
    assert entry.status == "posted"
    again = await post_balanced_entry(
        db,
        club_id=w["club"].id,
        currency="INR",
        source_type="test",
        source_id=None,
        source_event_key=key,
        memo="retry",
        lines=[
            (charts["cash"].id, Decimal("100.00"), Decimal("0")),
            (charts["membership_income"].id, Decimal("0"), Decimal("100.00")),
        ],
    )
    assert again.id == entry.id

    debit, credit = (
        await db.execute(
            select(
                func.coalesce(func.sum(JournalLine.debit), 0),
                func.coalesce(func.sum(JournalLine.credit), 0),
            ).where(JournalLine.entry_id == entry.id)
        )
    ).one()
    assert debit == credit == Decimal("100.00")


@pytest.mark.asyncio
async def test_unbalanced_rejected_in_app(db: AsyncSession):
    w = await _world(db)
    charts = await ensure_chart_of_accounts(db, club_id=w["club"].id, currency="INR")
    with pytest.raises(AppError) as ei:
        await post_balanced_entry(
            db,
            club_id=w["club"].id,
            currency="INR",
            source_type="test",
            source_id=None,
            source_event_key=f"bad:{uuid.uuid4()}",
            memo="unbalanced",
            lines=[
                (charts["cash"].id, Decimal("50.00"), Decimal("0")),
                (charts["membership_income"].id, Decimal("0"), Decimal("40.00")),
            ],
        )
    assert ei.value.code == "journal_unbalanced"


@pytest.mark.asyncio
async def test_db_trigger_rejects_unbalanced_posted(engine: AsyncEngine):
    """Deferred balance trigger fires on real commit (separate connection)."""
    Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    club_id = None
    user_ids: list[uuid.UUID] = []
    try:
        async with Session() as db:
            w = await _world(db)
            charts = await ensure_chart_of_accounts(db, club_id=w["club"].id, currency="INR")
            await db.commit()
            club_id = w["club"].id
            user_ids = [w["admin"].id, w["member"].id]
            cash_id = charts["cash"].id

        async with Session() as db:
            entry_id = uuid.uuid4()
            await db.execute(
                text(
                    """
                    INSERT INTO journal_entries
                      (id, club_id, currency, status, source_type, source_event_key, memo)
                    VALUES
                      (:id, :club, 'INR', 'draft', 'test', :key, 'x')
                    """
                ),
                {"id": entry_id, "club": club_id, "key": f"trig:{uuid.uuid4()}"},
            )
            await db.execute(
                text(
                    """
                    INSERT INTO journal_lines (id, entry_id, account_id, debit, credit)
                    VALUES (:id, :entry, :acc, 10, 0)
                    """
                ),
                {"id": uuid.uuid4(), "entry": entry_id, "acc": cash_id},
            )
            await db.execute(
                text("UPDATE journal_entries SET status = 'posted', posted_at = now() WHERE id = :id"),
                {"id": entry_id},
            )
            with pytest.raises(Exception):
                await db.commit()
            await db.rollback()
    finally:
        if club_id is not None:
            from tests.test_merchandise_projects import _cleanup

            await _cleanup(engine, club_ids=[club_id], user_ids=user_ids)


@pytest.mark.asyncio
async def test_reversal_and_demo_vs_cash_accounts(db: AsyncSession):
    w = await _world(db)
    order = Order(
        club_id=w["club"].id,
        user_id=w["member"].id,
        status="pending",
        total_amount=Decimal("250.00"),
        currency="INR",
    )
    db.add(order)
    await db.flush()
    payment_demo = Payment(
        order_id=order.id,
        amount=Decimal("250.00"),
        method="demo",
        status="confirmed",
    )
    db.add(payment_demo)
    await db.flush()

    entry = await post_payment_confirmation(db, order=order, payment=payment_demo)
    assert entry is not None
    charts = await ensure_chart_of_accounts(db, club_id=w["club"].id, currency="INR")
    lines = (await db.scalars(select(JournalLine).where(JournalLine.entry_id == entry.id))).all()
    asset_ids = {ln.account_id for ln in lines if ln.debit > 0}
    assert charts["demo_clearing"].id in asset_ids
    assert charts["cash"].id not in asset_ids

    refund_id = uuid.uuid4()
    rev = await post_refund_reversal(db, order=order, payment=payment_demo, refund_id=refund_id)
    assert rev.status == "posted"
    assert rev.reverses_entry_id == entry.id
    await db.refresh(entry)
    assert entry.status == "reversed"


@pytest.mark.asyncio
async def test_expense_transitions_self_approval_and_reimburse(db: AsyncSession):
    w = await _world(db)
    expense = await create_expense(
        db,
        club_id=w["club"].id,
        submitter_user_id=w["member"].id,
        amount=Decimal("80.00"),
        currency="INR",
        expense_date=date.today(),
        category="supplies",
        description="Poster paper",
    )
    assert expense.status == "draft"
    await submit_expense(
        db, club_id=w["club"].id, expense_id=expense.id, actor_user_id=w["member"].id
    )
    with pytest.raises(ConflictError):
        await patch_expense(
            db,
            club_id=w["club"].id,
            expense_id=expense.id,
            actor_user_id=w["member"].id,
            amount=Decimal("90.00"),
        )
    with pytest.raises(ForbiddenError):
        await decide_expense(
            db,
            club_id=w["club"].id,
            expense_id=expense.id,
            actor_user_id=w["member"].id,
            decision="approved",
        )
    await decide_expense(
        db,
        club_id=w["club"].id,
        expense_id=expense.id,
        actor_user_id=w["admin"].id,
        decision="approved",
    )
    # Approval must not post cash movement for this expense.
    je_for_expense = await db.scalar(
        select(func.count())
        .select_from(JournalEntry)
        .where(JournalEntry.source_event_key.like(f"%{expense.id}%"))
    )
    assert je_for_expense == 0

    reimb = await record_reimbursement(
        db,
        club_id=w["club"].id,
        expense_id=expense.id,
        actor_user_id=w["admin"].id,
        payment_reference="UPI-123",
    )
    assert reimb.amount == Decimal("80.00")
    await db.refresh(expense)
    assert expense.status == "reimbursed"
    with pytest.raises(ConflictError):
        await record_reimbursement(
            db,
            club_id=w["club"].id,
            expense_id=expense.id,
            actor_user_id=w["admin"].id,
            payment_reference="UPI-DUP",
        )
    posted = await db.scalar(
        select(func.count())
        .select_from(JournalEntry)
        .where(JournalEntry.source_event_key == f"reimbursement:{reimb.id}")
    )
    assert posted == 1


@pytest.mark.asyncio
async def test_cross_club_expense_isolated(db: AsyncSession):
    w = await _world(db)
    expense = await create_expense(
        db,
        club_id=w["club"].id,
        submitter_user_id=w["member"].id,
        amount=Decimal("10.00"),
        currency="INR",
        expense_date=date.today(),
        category="other",
        description="x",
    )
    with pytest.raises(NotFoundError):
        await get_expense(db, club_id=w["other"].id, expense_id=expense.id)
