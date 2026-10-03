"""Focused PostgreSQL tests for mentor-critical rules."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import RoleCode
from app.core.security import generate_token, hash_token
from app.core.tokens import seal_token
from app.models import (
    Announcement,
    Event,
    Membership,
    MembershipPlan,
    Order,
    OrderItem,
    Ticket,
    TicketPrice,
    TicketType,
)
from app.services.membership_eligibility import utcnow
from app.services.membership_service import compute_entitlement_window
from app.services.purchase_service import confirm_payment, create_ticket_order
from tests.conftest import login


async def test_club_permission_and_cross_club(client: AsyncClient, world, db: AsyncSession):
    headers = await login(client, world["member"].email)
    # Ordinary member cannot manage plans.
    res = await client.post(
        f"/api/v1/clubs/{world['club_a'].id}/plans",
        headers=headers,
        json={
            "name": "X",
            "description": "",
            "dues_amount": "10.00",
            "duration_days": 30,
            "fixed_expires_on": None,
            "is_active": True,
        },
    )
    assert res.status_code == 403

    admin_headers = await login(client, world["admin"].email)
    # Admin of A cannot manage B by swapping club id.
    res = await client.post(
        f"/api/v1/clubs/{world['club_b'].id}/plans",
        headers=admin_headers,
        json={
            "name": "Y",
            "description": "",
            "dues_amount": "10.00",
            "duration_days": 30,
            "fixed_expires_on": None,
            "is_active": True,
        },
    )
    assert res.status_code == 403


async def test_private_order_isolation(client: AsyncClient, world, db: AsyncSession):
    plan = MembershipPlan(
        club_id=world["club_a"].id,
        name="P",
        description="",
        dues_amount=Decimal("100.00"),
        duration_days=30,
        is_active=True,
    )
    db.add(plan)
    await db.flush()
    headers = await login(client, world["member"].email)
    order_res = await client.post(
        f"/api/v1/clubs/{world['club_a'].id}/orders/membership",
        headers=headers,
        json={"plan_id": str(plan.id)},
    )
    assert order_res.status_code == 200
    order_id = order_res.json()["id"]

    other_headers = await login(client, world["other"].email)
    res = await client.get(f"/api/v1/orders/{order_id}", headers=other_headers)
    assert res.status_code == 403


async def test_membership_renewal_dates(db: AsyncSession, world):
    plan = MembershipPlan(
        club_id=world["club_a"].id,
        name="Dur",
        description="",
        dues_amount=Decimal("50"),
        duration_days=10,
        is_active=True,
    )
    db.add(plan)
    await db.flush()
    now = utcnow()
    # Existing active membership ending in 5 days.
    order = Order(
        club_id=world["club_a"].id,
        user_id=world["member"].id,
        status="paid",
        total_amount=Decimal("50"),
        currency="INR",
    )
    db.add(order)
    await db.flush()
    item = OrderItem(
        order_id=order.id,
        item_kind="membership",
        membership_plan_id=plan.id,
        quantity=1,
        unit_price_snapshot=Decimal("50"),
        title_snapshot="Dur",
        duration_days_snapshot=10,
        fixed_expires_on_snapshot=None,
    )
    db.add(item)
    await db.flush()
    current_end = now + timedelta(days=5)
    db.add(
        Membership(
            club_id=world["club_a"].id,
            user_id=world["member"].id,
            plan_id=plan.id,
            order_item_id=item.id,
            starts_at=now - timedelta(days=5),
            ends_at=current_end,
            status="active",
        )
    )
    await db.flush()
    start, end = await compute_entitlement_window(
        db, club_id=world["club_a"].id, user_id=world["member"].id, plan=plan, now=now
    )
    assert start == current_end
    assert end == current_end + timedelta(days=10)


async def test_member_price_requires_membership(db: AsyncSession, world):
    event = Event(
        club_id=world["club_a"].id,
        title="E",
        description="",
        venue="V",
        starts_at=utcnow() + timedelta(days=2),
        ends_at=utcnow() + timedelta(days=2, hours=2),
        capacity=10,
        status="published",
        sales_opens_at=utcnow() - timedelta(hours=1),
        sales_closes_at=utcnow() + timedelta(days=1),
    )
    db.add(event)
    await db.flush()
    tt = TicketType(event_id=event.id, name="GA")
    db.add(tt)
    await db.flush()
    member_price = TicketPrice(ticket_type_id=tt.id, audience="member", amount=Decimal("10"))
    db.add(member_price)
    await db.flush()
    try:
        await create_ticket_order(
            db,
            club_id=world["club_a"].id,
            user_id=world["member"].id,
            ticket_price_id=member_price.id,
        )
        assert False, "expected forbidden"
    except Exception as exc:
        assert "membership" in str(exc).lower() or "Forbidden" in type(exc).__name__


async def test_member_price_pay_issues_ticket(db: AsyncSession, world):
    """Active membership → member ticket price → demo pay → valid ticket."""
    from app.services.purchase_service import create_membership_order

    plan = MembershipPlan(
        club_id=world["club_a"].id,
        name="MemberGate",
        description="",
        dues_amount=Decimal("5"),
        duration_days=30,
        is_active=True,
    )
    db.add(plan)
    await db.flush()
    m_order = await create_membership_order(
        db, club_id=world["club_a"].id, user_id=world["member"].id, plan_id=plan.id
    )
    await confirm_payment(
        db, order_id=m_order.id, actor_user_id=world["member"].id, method="demo", success=True
    )
    mem = await db.scalar(
        select(Membership).where(
            Membership.user_id == world["member"].id,
            Membership.club_id == world["club_a"].id,
            Membership.plan_id == plan.id,
        )
    )
    assert mem is not None and mem.status == "active"

    event = Event(
        club_id=world["club_a"].id,
        title="Member Night",
        description="",
        venue="V",
        starts_at=utcnow() + timedelta(days=2),
        ends_at=utcnow() + timedelta(days=2, hours=2),
        capacity=10,
        status="published",
        sales_opens_at=utcnow() - timedelta(hours=1),
        sales_closes_at=utcnow() + timedelta(days=1),
    )
    db.add(event)
    await db.flush()
    tt = TicketType(event_id=event.id, name="GA")
    db.add(tt)
    await db.flush()
    member_price = TicketPrice(ticket_type_id=tt.id, audience="member", amount=Decimal("10"))
    db.add(member_price)
    await db.flush()

    t_order = await create_ticket_order(
        db,
        club_id=world["club_a"].id,
        user_id=world["member"].id,
        ticket_price_id=member_price.id,
    )
    paid = await confirm_payment(
        db, order_id=t_order.id, actor_user_id=world["member"].id, method="demo", success=True
    )
    assert paid.status == "paid"
    ticket = await db.scalar(select(Ticket).where(Ticket.event_id == event.id, Ticket.user_id == world["member"].id))
    assert ticket is not None and ticket.status == "valid"


async def test_duplicate_payment_confirmation(db: AsyncSession, world):
    plan = MembershipPlan(
        club_id=world["club_a"].id,
        name="P2",
        description="",
        dues_amount=Decimal("20"),
        duration_days=30,
        is_active=True,
    )
    db.add(plan)
    await db.flush()
    from app.services.purchase_service import create_membership_order

    order = await create_membership_order(
        db, club_id=world["club_a"].id, user_id=world["member"].id, plan_id=plan.id
    )
    first = await confirm_payment(
        db, order_id=order.id, actor_user_id=world["member"].id, method="demo", success=True
    )
    second = await confirm_payment(
        db, order_id=order.id, actor_user_id=world["member"].id, method="demo", success=True
    )
    assert first.status == "paid"
    assert second.status == "paid"
    memberships = (
        await db.scalars(
            select(Membership).where(Membership.user_id == world["member"].id, Membership.plan_id == plan.id)
        )
    ).all()
    assert len(memberships) == 1


async def test_duplicate_and_wrong_event_checkin(client: AsyncClient, world, db: AsyncSession):
    # Grant event organizer role to admin already has all perms.
    now = utcnow()
    event = Event(
        club_id=world["club_a"].id,
        title="Check",
        description="",
        venue="V",
        starts_at=now - timedelta(minutes=10),
        ends_at=now + timedelta(hours=2),
        capacity=5,
        status="published",
    )
    other_event = Event(
        club_id=world["club_a"].id,
        title="Other",
        description="",
        venue="V",
        starts_at=now - timedelta(minutes=5),
        ends_at=now + timedelta(hours=3),
        capacity=5,
        status="published",
    )
    db.add_all([event, other_event])
    await db.flush()
    tt = TicketType(event_id=event.id, name="GA")
    db.add(tt)
    await db.flush()
    order = Order(
        club_id=world["club_a"].id,
        user_id=world["member"].id,
        status="paid",
        total_amount=Decimal("1"),
        currency="INR",
    )
    db.add(order)
    await db.flush()
    item = OrderItem(
        order_id=order.id,
        item_kind="ticket",
        quantity=1,
        unit_price_snapshot=Decimal("1"),
        title_snapshot="t",
        ticket_price_id=None,
        membership_plan_id=None,
    )
    # Bypass check by setting kind via temporary: create valid ticket row directly.
    # order_items check requires ticket_price_id for ticket kind — create price.
    price = TicketPrice(ticket_type_id=tt.id, audience="public", amount=Decimal("1"))
    db.add(price)
    await db.flush()
    item.ticket_price_id = price.id
    item.item_kind = "ticket"
    db.add(item)
    await db.flush()
    raw = generate_token(16)
    ticket = Ticket(
        order_item_id=item.id,
        event_id=event.id,
        club_id=world["club_a"].id,
        user_id=world["member"].id,
        ticket_type_id=tt.id,
        status="valid",
        unit_index=0,
        qr_token_hash=hash_token(raw),
        qr_token_sealed=seal_token(raw),
    )
    db.add(ticket)
    await db.flush()

    headers = await login(client, world["admin"].email)
    ok = await client.post(
        f"/api/v1/clubs/{world['club_a'].id}/events/{event.id}/check-in",
        headers=headers,
        json={"qr_token": raw},
    )
    assert ok.status_code == 200
    dup = await client.post(
        f"/api/v1/clubs/{world['club_a'].id}/events/{event.id}/check-in",
        headers=headers,
        json={"qr_token": raw},
    )
    assert dup.status_code == 409
    wrong = await client.post(
        f"/api/v1/clubs/{world['club_a'].id}/events/{other_event.id}/check-in",
        headers=headers,
        json={"qr_token": raw},
    )
    assert wrong.status_code == 400


async def test_member_only_announcement(client: AsyncClient, world, db: AsyncSession):
    ann = Announcement(
        club_id=world["club_a"].id,
        title="Secret",
        body="Members only",
        visibility="members",
        status="published",
        published_at=utcnow(),
        author_user_id=world["admin"].id,
    )
    db.add(ann)
    await db.flush()
    # Anonymous / non-member sees not found.
    res = await client.get(f"/api/v1/clubs/{world['club_a'].id}/announcements/{ann.id}")
    assert res.status_code == 404


async def test_last_admin_protection(client: AsyncClient, world, db: AsyncSession):
    headers = await login(client, world["admin"].email)
    assignments = (
        await client.get(
            f"/api/v1/clubs/{world['club_a'].id}/role-assignments",
            headers=headers,
        )
    ).json()
    admin_assignment = next(a for a in assignments if a["role_code"] == RoleCode.CLUB_ADMIN.value)
    res = await client.post(
        f"/api/v1/clubs/{world['club_a'].id}/role-assignments/{admin_assignment['id']}/end",
        headers=headers,
    )
    assert res.status_code == 409


async def test_handover_changes_permissions(client: AsyncClient, world, db: AsyncSession):
    headers = await login(client, world["admin"].email)
    # Assign event organizer to member.
    assign = await client.post(
        f"/api/v1/clubs/{world['club_a'].id}/role-assignments",
        headers=headers,
        json={
            "user_id": str(world["member"].id),
            "role_code": RoleCode.EVENT_ORGANIZER.value,
        },
    )
    assert assign.status_code == 200
    assignment_id = assign.json()["id"]
    # Handover to other.
    hand = await client.post(
        f"/api/v1/clubs/{world['club_a'].id}/role-assignments/handover",
        headers=headers,
        json={
            "outgoing_assignment_id": assignment_id,
            "incoming_user_id": str(world["other"].id),
        },
    )
    assert hand.status_code == 200
    other_headers = await login(client, world["other"].email)
    me = (await client.get("/api/v1/auth/me", headers=other_headers)).json()
    club = next(c for c in me["clubs"] if c["club"]["id"] == str(world["club_a"].id))
    assert "manage_events" in club["permissions"]
