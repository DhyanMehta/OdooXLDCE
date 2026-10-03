"""Focused PostgreSQL tests for mentor-critical rules."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

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


def test_club_permission_and_cross_club(client: TestClient, world, db: Session):
    headers = login(client, world["member"].email)
    # Ordinary member cannot manage plans.
    res = client.post(
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

    admin_headers = login(client, world["admin"].email)
    # Admin of A cannot manage B by swapping club id.
    res = client.post(
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


def test_private_order_isolation(client: TestClient, world, db: Session):
    plan = MembershipPlan(
        club_id=world["club_a"].id,
        name="P",
        description="",
        dues_amount=Decimal("100.00"),
        duration_days=30,
        is_active=True,
    )
    db.add(plan)
    db.flush()
    headers = login(client, world["member"].email)
    order_res = client.post(
        f"/api/v1/clubs/{world['club_a'].id}/orders/membership",
        headers=headers,
        json={"plan_id": str(plan.id)},
    )
    assert order_res.status_code == 200
    order_id = order_res.json()["id"]

    other_headers = login(client, world["other"].email)
    res = client.get(f"/api/v1/orders/{order_id}", headers=other_headers)
    assert res.status_code == 403


def test_membership_renewal_dates(db: Session, world):
    plan = MembershipPlan(
        club_id=world["club_a"].id,
        name="Dur",
        description="",
        dues_amount=Decimal("50"),
        duration_days=10,
        is_active=True,
    )
    db.add(plan)
    db.flush()
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
    db.flush()
    item = OrderItem(
        order_id=order.id,
        item_kind="membership",
        membership_plan_id=plan.id,
        quantity=1,
        unit_price_snapshot=Decimal("50"),
        title_snapshot="Dur",
    )
    db.add(item)
    db.flush()
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
    db.flush()
    start, end = compute_entitlement_window(
        db, club_id=world["club_a"].id, user_id=world["member"].id, plan=plan, now=now
    )
    assert start == current_end
    assert end == current_end + timedelta(days=10)


def test_member_price_requires_membership(db: Session, world):
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
    db.flush()
    tt = TicketType(event_id=event.id, name="GA")
    db.add(tt)
    db.flush()
    member_price = TicketPrice(ticket_type_id=tt.id, audience="member", amount=Decimal("10"))
    db.add(member_price)
    db.flush()
    try:
        create_ticket_order(
            db,
            club_id=world["club_a"].id,
            user_id=world["member"].id,
            ticket_price_id=member_price.id,
        )
        assert False, "expected forbidden"
    except Exception as exc:
        assert "membership" in str(exc).lower() or "Forbidden" in type(exc).__name__


def test_duplicate_payment_confirmation(db: Session, world):
    plan = MembershipPlan(
        club_id=world["club_a"].id,
        name="P2",
        description="",
        dues_amount=Decimal("20"),
        duration_days=30,
        is_active=True,
    )
    db.add(plan)
    db.flush()
    from app.services.purchase_service import create_membership_order

    order = create_membership_order(
        db, club_id=world["club_a"].id, user_id=world["member"].id, plan_id=plan.id
    )
    first = confirm_payment(
        db, order_id=order.id, actor_user_id=world["member"].id, method="demo", success=True
    )
    second = confirm_payment(
        db, order_id=order.id, actor_user_id=world["member"].id, method="demo", success=True
    )
    assert first.status == "paid"
    assert second.status == "paid"
    memberships = db.scalars(
        select(Membership).where(Membership.user_id == world["member"].id, Membership.plan_id == plan.id)
    ).all()
    assert len(memberships) == 1


def test_duplicate_and_wrong_event_checkin(client: TestClient, world, db: Session):
    # Grant event organizer role to admin already has all perms.
    event = Event(
        club_id=world["club_a"].id,
        title="Check",
        description="",
        venue="V",
        starts_at=utcnow() + timedelta(days=1),
        ends_at=utcnow() + timedelta(days=1, hours=1),
        capacity=5,
        status="published",
    )
    other_event = Event(
        club_id=world["club_a"].id,
        title="Other",
        description="",
        venue="V",
        starts_at=utcnow() + timedelta(days=2),
        ends_at=utcnow() + timedelta(days=2, hours=1),
        capacity=5,
        status="published",
    )
    db.add_all([event, other_event])
    db.flush()
    tt = TicketType(event_id=event.id, name="GA")
    db.add(tt)
    db.flush()
    order = Order(
        club_id=world["club_a"].id,
        user_id=world["member"].id,
        status="paid",
        total_amount=Decimal("1"),
        currency="INR",
    )
    db.add(order)
    db.flush()
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
    db.flush()
    item.ticket_price_id = price.id
    item.item_kind = "ticket"
    db.add(item)
    db.flush()
    raw = generate_token(16)
    ticket = Ticket(
        order_item_id=item.id,
        event_id=event.id,
        club_id=world["club_a"].id,
        user_id=world["member"].id,
        ticket_type_id=tt.id,
        status="valid",
        qr_token_hash=hash_token(raw),
        qr_token_sealed=seal_token(raw),
    )
    db.add(ticket)
    db.flush()

    headers = login(client, world["admin"].email)
    ok = client.post(
        f"/api/v1/clubs/{world['club_a'].id}/events/{event.id}/check-in",
        headers=headers,
        json={"qr_token": raw},
    )
    assert ok.status_code == 200
    dup = client.post(
        f"/api/v1/clubs/{world['club_a'].id}/events/{event.id}/check-in",
        headers=headers,
        json={"qr_token": raw},
    )
    assert dup.status_code == 409
    wrong = client.post(
        f"/api/v1/clubs/{world['club_a'].id}/events/{other_event.id}/check-in",
        headers=headers,
        json={"qr_token": raw},
    )
    assert wrong.status_code == 400


def test_member_only_announcement(client: TestClient, world, db: Session):
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
    db.flush()
    # Anonymous / non-member sees not found.
    res = client.get(f"/api/v1/clubs/{world['club_a'].id}/announcements/{ann.id}")
    assert res.status_code == 404


def test_last_admin_protection(client: TestClient, world, db: Session):
    headers = login(client, world["admin"].email)
    assignments = client.get(
        f"/api/v1/clubs/{world['club_a'].id}/role-assignments",
        headers=headers,
    ).json()
    admin_assignment = next(a for a in assignments if a["role_code"] == RoleCode.CLUB_ADMIN.value)
    res = client.post(
        f"/api/v1/clubs/{world['club_a'].id}/role-assignments/{admin_assignment['id']}/end",
        headers=headers,
    )
    assert res.status_code == 409


def test_handover_changes_permissions(client: TestClient, world, db: Session):
    headers = login(client, world["admin"].email)
    # Assign event organizer to member.
    assign = client.post(
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
    hand = client.post(
        f"/api/v1/clubs/{world['club_a'].id}/role-assignments/handover",
        headers=headers,
        json={
            "outgoing_assignment_id": assignment_id,
            "incoming_user_id": str(world["other"].id),
        },
    )
    assert hand.status_code == 200
    other_headers = login(client, world["other"].email)
    me = client.get("/api/v1/auth/me", headers=other_headers).json()
    club = next(c for c in me["clubs"] if c["club"]["id"] == str(world["club_a"].id))
    assert "manage_events" in club["permissions"]
