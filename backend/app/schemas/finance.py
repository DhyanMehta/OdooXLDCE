from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class CategoryTotalOut(ORMModel):
    category: str
    name: str
    currency: str
    amount: Decimal


class CategoryReportOut(BaseModel):
    basis: Literal["cash"] = "cash"
    start: date | None = None
    end: date | None = None
    # Demo collections are simulated (demo_clearing) and excluded unless requested.
    include_demo: bool = False
    rows: list[CategoryTotalOut]


class CashBalanceOut(ORMModel):
    code: str
    name: str
    currency: str
    balance: Decimal
    simulated: bool


class CashBalancesOut(BaseModel):
    basis: Literal["cash"] = "cash"
    as_of: date | None = None
    balances: list[CashBalanceOut]


class PendingReimbursementOut(ORMModel):
    expense_id: UUID
    submitter_user_id: UUID
    submitter_name: str
    amount: Decimal
    currency: str
    category: str
    description: str
    approved_at: datetime | None = None


class PendingReimbursementsOut(BaseModel):
    basis: Literal["cash"] = "cash"
    items: list[PendingReimbursementOut]
    total: Decimal


class BudgetIn(BaseModel):
    category: str = Field(min_length=1, max_length=64)
    period_start: date
    period_end: date
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    limit_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class BudgetOut(ORMModel):
    id: UUID
    club_id: UUID
    category: str
    period_start: date
    period_end: date
    currency: str
    limit_amount: Decimal


class BudgetActualOut(ORMModel):
    budget_id: UUID
    category: str
    currency: str
    period_start: date
    period_end: date
    limit_amount: Decimal
    actual_amount: Decimal
    remaining_amount: Decimal
    percent_used: Decimal


class BudgetVsActualOut(BaseModel):
    basis: Literal["cash"] = "cash"
    rows: list[BudgetActualOut]
