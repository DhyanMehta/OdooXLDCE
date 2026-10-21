"""Tests for the Club Analytics Dashboard API."""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import RoleCode
from app.core.security import hash_password, hash_token
from app.core.time import utcnow
from app.models import (
    AuditLog,
    Club,
    ClubMember,
    ClubRoleAssignment,
    Event,
    Membership,
    MembershipPlan,
    Order,
    OrderItem,
    Role,
    Ticket,
    TicketCheckin,
    TicketPrice,
    TicketType,
    User,
)
from tests.conftest import TEST_PASSWORD, login

API = "/api/v1"


@pytest.mark.asyncio
async def test_analytics_requires_auth(client: AsyncClient, world: dict):
    club_id = world["club_a"].id
    resp = await client.get(f"{API}/clubs/{club_id}/analytics/dashboard")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_analytics_requires_permission(client: AsyncClient, world: dict):
    # world["member"] has no view_finance permission
    headers = await login(client, world["member"].email)
    club_id = world["club_a"].id
    resp = await client.get(
        f"{API}/clubs/{club_id}/analytics/dashboard", headers=headers
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_analytics_returns_dashboard(client: AsyncClient, world: dict):
    # world["admin"] has CLUB_ADMIN which includes view_finance
    headers = await login(client, world["admin"].email)
    club_id = world["club_a"].id
    resp = await client.get(
        f"{API}/clubs/{club_id}/analytics/dashboard", headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()

    assert "summary" in data
    assert "membership_breakdown" in data
    assert "event_attendance" in data
    assert "revenue_by_type" in data
    assert "recent_activity" in data

    summary = data["summary"]
    assert "total_members" in summary
    assert "active_memberships" in summary
    assert "upcoming_events" in summary
    assert "total_revenue" in summary

    breakdown = data["membership_breakdown"]
    assert "active" in breakdown
    assert "expired" in breakdown
    assert "revoked" in breakdown


@pytest.mark.asyncio
async def test_analytics_empty_club(
    client: AsyncClient, db: AsyncSession, world: dict
):
    now = utcnow()
    # Create fresh club with admin
    fresh_club = Club(
        slug=f"empty-club-{uuid.uuid4().hex[:8]}",
        name="Empty Club",
        description="",
    )
    db.add(fresh_club)
    await db.flush()

    user = User(
        email=f"admin-{uuid.uuid4().hex[:6]}@empty.edu",
        full_name="Fresh Admin",
        password_hash=hash_password(TEST_PASSWORD),
    )
    db.add(user)
    await db.flush()

    db.add(ClubMember(club_id=fresh_club.id, user_id=user.id))
    admin_role = await db.scalar(
        select(Role).where(Role.code == RoleCode.CLUB_ADMIN.value)
    )
    assert admin_role is not None
    db.add(
        ClubRoleAssignment(
            club_id=fresh_club.id,
            user_id=user.id,
            role_id=admin_role.id,
            starts_at=now - timedelta(days=1),
        )
    )
    await db.flush()

    headers = await login(client, user.email)
    resp = await client.get(
        f"{API}/clubs/{fresh_club.id}/analytics/dashboard", headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["summary"]["total_members"] == 1
    assert data["summary"]["active_memberships"] == 0
    assert data["summary"]["upcoming_events"] == 0
    assert Decimal(str(data["summary"]["total_revenue"])) == Decimal("0.00")

    assert data["membership_breakdown"]["active"] == 0
    assert data["membership_breakdown"]["expired"] == 0
    assert data["membership_breakdown"]["revoked"] == 0
    assert data["event_attendance"] == []

    rev_map = {r["item_kind"]: Decimal(str(r["total_amount"])) for r in data["revenue_by_type"]}
    assert rev_map.get("membership") == Decimal("0.00")
    assert rev_map.get("ticket") == Decimal("0.00")
    assert rev_map.get("merchandise") == Decimal("0.00")


@pytest.mark.asyncio
async def test_analytics_counts_correct(
    client: AsyncClient, db: AsyncSession, world: dict
):
    now = utcnow()
    club = world["club_a"]
    admin = world["admin"]
    member = world["member"]

    # 1. Membership Plan & Orders
    plan = MembershipPlan(
        club_id=club.id,
        name=f"Standard Plan {uuid.uuid4().hex[:6]}",
        dues_amount=Decimal("50.00"),
        duration_days=30,
        is_active=True,
    )
    db.add(plan)
    await db.flush()

    # Create paid order with membership item
    order1 = Order(
        club_id=club.id,
        user_id=member.id,
        status="paid",
        total_amount=Decimal("50.00"),
        currency="INR",
    )
    db.add(order1)
    await db.flush()

    order_item1 = OrderItem(
        order_id=order1.id,
        item_kind="membership",
        membership_plan_id=plan.id,
        quantity=1,
        unit_price_snapshot=Decimal("50.00"),
        title_snapshot=plan.name,
        duration_days_snapshot=30,
    )
    db.add(order_item1)
    await db.flush()

    # Active membership
    active_m = Membership(
        club_id=club.id,
        user_id=member.id,
        plan_id=plan.id,
        order_item_id=order_item1.id,
        starts_at=now - timedelta(days=5),
        ends_at=now + timedelta(days=25),
        status="active",
    )
    db.add(active_m)

    # Expired membership (requires another order item)
    order2 = Order(
        club_id=club.id,
        user_id=member.id,
        status="paid",
        total_amount=Decimal("50.00"),
        currency="INR",
    )
    db.add(order2)
    await db.flush()

    order_item2 = OrderItem(
        order_id=order2.id,
        item_kind="membership",
        membership_plan_id=plan.id,
        quantity=1,
        unit_price_snapshot=Decimal("50.00"),
        title_snapshot=plan.name,
        duration_days_snapshot=30,
    )
    db.add(order_item2)
    await db.flush()

    expired_m = Membership(
        club_id=club.id,
        user_id=member.id,
        plan_id=plan.id,
        order_item_id=order_item2.id,
        starts_at=now - timedelta(days=40),
        ends_at=now - timedelta(days=10),
        status="active",
    )
    db.add(expired_m)

    # Revoked membership
    order3 = Order(
        club_id=club.id,
        user_id=member.id,
        status="paid",
        total_amount=Decimal("50.00"),
        currency="INR",
    )
    db.add(order3)
    await db.flush()

    order_item3 = OrderItem(
        order_id=order3.id,
        item_kind="membership",
        membership_plan_id=plan.id,
        quantity=1,
        unit_price_snapshot=Decimal("50.00"),
        title_snapshot=plan.name,
        duration_days_snapshot=30,
    )
    db.add(order_item3)
    await db.flush()

    revoked_m = Membership(
        club_id=club.id,
        user_id=member.id,
        plan_id=plan.id,
        order_item_id=order_item3.id,
        starts_at=now - timedelta(days=10),
        ends_at=now + timedelta(days=20),
        status="revoked",
    )
    db.add(revoked_m)

    # 2. Events & Attendance
    # Event 1: Published upcoming event
    event1 = Event(
        club_id=club.id,
        title="Hackathon 2026",
        description="Coding contest",
        venue="Main Hall",
        starts_at=now + timedelta(days=7),
        ends_at=now + timedelta(days=8),
        capacity=100,
        status="published",
    )
    # Event 2: Draft event (should not be counted in upcoming published)
    event2 = Event(
        club_id=club.id,
        title="Draft Meetup",
        description="Draft",
        venue="Room 101",
        starts_at=now + timedelta(days=2),
        ends_at=now + timedelta(days=3),
        capacity=50,
        status="draft",
    )
    # Event 3: Published recent event with tickets & checkins
    event3 = Event(
        club_id=club.id,
        title="Workshop",
        description="Hands-on",
        venue="Lab B",
        starts_at=now - timedelta(days=1),
        ends_at=now - timedelta(hours=20),
        capacity=50,
        status="published",
    )
    db.add_all([event1, event2, event3])
    await db.flush()

    tt = TicketType(event_id=event3.id, name="General")
    db.add(tt)
    await db.flush()

    tp = TicketPrice(ticket_type_id=tt.id, audience="member", amount=Decimal("100.00"))
    db.add(tp)
    await db.flush()

    # Ticket Order
    ticket_order = Order(
        club_id=club.id,
        user_id=member.id,
        status="paid",
        total_amount=Decimal("200.00"),
        currency="INR",
    )
    db.add(ticket_order)
    await db.flush()

    ticket_item = OrderItem(
        order_id=ticket_order.id,
        item_kind="ticket",
        ticket_price_id=tp.id,
        quantity=2,
        unit_price_snapshot=Decimal("100.00"),
        title_snapshot="Workshop Ticket",
    )
    db.add(ticket_item)
    await db.flush()

    t1 = Ticket(
        order_item_id=ticket_item.id,
        unit_index=0,
        event_id=event3.id,
        club_id=club.id,
        user_id=member.id,
        ticket_type_id=tt.id,
        status="used",
        qr_token_hash=hash_token("qr-1"),
        qr_token_sealed="sealed-1",
    )
    t2 = Ticket(
        order_item_id=ticket_item.id,
        unit_index=1,
        event_id=event3.id,
        club_id=club.id,
        user_id=member.id,
        ticket_type_id=tt.id,
        status="valid",
        qr_token_hash=hash_token("qr-2"),
        qr_token_sealed="sealed-2",
    )
    db.add_all([t1, t2])
    await db.flush()

    # Check in t1
    checkin = TicketCheckin(
        ticket_id=t1.id,
        event_id=event3.id,
        checked_in_by_user_id=admin.id,
    )
    db.add(checkin)

    # 3. Audit Log
    db.add(
        AuditLog(
            club_id=club.id,
            actor_user_id=admin.id,
            action="test.analytics_action",
            entity_type="club",
            entity_id=str(club.id),
        )
    )
    await db.flush()

    # Call endpoint
    headers = await login(client, admin.email)
    resp = await client.get(
        f"{API}/clubs/{club.id}/analytics/dashboard", headers=headers
    )
    assert resp.status_code == 200
    data = resp.json()

    # Assert Summary
    # Total members in club_a (world seeds admin, member, other in club_a -> 3 members)
    assert data["summary"]["total_members"] == 3
    assert data["summary"]["active_memberships"] == 1
    assert data["summary"]["upcoming_events"] == 1  # event1 is published & upcoming

    # Total revenue = order1(50) + order2(50) + order3(50) + ticket_order(200) = 350.00
    assert Decimal(str(data["summary"]["total_revenue"])) == Decimal("350.00")

    # Assert Breakdown
    assert data["membership_breakdown"]["active"] == 1
    assert data["membership_breakdown"]["expired"] == 1
    assert data["membership_breakdown"]["revoked"] == 1

    # Assert Event Attendance
    # event3 should be in event_attendance
    ea_map = {e["title"]: e for e in data["event_attendance"]}
    assert "Workshop" in ea_map
    assert ea_map["Workshop"]["total_tickets"] == 2
    assert ea_map["Workshop"]["checked_in"] == 1
    assert Decimal(str(ea_map["Workshop"]["check_in_rate"])) == Decimal("50.0")

    # Assert Revenue By Type
    rev_map = {r["item_kind"]: Decimal(str(r["total_amount"])) for r in data["revenue_by_type"]}
    assert rev_map["membership"] == Decimal("150.00")
    assert rev_map["ticket"] == Decimal("200.00")
    assert rev_map["merchandise"] == Decimal("0.00")

    # Assert Recent Activity
    actions = [a["action"] for a in data["recent_activity"]]
    assert "test.analytics_action" in actions
    matching = [a for a in data["recent_activity"] if a["action"] == "test.analytics_action"][0]
    assert matching["actor_name"] == admin.full_name
