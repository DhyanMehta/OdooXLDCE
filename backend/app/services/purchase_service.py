"""Shared purchase workflow for memberships and tickets."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings, get_settings
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.security import generate_token, hash_token
from app.core.tokens import seal_token
from app.models import (
    Event,
    Membership,
    MembershipPlan,
    Order,
    OrderItem,
    Payment,
    PaymentEvent,
    Ticket,
    TicketPrice,
    TicketType,
)
from app.services.audit import record_audit
from app.services.auth_service import ensure_club_member
from app.services.membership_eligibility import has_active_membership, utcnow
from app.services.membership_service import compute_entitlement_window, issue_membership_from_order_item
from app.services.rbac import require_permission


def _settings() -> Settings:
    return get_settings()


def count_event_commitments(db: Session, *, event_id: uuid.UUID) -> int:
    """Issued valid tickets + active unexpired pending reservations."""
    issued = db.scalar(
        select(func.count()).select_from(Ticket).where(Ticket.event_id == event_id, Ticket.status == "valid")
    ) or 0
    now = utcnow()
    reserved = db.scalar(
        select(func.coalesce(func.sum(OrderItem.quantity), 0))
        .select_from(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .join(TicketPrice, TicketPrice.id == OrderItem.ticket_price_id)
        .join(TicketType, TicketType.id == TicketPrice.ticket_type_id)
        .where(
            TicketType.event_id == event_id,
            OrderItem.item_kind == "ticket",
            Order.status == "pending",
            Order.expires_at.is_not(None),
            Order.expires_at > now,
        )
    ) or 0
    return int(issued) + int(reserved)


def create_membership_order(
    db: Session,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    plan_id: uuid.UUID,
) -> Order:
    plan = db.get(MembershipPlan, plan_id)
    if plan is None or plan.club_id != club_id or not plan.is_active or plan.archived_at is not None:
        raise NotFoundError("Membership plan not available.")
    compute_entitlement_window(db, club_id=club_id, user_id=user_id, plan=plan)
    ensure_club_member(db, club_id=club_id, user_id=user_id)

    order = Order(
        club_id=club_id,
        user_id=user_id,
        status="pending",
        total_amount=plan.dues_amount,
        currency=_settings().currency_code,
        expires_at=None,
    )
    db.add(order)
    db.flush()
    db.add(
        OrderItem(
            order_id=order.id,
            item_kind="membership",
            membership_plan_id=plan.id,
            ticket_price_id=None,
            quantity=1,
            unit_price_snapshot=plan.dues_amount,
            title_snapshot=plan.name,
        )
    )
    db.add(
        Payment(
            order_id=order.id,
            amount=order.total_amount,
            method="pending",
            status="pending",
        )
    )
    db.flush()
    return order


def create_ticket_order(
    db: Session,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    ticket_price_id: uuid.UUID,
    quantity: int = 1,
) -> Order:
    if quantity < 1:
        raise AppError("Quantity must be at least 1.")
    price = db.scalar(
        select(TicketPrice)
        .options(joinedload(TicketPrice.ticket_type).joinedload(TicketType.event))
        .where(TicketPrice.id == ticket_price_id)
    )
    if price is None or not price.is_active:
        raise NotFoundError("Ticket price not found.")
    ticket_type = price.ticket_type
    event = ticket_type.event
    if event.club_id != club_id:
        raise ForbiddenError("Ticket does not belong to this club.")
    if event.status != "published":
        raise AppError("Event is not open for ticket sales.")
    now = utcnow()
    if event.sales_opens_at and now < event.sales_opens_at:
        raise AppError("Ticket sales have not opened yet.")
    if event.sales_closes_at and now > event.sales_closes_at:
        raise AppError("Ticket sales have closed.")

    # Member prices require active paid membership; a member-price ID alone is insufficient.
    if price.audience == "member" and not has_active_membership(
        db, club_id=club_id, user_id=user_id, at=now
    ):
        raise ForbiddenError("Member pricing requires an active club membership.")

    locked_event = db.scalar(select(Event).where(Event.id == event.id).with_for_update())
    if locked_event is None:
        raise NotFoundError("Event not found.")
    committed = count_event_commitments(db, event_id=locked_event.id)
    if committed + quantity > locked_event.capacity:
        raise ConflictError("Not enough ticket capacity remaining.", code="capacity_exhausted")

    ensure_club_member(db, club_id=club_id, user_id=user_id)
    total = (price.amount * Decimal(quantity)).quantize(Decimal("0.01"))
    order = Order(
        club_id=club_id,
        user_id=user_id,
        status="pending",
        total_amount=total,
        currency=_settings().currency_code,
        expires_at=now + timedelta(minutes=_settings().reservation_minutes),
    )
    db.add(order)
    db.flush()
    db.add(
        OrderItem(
            order_id=order.id,
            item_kind="ticket",
            membership_plan_id=None,
            ticket_price_id=price.id,
            quantity=quantity,
            unit_price_snapshot=price.amount,
            title_snapshot=f"{event.title} — {ticket_type.name} ({price.audience})",
        )
    )
    db.add(Payment(order_id=order.id, amount=total, method="pending", status="pending"))
    db.flush()
    return order


def _fulfill_order(db: Session, *, order: Order) -> None:
    items = db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
    for item in items:
        if item.item_kind == "membership":
            if db.scalar(select(Membership).where(Membership.order_item_id == item.id)):
                continue
            plan = db.get(MembershipPlan, item.membership_plan_id)
            if plan is None:
                raise AppError("Membership plan missing during fulfillment.")
            issue_membership_from_order_item(
                db,
                club_id=order.club_id,
                user_id=order.user_id,
                plan=plan,
                order_item_id=item.id,
            )
        elif item.item_kind == "ticket":
            existing_count = (
                db.scalar(select(func.count()).select_from(Ticket).where(Ticket.order_item_id == item.id))
                or 0
            )
            if existing_count >= item.quantity:
                continue
            price = db.scalar(
                select(TicketPrice)
                .options(joinedload(TicketPrice.ticket_type))
                .where(TicketPrice.id == item.ticket_price_id)
            )
            if price is None:
                raise AppError("Ticket price missing during fulfillment.")
            for _ in range(item.quantity - int(existing_count)):
                raw_qr = generate_token(24)
                db.add(
                    Ticket(
                        order_item_id=item.id,
                        event_id=price.ticket_type.event_id,
                        club_id=order.club_id,
                        user_id=order.user_id,
                        ticket_type_id=price.ticket_type_id,
                        status="valid",
                        qr_token_hash=hash_token(raw_qr),
                        qr_token_sealed=seal_token(raw_qr),
                    )
                )
            db.flush()


def confirm_payment(
    db: Session,
    *,
    order_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    method: str,
    provider_ref: str | None = None,
    success: bool = True,
    manual: bool = False,
) -> Order:
    order = db.scalar(
        select(Order)
        .options(joinedload(Order.items), joinedload(Order.payments))
        .where(Order.id == order_id)
    )
    if order is None:
        raise NotFoundError("Order not found.")

    # Idempotent: confirmed orders return as-is without re-issuing entitlements.
    if order.status == "paid":
        return order
    if order.status == "refund_required":
        raise ConflictError("Order already marked refund-required.")
    if order.status == "cancelled":
        raise AppError("Order is cancelled.")

    if manual:
        require_permission(db, club_id=order.club_id, user_id=actor_user_id, permission="confirm_dues")
        if actor_user_id == order.user_id:
            raise ForbiddenError("Buyers cannot manually confirm their own payment.")
    else:
        if order.user_id != actor_user_id:
            raise ForbiddenError("You can only pay for your own orders.")
        if method == "demo" and not _settings().demo_payments_enabled:
            raise AppError("Demo payments are disabled.", code="demo_disabled")

    payment = order.payments[0] if order.payments else None
    if payment is None:
        payment = Payment(order_id=order.id, amount=order.total_amount, method=method, status="pending")
        db.add(payment)
        db.flush()

    if not success:
        payment.status = "failed"
        payment.method = method
        db.add(PaymentEvent(payment_id=payment.id, event_type="payment.failed", payload={"method": method}))
        return order

    has_tickets = any(i.item_kind == "ticket" for i in order.items)
    if has_tickets:
        event_ids: set[uuid.UUID] = set()
        needed = 0
        for item in order.items:
            if item.item_kind != "ticket" or not item.ticket_price_id:
                continue
            needed += item.quantity
            price = db.get(TicketPrice, item.ticket_price_id)
            if price:
                tt = db.get(TicketType, price.ticket_type_id)
                if tt:
                    event_ids.add(tt.event_id)
        for event_id in event_ids:
            event = db.scalar(select(Event).where(Event.id == event_id).with_for_update())
            if event is None:
                raise NotFoundError("Event not found.")
            expired = order.expires_at is not None and order.expires_at <= utcnow()
            if expired:
                committed = count_event_commitments(db, event_id=event.id)
                if committed + needed > event.capacity:
                    order.status = "refund_required"
                    payment.status = "refund_required"
                    payment.method = method
                    payment.provider_ref = provider_ref
                    payment.confirmed_by_user_id = actor_user_id
                    payment.confirmed_at = utcnow()
                    db.add(
                        PaymentEvent(
                            payment_id=payment.id,
                            event_type="payment.refund_required",
                            payload={"reason": "capacity_after_expiry"},
                        )
                    )
                    record_audit(
                        db,
                        club_id=order.club_id,
                        actor_user_id=actor_user_id,
                        action="order.refund_required",
                        entity_type="order",
                        entity_id=order.id,
                    )
                    return order

    payment.status = "confirmed"
    payment.method = method
    payment.provider_ref = provider_ref or ("demo-success" if method == "demo" else provider_ref)
    payment.confirmed_by_user_id = actor_user_id
    payment.confirmed_at = utcnow()
    db.add(
        PaymentEvent(
            payment_id=payment.id,
            event_type="payment.confirmed",
            payload={"method": method, "simulated": method == "demo"},
        )
    )
    _fulfill_order(db, order=order)
    order.status = "paid"
    record_audit(
        db,
        club_id=order.club_id,
        actor_user_id=actor_user_id,
        action="order.paid",
        entity_type="order",
        entity_id=order.id,
        details={"method": method},
    )
    return order


def get_order_for_user(db: Session, *, order_id: uuid.UUID, user_id: uuid.UUID) -> Order:
    order = db.get(Order, order_id)
    if order is None:
        raise NotFoundError("Order not found.")
    if order.user_id != user_id:
        raise ForbiddenError("You cannot access another user's order.")
    return order
