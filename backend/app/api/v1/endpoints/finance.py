from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import ForbiddenError
from app.db.session import get_db
from app.dependencies.auth import AuthContext, get_club, require_csrf
from app.models import Club
from app.schemas.finance import (
    BudgetActualOut,
    BudgetIn,
    BudgetOut,
    BudgetVsActualOut,
    CashBalanceOut,
    CashBalancesOut,
    CategoryReportOut,
    CategoryTotalOut,
    PendingReimbursementOut,
    PendingReimbursementsOut,
)
from app.services.finance_report_service import (
    budget_vs_actual,
    cash_balances,
    income_by_category,
    list_budgets,
    pending_reimbursements,
    spending_by_category,
    upsert_budget,
)
from app.services.rbac import effective_permissions

router = APIRouter(tags=["finance"])


async def _require_any(
    db: AsyncSession, *, club_id: uuid.UUID, user_id: uuid.UUID, allowed: set[str]
) -> None:
    perms = set(await effective_permissions(db, club_id=club_id, user_id=user_id))
    if not perms & allowed:
        raise ForbiddenError("You do not have permission for this action.")


async def _require_view(db: AsyncSession, club: Club, auth: AuthContext) -> None:
    await _require_any(db, club_id=club.id, user_id=auth.user.id, allowed={"view_finance"})


@router.get("/clubs/{club_id}/finance/income", response_model=CategoryReportOut)
async def get_income_report(
    start: date | None = None,
    end: date | None = None,
    include_demo: bool = False,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> CategoryReportOut:
    await _require_view(db, club, auth)
    rows = await income_by_category(
        db, club_id=club.id, start=start, end=end, include_demo=include_demo
    )
    return CategoryReportOut(
        start=start,
        end=end,
        include_demo=include_demo,
        rows=[CategoryTotalOut.model_validate(r) for r in rows],
    )


@router.get("/clubs/{club_id}/finance/spending", response_model=CategoryReportOut)
async def get_spending_report(
    start: date | None = None,
    end: date | None = None,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> CategoryReportOut:
    await _require_view(db, club, auth)
    rows = await spending_by_category(db, club_id=club.id, start=start, end=end)
    return CategoryReportOut(
        start=start, end=end, rows=[CategoryTotalOut.model_validate(r) for r in rows]
    )


@router.get("/clubs/{club_id}/finance/cash-balances", response_model=CashBalancesOut)
async def get_cash_balances(
    as_of: date | None = None,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> CashBalancesOut:
    await _require_view(db, club, auth)
    rows = await cash_balances(db, club_id=club.id, as_of=as_of)
    return CashBalancesOut(as_of=as_of, balances=[CashBalanceOut.model_validate(r) for r in rows])


@router.get(
    "/clubs/{club_id}/finance/pending-reimbursements", response_model=PendingReimbursementsOut
)
async def get_pending_reimbursements(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> PendingReimbursementsOut:
    await _require_any(
        db,
        club_id=club.id,
        user_id=auth.user.id,
        allowed={"view_finance", "record_reimbursement"},
    )
    rows = await pending_reimbursements(db, club_id=club.id)
    return PendingReimbursementsOut(
        items=[PendingReimbursementOut.model_validate(r) for r in rows],
        total=sum((r.amount for r in rows), Decimal("0.00")),
    )


@router.get("/clubs/{club_id}/finance/budget-vs-actual", response_model=BudgetVsActualOut)
async def get_budget_vs_actual(
    start: date | None = None,
    end: date | None = None,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> BudgetVsActualOut:
    await _require_any(
        db,
        club_id=club.id,
        user_id=auth.user.id,
        allowed={"view_finance", "manage_budgets"},
    )
    rows = await budget_vs_actual(db, club_id=club.id, start=start, end=end)
    return BudgetVsActualOut(rows=[BudgetActualOut.model_validate(r) for r in rows])


@router.get("/clubs/{club_id}/finance/budgets", response_model=list[BudgetOut])
async def get_budgets(
    start: date | None = None,
    end: date | None = None,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> list[BudgetOut]:
    await _require_any(
        db,
        club_id=club.id,
        user_id=auth.user.id,
        allowed={"view_finance", "manage_budgets"},
    )
    rows = await list_budgets(db, club_id=club.id, start=start, end=end)
    return [BudgetOut.model_validate(b) for b in rows]


@router.post("/clubs/{club_id}/finance/budgets", response_model=BudgetOut)
async def post_budget(
    payload: BudgetIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> BudgetOut:
    await _require_any(db, club_id=club.id, user_id=auth.user.id, allowed={"manage_budgets"})
    budget = await upsert_budget(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        category=payload.category,
        period_start=payload.period_start,
        period_end=payload.period_end,
        currency=payload.currency or get_settings().currency_code,
        limit_amount=payload.limit_amount,
    )
    await db.commit()
    return BudgetOut.model_validate(budget)
