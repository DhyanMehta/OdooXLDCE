from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.errors import ForbiddenError, NotFoundError
from app.core.tokens import unseal_token
from app.db.session import get_db
from app.dependencies.auth import AuthContext, get_club, get_current_auth, get_optional_auth, require_csrf
from app.models import Club, Event, Ticket, TicketCheckin, TicketType, User
from app.schemas.events import (
    AffectedBookingOut,
    AttendanceOut,
    AttendeeTicketOut,
    CheckInIn,
    CheckInListItem,
    CheckInOut,
    EventCreateIn,
    EventIn,
    EventOut,
    EventStatusIn,
    EventStatusOut,
    TicketOut,
    TicketTypeIn,
    TicketTypeOut,
    TicketTypePatch,
)
from app.services.event_service import (
    attendance_report,
    check_in_ticket,
    create_event_bundle,
    set_event_status,
    update_event,
    update_ticket_type,
    upsert_ticket_type,
)
from app.services.purchase_service import count_event_commitments
from app.services.rbac import require_permission

router = APIRouter(tags=["events"])


async def _event_out(db: AsyncSession, event: Event) -> EventOut:
    remaining = max(event.capacity - await count_event_commitments(db, event_id=event.id), 0)
    data = EventOut.model_validate(event)
    data.seats_remaining = remaining
    return data


async def _can_manage_events(db: AsyncSession, club_id: uuid.UUID, auth: AuthContext | None) -> bool:
    if auth is None:
        return False
    try:
        await require_permission(db, club_id=club_id, user_id=auth.user.id, permission="manage_events")
        return True
    except ForbiddenError:
        return False


@router.get("/clubs/{club_id}/events", response_model=list[EventOut])
async def list_events(
    club: Club = Depends(get_club),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext | None = Depends(get_optional_auth),
) -> list[EventOut]:
    stmt = (
        select(Event)
        .options(joinedload(Event.ticket_types).joinedload(TicketType.prices))
        .where(Event.club_id == club.id)
        .order_by(Event.starts_at.asc())
    )
    if not await _can_manage_events(db, club.id, auth):
        stmt = stmt.where(Event.status == "published")
    events = (await db.scalars(stmt)).unique().all()
    return [await _event_out(db, e) for e in events]


@router.get("/clubs/{club_id}/events/{event_id}", response_model=EventOut)
async def get_event(
    event_id: uuid.UUID,
    club: Club = Depends(get_club),
    db: AsyncSession = Depends(get_db),
    auth: AuthContext | None = Depends(get_optional_auth),
) -> EventOut:
    event = (
        await db.scalars(
            select(Event)
            .options(joinedload(Event.ticket_types).joinedload(TicketType.prices))
            .where(Event.id == event_id, Event.club_id == club.id)
        )
    ).unique().first()
    if event is None:
        raise NotFoundError("Event not found.")
    if event.status != "published" and not await _can_manage_events(db, club.id, auth):
        raise NotFoundError("Event not found.")
    return await _event_out(db, event)


