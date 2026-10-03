"""PostgreSQL-backed integrity, payment, booking, and membership tests."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import generate_token, hash_token
from app.core.tokens import seal_token, unseal_token
from app.models import (
    Club,
    ClubMember,
    Event,
    Membership,
    MembershipPlan,
    Order,
    OrderItem,
    Payment,
    PaymentEvent,
    Role,
    Ticket,
    TicketCheckin,
    TicketPrice,
    TicketType,
    User,
)
from app.services.event_service import check_in_ticket, set_event_status
from app.services.membership_eligibility import (
    continuous_entitlement_chain_end,
    effective_membership_state,
    fixed_period_exclusive_end,
    utcnow,
)
from app.services.membership_service import compute_entitlement_window, update_plan
from app.services.purchase_service import (
    cancel_pending_order,
    confirm_payment,
    create_membership_order,
    create_ticket_order,
)
from tests.conftest import TEST_PASSWORD, login, resolve_test_database_url


async def _public_price(
    db: AsyncSession, *, club_id, capacity: int = 2, title: str | None = None
) -> tuple[Event, TicketPrice]:
    now = utcnow()
    event = Event(
        club_id=club_id,
        title=title or f"E-{uuid.uuid4().hex[:6]}",
        description="",
        venue="V",
        starts_at=now + timedelta(days=2),
        ends_at=now + timedelta(days=2, hours=2),
        capacity=capacity,
        status="published",
        sales_opens_at=now - timedelta(hours=1),
        sales_closes_at=now + timedelta(days=1),
    )
    db.add(event)
    await db.flush()
    tt = TicketType(event_id=event.id, name="GA", is_active=True)
    db.add(tt)
    await db.flush()
    price = TicketPrice(ticket_type_id=tt.id, audience="public", amount=Decimal("25.00"), is_active=True)
    db.add(price)
    await db.flush()
    return event, price


async def _cleanup_race_artifacts(
    engine: AsyncEngine, *, club_id: uuid.UUID, user_ids: list[uuid.UUID]
) -> None:
    """Remove concurrency-test rows only; never touch ordinary fixture/app data."""
    async with AsyncSession(engine, expire_on_commit=False, autoflush=False) as db:
        event_ids = (
            await db.scalars(select(Event.id).where(Event.club_id == club_id))
        ).all()
        if event_ids:
            ticket_ids = (
                await db.scalars(select(Ticket.id).where(Ticket.event_id.in_(event_ids)))
            ).all()
            if ticket_ids:
                await db.execute(delete(TicketCheckin).where(TicketCheckin.ticket_id.in_(ticket_ids)))
            await db.execute(delete(Ticket).where(Ticket.event_id.in_(event_ids)))
            price_ids = (
                await db.scalars(
                    select(TicketPrice.id).where(
                        TicketPrice.ticket_type_id.in_(
                            select(TicketType.id).where(TicketType.event_id.in_(event_ids))
                        )
                    )
                )
            ).all()
            order_ids = (
                await db.scalars(select(Order.id).where(Order.club_id == club_id))
            ).all()
            if order_ids:
                item_ids = (
                    await db.scalars(select(OrderItem.id).where(OrderItem.order_id.in_(order_ids)))
                ).all()
                if item_ids:
                    await db.execute(delete(Membership).where(Membership.order_item_id.in_(item_ids)))
                    await db.execute(delete(OrderItem).where(OrderItem.id.in_(item_ids)))
                pay_ids = (
                    await db.scalars(select(Payment.id).where(Payment.order_id.in_(order_ids)))
                ).all()
                if pay_ids:
                    await db.execute(delete(PaymentEvent).where(PaymentEvent.payment_id.in_(pay_ids)))
                    await db.execute(delete(Payment).where(Payment.id.in_(pay_ids)))
                await db.execute(delete(Order).where(Order.id.in_(order_ids)))
            if price_ids:
                await db.execute(delete(TicketPrice).where(TicketPrice.id.in_(price_ids)))
            await db.execute(delete(TicketType).where(TicketType.event_id.in_(event_ids)))
            await db.execute(delete(Event).where(Event.id.in_(event_ids)))

        order_ids = (await db.scalars(select(Order.id).where(Order.club_id == club_id))).all()
        if order_ids:
            item_ids = (
                await db.scalars(select(OrderItem.id).where(OrderItem.order_id.in_(order_ids)))
            ).all()
            if item_ids:
                await db.execute(delete(Membership).where(Membership.order_item_id.in_(item_ids)))
                await db.execute(delete(OrderItem).where(OrderItem.id.in_(item_ids)))
            pay_ids = (
                await db.scalars(select(Payment.id).where(Payment.order_id.in_(order_ids)))
            ).all()
            if pay_ids:
                await db.execute(delete(PaymentEvent).where(PaymentEvent.payment_id.in_(pay_ids)))
                await db.execute(delete(Payment).where(Payment.id.in_(pay_ids)))
            await db.execute(delete(Order).where(Order.id.in_(order_ids)))

        await db.execute(delete(Membership).where(Membership.club_id == club_id))
        await db.execute(delete(MembershipPlan).where(MembershipPlan.club_id == club_id))
        await db.execute(
            text(
                "DELETE FROM journal_lines WHERE entry_id IN "
                "(SELECT id FROM journal_entries WHERE club_id = :c)"
            ),
            {"c": club_id},
        )
        await db.execute(text("DELETE FROM journal_entries WHERE club_id = :c"), {"c": club_id})
        await db.execute(text("DELETE FROM accounts WHERE club_id = :c"), {"c": club_id})
        await db.execute(text("DELETE FROM refunds WHERE club_id = :c"), {"c": club_id})
        await db.execute(delete(ClubMember).where(ClubMember.club_id == club_id))
        await db.execute(text("DELETE FROM club_role_assignments WHERE club_id = :c"), {"c": club_id})
        await db.execute(delete(Club).where(Club.id == club_id))
        if user_ids:
            await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()


async def test_paid_order_ownership_bypass(client: AsyncClient, world, db: AsyncSession):
    plan = MembershipPlan(
        club_id=world["club_a"].id,
        name="Own",
        description="",
        dues_amount=Decimal("10"),
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
    assert order_res.status_code == 200, order_res.text
    order_id = order_res.json()["id"]
    assert (
        (
            await client.post(
                f"/api/v1/orders/{order_id}/pay/demo", headers=headers, json={"success": True}
            )
        ).status_code
        == 200
    )

    other_headers = await login(client, world["other"].email)
    bypass = await client.post(
        f"/api/v1/orders/{order_id}/pay/demo",
        headers=other_headers,
        json={"success": True},
    )
    assert bypass.status_code == 403


async def test_success_failure_ordering(db: AsyncSession, world):
    plan = MembershipPlan(
        club_id=world["club_a"].id,
        name="SF",
        description="",
        dues_amount=Decimal("15"),
        duration_days=30,
        is_active=True,
    )
    db.add(plan)
    await db.flush()
    order = await create_membership_order(
        db, club_id=world["club_a"].id, user_id=world["member"].id, plan_id=plan.id
    )
    paid = await confirm_payment(
        db, order_id=order.id, actor_user_id=world["member"].id, method="demo", success=True
    )
    assert paid.status == "paid"
    # Late failure must not regress a confirmed payment.
    after = await confirm_payment(
        db, order_id=order.id, actor_user_id=world["member"].id, method="demo", success=False
    )
    assert after.status == "paid"
    payment = await db.scalar(select(Payment).where(Payment.order_id == order.id))
    assert payment is not None
    assert payment.status == "confirmed"


async def test_cancellation_followed_by_payment(db: AsyncSession, world):
    event, price = await _public_price(db, club_id=world["club_a"].id, capacity=5)
    order = await create_ticket_order(
        db,
        club_id=world["club_a"].id,
        user_id=world["member"].id,
        ticket_price_id=price.id,
    )
    await cancel_pending_order(db, order_id=order.id, actor_user_id=world["member"].id)
    with pytest.raises(AppError) as exc:
        await confirm_payment(
            db, order_id=order.id, actor_user_id=world["member"].id, method="demo", success=True
        )
    assert getattr(exc.value, "code", None) == "order_cancelled"
    assert (await db.scalar(select(Order).where(Order.id == order.id))).status == "cancelled"


async def test_late_successful_payment_after_reservation_expiry(db: AsyncSession, world):
    _event, price = await _public_price(db, club_id=world["club_a"].id, capacity=1, title="LastSeat")
    # Reserve, then expire the hold so capacity frees for another buyer.
    late = await create_ticket_order(
        db,
        club_id=world["club_a"].id,
        user_id=world["member"].id,
        ticket_price_id=price.id,
    )
    late.expires_at = utcnow() - timedelta(minutes=1)
    await db.flush()
    filler = await create_ticket_order(
        db,
        club_id=world["club_a"].id,
        user_id=world["other"].id,
        ticket_price_id=price.id,
    )
    await confirm_payment(db, order_id=filler.id, actor_user_id=world["other"].id, method="demo", success=True)
    result = await confirm_payment(
        db, order_id=late.id, actor_user_id=world["member"].id, method="demo", success=True
    )
    assert result.status == "refund_required"
    late_item_id = (await db.scalars(select(OrderItem).where(OrderItem.order_id == late.id))).first().id
    assert await db.scalar(select(Ticket).where(Ticket.order_item_id == late_item_id)) is None


async def test_repeated_early_renewal(db: AsyncSession, world):
    plan = MembershipPlan(
        club_id=world["club_a"].id,
        name="Renew",
        description="",
        dues_amount=Decimal("20"),
        duration_days=10,
        is_active=True,
    )
    db.add(plan)
    await db.flush()
    now = utcnow()
    order = Order(
        club_id=world["club_a"].id,
        user_id=world["member"].id,
        status="paid",
        total_amount=Decimal("20"),
        currency="INR",
    )
    db.add(order)
    await db.flush()
    item = OrderItem(
        order_id=order.id,
        item_kind="membership",
        membership_plan_id=plan.id,
        quantity=1,
        unit_price_snapshot=Decimal("20"),
        title_snapshot="Renew",
        duration_days_snapshot=10,
        fixed_expires_on_snapshot=None,
    )
    db.add(item)
    await db.flush()
    future_end = now + timedelta(days=20)
    db.add(
        Membership(
            club_id=world["club_a"].id,
            user_id=world["member"].id,
            plan_id=plan.id,
            order_item_id=item.id,
            starts_at=now + timedelta(days=5),
            ends_at=future_end,
            status="active",
        )
    )
    await db.flush()
    # Active-today membership ends sooner; chain must use the future period end.
    order2 = Order(
        club_id=world["club_a"].id,
        user_id=world["member"].id,
        status="paid",
        total_amount=Decimal("20"),
        currency="INR",
    )
    db.add(order2)
    await db.flush()
    item2 = OrderItem(
        order_id=order2.id,
        item_kind="membership",
        membership_plan_id=plan.id,
        quantity=1,
        unit_price_snapshot=Decimal("20"),
        title_snapshot="Renew",
        duration_days_snapshot=10,
        fixed_expires_on_snapshot=None,
    )
    db.add(item2)
    await db.flush()
    db.add(
        Membership(
            club_id=world["club_a"].id,
            user_id=world["member"].id,
            plan_id=plan.id,
            order_item_id=item2.id,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=5),
            status="active",
        )
    )
    await db.flush()
    chain = await continuous_entitlement_chain_end(
        db, club_id=world["club_a"].id, user_id=world["member"].id, at=now
    )
    assert chain == future_end
    start, end = await compute_entitlement_window(
        db, club_id=world["club_a"].id, user_id=world["member"].id, plan=plan, now=now
    )
    assert start == future_end
    assert end == future_end + timedelta(days=10)


def test_fixed_period_exclusive_end_semantics():
    d = date(2026, 12, 31)
    end = fixed_period_exclusive_end(d)
    assert end.isoformat().startswith("2027-01-01")
    # Still valid late on Dec 31 UTC.
    assert effective_membership_state(
        Membership(
            club_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            plan_id=uuid.uuid4(),
            order_item_id=uuid.uuid4(),
            starts_at=utcnow() - timedelta(days=1),
            ends_at=end,
            status="active",
        ),
        at=end - timedelta(seconds=1),
    ) == "active"


async def test_plan_null_clear(db: AsyncSession, world):
    plan = MembershipPlan(
        club_id=world["club_a"].id,
        name="Flip",
        description="",
        dues_amount=Decimal("5"),
        duration_days=30,
        is_active=True,
    )
    db.add(plan)
    await db.flush()
    await update_plan(
        db,
        club_id=world["club_a"].id,
        actor_user_id=world["admin"].id,
        plan_id=plan.id,
        fields={"duration_days": None, "fixed_expires_on": date(2027, 6, 1)},
    )
    await db.refresh(plan)
    assert plan.duration_days is None
    assert plan.fixed_expires_on == date(2027, 6, 1)


async def test_duplicate_checkin_and_cancelled_event(db: AsyncSession, world):
    now = utcnow()
    event = Event(
        club_id=world["club_a"].id,
        title="CI",
        description="",
        venue="V",
        starts_at=now - timedelta(minutes=5),
        ends_at=now + timedelta(hours=2),
        capacity=5,
        status="published",
    )
    db.add(event)
    await db.flush()
    tt = TicketType(event_id=event.id, name="GA")
    db.add(tt)
    await db.flush()
    price = TicketPrice(ticket_type_id=tt.id, audience="public", amount=Decimal("1"))
    db.add(price)
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
        ticket_price_id=price.id,
        quantity=1,
        unit_price_snapshot=Decimal("1"),
        title_snapshot="t",
    )
    db.add(item)
    await db.flush()
    raw = generate_token(16)
    ticket = Ticket(
        order_item_id=item.id,
        unit_index=0,
        event_id=event.id,
        club_id=world["club_a"].id,
        user_id=world["member"].id,
        ticket_type_id=tt.id,
        status="valid",
        qr_token_hash=hash_token(raw),
        qr_token_sealed=seal_token(raw),
    )
    db.add(ticket)
    await db.flush()
    _, ticket_after, dup1 = await check_in_ticket(
        db,
        club_id=world["club_a"].id,
        actor_user_id=world["admin"].id,
        event_id=event.id,
        qr_token=raw,
    )
    assert dup1 is False
    assert ticket_after.status == "used"
    _, _, dup2 = await check_in_ticket(
        db,
        club_id=world["club_a"].id,
        actor_user_id=world["admin"].id,
        event_id=event.id,
        qr_token=raw,
    )
    assert dup2 is True

    await set_event_status(
        db,
        club_id=world["club_a"].id,
        actor_user_id=world["admin"].id,
        event_id=event.id,
        status="cancelled",
    )
    # Checked-in (used) tickets also enter the refund_required queue on cancel.
    await db.refresh(ticket)
    assert ticket.status == "refund_required"


async def test_cross_club_relationship_validation(db: AsyncSession, world):
    plan_b = MembershipPlan(
        club_id=world["club_b"].id,
        name="B",
        description="",
        dues_amount=Decimal("9"),
        duration_days=30,
        is_active=True,
    )
    db.add(plan_b)
    await db.flush()
    order = Order(
        club_id=world["club_a"].id,
        user_id=world["member"].id,
        status="paid",
        total_amount=Decimal("9"),
        currency="INR",
    )
    db.add(order)
    await db.flush()
    item = OrderItem(
        order_id=order.id,
        item_kind="membership",
        membership_plan_id=plan_b.id,
        quantity=1,
        unit_price_snapshot=Decimal("9"),
        title_snapshot="B",
        duration_days_snapshot=30,
        fixed_expires_on_snapshot=None,
    )
    db.add(item)
    await db.flush()
    # Let the constraint abort the nested savepoint (catching inside begin_nested
    # leaves a closed transaction the context manager cannot exit cleanly).
    with pytest.raises(Exception) as exc:
        async with db.begin_nested():
            db.add(
                Membership(
                    club_id=world["club_a"].id,
                    user_id=world["member"].id,
                    plan_id=plan_b.id,
                    order_item_id=item.id,
                    starts_at=utcnow(),
                    ends_at=utcnow() + timedelta(days=30),
                    status="active",
                )
            )
            await db.flush()
    assert "cross_club" in str(exc.value).lower()


def test_qr_aead_and_legacy_compat():
    raw = generate_token(12)
    sealed = seal_token(raw)
    assert sealed.startswith("enc:v1:")
    assert unseal_token(sealed) == raw
    # Legacy signed-only seals still unseal.
    from itsdangerous import URLSafeSerializer
    from app.core.config import get_settings

    legacy = URLSafeSerializer(get_settings().secret_key, salt="campusos-qr").dumps(raw)
    assert unseal_token(legacy) == raw


async def _seed_committed_club_users(engine: AsyncEngine):
    """Commit club + users visible to concurrent sessions (roles get-or-create)."""
    from app.core.permissions import RoleCode
    from app.core.security import hash_password

    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, autoflush=False, expire_on_commit=False
    )
    async with SessionLocal() as db:
        for code, name in [
            (RoleCode.CLUB_ADMIN.value, "Admin"),
            (RoleCode.MEMBERSHIP_MANAGER.value, "Membership"),
            (RoleCode.EVENT_ORGANIZER.value, "Events"),
            (RoleCode.COMMUNICATIONS_OFFICER.value, "Comms"),
        ]:
            if await db.scalar(select(Role).where(Role.code == code)) is None:
                db.add(Role(code=code, name=name))
        club = Club(slug=f"c-{uuid.uuid4().hex[:10]}", name="Race Club", description="")
        db.add(club)
        await db.flush()
        users = []
        for label in ("a", "b"):
            u = User(
                email=f"{label}-{uuid.uuid4().hex[:8]}@race.test",
                full_name=label,
                password_hash=hash_password(TEST_PASSWORD),
            )
            db.add(u)
            await db.flush()
            db.add(ClubMember(club_id=club.id, user_id=u.id))
            users.append(u)
        await db.commit()
        return {"club_id": club.id, "user_a": users[0].id, "user_b": users[1].id}


async def test_simultaneous_confirmation(engine: AsyncEngine):
    """Two independent sessions race confirm_payment; only one membership is issued."""
    seeded = await _seed_committed_club_users(engine)
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, autoflush=False, expire_on_commit=False
    )
    async with SessionLocal() as db:
        plan = MembershipPlan(
            club_id=seeded["club_id"],
            name=f"Race-{uuid.uuid4().hex[:6]}",
            description="",
            dues_amount=Decimal("12"),
            duration_days=30,
            is_active=True,
        )
        db.add(plan)
        await db.flush()
        order = await create_membership_order(
            db, club_id=seeded["club_id"], user_id=seeded["user_a"], plan_id=plan.id
        )
        await db.commit()
        order_id = order.id
        user_id = seeded["user_a"]
        plan_id = plan.id

    outcomes: list[str] = []
    lock = asyncio.Lock()
    ready = asyncio.Event()
    started = 0
    started_lock = asyncio.Lock()

    async def worker():
        nonlocal started
        session = SessionLocal()
        try:
            async with started_lock:
                started += 1
                if started == 2:
                    ready.set()
            await ready.wait()
            await confirm_payment(
                session, order_id=order_id, actor_user_id=user_id, method="demo", success=True
            )
            await session.commit()
            async with lock:
                outcomes.append("ok")
        except Exception as exc:  # noqa: BLE001 — concurrency surface
            await session.rollback()
            async with lock:
                outcomes.append(type(exc).__name__)
        finally:
            await session.close()

    try:
        await asyncio.gather(worker(), worker())
        async with SessionLocal() as verify:
            memberships = (
                await verify.scalars(
                    select(Membership).where(Membership.user_id == user_id, Membership.plan_id == plan_id)
                )
            ).all()
            assert len(memberships) == 1
            order_row = await verify.get(Order, order_id)
            assert order_row is not None
            assert order_row.status == "paid"
            assert outcomes.count("ok") >= 1
    finally:
        await _cleanup_race_artifacts(
            engine, club_id=seeded["club_id"], user_ids=[seeded["user_a"], seeded["user_b"]]
        )


async def test_final_seat_booking_independent_sessions(engine: AsyncEngine):
    seeded = await _seed_committed_club_users(engine)
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, autoflush=False, expire_on_commit=False
    )
    async with SessionLocal() as db:
        event, price = await _public_price(
            db, club_id=seeded["club_id"], capacity=1, title=f"Cap-{uuid.uuid4().hex[:6]}"
        )
        await db.commit()
        price_id = price.id
        club_id = seeded["club_id"]
        member_id = seeded["user_a"]
        other_id = seeded["user_b"]
        event_id = event.id

    results: list[str] = []
    lock = asyncio.Lock()
    ready = asyncio.Event()
    started = 0
    started_lock = asyncio.Lock()

    async def worker(user_id: uuid.UUID):
        nonlocal started
        session = SessionLocal()
        try:
            async with started_lock:
                started += 1
                if started == 2:
                    ready.set()
            await ready.wait()
            order = await create_ticket_order(
                session, club_id=club_id, user_id=user_id, ticket_price_id=price_id, quantity=1
            )
            await confirm_payment(
                session, order_id=order.id, actor_user_id=user_id, method="demo", success=True
            )
            await session.commit()
            async with lock:
                results.append("paid")
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            async with lock:
                results.append(getattr(exc, "code", None) or type(exc).__name__)
        finally:
            await session.close()

    try:
        await asyncio.gather(worker(member_id), worker(other_id))
        async with SessionLocal() as verify:
            count = len(
                (
                    await verify.scalars(
                        select(Ticket).where(Ticket.event_id == event_id, Ticket.status == "valid")
                    )
                ).all()
            )
            assert count == 1
            assert "paid" in results
            assert len(results) == 2
    finally:
        await _cleanup_race_artifacts(
            engine, club_id=seeded["club_id"], user_ids=[seeded["user_a"], seeded["user_b"]]
        )


async def test_concurrent_renewal(engine: AsyncEngine):
    seeded = await _seed_committed_club_users(engine)
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, autoflush=False, expire_on_commit=False
    )
    async with SessionLocal() as db:
        plan = MembershipPlan(
            club_id=seeded["club_id"],
            name=f"CR-{uuid.uuid4().hex[:6]}",
            description="",
            dues_amount=Decimal("18"),
            duration_days=7,
            is_active=True,
        )
        db.add(plan)
        await db.commit()
        plan_id = plan.id
        club_id = seeded["club_id"]
        user_id = seeded["user_a"]

    ready = asyncio.Event()
    started = 0
    started_lock = asyncio.Lock()

    async def worker():
        nonlocal started
        session = SessionLocal()
        try:
            async with started_lock:
                started += 1
                if started == 2:
                    ready.set()
            await ready.wait()
            order = await create_membership_order(
                session, club_id=club_id, user_id=user_id, plan_id=plan_id
            )
            await confirm_payment(
                session, order_id=order.id, actor_user_id=user_id, method="demo", success=True
            )
            await session.commit()
        except Exception:  # noqa: BLE001
            await session.rollback()
        finally:
            await session.close()

    try:
        await asyncio.gather(worker(), worker())
        async with SessionLocal() as verify:
            rows = (
                await verify.scalars(
                    select(Membership).where(Membership.user_id == user_id, Membership.plan_id == plan_id)
                )
            ).all()
            assert len(rows) == 2
            ordered = sorted(rows, key=lambda m: m.starts_at)
            assert ordered[0].ends_at == ordered[1].starts_at
    finally:
        await _cleanup_race_artifacts(
            engine, club_id=seeded["club_id"], user_ids=[seeded["user_a"], seeded["user_b"]]
        )


def test_conftest_refuses_same_database(monkeypatch):
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://postgres:x@localhost:5432/campusos_test",
    )
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://postgres:x@localhost:5432/campusos_test",
    )
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="must differ"):
        resolve_test_database_url()
    get_settings.cache_clear()
