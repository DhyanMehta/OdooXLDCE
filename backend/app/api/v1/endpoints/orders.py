from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import get_settings
from app.core.errors import AppError
from app.db.session import get_db
from app.dependencies.auth import AuthContext, get_club, get_current_auth, require_csrf
from app.models import Club, Order, OrderItem, User
from app.schemas.orders import (
    DemoPayIn,
    ManualPayIn,
    MembershipOrderIn,
    OrderOut,
    OrderPageOut,
    TicketOrderIn,
)
from app.services.purchase_service import (
    cancel_pending_order,
    confirm_payment,
    create_membership_order,
    create_ticket_order,
    get_order_for_user,
)
from app.services.rbac import require_permission

router = APIRouter(tags=["orders"])


async def _load_order(db: AsyncSession, order_id: uuid.UUID) -> Order:
    return (
        await db.scalars(
            select(Order)
            .options(joinedload(Order.items), joinedload(Order.payments))
            .where(Order.id == order_id)
        )
    ).unique().one()


async def _order_out(db: AsyncSession, order: Order, *, enrich_buyer: bool = False) -> OrderOut:
    data = OrderOut.model_validate(order)
    if enrich_buyer:
        user = await db.get(User, order.user_id)
        data.buyer_email = user.email if user else None
        data.buyer_name = user.full_name if user else None
    return data


@router.post("/clubs/{club_id}/orders/membership", response_model=OrderOut)
async def buy_membership(
    payload: MembershipOrderIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> OrderOut:
    order = await create_membership_order(
        db, club_id=club.id, user_id=auth.user.id, plan_id=payload.plan_id
    )
    await db.commit()
    return await _order_out(db, await _load_order(db, order.id))


@router.post("/clubs/{club_id}/orders/tickets", response_model=OrderOut)
async def buy_tickets(
    payload: TicketOrderIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> OrderOut:
    order = await create_ticket_order(
        db,
        club_id=club.id,
        user_id=auth.user.id,
        ticket_price_id=payload.ticket_price_id,
        quantity=payload.quantity,
    )
    await db.commit()
    return await _order_out(db, await _load_order(db, order.id))


@router.get("/me/orders", response_model=OrderPageOut)
async def my_orders(
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = None,
) -> OrderPageOut:
    stmt = select(Order).where(Order.user_id == auth.user.id)
    if status:
        stmt = stmt.where(Order.status == status)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.scalars(
            stmt.options(joinedload(Order.items), joinedload(Order.payments))
            .order_by(Order.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).unique().all()
    return OrderPageOut(
        items=[await _order_out(db, o) for o in rows],
        total=int(total),
        limit=limit,
        offset=offset,
    )


@router.get("/clubs/{club_id}/pending-dues", response_model=list[OrderOut])
async def pending_dues(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> list[OrderOut]:
    await require_permission(db, club_id=club.id, user_id=auth.user.id, permission="confirm_dues")
    rows = (
        await db.scalars(
            select(Order)
            .join(OrderItem, OrderItem.order_id == Order.id)
            .options(joinedload(Order.items), joinedload(Order.payments))
            .where(
                Order.club_id == club.id,
                Order.status == "pending",
                OrderItem.item_kind == "membership",
            )
            .order_by(Order.created_at.asc())
        )
    ).unique().all()
    return [await _order_out(db, o, enrich_buyer=True) for o in rows]


@router.get("/clubs/{club_id}/orders/refundable", response_model=list[OrderOut])
async def refundable_orders(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=100),
) -> list[OrderOut]:
    """Paid or refund_required club orders for staff refund request (searchable UI)."""
    await require_permission(db, club_id=club.id, user_id=auth.user.id, permission="record_refunds")
    rows = (
        await db.scalars(
            select(Order)
            .options(joinedload(Order.items), joinedload(Order.payments))
            .where(
                Order.club_id == club.id,
                Order.status.in_(["paid", "refund_required"]),
            )
            .order_by(Order.created_at.desc())
            .limit(limit)
        )
    ).unique().all()
    return [await _order_out(db, o, enrich_buyer=True) for o in rows]


@router.get("/orders/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: uuid.UUID,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> OrderOut:
    order = await get_order_for_user(db, order_id=order_id, user_id=auth.user.id)
    return await _order_out(db, await _load_order(db, order.id))


@router.post("/orders/{order_id}/cancel", response_model=OrderOut)
async def cancel_order(
    order_id: uuid.UUID,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> OrderOut:
    order = await cancel_pending_order(db, order_id=order_id, actor_user_id=auth.user.id)
    await db.commit()
    return await _order_out(db, await _load_order(db, order.id))


@router.post("/orders/{order_id}/pay/demo", response_model=OrderOut)
async def pay_demo(
    order_id: uuid.UUID,
    payload: DemoPayIn,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> OrderOut:
    if not get_settings().demo_payments_allowed():
        raise AppError("Demo payments are disabled.", code="demo_disabled")
    order = await confirm_payment(
        db,
        order_id=order_id,
        actor_user_id=auth.user.id,
        method="demo",
        success=payload.success,
        manual=False,
    )
    await db.commit()
    return await _order_out(db, await _load_order(db, order.id))


@router.post("/orders/{order_id}/pay/manual", response_model=OrderOut)
async def pay_manual(
    order_id: uuid.UUID,
    payload: ManualPayIn,
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> OrderOut:
    order = await confirm_payment(
        db,
        order_id=order_id,
        actor_user_id=auth.user.id,
        method="offline",
        provider_ref=payload.provider_ref,
        success=True,
        manual=True,
    )
    await db.commit()
    return await _order_out(db, await _load_order(db, order.id))
