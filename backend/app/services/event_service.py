"""Event lifecycle, attendance, and check-in."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.security import hash_token
from app.models import Event, Order, OrderItem, Ticket, TicketCheckin, TicketPrice, TicketType
from app.services.audit import record_audit
from app.services.purchase_service import count_event_commitments
from app.services.rbac import require_permission


def create_event(
    db: Session,
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
    require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_events")
    if ends_at <= starts_at:
        raise AppError("Event end must be after start.")
    if capacity < 0:
        raise AppError("Capacity cannot be negative.")
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
    db.flush()
    record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="event.created",
        entity_type="event",
        entity_id=event.id,
    )
    return event


def update_event(
    db: Session,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    event_id: uuid.UUID,
    **fields,
) -> Event:
    require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_events")
    event = db.scalar(select(Event).where(Event.id == event_id, Event.club_id == club_id).with_for_update())
    if event is None:
        raise NotFoundError("Event not found.")
    if "capacity" in fields and fields["capacity"] is not None:
        committed = count_event_commitments(db, event_id=event.id)
        if fields["capacity"] < committed:
            raise AppError(
                f"Cannot reduce capacity below existing commitments ({committed}).",
                code="capacity_too_low",
            )
    for key, value in fields.items():
        if value is not None and hasattr(event, key) and key not in {"id", "club_id"}:
            setattr(event, key, value)
    record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="event.updated",
        entity_type="event",
        entity_id=event.id,
    )
    return event


def set_event_status(
    db: Session,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    event_id: uuid.UUID,
    status: str,
) -> Event:
    require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_events")
    if status not in {"draft", "published", "cancelled"}:
        raise AppError("Invalid event status.")
    event = db.get(Event, event_id)
    if event is None or event.club_id != club_id:
        raise NotFoundError("Event not found.")
    event.status = status
    if status == "cancelled":
        # Mark outstanding valid tickets as refund_required; do not silently keep them valid.
        tickets = db.scalars(
            select(Ticket).where(Ticket.event_id == event.id, Ticket.status == "valid")
        ).all()
        for ticket in tickets:
            ticket.status = "refund_required"
        order_ids = {
            item.order_id
            for item in db.scalars(
                select(OrderItem).where(
                    OrderItem.id.in_([t.order_item_id for t in tickets] or [uuid.uuid4()])
                )
            ).all()
        }
        for order_id in order_ids:
            order = db.get(Order, order_id)
            if order and order.status == "paid":
                order.status = "refund_required"
    record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action=f"event.{status}",
        entity_type="event",
        entity_id=event.id,
    )
    return event


def upsert_ticket_type(
    db: Session,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    event_id: uuid.UUID,
    name: str,
    description: str,
    member_price: Decimal,
    public_price: Decimal,
) -> TicketType:
    require_permission(db, club_id=club_id, user_id=actor_user_id, permission="manage_events")
    event = db.get(Event, event_id)
    if event is None or event.club_id != club_id:
        raise NotFoundError("Event not found.")
    ticket_type = TicketType(event_id=event.id, name=name.strip(), description=description.strip())
    db.add(ticket_type)
    db.flush()
    db.add(TicketPrice(ticket_type_id=ticket_type.id, audience="member", amount=member_price))
    db.add(TicketPrice(ticket_type_id=ticket_type.id, audience="public", amount=public_price))
    db.flush()
    return ticket_type


def check_in_ticket(
    db: Session,
    *,
    club_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    event_id: uuid.UUID,
    qr_token: str,
) -> TicketCheckin:
    require_permission(db, club_id=club_id, user_id=actor_user_id, permission="check_in")
    event = db.get(Event, event_id)
    if event is None or event.club_id != club_id:
        raise NotFoundError("Event not found.")
    ticket = db.scalar(select(Ticket).where(Ticket.qr_token_hash == hash_token(qr_token)))
    if ticket is None:
        raise NotFoundError("Ticket not recognized.")
    if ticket.event_id != event_id:
        raise AppError("Ticket does not belong to this event.", code="wrong_event")
    if ticket.status != "valid":
        raise AppError(f"Ticket is {ticket.status} and cannot be checked in.")
    existing = db.scalar(select(TicketCheckin).where(TicketCheckin.ticket_id == ticket.id))
    if existing:
        raise ConflictError("Ticket already checked in.", code="duplicate_checkin")
    checkin = TicketCheckin(
        ticket_id=ticket.id,
        event_id=event_id,
        checked_in_by_user_id=actor_user_id,
    )
    db.add(checkin)
    try:
        db.flush()
    except IntegrityError as exc:
        raise ConflictError("Ticket already checked in.", code="duplicate_checkin") from exc
    record_audit(
        db,
        club_id=club_id,
        actor_user_id=actor_user_id,
        action="ticket.checked_in",
        entity_type="ticket",
        entity_id=ticket.id,
    )
    return checkin


def attendance_report(db: Session, *, club_id: uuid.UUID, actor_user_id: uuid.UUID, event_id: uuid.UUID) -> dict:
    require_permission(db, club_id=club_id, user_id=actor_user_id, permission="view_attendance")
    event = db.get(Event, event_id)
    if event is None or event.club_id != club_id:
        raise NotFoundError("Event not found.")
    issued = db.scalar(
        select(func.count()).select_from(Ticket).where(
            Ticket.event_id == event_id, Ticket.status.in_(["valid", "refund_required"])
        )
    ) or 0
    checkins = db.scalar(
        select(func.count()).select_from(TicketCheckin).where(TicketCheckin.event_id == event_id)
    ) or 0
    # Denominator is tickets issued (valid + refund_required historical issues still tracked).
    percentage = round((checkins / issued) * 100, 1) if issued else 0.0
    return {
        "event_id": str(event_id),
        "tickets_issued": int(issued),
        "unique_checkins": int(checkins),
        "attendance_percentage": percentage,
        "denominator": "tickets_issued",
    }


def get_public_event(db: Session, *, club_id: uuid.UUID, event_id: uuid.UUID) -> Event:
    event = db.scalar(
        select(Event)
        .options(joinedload(Event.ticket_types).joinedload(TicketType.prices))
        .where(Event.id == event_id, Event.club_id == club_id, Event.status == "published")
    )
    if event is None:
        raise NotFoundError("Event not found.")
    return event
