"""Event lifecycle, attendance, and check-in."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import get_settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.security import hash_token
from app.models import Event, Order, OrderItem, Payment, PaymentEvent, Ticket, TicketCheckin, TicketPrice, TicketType, User
from app.services.audit import record_audit
from app.services.membership_eligibility import utcnow
from app.services.purchase_service import count_event_commitments
from app.services.rbac import require_permission


class CancelImpact:
    def __init__(self, event: Event, affected: list[dict]):
        self.event = event
        self.affected = affected


async def create_event(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    title: str,
    description: str,
    venue: str,
    starts_at: datetime,
    ends_at: datetime,
    capacity: int,
    sales_opens_at: datetime | None,
    sales_closes_at: datetime | None,
) -> Event:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_events")
    if ends_at <= starts_at:
        raise AppError("Event end must be after start.")
    if capacity < 0:
        raise AppError("Capacity cannot be negative.")
    if sales_opens_at and sales_closes_at and sales_closes_at <= sales_opens_at:
        raise AppError("Sales close must be after sales open.")
    event = Event(
        club_id=club_id,
        title=title.strip(),
        description=description.strip(),
        venue=venue.strip(),
        starts_at=starts_at,
        ends_at=ends_at,
        capacity=capacity,
        status="draft",
        sales_opens_at=sales_opens_at,
        sales_closes_at=sales_closes_at,
        created_by_user_id=actor_user_id,
    )
    db.add(event)
    await db.flush()
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="event.created",
        entity_type="event",
        entity_id=event.id,
    )
    return event


async def update_event(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    event_id: uuid.UUID,
    **fields,
) -> Event:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_events")
    event = await db.scalar(select(Event).where(Event.id == event_id, Event.club_id == club_id).with_for_update())
    if event is None:
        raise NotFoundError("Event not found.")
    if "capacity" in fields and fields["capacity"] is not None:
        committed = await count_event_commitments(db, event_id=event.id)
        if fields["capacity"] < committed:
            raise AppError(
                f"Cannot reduce capacity below existing commitments ({committed}).",
                code="capacity_too_low",
            )
    for key, value in fields.items():
        if value is not None and hasattr(event, key) and key not in {"id", "club_id"}:
            setattr(event, key, value)
    if event.ends_at <= event.starts_at:
        raise AppError("Event end must be after start.")
    if event.sales_opens_at and event.sales_closes_at and event.sales_closes_at <= event.sales_opens_at:
        raise AppError("Sales close must be after sales open.")
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="event.updated",
        entity_type="event",
        entity_id=event.id,
    )
    return event


async def _cancel_pending_reservations_for_event(
    db: AsyncSession, *, event_id: uuid.UUID, actor_user_id: uuid.UUID
) -> None:
    """Cancel unpaid holds so cancelled events cannot later mint valid tickets."""
    now = utcnow()
    pending_orders = (
        await db.scalars(
            select(Order)
            .join(OrderItem, OrderItem.order_id == Order.id)
            .join(TicketPrice, TicketPrice.id == OrderItem.ticket_price_id)
            .join(TicketType, TicketType.id == TicketPrice.ticket_type_id)
            .where(
                TicketType.event_id == event_id,
                OrderItem.item_kind == "ticket",
                Order.status == "pending",
            )
            .with_for_update()
        )
    ).unique().all()
    for order in pending_orders:
        order.status = "cancelled"
        payment = await db.scalar(select(Payment).where(Payment.order_id == order.id).with_for_update())
        if payment and payment.status == "pending":
            payment.status = "failed"
            db.add(
                PaymentEvent(
                    payment_id=payment.id,
                    event_type="payment.cancelled_with_order",
                    payload={"reason": "event_cancelled", "at": now.isoformat()},
                )
            )
        await record_audit(
            db,
            club_id=order.club_id,
            actor_user_id=actor_user_id,
            action="order.cancelled",
            entity_type="order",
            entity_id=order.id,
            details={"reason": "event_cancelled"},
        )


async def set_event_status(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    event_id: uuid.UUID,
    status: str,
) -> CancelImpact:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_events")
    if status not in {"draft", "published", "cancelled"}:
        raise AppError("Invalid event status.")
    event = await db.scalar(select(Event).where(Event.id == event_id, Event.club_id == club_id).with_for_update())
    if event is None:
        raise NotFoundError("Event not found.")
    # Unpublish = back to draft (sales closed to public).
    if status == "draft" and event.status == "published":
        event.status = "draft"
    else:
        event.status = status
    affected: list[dict] = []
    if status == "cancelled":
        # Include used (checked-in) tickets so cancel still opens the refund queue.
        tickets = (
            await db.scalars(
                select(Ticket)
                .where(Ticket.event_id == event.id, Ticket.status.in_(["valid", "used"]))
                .with_for_update()
            )
        ).all()
        for ticket in tickets:
            ticket.status = "refund_required"
        item_ids = [t.order_item_id for t in tickets]
        order_ticket_counts: dict[uuid.UUID, int] = {}
        if item_ids:
            items = (await db.scalars(select(OrderItem).where(OrderItem.id.in_(item_ids)))).all()
            item_by_id = {i.id: i for i in items}
            for ticket in tickets:
                item = item_by_id.get(ticket.order_item_id)
                if item:
                    order_ticket_counts[item.order_id] = order_ticket_counts.get(item.order_id, 0) + 1
            for order_id, count in order_ticket_counts.items():
                order = await db.scalar(select(Order).where(Order.id == order_id).with_for_update())
                if order and order.status == "paid":
                    order.status = "refund_required"
                    payment = await db.scalar(select(Payment).where(Payment.order_id == order.id).with_for_update())
                    if payment and payment.status == "confirmed":
                        payment.status = "refund_required"
                        db.add(
                            PaymentEvent(
                                payment_id=payment.id,
                                event_type="payment.refund_required",
                                payload={"reason": "event_cancelled"},
                            )
                        )
                    user = await db.get(User, order.user_id)
                    affected.append(
                        {
                            "order_id": order.id,
                            "user_id": order.user_id,
                            "user_email": user.email if user else None,
                            "user_name": user.full_name if user else None,
                            "order_status": order.status,
                            "ticket_count": count,
                            "reason": "paid_tickets_refund_required",
                        }
                    )
        pending_before = (
            await db.scalars(
                select(Order)
                .join(OrderItem, OrderItem.order_id == Order.id)
                .join(TicketPrice, TicketPrice.id == OrderItem.ticket_price_id)
                .join(TicketType, TicketType.id == TicketPrice.ticket_type_id)
                .where(
                    TicketType.event_id == event.id,
                    OrderItem.item_kind == "ticket",
                    Order.status == "pending",
                )
            )
        ).unique().all()
        await _cancel_pending_reservations_for_event(db, event_id=event.id, actor_user_id=actor_user_id)
        for order in pending_before:
            user = await db.get(User, order.user_id)
            affected.append(
                {
                    "order_id": order.id,
                    "user_id": order.user_id,
                    "user_email": user.email if user else None,
                    "user_name": user.full_name if user else None,
                    "order_status": "cancelled",
                    "ticket_count": 0,
                    "reason": "pending_reservation_cancelled",
                }
            )
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action=f"event.{status}",
        entity_type="event",
        entity_id=event.id,
        details={"affected_count": len(affected)},
    )
    await db.flush()
    return CancelImpact(event=event, affected=affected)


async def upsert_ticket_type(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    event_id: uuid.UUID,
    name: str,
    description: str,
    member_price: Decimal,
    public_price: Decimal,
) -> TicketType:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_events")
    event = await db.get(Event, event_id)
    if event is None or event.club_id != club_id:
        raise NotFoundError("Event not found.")
    ticket_type = TicketType(event_id=event.id, name=name.strip(), description=description.strip())
    db.add(ticket_type)
    await db.flush()
    db.add(TicketPrice(ticket_type_id=ticket_type.id, audience="member", amount=member_price))
    db.add(TicketPrice(ticket_type_id=ticket_type.id, audience="public", amount=public_price))
    await db.flush()
    return ticket_type


async def update_ticket_type(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    event_id: uuid.UUID,
    ticket_type_id: uuid.UUID,
    fields: dict,
) -> TicketType:
    """Edit category/prices without rewriting historical order snapshots."""
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_events")
    event = await db.get(Event, event_id)
    if event is None or event.club_id != club_id:
        raise NotFoundError("Event not found.")
    ticket_type = (
        await db.scalars(
            select(TicketType)
            .options(joinedload(TicketType.prices))
            .where(TicketType.id == ticket_type_id, TicketType.event_id == event_id)
        )
    ).unique().first()
    if ticket_type is None:
        raise NotFoundError("Ticket type not found.")
    if "name" in fields and fields["name"] is not None:
        ticket_type.name = str(fields["name"]).strip()
    if "description" in fields and fields["description"] is not None:
        ticket_type.description = str(fields["description"]).strip()
    if "is_active" in fields and fields["is_active"] is not None:
        ticket_type.is_active = bool(fields["is_active"])
    prices = {p.audience: p for p in ticket_type.prices}
    if "member_price" in fields and fields["member_price"] is not None:
        if "member" in prices:
            prices["member"].amount = fields["member_price"]
    if "public_price" in fields and fields["public_price"] is not None:
        if "public" in prices:
            prices["public"].amount = fields["public_price"]
    if "member_price_active" in fields and fields["member_price_active"] is not None and "member" in prices:
        prices["member"].is_active = bool(fields["member_price_active"])
    if "public_price_active" in fields and fields["public_price_active"] is not None and "public" in prices:
        prices["public"].is_active = bool(fields["public_price_active"])
    await db.flush()
    return ticket_type


async def create_event_bundle(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    event_fields: dict,
    ticket_types: list[dict],
    publish: bool,
) -> Event:
    """Create event + ticket types in one transaction; optional publish."""
    event = await create_event(db, club_id=club_id, actor_user_id=actor_user_id, **event_fields)
    for tt in ticket_types:
        await upsert_ticket_type(
            db,
            club_id=club_id,
            actor_user_id=actor_user_id,
            event_id=event.id,
            name=tt["name"],
            description=tt.get("description", ""),
            member_price=tt["member_price"],
            public_price=tt["public_price"],
        )
    if publish:
        await set_event_status(
            db, club_id=club_id, actor_user_id=actor_user_id, event_id=event.id, status="published"
        )
    return event


async def check_in_ticket(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    event_id: uuid.UUID,
    qr_token: str | None = None,
    ticket_id: uuid.UUID | None = None,
    override_window: bool = False,
) -> tuple[TicketCheckin, Ticket, bool]:
    """Return (checkin, ticket, duplicate). Same server rules for QR and lookup paths."""
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="check_in")
    event = await db.scalar(select(Event).where(Event.id == event_id, Event.club_id == club_id).with_for_update())
    if event is None:
        raise NotFoundError("Event not found.")
    if event.status == "cancelled":
        raise AppError("Cannot check in for a cancelled event.", code="event_cancelled")

    settings = get_settings()
    now = utcnow()
    window_open = event.starts_at - timedelta(minutes=settings.check_in_open_minutes_before)
    window_close = event.ends_at + timedelta(minutes=settings.check_in_close_minutes_after)
    if now < window_open or now > window_close:
        if not override_window:
            raise AppError(
                "Check-in is outside the configured window.",
                code="check_in_window",
            )
        await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_events")

    if ticket_id is not None:
        ticket = await db.scalar(select(Ticket).where(Ticket.id == ticket_id).with_for_update())
    elif qr_token:
        ticket = await db.scalar(
            select(Ticket).where(Ticket.qr_token_hash == hash_token(qr_token)).with_for_update()
        )
    else:
        raise AppError("Provide a QR token or ticket_id.")
    if ticket is None:
        raise NotFoundError("Ticket not recognized.")
    if ticket.event_id != event_id:
        raise AppError("Ticket does not belong to this event.", code="wrong_event")
    if ticket.club_id != club_id:
        raise AppError("Ticket club mismatch.", code="cross_club_violation")
    # Duplicate detection before status gate so a second scan returns duplicate, not "used".
    existing = await db.scalar(select(TicketCheckin).where(TicketCheckin.ticket_id == ticket.id))
    if existing:
        return existing, ticket, True
    if ticket.status in {"cancelled", "refund_required"}:
        raise AppError(
            f"Ticket is {ticket.status} and cannot be checked in.",
            code="ticket_not_valid",
        )
    if ticket.status != "valid":
        # Includes unexpected states; "used" without a check-in row should not happen.
        raise AppError(f"Ticket is {ticket.status} and cannot be checked in.", code="ticket_not_valid")
    checkin = TicketCheckin(
        ticket_id=ticket.id,
        event_id=event_id,
        checked_in_by_user_id=actor_user_id,
    )
    db.add(checkin)
    ticket.status = "used"
    try:
        await db.flush()
    except IntegrityError as exc:
        existing = await db.scalar(select(TicketCheckin).where(TicketCheckin.ticket_id == ticket.id))
        if existing:
            return existing, ticket, True
        raise ConflictError("Ticket already checked in.", code="duplicate_checkin") from exc
    await record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="ticket.checked_in",
        entity_type="ticket",
        entity_id=ticket.id,
        details={"override_window": override_window, "via": "ticket_id" if ticket_id else "qr"},
    )
    return checkin, ticket, False


async def attendance_report(
    db: AsyncSession, *, club_id: uuid.UUID, actor_user_id: uuid.UUID, event_id: uuid.UUID
) -> dict:
    await require_permission(db, club_id=club_id, user_id=actor_user_id, permission="view_attendance")
    event = await db.get(Event, event_id)
    if event is None or event.club_id != club_id:
        raise NotFoundError("Event not found.")
    issued = await db.scalar(
        select(func.count()).select_from(Ticket).where(
            Ticket.event_id == event_id,
            Ticket.status.in_(["valid", "used", "refund_required"]),
        )
    ) or 0
    checkins = await db.scalar(
        select(func.count()).select_from(TicketCheckin).where(TicketCheckin.event_id == event_id)
    ) or 0
    percentage = round((checkins / issued) * 100, 1) if issued else 0.0
    return {
        "event_id": str(event_id),
        "tickets_issued": int(issued),
        "unique_checkins": int(checkins),
        "attendance_percentage": percentage,
        "denominator": "tickets_issued",
    }


async def get_public_event(db: AsyncSession, *, club_id: uuid.UUID, event_id: uuid.UUID) -> Event:
    event = (
        await db.scalars(
            select(Event)
            .options(joinedload(Event.ticket_types).joinedload(TicketType.prices))
            .where(Event.id == event_id, Event.club_id == club_id, Event.status == "published")
        )
    ).unique().first()
    if event is None:
        raise NotFoundError("Event not found.")
    return event
