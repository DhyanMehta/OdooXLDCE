from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.errors import ForbiddenError, NotFoundError
from app.core.tokens import unseal_token
from app.db.session import get_db
from app.dependencies.auth import AuthContext, get_club, get_current_auth, get_optional_auth, require_csrf
from app.models import Club, Event, Ticket, TicketType
from app.schemas.events import (
    CheckInIn,
    EventIn,
    EventOut,
    EventStatusIn,
    TicketOut,
    TicketTypeIn,
    TicketTypeOut,
)
from app.services.event_service import (
    attendance_report,
    check_in_ticket,
    create_event,
    set_event_status,
    update_event,
    upsert_ticket_type,
)
from app.services.purchase_service import count_event_commitments
from app.services.rbac import require_permission

router = APIRouter(tags=["events"])


def _event_out(db: Session, event: Event) -> EventOut:
    remaining = max(event.capacity - count_event_commitments(db, event_id=event.id), 0)
    data = EventOut.model_validate(event)
    data.seats_remaining = remaining
    return data


@router.get("/clubs/{club_id}/events", response_model=list[EventOut])
def list_events(
    club: Club = Depends(get_club),
    db: Session = Depends(get_db),
    auth: AuthContext | None = Depends(get_optional_auth),
) -> list[EventOut]:
    stmt = (
        select(Event)
        .options(joinedload(Event.ticket_types).joinedload(TicketType.prices))
        .where(Event.club_id == club.id)
        .order_by(Event.starts_at.asc())
    )
    can_manage = False
    if auth:
        try:
            require_permission(db, club_id=club.id, user_id=auth.user.id, permission="manage_events")
            can_manage = True
        except ForbiddenError:
            can_manage = False
    if not can_manage:
        stmt = stmt.where(Event.status == "published")
    events = db.scalars(stmt).unique().all()
    return [_event_out(db, e) for e in events]


@router.get("/clubs/{club_id}/events/{event_id}", response_model=EventOut)
def get_event(
    event_id: uuid.UUID,
    club: Club = Depends(get_club),
    db: Session = Depends(get_db),
) -> EventOut:
    event = db.scalar(
        select(Event)
        .options(joinedload(Event.ticket_types).joinedload(TicketType.prices))
        .where(Event.id == event_id, Event.club_id == club.id)
    )
    if event is None or event.status == "draft":
        # Public detail hides drafts.
        if event is None or event.status != "published":
            raise NotFoundError("Event not found.")
    return _event_out(db, event)


@router.post("/clubs/{club_id}/events", response_model=EventOut)
def create_event_endpoint(
    payload: EventIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> EventOut:
    event = create_event(db, club_id=club.id, actor_user_id=auth.user.id, **payload.model_dump())
    db.commit()
    event = db.scalar(
        select(Event)
        .options(joinedload(Event.ticket_types).joinedload(TicketType.prices))
        .where(Event.id == event.id)
    )
    assert event is not None
    return _event_out(db, event)


@router.patch("/clubs/{club_id}/events/{event_id}", response_model=EventOut)
def patch_event(
    event_id: uuid.UUID,
    payload: EventIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> EventOut:
    event = update_event(
        db, club_id=club.id, actor_user_id=auth.user.id, event_id=event_id, **payload.model_dump()
    )
    db.commit()
    loaded = db.scalar(
        select(Event)
        .options(joinedload(Event.ticket_types).joinedload(TicketType.prices))
        .where(Event.id == event.id)
    )
    assert loaded is not None
    return _event_out(db, loaded)


@router.post("/clubs/{club_id}/events/{event_id}/status", response_model=EventOut)
def change_status(
    event_id: uuid.UUID,
    payload: EventStatusIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> EventOut:
    event = set_event_status(
        db, club_id=club.id, actor_user_id=auth.user.id, event_id=event_id, status=payload.status
    )
    db.commit()
    loaded = db.scalar(
        select(Event)
        .options(joinedload(Event.ticket_types).joinedload(TicketType.prices))
        .where(Event.id == event.id)
    )
    assert loaded is not None
    return _event_out(db, loaded)


@router.post("/clubs/{club_id}/events/{event_id}/ticket-types", response_model=TicketTypeOut)
def add_ticket_type(
    event_id: uuid.UUID,
    payload: TicketTypeIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> TicketType:
    tt = upsert_ticket_type(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        event_id=event_id,
        name=payload.name,
        description=payload.description,
        member_price=payload.member_price,
        public_price=payload.public_price,
    )
    db.commit()
    return db.scalar(
        select(TicketType).options(joinedload(TicketType.prices)).where(TicketType.id == tt.id)
    )


@router.post("/clubs/{club_id}/events/{event_id}/check-in")
def check_in(
    event_id: uuid.UUID,
    payload: CheckInIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    checkin = check_in_ticket(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        event_id=event_id,
        qr_token=payload.qr_token,
    )
    db.commit()
    return {"status": "checked_in", "ticket_id": str(checkin.ticket_id)}


@router.get("/clubs/{club_id}/events/{event_id}/attendance")
def attendance(
    event_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: Session = Depends(get_db),
) -> dict:
    report = attendance_report(
        db, club_id=club.id, actor_user_id=auth.user.id, event_id=event_id
    )
    return report


@router.get("/me/tickets", response_model=list[TicketOut])
def my_tickets(
    auth: AuthContext = Depends(get_current_auth),
    db: Session = Depends(get_db),
) -> list[TicketOut]:
    tickets = db.scalars(
        select(Ticket).where(Ticket.user_id == auth.user.id).order_by(Ticket.issued_at.desc())
    ).all()
    out: list[TicketOut] = []
    for ticket in tickets:
        event = db.get(Event, ticket.event_id)
        item = TicketOut.model_validate(ticket)
        item.qr_token = unseal_token(ticket.qr_token_sealed)
        item.event_title = event.title if event else None
        out.append(item)
    return out
