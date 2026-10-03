from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies.auth import AuthContext, get_club, require_csrf
from app.models import Club
from app.schemas.refunds import RefundCompleteIn, RefundDecideIn, RefundOut, RefundRequestIn
from app.services.refund_service import (
    complete_manual_refund,
    decide_refund,
    list_my_refunds,
    list_refunds,
    request_refund,
)

router = APIRouter(tags=["refunds"])


@router.post("/clubs/{club_id}/refunds", response_model=RefundOut)
async def post_refund_request(
    payload: RefundRequestIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> RefundOut:
    refund = await request_refund(
        db,
        club_id=club.id,
        order_id=payload.order_id,
        actor_user_id=auth.user.id,
        reason=payload.reason,
    )
    await db.commit()
    return RefundOut.model_validate(refund)


@router.get("/clubs/{club_id}/refunds", response_model=list[RefundOut])
async def get_refunds(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[RefundOut]:
    rows = await list_refunds(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        status=status,
        limit=limit,
        offset=offset,
    )
    return [RefundOut.model_validate(r) for r in rows]


@router.get("/clubs/{club_id}/refunds/mine", response_model=list[RefundOut])
async def get_my_refunds(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> list[RefundOut]:
    rows = await list_my_refunds(db, club_id=club.id, user_id=auth.user.id)
    return [RefundOut.model_validate(r) for r in rows]


@router.post("/clubs/{club_id}/refunds/{refund_id}/decide", response_model=RefundOut)
async def post_refund_decision(
    refund_id: uuid.UUID,
    payload: RefundDecideIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> RefundOut:
    refund = await decide_refund(
        db,
        club_id=club.id,
        refund_id=refund_id,
        actor_user_id=auth.user.id,
        decision=payload.decision,
        reason=payload.reason,
    )
    await db.commit()
    return RefundOut.model_validate(refund)


@router.post("/clubs/{club_id}/refunds/{refund_id}/complete", response_model=RefundOut)
async def post_refund_complete(
    refund_id: uuid.UUID,
    payload: RefundCompleteIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> RefundOut:
    refund = await complete_manual_refund(
        db,
        club_id=club.id,
        refund_id=refund_id,
        actor_user_id=auth.user.id,
        manual_reference=payload.manual_reference,
        acknowledge_used=payload.acknowledge_used,
        physical_return=payload.physical_return,
        idempotency_key=payload.idempotency_key,
    )
    await db.commit()
    return RefundOut.model_validate(refund)
