"""Pure query service for the Club Analytics Dashboard (no writes)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.models import (
    AuditLog,
    ClubMember,
    Event,
    Membership,
    Order,
    OrderItem,
    Ticket,
    TicketCheckin,
    User,
)
from app.schemas.analytics import (
    AnalyticsDashboardOut,
    ClubSummaryOut,
    EventAttendanceOut,
    MembershipBreakdownOut,
    RecentActivityOut,
    RevenueByTypeOut,
)


async def club_summary(db: AsyncSession, club_id: uuid.UUID) -> ClubSummaryOut:
    """Compute top-level summary metrics for a club."""
    now = utcnow()

    # Total members
    total_members = (
        await db.scalar(
            select(func.count(ClubMember.id)).where(ClubMember.club_id == club_id)
        )
    ) or 0

    # Active memberships: active status, started, not expired
    active_memberships = (
        await db.scalar(
            select(func.count(Membership.id)).where(
                Membership.club_id == club_id,
                Membership.status == "active",
                Membership.starts_at <= now,
                Membership.ends_at > now,
            )
        )
    ) or 0

    # Upcoming published events
    upcoming_events = (
        await db.scalar(
            select(func.count(Event.id)).where(
                Event.club_id == club_id,
                Event.status == "published",
                Event.starts_at > now,
            )
        )
    ) or 0

    # Total paid order revenue
    total_revenue = (
        await db.scalar(
            select(func.coalesce(func.sum(Order.total_amount), Decimal("0.00"))).where(
                Order.club_id == club_id,
                Order.status == "paid",
            )
        )
    ) or Decimal("0.00")

    return ClubSummaryOut(
        total_members=int(total_members),
        active_memberships=int(active_memberships),
        upcoming_events=int(upcoming_events),
        total_revenue=Decimal(str(total_revenue)),
    )


async def membership_breakdown(
    db: AsyncSession, club_id: uuid.UUID
) -> MembershipBreakdownOut:
    """Breakdown of club memberships into active, expired, and revoked counts."""
    now = utcnow()
    stmt = select(
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(Membership.status == "active", Membership.ends_at > now),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ),
        func.coalesce(
            func.sum(
                case(
                    (
                        and_(Membership.status == "active", Membership.ends_at <= now),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ),
        func.coalesce(
            func.sum(
                case(
                    (Membership.status == "revoked", 1),
                    else_=0,
                )
            ),
            0,
        ),
    ).where(Membership.club_id == club_id)

    row = (await db.execute(stmt)).one()
    return MembershipBreakdownOut(
        active=int(row[0]),
        expired=int(row[1]),
        revoked=int(row[2]),
    )


async def event_attendance(
    db: AsyncSession, club_id: uuid.UUID, limit: int = 5
) -> list[EventAttendanceOut]:
    """Attendance stats for the last N published events."""
    ticket_sub = (
        select(Ticket.event_id, func.count(Ticket.id).label("total_tickets"))
        .where(
            Ticket.club_id == club_id,
            Ticket.status.in_(["valid", "used", "refund_required"]),
        )
        .group_by(Ticket.event_id)
        .subquery()
    )
    checkin_sub = (
        select(TicketCheckin.event_id, func.count(TicketCheckin.id).label("checked_in"))
        .group_by(TicketCheckin.event_id)
        .subquery()
    )

    stmt = (
        select(
            Event.id,
            Event.title,
            Event.starts_at,
            func.coalesce(ticket_sub.c.total_tickets, 0).label("total_tickets"),
            func.coalesce(checkin_sub.c.checked_in, 0).label("checked_in"),
        )
        .outerjoin(ticket_sub, Event.id == ticket_sub.c.event_id)
        .outerjoin(checkin_sub, Event.id == checkin_sub.c.event_id)
        .where(Event.club_id == club_id, Event.status == "published")
        .order_by(Event.starts_at.desc())
        .limit(limit)
    )

    rows = (await db.execute(stmt)).all()
    results: list[EventAttendanceOut] = []
    for r in rows:
        total = int(r.total_tickets)
        checked = int(r.checked_in)
        rate = (
            Decimal(str(round((checked / total) * 100, 1)))
            if total > 0
            else Decimal("0.0")
        )
        results.append(
            EventAttendanceOut(
                event_id=r.id,
                title=r.title,
                starts_at=r.starts_at,
                total_tickets=total,
                checked_in=checked,
                check_in_rate=rate,
            )
        )
    return results


async def revenue_by_type(
    db: AsyncSession, club_id: uuid.UUID
) -> list[RevenueByTypeOut]:
    """Aggregate paid order items by item_kind (membership, ticket, merchandise)."""
    stmt = (
        select(
            OrderItem.item_kind,
            func.coalesce(
                func.sum(OrderItem.quantity * OrderItem.unit_price_snapshot),
                Decimal("0.00"),
            ),
            func.count(func.distinct(Order.id)),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .where(Order.club_id == club_id, Order.status == "paid")
        .group_by(OrderItem.item_kind)
    )

    rows = (await db.execute(stmt)).all()
    kind_data = {r[0]: (Decimal(str(r[1])), int(r[2])) for r in rows}

    standard_kinds = ["membership", "ticket", "merchandise"]
    results: list[RevenueByTypeOut] = []
    for kind in standard_kinds:
        amount, count = kind_data.pop(kind, (Decimal("0.00"), 0))
        results.append(
            RevenueByTypeOut(
                item_kind=kind,
                total_amount=amount,
                order_count=count,
            )
        )
    for kind, (amount, count) in kind_data.items():
        results.append(
            RevenueByTypeOut(
                item_kind=kind,
                total_amount=amount,
                order_count=count,
            )
        )
    return results


async def recent_activity(
    db: AsyncSession, club_id: uuid.UUID, limit: int = 10
) -> list[RecentActivityOut]:
    """Fetch the latest audit logs with actor display names."""
    stmt = (
        select(
            AuditLog.id,
            AuditLog.action,
            AuditLog.entity_type,
            User.full_name.label("actor_name"),
            AuditLog.created_at,
        )
        .outerjoin(User, AuditLog.actor_user_id == User.id)
        .where(AuditLog.club_id == club_id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
    )

    rows = (await db.execute(stmt)).all()
    return [
        RecentActivityOut(
            id=r.id,
            action=r.action,
            entity_type=r.entity_type,
            actor_name=r.actor_name,
            created_at=r.created_at,
        )
        for r in rows
    ]


async def get_dashboard_data(
    db: AsyncSession, club_id: uuid.UUID
) -> AnalyticsDashboardOut:
    """Composite dashboard retrieval."""
    summary = await club_summary(db, club_id)
    breakdown = await membership_breakdown(db, club_id)
    attendance = await event_attendance(db, club_id)
    revenue = await revenue_by_type(db, club_id)
    activity = await recent_activity(db, club_id)

    return AnalyticsDashboardOut(
        summary=summary,
        membership_breakdown=breakdown,
        event_attendance=attendance,
        revenue_by_type=revenue,
        recent_activity=activity,
    )
