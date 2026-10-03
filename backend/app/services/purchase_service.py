"""Shared purchase workflow for memberships and tickets.

Payment state machine (explicit transitions):
  pending → confirmed | failed | refund_required
  failed → confirmed | failed (retry allowed)
  confirmed → refund_required (event cancellation / capacity loss after pay)
  confirmed must never regress to failed when a late failure arrives.
  refund_required is terminal for automated payment attempts.

Order state machine:
  pending → paid | cancelled | refund_required
  paid → refund_required
  cancelled / refund_required are terminal for further confirmation.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

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
    Product,
    ProductVariant,
    Ticket,
    TicketPrice,
    TicketType,
)
from app.services.audit import record_audit
from app.services.auth_service import ensure_club_member
from app.services.ledger_service import post_payment_confirmation
from app.services.membership_eligibility import has_active_membership, utcnow
from app.services.membership_service import compute_entitlement_window, issue_membership_from_order_item
from app.services.merchandise_service import (
    consume_reservation_as_sale,
    lock_variants_sorted,
    release_expired_reservations_for_variants,
    release_reservation,
    reserve_stock,
)
from app.services.rbac import require_permission

_CONFIRMED_PAYMENT = frozenset({"confirmed", "refund_required"})


def _settings() -> Settings:
    return get_settings()


async def count_event_commitments(db: AsyncSession, *, event_id: uuid.UUID) -> int:
    """Issued valid tickets + active unexpired pending reservations."""
    issued = await db.scalar(
        select(func.count()).select_from(Ticket).where(Ticket.event_id == event_id, Ticket.status == "valid")
    ) or 0
    now = utcnow()
    reserved = await db.scalar(
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


def _assert_event_purchasable(event: Event, *, now, require_published: bool = True) -> None:
    if event.status == "cancelled":
        raise AppError("Event is cancelled.", code="event_cancelled")
    if require_published and event.status != "published":
        raise AppError("Event is not open for ticket sales.")
    # Policy: sales stop once the event has ended (UTC).
    if event.ends_at <= now:
        raise AppError("Event has already ended.", code="event_ended")
    if event.sales_opens_at and now < event.sales_opens_at:
        raise AppError("Ticket sales have not opened yet.")
    if event.sales_closes_at and now > event.sales_closes_at:
        raise AppError("Ticket sales have closed.")


async def create_membership_order(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    plan_id: uuid.UUID,
) -> Order:
    plan = await db.get(MembershipPlan, plan_id)
    if plan is None or plan.club_id != club_id or not plan.is_active or plan.archived_at is not None:
        raise NotFoundError("Membership plan not available.")
    await compute_entitlement_window(db, club_id=club_id, user_id=user_id, plan=plan)
    await ensure_club_member(db, club_id=club_id, user_id=user_id)

    order = Order(
        club_id=club_id,
        user_id=user_id,
        status="pending",
        total_amount=plan.dues_amount,
        currency=_settings().currency_code,
        expires_at=None,
    )
    db.add(order)
    await db.flush()
    db.add(
        OrderItem(
            order_id=order.id,
            item_kind="membership",
            membership_plan_id=plan.id,
            ticket_price_id=None,
            quantity=1,
            unit_price_snapshot=plan.dues_amount,
            title_snapshot=plan.name,
            duration_days_snapshot=plan.duration_days,
            fixed_expires_on_snapshot=plan.fixed_expires_on,
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
    await db.flush()
    return order


async def create_ticket_order(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    ticket_price_id: uuid.UUID,
    quantity: int = 1,
) -> Order:
    if quantity < 1:
        raise AppError("Quantity must be at least 1.")
    price = (
        await db.scalars(
            select(TicketPrice)
            .options(joinedload(TicketPrice.ticket_type).joinedload(TicketType.event))
            .where(TicketPrice.id == ticket_price_id)
        )
    ).unique().first()
    if price is None or not price.is_active:
        raise NotFoundError("Ticket price not found.")
    ticket_type = price.ticket_type
    if not ticket_type.is_active:
        raise AppError("Ticket type is inactive.", code="ticket_type_inactive")
    event = ticket_type.event
    if event.club_id != club_id:
        raise ForbiddenError("Ticket does not belong to this club.")
    now = utcnow()
    _assert_event_purchasable(event, now=now)

    if price.audience == "member" and not await has_active_membership(
        db, club_id=club_id, user_id=user_id, at=now
    ):
        raise ForbiddenError("Member pricing requires an active club membership.")

    locked_event = await db.scalar(select(Event).where(Event.id == event.id).with_for_update())
    if locked_event is None:
        raise NotFoundError("Event not found.")
    # Re-read mutable state after lock.
    _assert_event_purchasable(locked_event, now=utcnow())
    committed = await count_event_commitments(db, event_id=locked_event.id)
    if committed + quantity > locked_event.capacity:
        raise ConflictError("Not enough ticket capacity remaining.", code="capacity_exhausted")

    await ensure_club_member(db, club_id=club_id, user_id=user_id)
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
    await db.flush()
    db.add(
        OrderItem(
            order_id=order.id,
            item_kind="ticket",
            membership_plan_id=None,
            ticket_price_id=price.id,
            quantity=quantity,
            unit_price_snapshot=price.amount,
            title_snapshot=f"{event.title} — {ticket_type.name} ({price.audience})",
            duration_days_snapshot=None,
            fixed_expires_on_snapshot=None,
        )
    )
    db.add(Payment(order_id=order.id, amount=total, method="pending", status="pending"))
    await db.flush()
    return order


async def create_merchandise_order(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    user_id: uuid.UUID,
    product_variant_id: uuid.UUID,
    quantity: int = 1,
) -> Order:
    """Single-variant merch checkout with atomic stock reservation."""
    if quantity < 1:
        raise AppError("Quantity must be at least 1.")

    variant = (
        await db.scalars(
            select(ProductVariant)
            .options(joinedload(ProductVariant.product))
            .where(ProductVariant.id == product_variant_id)
        )
    ).unique().first()
    if variant is None or not variant.is_active:
        raise NotFoundError("Product variant not available.")
    product = variant.product
    if product.club_id != club_id:
        raise ForbiddenError("Variant does not belong to this club.")
    if product.status != "active":
        raise AppError("Product is not available for purchase.")

    await ensure_club_member(db, club_id=club_id, user_id=user_id)
    now = utcnow()

    # Deterministic lock + reclaim expired holds before availability check.
    await release_expired_reservations_for_variants(db, variant_ids=[variant.id])
    locked = await lock_variants_sorted(db, variant_ids=[variant.id])
    locked_variant = locked[variant.id]
    # Re-check after lock.
    product_row = await db.get(Product, locked_variant.product_id)
    if product_row is None or product_row.status != "active" or not locked_variant.is_active:
        raise AppError("Product variant is not available for purchase.")

    total = (locked_variant.price * Decimal(quantity)).quantize(Decimal("0.01"))
    order = Order(
        club_id=club_id,
        user_id=user_id,
        status="pending",
        total_amount=total,
        currency=_settings().currency_code,
        expires_at=now + timedelta(minutes=_settings().reservation_minutes),
    )
    db.add(order)
    await db.flush()
    item = OrderItem(
        order_id=order.id,
        item_kind="merchandise",
        membership_plan_id=None,
        ticket_price_id=None,
        product_variant_id=locked_variant.id,
        quantity=quantity,
        unit_price_snapshot=locked_variant.price,
        title_snapshot=f"{product_row.name} — {locked_variant.label}",
        duration_days_snapshot=None,
        fixed_expires_on_snapshot=None,
        fulfillment_status="reserved",
    )
    db.add(item)
    await db.flush()
    await reserve_stock(
        db,
        variant=locked_variant,
        quantity=quantity,
        order_item_id=item.id,
        actor_user_id=user_id,
    )
    db.add(Payment(order_id=order.id, amount=total, method="pending", status="pending"))
    await db.flush()
    return order


async def cancel_pending_order(
    db: AsyncSession,
    *,
    order_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> Order:
    """Buyer cancels an unpaid reservation / pending membership checkout."""
    order = await db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise NotFoundError("Order not found.")
    if order.user_id != actor_user_id:
        raise ForbiddenError("You can only cancel your own orders.")
    if order.status == "cancelled":
        return order
    if order.status != "pending":
        raise AppError("Only pending orders can be cancelled.", code="order_not_pending")
    order.status = "cancelled"
    items = (await db.scalars(select(OrderItem).where(OrderItem.order_id == order.id))).all()
    for item in items:
        if item.item_kind == "merchandise":
            await release_reservation(
                db, order_item=item, actor_user_id=actor_user_id, cancel_item=True
            )
    payment = await db.scalar(select(Payment).where(Payment.order_id == order.id).with_for_update())
    if payment and payment.status == "pending":
        payment.status = "failed"
        payment.method = payment.method if payment.method != "pending" else "cancelled"
        db.add(
            PaymentEvent(
                payment_id=payment.id,
                event_type="payment.cancelled_with_order",
                payload={"reason": "buyer_cancelled"},
            )
        )
    await record_audit(
        db,
        club_id=order.club_id,
        actor_user_id=actor_user_id,
        action="order.cancelled",
        entity_type="order",
        entity_id=order.id,
    )
    return order


async def _ticket_lines_by_event(db: AsyncSession, order: Order) -> dict[uuid.UUID, int]:
    """Map event_id → seats required. Enforces single-event orders."""
    needed: dict[uuid.UUID, int] = defaultdict(int)
    for item in order.items:
        if item.item_kind != "ticket" or not item.ticket_price_id:
            continue
        price = (
            await db.scalars(
                select(TicketPrice)
                .options(joinedload(TicketPrice.ticket_type))
                .where(TicketPrice.id == item.ticket_price_id)
            )
        ).unique().first()
        if price is None:
            raise AppError("Ticket price missing on order item.")
        needed[price.ticket_type.event_id] += item.quantity
    if len(needed) > 1:
        raise AppError(
            "Orders spanning multiple events are not supported.",
            code="mixed_event_order",
        )
    return dict(needed)


async def _fulfill_order(db: AsyncSession, *, order: Order) -> None:
    items = (await db.scalars(select(OrderItem).where(OrderItem.order_id == order.id))).all()
    for item in items:
        if item.item_kind == "membership":
            if await db.scalar(select(Membership).where(Membership.order_item_id == item.id)):
                continue
            plan = await db.get(MembershipPlan, item.membership_plan_id)
            if plan is None:
                raise AppError("Membership plan missing during fulfillment.")
            await issue_membership_from_order_item(
                db,
                club_id=order.club_id,
                user_id=order.user_id,
                plan=plan,
                order_item=item,
            )
        elif item.item_kind == "ticket":
            price = (
                await db.scalars(
                    select(TicketPrice)
                    .options(joinedload(TicketPrice.ticket_type).joinedload(TicketType.event))
                    .where(TicketPrice.id == item.ticket_price_id)
                )
            ).unique().first()
            if price is None:
                raise AppError("Ticket price missing during fulfillment.")
            event = price.ticket_type.event
            if event.club_id != order.club_id:
                raise AppError("Ticket/event club mismatch.", code="cross_club_violation")
            if event.status == "cancelled":
                raise AppError("Cannot issue tickets for a cancelled event.", code="event_cancelled")
            existing = {
                t.unit_index: t
                for t in (await db.scalars(select(Ticket).where(Ticket.order_item_id == item.id))).all()
            }
            for unit_index in range(item.quantity):
                if unit_index in existing:
                    continue
                raw_qr = generate_token(24)
                db.add(
                    Ticket(
                        order_item_id=item.id,
                        unit_index=unit_index,
                        event_id=price.ticket_type.event_id,
                        club_id=order.club_id,
                        user_id=order.user_id,
                        ticket_type_id=price.ticket_type_id,
                        status="valid",
                        qr_token_hash=hash_token(raw_qr),
                        qr_token_sealed=seal_token(raw_qr),
                    )
                )
            await db.flush()
        elif item.item_kind == "merchandise":
            await consume_reservation_as_sale(db, order_item=item, actor_user_id=order.user_id)


async def _merch_lines(db: AsyncSession, order: Order) -> list[OrderItem]:
    return [item for item in order.items if item.item_kind == "merchandise" and item.product_variant_id]


async def _authorize_payment(
    db: AsyncSession,
    *,
    order: Order,
    actor_user_id: uuid.UUID,
    method: str,
    manual: bool,
) -> None:
    if manual:
        await require_permission(db, club_id=order.club_id, user_id=actor_user_id, permission="confirm_dues")
        if actor_user_id == order.user_id:
            raise ForbiddenError("Buyers cannot manually confirm their own payment.")
        return
    if order.user_id != actor_user_id:
        raise ForbiddenError("You can only pay for your own orders.")
    if method == "demo" and not _settings().demo_payments_allowed():
        raise AppError("Demo payments are disabled.", code="demo_disabled")


async def confirm_payment(
    db: AsyncSession,
    *,
    order_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    method: str,
    provider_ref: str | None = None,
    success: bool = True,
    manual: bool = False,
) -> Order:
    # Lock order first so concurrent confirms serialize on the same row.
    order = await db.scalar(select(Order).where(Order.id == order_id).with_for_update())
    if order is None:
        raise NotFoundError("Order not found.")

    # Authorize before returning any order payload (including paid/idempotent paths).
    await _authorize_payment(db, order=order, actor_user_id=actor_user_id, method=method, manual=manual)

    # Re-load collections after lock.
    order = (
        await db.scalars(
            select(Order)
            .options(joinedload(Order.items), joinedload(Order.payments))
            .where(Order.id == order_id)
        )
    ).unique().one()

    if order.status == "paid":
        return order
    if order.status == "refund_required":
        raise ConflictError("Order already marked refund-required.")
    if order.status == "cancelled":
        raise AppError("Order is cancelled.", code="order_cancelled")

    payment = await db.scalar(select(Payment).where(Payment.order_id == order.id).with_for_update())
    if payment is None:
        payment = Payment(order_id=order.id, amount=order.total_amount, method=method, status="pending")
        db.add(payment)
        await db.flush()
        payment = await db.scalar(select(Payment).where(Payment.id == payment.id).with_for_update())
        assert payment is not None

    # Terminal confirmed payments must not regress on a late failure.
    if payment.status in _CONFIRMED_PAYMENT:
        if order.status == "paid":
            return order
        if not success:
            db.add(
                PaymentEvent(
                    payment_id=payment.id,
                    event_type="payment.failure_ignored",
                    payload={"reason": "already_confirmed", "method": method},
                )
            )
            return order

    if not success:
        if payment.status == "confirmed":
            return order
        payment.status = "failed"
        payment.method = method
        db.add(PaymentEvent(payment_id=payment.id, event_type="payment.failed", payload={"method": method}))
        return order

    # Success path — re-validate ticket resources under deterministic event locks.
    needed_by_event = await _ticket_lines_by_event(db, order)
    if needed_by_event:
        for event_id in sorted(needed_by_event.keys(), key=str):
            event = await db.scalar(select(Event).where(Event.id == event_id).with_for_update())
            if event is None:
                raise NotFoundError("Event not found.")
            now = utcnow()
            if event.status == "cancelled":
                return await _mark_refund_required(
                    db,
                    order=order,
                    payment=payment,
                    actor_user_id=actor_user_id,
                    method=method,
                    provider_ref=provider_ref,
                    reason="event_cancelled_after_payment",
                )
            if event.status != "published":
                return await _mark_refund_required(
                    db,
                    order=order,
                    payment=payment,
                    actor_user_id=actor_user_id,
                    method=method,
                    provider_ref=provider_ref,
                    reason="event_not_purchasable",
                )
            # Validate ticket types/prices still active for fulfillment of new tickets.
            for item in order.items:
                if item.item_kind != "ticket" or not item.ticket_price_id:
                    continue
                price = (
                    await db.scalars(
                        select(TicketPrice)
                        .options(joinedload(TicketPrice.ticket_type))
                        .where(TicketPrice.id == item.ticket_price_id)
                    )
                ).unique().first()
                if price is None or not price.is_active or not price.ticket_type.is_active:
                    return await _mark_refund_required(
                        db,
                        order=order,
                        payment=payment,
                        actor_user_id=actor_user_id,
                        method=method,
                        provider_ref=provider_ref,
                        reason="ticket_type_inactive",
                    )

            expired = order.expires_at is not None and order.expires_at <= now
            committed = await count_event_commitments(db, event_id=event.id)
            # Unexpired pending holds include this order; subtract self before comparing.
            self_count = needed_by_event[event_id] if (order.expires_at and order.expires_at > now) else 0
            others = committed - self_count
            if others + needed_by_event[event_id] > event.capacity:
                return await _mark_refund_required(
                    db,
                    order=order,
                    payment=payment,
                    actor_user_id=actor_user_id,
                    method=method,
                    provider_ref=provider_ref,
                    reason="capacity_after_expiry" if expired else "capacity_exhausted",
                )

    # Merchandise: lock variants in UUID order; expired reservation → release + refund_required.
    merch_items = await _merch_lines(db, order)
    if merch_items:
        variant_ids = [item.product_variant_id for item in merch_items if item.product_variant_id]
        await lock_variants_sorted(db, variant_ids=variant_ids)
        now = utcnow()
        expired = order.expires_at is not None and order.expires_at <= now
        if expired:
            for item in merch_items:
                await release_reservation(
                    db, order_item=item, actor_user_id=actor_user_id, cancel_item=True
                )
            return await _mark_refund_required(
                db,
                order=order,
                payment=payment,
                actor_user_id=actor_user_id,
                method=method,
                provider_ref=provider_ref,
                reason="reservation_expired",
            )
        for item in merch_items:
            if item.fulfillment_status != "reserved":
                return await _mark_refund_required(
                    db,
                    order=order,
                    payment=payment,
                    actor_user_id=actor_user_id,
                    method=method,
                    provider_ref=provider_ref,
                    reason="merch_reservation_missing",
                )
            variant = await db.get(ProductVariant, item.product_variant_id)
            product = await db.get(Product, variant.product_id) if variant else None
            if (
                variant is None
                or not variant.is_active
                or product is None
                or product.club_id != order.club_id
                or product.status != "active"
            ):
                await release_reservation(
                    db, order_item=item, actor_user_id=actor_user_id, cancel_item=True
                )
                return await _mark_refund_required(
                    db,
                    order=order,
                    payment=payment,
                    actor_user_id=actor_user_id,
                    method=method,
                    provider_ref=provider_ref,
                    reason="merch_unavailable",
                )

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
    # Cash-basis ledger: demo → demo_clearing; manual → cash. Idempotent per payment.
    await post_payment_confirmation(db, order=order, payment=payment)
    try:
        await _fulfill_order(db, order=order)
    except AppError as exc:
        if getattr(exc, "code", None) in {"event_cancelled", "capacity_exhausted"}:
            return await _mark_refund_required(
                db,
                order=order,
                payment=payment,
                actor_user_id=actor_user_id,
                method=method,
                provider_ref=provider_ref,
                reason=str(getattr(exc, "code", "fulfillment_failed")),
            )
        raise
    order.status = "paid"
    await record_audit(
        db,
        club_id=order.club_id,
        actor_user_id=actor_user_id,
        action="order.paid",
        entity_type="order",
        entity_id=order.id,
        details={"method": method},
    )
    return order


async def _mark_refund_required(
    db: AsyncSession,
    *,
    order: Order,
    payment: Payment,
    actor_user_id: uuid.UUID,
    method: str,
    provider_ref: str | None,
    reason: str,
) -> Order:
    """Successful money movement that cannot be fulfilled → operator refund queue."""
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
            payload={"reason": reason},
        )
    )
    await record_audit(
        db,
        club_id=order.club_id,
        actor_user_id=actor_user_id,
        action="order.refund_required",
        entity_type="order",
        entity_id=order.id,
        details={"reason": reason},
    )
    return order


async def get_order_for_user(db: AsyncSession, *, order_id: uuid.UUID, user_id: uuid.UUID) -> Order:
    order = await db.get(Order, order_id)
    if order is None:
        raise NotFoundError("Order not found.")
    if order.user_id != user_id:
        raise ForbiddenError("You cannot access another user's order.")
    return order
