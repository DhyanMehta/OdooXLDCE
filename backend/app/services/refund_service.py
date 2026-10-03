"""Full manual refunds of one confirmed / refund-required payment.

Flow: ``requested`` → ``approved`` → ``completed`` (or ``rejected``). A request
alone never changes the order, entitlements, inventory, or ledger. Completion is
a single database transaction that records the operator's off-platform payout
reference, reverses entitlements, restocks eligible merchandise, and posts the
ledger reversal. There is no payment-provider integration; money is returned by
the operator outside this system and recorded here.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.models import Membership, Order, Payment, Refund, Ticket
from app.services.audit import record_audit
from app.services.ledger_service import post_payment_confirmation, post_refund_reversal
from app.services.membership_eligibility import utcnow
from app.services.merchandise_service import (
    lock_variants_sorted,
    release_reservation,
    restock_for_refund,
)
from app.services.rbac import require_permission

ACTIVE_STATUSES = frozenset({"requested", "approved", "processing"})
COMPLETABLE_STATUSES = frozenset({"approved", "processing"})
REFUNDABLE_ORDER_STATUSES = frozenset({"paid", "refund_required"})
REFUNDABLE_PAYMENT_STATUSES = frozenset({"confirmed", "refund_required"})
REFUND_STATUSES = frozenset(
    {"requested", "approved", "processing", "completed", "failed", "rejected"}
)


async def _get_refund(
    db: AsyncSession, *, club_id: uuid.UUID, refund_id: uuid.UUID, for_update: bool = False
) -> Refund:
    stmt = select(Refund).where(Refund.id == refund_id, Refund.club_id == club_id)
    if for_update:
        stmt = stmt.with_for_update()
    refund = await db.scalar(stmt)
    if refund is None:
        raise NotFoundError("Refund not found.")
    return refund


async def request_refund(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    order_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    reason: str = "",
) -> Refund:
    """Buyer or ``record_refunds`` staff asks for a full refund. Status ``requested`` only."""
    order = await db.scalar(
        select(Order).where(Order.id == order_id, Order.club_id == club_id).with_for_update()
    )
    if order is None:
        raise NotFoundError("Order not found.")
    if order.user_id != actor_user_id:
        await require_permission(
            db, club_id=club_id, user_id=actor_user_id, permission="record_refunds"
        )
    if order.status == "refunded":
        raise ConflictError("Order is already refunded.", code="already_refunded")
    if order.status not in REFUNDABLE_ORDER_STATUSES:
        raise ConflictError("Only paid orders can be refunded.", code="order_not_refundable")

    payment = await db.scalar(
        select(Payment)
        .where(Payment.order_id == order.id, Payment.status.in_(REFUNDABLE_PAYMENT_STATUSES))
        .with_for_update()
    )
    if payment is None:
        raise ConflictError("No refundable payment on this order.", code="payment_not_refundable")
    if payment.amount <= 0:
        raise AppError("Zero-amount payments cannot be refunded.", code="refund_zero_amount")

    open_or_done = await db.scalar(
        select(func.count())
        .select_from(Refund)
        .where(
            Refund.payment_id == payment.id,
            Refund.status.in_(ACTIVE_STATUSES | {"completed"}),
        )
    )
    if int(open_or_done or 0) > 0:
        raise ConflictError("A refund already exists for this payment.", code="refund_exists")

    refund = Refund(
        club_id=club_id,
        order_id=order.id,
        payment_id=payment.id,
        amount=payment.amount,
        currency=order.currency,
        status="requested",
        reason=reason.strip(),
        requested_by_user_id=actor_user_id,
    )
    db.add(refund)
    await db.flush()
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="refund.requested",
        entity_type="refund",
        entity_id=refund.id,
        details={"order_id": str(order.id), "amount": str(refund.amount)},
    )
    return refund


async def decide_refund(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    refund_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    decision: str,
    reason: str = "",
) -> Refund:
    """Approve or reject a requested refund. Approval does not move money or entitlements."""
    await require_permission(
        db, club_id=club_id, user_id=actor_user_id, permission="record_refunds"
    )
    if decision not in {"approved", "rejected"}:
        raise AppError("Invalid decision.", code="invalid_decision")
    if decision == "rejected" and not reason.strip():
        raise AppError("Rejection requires a reason.", code="reason_required")
    refund = await _get_refund(db, club_id=club_id, refund_id=refund_id, for_update=True)
    if refund.status != "requested":
        raise ConflictError("Only requested refunds can be decided.", code="refund_not_requested")
    if decision == "approved":
        order = await db.get(Order, refund.order_id)
        buyer_id = order.user_id if order else None
        if actor_user_id in {refund.requested_by_user_id, buyer_id}:
            raise ForbiddenError("Self-approval is not allowed.")

    refund.status = decision
    refund.decided_by_user_id = actor_user_id
    refund.decided_at = utcnow()
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action=f"refund.{decision}",
        entity_type="refund",
        entity_id=refund.id,
        details={"reason": reason.strip()},
    )
    await db.flush()
    return refund


async def _completed_total(
    db: AsyncSession, *, payment_id: uuid.UUID, exclude_refund_id: uuid.UUID
) -> Decimal:
    total = await db.scalar(
        select(func.coalesce(func.sum(Refund.amount), 0)).where(
            Refund.payment_id == payment_id,
            Refund.status == "completed",
            Refund.id != exclude_refund_id,
        )
    )
    return Decimal(total or 0)


async def complete_manual_refund(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    refund_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    manual_reference: str,
    acknowledge_used: bool = False,
    physical_return: bool = False,
    idempotency_key: str | None = None,
) -> Refund:
    """Record an off-platform payout and atomically reverse everything the order granted."""
    await require_permission(
        db, club_id=club_id, user_id=actor_user_id, permission="record_refunds"
    )
    reference = manual_reference.strip()
    if not reference:
        raise AppError("A manual payout reference is required.", code="reference_required")
    key = (idempotency_key or "").strip() or f"refund-complete:{uuid.uuid4().hex}"

    refund = await _get_refund(db, club_id=club_id, refund_id=refund_id, for_update=True)
    if refund.status == "completed" and refund.completion_idempotency_key == key:
        return refund  # exact replay of a finished request
    if refund.status == "completed":
        raise ConflictError("Refund is already completed.", code="refund_already_completed")
    if refund.status not in COMPLETABLE_STATUSES:
        raise ConflictError("Refund must be approved before completion.", code="refund_not_approved")

    reused = await db.scalar(
        select(Refund.id).where(
            Refund.completion_idempotency_key == key, Refund.id != refund.id
        )
    )
    if reused is not None:
        raise ConflictError("Idempotency key already used.", code="idempotency_key_reused")

    # Lock order: refund → order → payment.
    order = await db.scalar(
        select(Order)
        .options(selectinload(Order.items))
        .where(Order.id == refund.order_id, Order.club_id == club_id)
        .with_for_update(of=Order)
    )
    if order is None:
        raise NotFoundError("Order not found.")
    payment = await db.scalar(
        select(Payment).where(Payment.id == refund.payment_id).with_for_update()
    )
    if payment is None or payment.order_id != order.id:
        raise NotFoundError("Payment not found.")
    if order.status not in REFUNDABLE_ORDER_STATUSES or payment.status not in REFUNDABLE_PAYMENT_STATUSES:
        raise ConflictError("Order is no longer refundable.", code="order_not_refundable")
    already = await _completed_total(db, payment_id=payment.id, exclude_refund_id=refund.id)
    if already + refund.amount > payment.amount:
        raise ConflictError("Refunds would exceed the payment amount.", code="refund_exceeds_payment")

    items = list(order.items)
    item_ids = [i.id for i in items]
    tickets: list[Ticket] = []
    memberships: list[Membership] = []
    if item_ids:
        tickets = list(
            (
                await db.scalars(
                    select(Ticket)
                    .where(Ticket.order_item_id.in_(item_ids))
                    .order_by(Ticket.id)
                    .with_for_update()
                )
            ).all()
        )
        memberships = list(
            (
                await db.scalars(
                    select(Membership)
                    .where(Membership.order_item_id.in_(item_ids))
                    .order_by(Membership.id)
                    .with_for_update()
                )
            ).all()
        )
    if any(t.status == "used" for t in tickets) and not acknowledge_used:
        raise ConflictError(
            "A ticket on this order was already used; acknowledge_used is required.",
            code="used_ticket_ack_required",
        )

    merch_items = [i for i in items if i.item_kind == "merchandise" and i.product_variant_id]
    if merch_items:
        await lock_variants_sorted(
            db, variant_ids=[i.product_variant_id for i in merch_items if i.product_variant_id]
        )

    # Ledger first: refund_required payments were never journaled, so record the
    # collection (idempotent) and then reverse it, leaving an honest audit trail.
    await post_payment_confirmation(db, order=order, payment=payment)
    await post_refund_reversal(db, order=order, payment=payment, refund_id=refund.id)

    for ticket in tickets:
        if ticket.status in {"valid", "used", "refund_required"}:
            ticket.status = "cancelled"
    for membership in memberships:
        if membership.status != "revoked":
            membership.status = "revoked"
    restocked = 0
    for item in merch_items:
        status = item.fulfillment_status
        if status == "awaiting_collection":
            item.fulfillment_status = "cancelled"
            await restock_for_refund(
                db, order_item=item, refund_id=refund.id, actor_user_id=actor_user_id
            )
            restocked += item.quantity
        elif status == "collected":
            item.fulfillment_status = "cancelled"
            if physical_return:
                await restock_for_refund(
                    db, order_item=item, refund_id=refund.id, actor_user_id=actor_user_id
                )
                restocked += item.quantity
        elif status == "reserved":
            await release_reservation(
                db, order_item=item, actor_user_id=actor_user_id, cancel_item=True
            )

    order.status = "refunded"
    payment.status = "refunded"
    now = utcnow()
    refund.status = "completed"
    refund.manual_reference = reference
    refund.acknowledge_used = acknowledge_used
    refund.physical_return = physical_return
    refund.completed_by_user_id = actor_user_id
    refund.completed_at = now
    refund.completion_idempotency_key = key
    await db.flush()
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="refund.completed",
        entity_type="refund",
        entity_id=refund.id,
        details={
            "order_id": str(order.id),
            "payment_id": str(payment.id),
            "amount": str(refund.amount),
            "manual_reference": reference,
            "acknowledge_used": acknowledge_used,
            "physical_return": physical_return,
            "tickets_cancelled": len(tickets),
            "memberships_revoked": len(memberships),
            "units_restocked": restocked,
        },
    )
    await db.flush()
    return refund


async def list_refunds(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Refund]:
    await require_permission(
        db, club_id=club_id, user_id=actor_user_id, permission="record_refunds"
    )
    stmt = select(Refund).where(Refund.club_id == club_id)
    if status is not None:
        if status not in REFUND_STATUSES:
            raise AppError("Invalid refund status filter.", code="invalid_status")
        stmt = stmt.where(Refund.status == status)
    stmt = stmt.order_by(Refund.requested_at.desc(), Refund.id).limit(limit).offset(offset)
    return list((await db.scalars(stmt)).all())


async def list_my_refunds(
    db: AsyncSession, *, club_id: uuid.UUID, user_id: uuid.UUID
) -> list[Refund]:
    stmt = (
        select(Refund)
        .join(Order, Order.id == Refund.order_id)
        .where(Refund.club_id == club_id, Order.user_id == user_id)
        .order_by(Refund.requested_at.desc(), Refund.id)
    )
    return list((await db.scalars(stmt)).all())
