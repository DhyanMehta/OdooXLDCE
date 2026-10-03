from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ExpenseIn(BaseModel):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    # Defaults to the deployment currency (CURRENCY_CODE) when omitted.
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    expense_date: date
    category: str = Field(default="general", min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=2000)


class ExpensePatch(BaseModel):
    amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    expense_date: date | None = None
    category: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, min_length=1, max_length=2000)


class ExpenseDecideIn(BaseModel):
    decision: Literal["approved", "rejected"]
    reason: str = Field(default="", max_length=1000)


class ReimburseIn(BaseModel):
    payment_reference: str = Field(min_length=1, max_length=200)
    paid_at: datetime | None = None


class ExpenseAttachmentOut(ORMModel):
    """Receipt metadata. The on-disk storage key is never exposed."""

    id: UUID
    expense_id: UUID
    original_filename: str
    content_type: str
    byte_size: int
    uploaded_by_user_id: UUID | None = None
    created_at: datetime


class ExpenseApprovalOut(ORMModel):
    id: UUID
    actor_user_id: UUID
    decision: str
    reason: str
    created_at: datetime


class ReimbursementOut(ORMModel):
    id: UUID
    expense_id: UUID
    amount: Decimal
    currency: str
    payment_reference: str
    paid_at: datetime
    recorded_by_user_id: UUID
    created_at: datetime


class ExpenseOut(ORMModel):
    id: UUID
    club_id: UUID
    submitter_user_id: UUID
    amount: Decimal
    currency: str
    expense_date: date
    category: str
    description: str
    status: str
    submitted_at: datetime | None = None
    decided_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    attachments: list[ExpenseAttachmentOut] = Field(default_factory=list)
    approvals: list[ExpenseApprovalOut] = Field(default_factory=list)
    reimbursement: ReimbursementOut | None = None
