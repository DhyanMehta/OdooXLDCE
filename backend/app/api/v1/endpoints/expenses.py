from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import receipt_storage
from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.db.session import get_db
from app.dependencies.auth import AuthContext, get_club, require_csrf
from app.models import Club
from app.schemas.expenses import (
    ExpenseAttachmentOut,
    ExpenseDecideIn,
    ExpenseIn,
    ExpenseOut,
    ExpensePatch,
    ReimbursementOut,
    ReimburseIn,
)
from app.services.expense_service import (
    add_attachment,
    create_expense,
    decide_expense,
    get_attachment_for_download,
    get_expense,
    get_expense_for_actor,
    list_club_expenses,
    list_my_expenses,
    patch_expense,
    record_reimbursement,
    submit_expense,
)

router = APIRouter(tags=["expenses"])


async def _reload(db: AsyncSession, club_id: uuid.UUID, expense_id: uuid.UUID) -> ExpenseOut:
    """Re-read after commit so children (attachments, approvals, reimbursement) are current."""
    expense = await get_expense(db, club_id=club_id, expense_id=expense_id, refresh=True)
    return ExpenseOut.model_validate(expense)


@router.post("/clubs/{club_id}/expenses", response_model=ExpenseOut)
async def post_expense(
    payload: ExpenseIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> ExpenseOut:
    expense = await create_expense(
        db,
        club_id=club.id,
        submitter_user_id=auth.user.id,
        amount=payload.amount,
        currency=payload.currency or get_settings().currency_code,
        expense_date=payload.expense_date,
        category=payload.category,
        description=payload.description,
    )
    await db.commit()
    return await _reload(db, club.id, expense.id)


@router.get("/clubs/{club_id}/expenses", response_model=list[ExpenseOut])
async def get_my_expenses(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> list[ExpenseOut]:
    rows = await list_my_expenses(db, club_id=club.id, user_id=auth.user.id)
    return [ExpenseOut.model_validate(e) for e in rows]


# Declared before ``/expenses/{expense_id}`` so "queue" is never parsed as an id.
@router.get("/clubs/{club_id}/expenses/queue", response_model=list[ExpenseOut])
async def review_queue(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(default="submitted", description="Expense status, or 'all'."),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ExpenseOut]:
    rows = await list_club_expenses(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        status=None if status in (None, "all") else status,
        limit=limit,
        offset=offset,
    )
    return [ExpenseOut.model_validate(e) for e in rows]


@router.get("/clubs/{club_id}/expenses/{expense_id}", response_model=ExpenseOut)
async def get_one_expense(
    expense_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> ExpenseOut:
    expense = await get_expense_for_actor(
        db, club_id=club.id, expense_id=expense_id, actor_user_id=auth.user.id
    )
    return ExpenseOut.model_validate(expense)


@router.patch("/clubs/{club_id}/expenses/{expense_id}", response_model=ExpenseOut)
async def patch_one_expense(
    expense_id: uuid.UUID,
    payload: ExpensePatch,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> ExpenseOut:
    await patch_expense(
        db,
        club_id=club.id,
        expense_id=expense_id,
        actor_user_id=auth.user.id,
        **payload.model_dump(exclude_unset=True),
    )
    await db.commit()
    return await _reload(db, club.id, expense_id)


@router.post("/clubs/{club_id}/expenses/{expense_id}/submit", response_model=ExpenseOut)
async def post_submit(
    expense_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> ExpenseOut:
    await submit_expense(db, club_id=club.id, expense_id=expense_id, actor_user_id=auth.user.id)
    await db.commit()
    return await _reload(db, club.id, expense_id)


@router.post("/clubs/{club_id}/expenses/{expense_id}/decide", response_model=ExpenseOut)
async def post_decide(
    expense_id: uuid.UUID,
    payload: ExpenseDecideIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> ExpenseOut:
    await decide_expense(
        db,
        club_id=club.id,
        expense_id=expense_id,
        actor_user_id=auth.user.id,
        decision=payload.decision,
        reason=payload.reason,
    )
    await db.commit()
    return await _reload(db, club.id, expense_id)


@router.post("/clubs/{club_id}/expenses/{expense_id}/reimburse", response_model=ReimbursementOut)
async def post_reimburse(
    expense_id: uuid.UUID,
    payload: ReimburseIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> ReimbursementOut:
    reimbursement = await record_reimbursement(
        db,
        club_id=club.id,
        expense_id=expense_id,
        actor_user_id=auth.user.id,
        payment_reference=payload.payment_reference,
        paid_at=payload.paid_at,
    )
    await db.commit()
    return ReimbursementOut.model_validate(reimbursement)


@router.post(
    "/clubs/{club_id}/expenses/{expense_id}/attachments", response_model=ExpenseAttachmentOut
)
async def post_attachment(
    expense_id: uuid.UUID,
    file: UploadFile = File(...),
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> ExpenseAttachmentOut:
    # Read at most limit+1 bytes so an oversized upload is rejected without buffering it all.
    data = await file.read(receipt_storage.max_bytes() + 1)
    attachment = await add_attachment(
        db,
        club_id=club.id,
        expense_id=expense_id,
        actor_user_id=auth.user.id,
        filename=file.filename or "receipt",
        content_type=file.content_type,
        data=data,
    )
    try:
        await db.commit()
    except Exception:
        receipt_storage.delete_receipt(attachment.storage_key)
        raise
    return ExpenseAttachmentOut.model_validate(attachment)


@router.get("/clubs/{club_id}/expenses/{expense_id}/attachments/{attachment_id}/download")
async def download_attachment(
    expense_id: uuid.UUID,
    attachment_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    attachment = await get_attachment_for_download(
        db, club_id=club.id, attachment_id=attachment_id, actor_user_id=auth.user.id
    )
    if attachment.expense_id != expense_id:
        raise NotFoundError("Receipt not found.")
    path = receipt_storage.resolve_key(attachment.storage_key)
    if not path.is_file():
        raise NotFoundError("Receipt file not found.")
    return FileResponse(
        path,
        media_type=attachment.content_type,
        filename=attachment.original_filename,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )
