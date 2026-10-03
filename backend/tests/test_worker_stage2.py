"""Stage 2 worker reliability: claims, retries, recovery, shutdown, reminders."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.db_url import normalize_async_database_url
from app.core.security import hash_password
from app.core.time import utcnow
from app.models import Club, Membership, MembershipPlan, NotificationDelivery, Order, OrderItem, Payment, User
from app.services import announcement_service as ann_svc
from app.worker import (
    MAX_ATTEMPTS,
    claim_deliveries,
    interruptible_sleep,
    process_deliveries,
    process_one,
    reset_shutdown_flag,
    _outbox_dir,
    _request_shutdown,
)
from tests.conftest import resolve_test_database_url

REPO_BACKEND = Path(__file__).resolve().parents[1]


async def _seed_queued(engine: AsyncEngine, n: int) -> tuple[uuid.UUID, list[uuid.UUID]]:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        club = Club(slug=f"w2-{uuid.uuid4().hex[:8]}", name="W2", description="d")
        db.add(club)
        await db.flush()
        ids: list[uuid.UUID] = []
        for i in range(n):
            row = NotificationDelivery(
                club_id=club.id,
                kind="announcement",
                recipient_email=f"w2-{i}-{uuid.uuid4().hex[:6]}@example.com",
                subject="S",
                body="B",
                status="queued",
                idempotency_key=f"w2-{uuid.uuid4().hex}",
                meta={},
            )
            db.add(row)
            await db.flush()
            ids.append(row.id)
        await db.commit()
        return club.id, ids


async def _cleanup(engine: AsyncEngine, club_id: uuid.UUID) -> None:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        await db.execute(delete(NotificationDelivery).where(NotificationDelivery.club_id == club_id))
        await db.execute(delete(Club).where(Club.id == club_id))
        await db.commit()


async def test_two_claimers_each_delivery_once(engine: AsyncEngine):
    club_id, ids = await _seed_queued(engine, 6)
    test_url, _ = resolve_test_database_url()
    eng = create_async_engine(normalize_async_database_url(test_url).url, pool_size=4)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    claimed: list[uuid.UUID] = []
    lock = asyncio.Lock()

    async def claimer(name: str):
        async with factory() as db:
            # High limit so shared-DB leftovers cannot starve our seeded rows.
            rows = await claim_deliveries(db, limit=100, worker_id=name)
            await db.commit()
            async with lock:
                claimed.extend(r.id for r in rows)

    try:
        await asyncio.gather(claimer("a"), claimer("b"))
        assert len(claimed) == len(set(claimed))
        assert set(ids).issubset(set(claimed))
        assert sum(1 for c in claimed if c in set(ids)) == 6
    finally:
        await eng.dispose()
        await _cleanup(engine, club_id)


async def test_provider_file_crash_recovery(engine: AsyncEngine):
    club_id, ids = await _seed_queued(engine, 1)
    delivery_id = ids[0]
    provider_id = f"delivery-{delivery_id}.txt"
    outbox = _outbox_dir()
    (outbox / provider_id).write_text("To: x\nSubject: S\n\nrecovered\n", encoding="utf-8")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        row = await db.get(NotificationDelivery, delivery_id)
        assert row is not None
        row.provider_message_id = provider_id
        row.status = "queued"
        await db.commit()

    async with factory() as db:
        claimed = await claim_deliveries(db, limit=50, worker_id="recover")
        await db.commit()
        # Recovered row is finalized as sent_simulated and not returned as a claim.
        assert delivery_id not in {r.id for r in claimed}
        row = await db.get(NotificationDelivery, delivery_id)
        assert row is not None
        assert row.status == "sent_simulated"
        assert (row.meta or {}).get("recovered_from_provider_file") is True
    await _cleanup(engine, club_id)
    (outbox / provider_id).unlink(missing_ok=True)


async def test_retry_then_fail_after_max_attempts(engine: AsyncEngine):
    club_id, ids = await _seed_queued(engine, 1)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    delivery_id = ids[0]

    # Force process_one to fail by using a non-dev adapter temporarily via monkeypatch.
    from app.core.config import get_settings

    settings = get_settings()
    original = settings.email_adapter
    settings.email_adapter = "smtp-not-enabled"
    try:
        for _ in range(MAX_ATTEMPTS):
            async with factory() as db:
                row = await db.get(NotificationDelivery, delivery_id)
                assert row is not None
                row.status = "processing"
                row.claimed_at = utcnow()
                row.claimed_by = "t"
                await db.flush()
                try:
                    await process_one(db, row)
                except Exception:
                    row.last_error = "forced"
                    row.claimed_at = None
                    row.claimed_by = None
                    if row.attempts >= MAX_ATTEMPTS:
                        row.status = "failed"
                        row.processed_at = utcnow()
                    else:
                        row.status = "queued"
                        row.next_attempt_at = utcnow()
                await db.commit()
        async with factory() as db:
            row = await db.get(NotificationDelivery, delivery_id)
            assert row is not None
            assert row.status == "failed"
            assert row.attempts == MAX_ATTEMPTS
    finally:
        settings.email_adapter = original
        await _cleanup(engine, club_id)


async def test_shutdown_skips_new_claims_after_flag(engine: AsyncEngine):
    club_id, _ids = await _seed_queued(engine, 2)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    reset_shutdown_flag()
    _request_shutdown()
    try:
        processed = await process_deliveries(factory, limit=10)
        assert processed == 0
        async with factory() as db:
            queued = await db.scalar(
                select(func.count())
                .select_from(NotificationDelivery)
                .where(
                    NotificationDelivery.club_id == club_id,
                    NotificationDelivery.status == "queued",
                )
            )
            assert queued == 2
    finally:
        reset_shutdown_flag()
        await _cleanup(engine, club_id)


async def test_interruptible_sleep_honors_shutdown():
    reset_shutdown_flag()
    task = asyncio.create_task(interruptible_sleep(30))
    await asyncio.sleep(0.05)
    _request_shutdown()
    await asyncio.wait_for(task, timeout=2)
    reset_shutdown_flag()


async def test_concurrent_renewal_reminder_inserts(engine: AsyncEngine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        club = Club(slug=f"rem-{uuid.uuid4().hex[:8]}", name="R", description="d")
        db.add(club)
        await db.flush()
        user = User(
            email=f"rem-{uuid.uuid4().hex[:8]}@test.edu",
            full_name="R",
            password_hash=hash_password("Password123!"),
        )
        db.add(user)
        await db.flush()
        plan = MembershipPlan(
            club_id=club.id,
            name="P",
            description="d",
            dues_amount=Decimal("1.00"),
            duration_days=30,
            is_active=True,
        )
        db.add(plan)
        await db.flush()
        now = utcnow()
        order = Order(
            club_id=club.id,
            user_id=user.id,
            status="paid",
            total_amount=plan.dues_amount,
            currency="INR",
        )
        db.add(order)
        await db.flush()
        item = OrderItem(
            order_id=order.id,
            item_kind="membership",
            membership_plan_id=plan.id,
            quantity=1,
            unit_price_snapshot=plan.dues_amount,
            title_snapshot="P",
            duration_days_snapshot=30,
        )
        db.add(item)
        db.add(
            Payment(
                order_id=order.id,
                amount=plan.dues_amount,
                method="test",
                status="confirmed",
                confirmed_at=now,
            )
        )
        await db.flush()
        m = Membership(
            club_id=club.id,
            user_id=user.id,
            plan_id=plan.id,
            order_item_id=item.id,
            starts_at=now - timedelta(days=20),
            ends_at=now + timedelta(days=5),
            status="active",
        )
        db.add(m)
        await db.commit()
        club_id, membership_id, user_id = club.id, m.id, user.id

    test_url, _ = resolve_test_database_url()
    eng = create_async_engine(normalize_async_database_url(test_url).url, pool_size=4)
    SessionLocal = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)

    async def scan():
        async with SessionLocal() as db:
            n = await ann_svc.queue_renewal_reminders(db, within_days=14)
            await db.commit()
            return n

    try:
        await asyncio.gather(scan(), scan())
        # Scanners may also queue other due memberships in the shared DB; our key is unique.
        async with SessionLocal() as db:
            count = await db.scalar(
                select(func.count())
                .select_from(NotificationDelivery)
                .where(NotificationDelivery.membership_id == membership_id)
            )
            assert count == 1
            key = f"renewal:{membership_id}:"
            keys = (
                await db.scalars(
                    select(NotificationDelivery.idempotency_key).where(
                        NotificationDelivery.membership_id == membership_id
                    )
                )
            ).all()
            assert len(keys) == 1 and keys[0].startswith(key)
    finally:
        await eng.dispose()
        async with factory() as db:
            await db.execute(delete(NotificationDelivery).where(NotificationDelivery.club_id == club_id))
            await db.execute(delete(Membership).where(Membership.club_id == club_id))
            await db.execute(
                delete(Payment).where(
                    Payment.order_id.in_(select(Order.id).where(Order.club_id == club_id))
                )
            )
            await db.execute(
                delete(OrderItem).where(
                    OrderItem.order_id.in_(select(Order.id).where(Order.club_id == club_id))
                )
            )
            await db.execute(delete(Order).where(Order.club_id == club_id))
            await db.execute(delete(MembershipPlan).where(MembershipPlan.club_id == club_id))
            await db.execute(delete(Club).where(Club.id == club_id))
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()


async def test_two_worker_processes_process_once(engine: AsyncEngine):
    """Two real worker processes against dedicated seeded rows."""
    club_id, ids = await _seed_queued(engine, 8)
    env = {
        **dict(**{k: v for k, v in __import__("os").environ.items()}),
    }
    # Ensure workers use the test database.
    test_url, _ = resolve_test_database_url()
    env["DATABASE_URL"] = test_url
    env["APP_ENV"] = "test"

    def run_worker():
        return subprocess.run(
            [sys.executable, "-m", "app.worker", "--once", "--deliveries-only", "--limit", "20"],
            cwd=str(REPO_BACKEND),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    try:
        r1, r2 = await asyncio.gather(
            asyncio.to_thread(run_worker),
            asyncio.to_thread(run_worker),
        )
        assert r1.returncode == 0, r1.stderr
        assert r2.returncode == 0, r2.stderr
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as db:
            rows = (
                await db.scalars(
                    select(NotificationDelivery).where(NotificationDelivery.id.in_(ids))
                )
            ).all()
            statuses = [r.status for r in rows]
            attempts = [r.attempts for r in rows]
            assert all(s == "sent_simulated" for s in statuses)
            assert sum(1 for a in attempts if a == 1) == 8
            assert len(rows) == 8
            print(
                "TWO_PROCESS_STATUS_COUNTS",
                {s: statuses.count(s) for s in set(statuses)},
                "ATTEMPTS",
                attempts,
            )
    finally:
        await _cleanup(engine, club_id)


async def test_worker_pool_connections_visible(engine: AsyncEngine):
    """pg_stat_activity shows worker connections; count ≠ number of engine objects."""
    from app.core.config import get_settings
    from app.db.session import create_async_engine_from_settings

    settings = get_settings()
    worker_engine = create_async_engine_from_settings(settings, worker=True)
    try:
        async with worker_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            rows = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() AND state IS NOT NULL"
                    )
                )
            ).scalar()
        assert rows is not None and int(rows) >= 1
        print(
            "PG_STAT_ACTIVITY_CONNECTIONS",
            int(rows),
            "WORKER_POOL_SIZE",
            settings.worker_db_pool_size,
            "NOTE",
            "connection counts do not equal engine object counts",
        )
    finally:
        await worker_engine.dispose()
