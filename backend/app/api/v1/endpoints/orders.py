from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.session import get_db
from app.dependencies.auth import AuthContext, get_club, require_csrf
from app.models import Club, Order
from app.schemas.orders import DemoPayIn, ManualPayIn, MembershipOrderIn, OrderOut, TicketOrderIn
from app.services.purchase_service import (
    confirm_payment,
    create_membership_order,
    create_ticket_order,
    get_order_for_user,
)

router = APIRouter(tags=["orders"])


def _load_order(db: Session, order_id: uuid.UUID) -> Order:
    return db.scalars(
        select(Order)
        .options(joinedload(Order.items), joinedload(Order.payments))
        .where(Order.id == order_id)
    ).unique().one()


@router.post("/clubs/{club_id}/orders/membership", response_model=OrderOut)
def buy_membership(
    payload: MembershipOrderIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Order:
    order = create_membership_order(
        db, club_id=club.id, user_id=auth.user.id, plan_id=payload.plan_id
    )
    db.commit()
    return _load_order(db, order.id)


@router.post("/clubs/{club_id}/orders/tickets", response_model=OrderOut)
def buy_tickets(
    payload: TicketOrderIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Order:
    order = create_ticket_order(
        db,
        club_id=club.id,
        user_id=auth.user.id,
        ticket_price_id=payload.ticket_price_id,
        quantity=payload.quantity,
    )
    db.commit()
    return _load_order(db, order.id)


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(
    order_id: uuid.UUID,
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Order:
    order = get_order_for_user(db, order_id=order_id, user_id=auth.user.id)
    return _load_order(db, order.id)


@router.post("/orders/{order_id}/pay/demo", response_model=OrderOut)
def pay_demo(
    order_id: uuid.UUID,
    payload: DemoPayIn,
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Order:
    order = confirm_payment(
        db,
        order_id=order_id,
        actor_user_id=auth.user.id,
        method="demo",
        success=payload.success,
        manual=False,
    )
    db.commit()
    return _load_order(db, order.id)


@router.post("/orders/{order_id}/pay/manual", response_model=OrderOut)
def pay_manual(
    order_id: uuid.UUID,
    payload: ManualPayIn,
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> Order:
    order = confirm_payment(
        db,
        order_id=order_id,
        actor_user_id=auth.user.id,
        method="offline",
        provider_ref=payload.provider_ref,
        success=True,
        manual=True,
    )
    db.commit()
    return _load_order(db, order.id)