@router.post("/clubs/{club_id}/events", response_model=EventOut)
async def create_event_endpoint(
    payload: EventCreateIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> EventOut:
    data = payload.model_dump()
    ticket_types = data.pop("ticket_types")
    publish = data.pop("publish")
    event = await create_event_bundle(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        event_fields=data,
        ticket_types=ticket_types,
        publish=bool(publish),
    )
    await db.commit()
    loaded = (
        await db.scalars(
            select(Event)
            .options(joinedload(Event.ticket_types).joinedload(TicketType.prices))
            .where(Event.id == event.id)
        )
    ).unique().first()
    assert loaded is not None
    return await _event_out(db, loaded)


@router.patch("/clubs/{club_id}/events/{event_id}", response_model=EventOut)
async def patch_event(
    event_id: uuid.UUID,
    payload: EventIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> EventOut:
    event = await update_event(
        db, club_id=club.id, actor_user_id=auth.user.id, event_id=event_id, **payload.model_dump()
    )
    await db.commit()
    loaded = (
        await db.scalars(
            select(Event)
            .options(joinedload(Event.ticket_types).joinedload(TicketType.prices))
            .where(Event.id == event.id)
        )
    ).unique().first()
    assert loaded is not None
    return await _event_out(db, loaded)


@router.post("/clubs/{club_id}/events/{event_id}/status", response_model=EventStatusOut)
async def change_status(
    event_id: uuid.UUID,
    payload: EventStatusIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> EventStatusOut:
    impact = await set_event_status(
        db, club_id=club.id, actor_user_id=auth.user.id, event_id=event_id, status=payload.status
    )
    await db.commit()
    loaded = (
        await db.scalars(
            select(Event)
            .options(joinedload(Event.ticket_types).joinedload(TicketType.prices))
            .where(Event.id == impact.event.id)
        )
    ).unique().first()
    assert loaded is not None
    return EventStatusOut(
        event=await _event_out(db, loaded),
        affected_bookings=[AffectedBookingOut(**row) for row in impact.affected],
    )


@router.post("/clubs/{club_id}/events/{event_id}/ticket-types", response_model=TicketTypeOut)
async def add_ticket_type(
    event_id: uuid.UUID,
    payload: TicketTypeIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> TicketType:
    tt = await upsert_ticket_type(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        event_id=event_id,
        name=payload.name,
        description=payload.description,
        member_price=payload.member_price,
        public_price=payload.public_price,
    )
    await db.commit()
    loaded = (
        await db.scalars(
            select(TicketType).options(joinedload(TicketType.prices)).where(TicketType.id == tt.id)
        )
    ).unique().first()
    assert loaded is not None
    return loaded


@router.patch(
    "/clubs/{club_id}/events/{event_id}/ticket-types/{ticket_type_id}",
    response_model=TicketTypeOut,
)
async def patch_ticket_type(
    event_id: uuid.UUID,
    ticket_type_id: uuid.UUID,
    payload: TicketTypePatch,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> TicketType:
    tt = await update_ticket_type(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        event_id=event_id,
        ticket_type_id=ticket_type_id,
        fields=payload.model_dump(exclude_unset=True),
    )
    await db.commit()
    loaded = (
        await db.scalars(
            select(TicketType).options(joinedload(TicketType.prices)).where(TicketType.id == tt.id)
        )
    ).unique().first()
    assert loaded is not None
    return loaded


async def _build_checkin_out(
    db: AsyncSession,
    *,
    checkin: TicketCheckin,
    ticket: Ticket,
    duplicate: bool,
) -> CheckInOut:
    user = await db.get(User, ticket.user_id)
    actor = await db.get(User, checkin.checked_in_by_user_id) if checkin.checked_in_by_user_id else None
    tt = await db.get(TicketType, ticket.ticket_type_id)
    return CheckInOut(
        status="duplicate" if duplicate else "checked_in",
        duplicate=duplicate,
        ticket_id=ticket.id,
        event_id=ticket.event_id,
        attendee_name=user.full_name if user else None,
        attendee_email=user.email if user else None,
        ticket_type_name=tt.name if tt else None,
        ticket_status=ticket.status,
        checked_in_at=checkin.checked_in_at,
        checked_in_by_name=actor.full_name if actor else None,
        original_checked_in_at=checkin.checked_in_at if duplicate else None,
    )


@router.post(
    "/clubs/{club_id}/events/{event_id}/check-in",
    response_model=None,
    responses={
        200: {"model": CheckInOut, "description": "First successful check-in"},
        409: {"model": CheckInOut, "description": "Duplicate check-in (same JSON body)"},
    },
)
async def check_in(
    event_id: uuid.UUID,
    payload: CheckInIn,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
):
    checkin, ticket, duplicate = await check_in_ticket(
        db,
        club_id=club.id,
        actor_user_id=auth.user.id,
        event_id=event_id,
        qr_token=payload.qr_token if not payload.ticket_id else None,
        ticket_id=payload.ticket_id,
        override_window=payload.override_window,
    )
    await db.commit()
    await db.refresh(checkin)
    out = await _build_checkin_out(db, checkin=checkin, ticket=ticket, duplicate=duplicate)
    if duplicate:
        return JSONResponse(status_code=409, content=out.model_dump(mode="json"))
    return out


@router.get("/clubs/{club_id}/events/{event_id}/check-ins", response_model=list[CheckInListItem])
async def list_check_ins(
    event_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=30, ge=1, le=100),
) -> list[CheckInListItem]:
    await require_permission(db, club_id=club.id, user_id=auth.user.id, permission="check_in")
    event = await db.get(Event, event_id)
    if event is None or event.club_id != club.id:
        raise NotFoundError("Event not found.")
    rows = (
        await db.scalars(
            select(TicketCheckin)
            .where(TicketCheckin.event_id == event_id)
            .order_by(TicketCheckin.checked_in_at.desc())
            .limit(limit)
        )
    ).all()
    out: list[CheckInListItem] = []
    for row in rows:
        ticket = await db.get(Ticket, row.ticket_id)
        user = await db.get(User, ticket.user_id) if ticket else None
        actor = await db.get(User, row.checked_in_by_user_id) if row.checked_in_by_user_id else None
        tt = await db.get(TicketType, ticket.ticket_type_id) if ticket else None
        out.append(
            CheckInListItem(
                id=row.id,
                ticket_id=row.ticket_id,
                attendee_name=user.full_name if user else None,
                attendee_email=user.email if user else None,
                ticket_type_name=tt.name if tt else None,
                checked_in_at=row.checked_in_at,
                checked_in_by_name=actor.full_name if actor else None,
            )
        )
    return out


@router.get("/clubs/{club_id}/events/{event_id}/attendees", response_model=list[AttendeeTicketOut])
async def lookup_attendees(
    event_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
    q: str = Query(min_length=1, max_length=120),
) -> list[AttendeeTicketOut]:
    """Name/email lookup returns concrete tickets — a name alone never admits."""
    await require_permission(db, club_id=club.id, user_id=auth.user.id, permission="check_in")
    event = await db.get(Event, event_id)
    if event is None or event.club_id != club.id:
        raise NotFoundError("Event not found.")
    term = f"%{q.strip()}%"
    tickets = (
        await db.scalars(
            select(Ticket)
            .join(User, User.id == Ticket.user_id)
            .where(
                Ticket.event_id == event_id,
                Ticket.club_id == club.id,
                or_(User.full_name.ilike(term), User.email.ilike(term)),
            )
            .order_by(User.full_name)
            .limit(25)
        )
    ).all()
    out: list[AttendeeTicketOut] = []
    for ticket in tickets:
        user = await db.get(User, ticket.user_id)
        tt = await db.get(TicketType, ticket.ticket_type_id)
        checkin = await db.scalar(select(TicketCheckin).where(TicketCheckin.ticket_id == ticket.id))
        out.append(
            AttendeeTicketOut(
                ticket_id=ticket.id,
                user_id=ticket.user_id,
                attendee_name=user.full_name if user else "",
                attendee_email=user.email if user else "",
                ticket_type_name=tt.name if tt else "",
                ticket_status=ticket.status,
                checked_in=checkin is not None,
                checked_in_at=checkin.checked_in_at if checkin else None,
            )
        )
    return out


@router.get("/clubs/{club_id}/events/{event_id}/attendance", response_model=AttendanceOut)
async def attendance(
    event_id: uuid.UUID,
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> AttendanceOut:
    data = await attendance_report(
        db, club_id=club.id, actor_user_id=auth.user.id, event_id=event_id
    )
    return AttendanceOut(**data)


@router.get("/me/tickets", response_model=list[TicketOut])
async def my_tickets(
    auth: AuthContext = Depends(get_current_auth),
    db: AsyncSession = Depends(get_db),
) -> list[TicketOut]:
    tickets = (
        await db.scalars(
            select(Ticket).where(Ticket.user_id == auth.user.id).order_by(Ticket.issued_at.desc())
        )
    ).all()
    out: list[TicketOut] = []
    for ticket in tickets:
        event = await db.get(Event, ticket.event_id)
        item = TicketOut.model_validate(ticket)
        item.qr_token = unseal_token(ticket.qr_token_sealed)
        item.event_title = event.title if event else None
        out.append(item)
    return out
