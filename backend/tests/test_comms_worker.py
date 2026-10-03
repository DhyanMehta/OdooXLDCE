"""Announcements, mailing list, worker, seed guard, and leadership concurrency."""

from __future__ import annotations

import asyncio
import re
import uuid
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.db_url import normalize_async_database_url
from app.core.permissions import RoleCode
from app.core.security import generate_token, hash_password, hash_token
from app.core.time import utcnow
from app.models import (
    Announcement,
    Club,
    ClubMember,
    ClubRoleAssignment,
    MailingListSubscription,
    Membership,
    MembershipPlan,
    NotificationDelivery,
    Order,
    OrderItem,
    Payment,
    Role,
    User,
)
from app.services import announcement_service as ann_svc
from app.services.rbac import handover_role
from app.worker import claim_deliveries, process_one
from tests.conftest import TEST_PASSWORD, login, resolve_test_database_url

OUTBOX = Path(__file__).resolve().parents[1] / "app" / "var" / "email_outbox"
OPAQUE = ann_svc.OPAQUE_SUBSCRIBE_MSG


def _confirm_token_from_outbox(email: str) -> str:
    assert OUTBOX.is_dir(), "dev email outbox missing"
    candidates = sorted(OUTBOX.glob("confirm-*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        if email.lower() not in text.lower():
            continue
        match = re.search(r"token=([A-Za-z0-9_-]+)", text)
        if match:
            return match.group(1)
    raise AssertionError(f"No confirm preview found for {email}")


def _unsub_token_from_outbox(email: str) -> str:
    candidates = sorted(OUTBOX.glob("welcome-*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        text = path.read_text(encoding="utf-8")
        if email.lower() not in text.lower():
            continue
        match = re.search(r"token=([A-Za-z0-9_-]+)", text)
        if match:
            return match.group(1)
    raise AssertionError(f"No welcome/unsub preview found for {email}")


async def test_subscribe_opaque_confirm_unsubscribe(client: AsyncClient, world, db: AsyncSession):
    club_id = world["club_a"].id
    email = f"fan-{uuid.uuid4().hex[:8]}@example.com"

    r1 = await client.post(
        f"/api/v1/clubs/{club_id}/mailing-list/subscribe",
        json={"email": email, "consent": True},
    )
    assert r1.status_code == 200
    body = r1.json()
    assert body["message"] == OPAQUE
    assert set(body.keys()) == {"message"}

    r2 = await client.post(
        f"/api/v1/clubs/{club_id}/mailing-list/subscribe",
        json={"email": email, "consent": True},
    )
    assert r2.status_code == 200
    assert r2.json()["message"] == OPAQUE

    no_consent = await client.post(
        f"/api/v1/clubs/{club_id}/mailing-list/subscribe",
        json={"email": f"x-{uuid.uuid4().hex[:6]}@example.com", "consent": False},
    )
    assert no_consent.status_code == 400

    token = _confirm_token_from_outbox(email)
    conf = await client.post("/api/v1/mailing-list/confirm", json={"token": token})
    assert conf.status_code == 200

    conf2 = await client.post("/api/v1/mailing-list/confirm", json={"token": token})
    assert conf2.status_code == 200

    unsub_token = _unsub_token_from_outbox(email)
    unsub = await client.post("/api/v1/mailing-list/unsubscribe", json={"token": unsub_token})
    assert unsub.status_code == 200

    r3 = await client.post(
        f"/api/v1/clubs/{club_id}/mailing-list/subscribe",
        json={"email": email, "consent": True},
    )
    assert r3.status_code == 200
    assert r3.json()["message"] == OPAQUE
    db.expire_all()
    sub = await db.scalar(
        select(MailingListSubscription).where(
            MailingListSubscription.club_id == club_id,
            MailingListSubscription.email == email.lower(),
        )
    )
    assert sub is not None
    assert sub.status == "pending"


async def test_unsubscribe_after_queue_before_delivery(client: AsyncClient, world, db: AsyncSession):
    club_id = world["club_a"].id
    email = f"queued-{uuid.uuid4().hex[:8]}@example.com"
    raw_unsub = generate_token(32)
    db.add(
        MailingListSubscription(
            club_id=club_id,
            email=email,
            status="active",
            consent_at=utcnow(),
            unsubscribe_token_hash=hash_token(raw_unsub),
        )
    )
    ann = Announcement(
        club_id=club_id,
        title="Hello",
        body="Body",
        visibility="public",
        status="draft",
        author_user_id=world["admin"].id,
    )
    db.add(ann)
    await db.flush()

    headers = await login(client, world["admin"].email)
    pub = await client.post(
        f"/api/v1/clubs/{club_id}/announcements/{ann.id}/publish",
        headers=headers,
    )
    assert pub.status_code == 200

    delivery = await db.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.announcement_id == ann.id,
            NotificationDelivery.recipient_email == email,
        )
    )
    assert delivery is not None
    assert delivery.status == "queued"

    assert (
        await client.post("/api/v1/mailing-list/unsubscribe", json={"token": raw_unsub})
    ).status_code == 200
    delivery_id = delivery.id
    db.expire_all()

    claimed = await claim_deliveries(db, limit=50, worker_id="test-worker")
    for row in claimed:
        await process_one(db, row)
    await db.flush()
    db.expire_all()
    delivery = await db.get(NotificationDelivery, delivery_id)
    assert delivery is not None
    assert delivery.status == "suppressed"


async def test_member_only_delivery_eligibility(client: AsyncClient, world, db: AsyncSession):
    club_id = world["club_a"].id
    email = world["other"].email
    db.add(
        MailingListSubscription(
            club_id=club_id,
            email=email,
            status="active",
            consent_at=utcnow(),
            unsubscribe_token_hash=hash_token(generate_token(24)),
        )
    )
    ann = Announcement(
        club_id=club_id,
        title="Members only mail",
        body="Secret",
        visibility="members",
        status="draft",
        author_user_id=world["admin"].id,
    )
    db.add(ann)
    await db.flush()
    headers = await login(client, world["admin"].email)
    assert (
        (await client.post(
            f"/api/v1/clubs/{club_id}/announcements/{ann.id}/publish",
            headers=headers,
        )).status_code
        == 200
    )
    queued = await db.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.announcement_id == ann.id,
            NotificationDelivery.recipient_email == email,
        )
    )
    assert queued is None


async def test_duplicate_publish_idempotent(client: AsyncClient, world, db: AsyncSession):
    club_id = world["club_a"].id
    email = f"pub-{uuid.uuid4().hex[:8]}@example.com"
    db.add(
        MailingListSubscription(
            club_id=club_id,
            email=email,
            status="active",
            consent_at=utcnow(),
            unsubscribe_token_hash=hash_token(generate_token(24)),
        )
    )
    ann = Announcement(
        club_id=club_id,
        title="Once",
        body="Once body",
        visibility="public",
        status="draft",
        author_user_id=world["admin"].id,
    )
    db.add(ann)
    await db.flush()
    headers = await login(client, world["admin"].email)
    url = f"/api/v1/clubs/{club_id}/announcements/{ann.id}/publish"
    assert (await client.post(url, headers=headers)).status_code == 200
    assert (await client.post(url, headers=headers)).status_code == 200
    count = len(
        (
            await db.scalars(
                select(NotificationDelivery).where(NotificationDelivery.announcement_id == ann.id)
            )
        ).all()
    )
    assert count == 1


async def test_edit_does_not_queue_correction(client: AsyncClient, world, db: AsyncSession):
    club_id = world["club_a"].id
    email = f"edit-{uuid.uuid4().hex[:8]}@example.com"
    db.add(
        MailingListSubscription(
            club_id=club_id,
            email=email,
            status="active",
            consent_at=utcnow(),
            unsubscribe_token_hash=hash_token(generate_token(24)),
        )
    )
    headers = await login(client, world["admin"].email)
    created = await client.post(
        f"/api/v1/clubs/{club_id}/announcements",
        headers=headers,
        json={"title": "T", "body": "B", "visibility": "public"},
    )
    ann_id = created.json()["id"]
    await client.post(f"/api/v1/clubs/{club_id}/announcements/{ann_id}/publish", headers=headers)
    before = len(
        (
            await db.scalars(
                select(NotificationDelivery).where(NotificationDelivery.announcement_id == ann_id)
            )
        ).all()
    )
    patch_res = await client.patch(
        f"/api/v1/clubs/{club_id}/announcements/{ann_id}",
        headers=headers,
        json={"body": "Corrected on site only"},
    )
    assert patch_res.status_code == 200
    after = len(
        (
            await db.scalars(
                select(NotificationDelivery).where(NotificationDelivery.announcement_id == ann_id)
            )
        ).all()
    )
    assert after == before
    corr = await client.post(
        f"/api/v1/clubs/{club_id}/announcements/{ann_id}/send-correction",
        headers=headers,
    )
    assert corr.status_code == 200
    final = len(
        (
            await db.scalars(
                select(NotificationDelivery).where(NotificationDelivery.announcement_id == ann_id)
            )
        ).all()
    )
    assert final == before + 1


async def test_reminder_suppressed_after_renewal(world, db: AsyncSession):
    club_id = world["club_a"].id
    user = world["member"]
    now = utcnow()
    plan = MembershipPlan(
        club_id=club_id,
        name=f"Plan-{uuid.uuid4().hex[:6]}",
        description="t",
        dues_amount=Decimal("10.00"),
        duration_days=30,
        is_active=True,
    )
    db.add(plan)
    await db.flush()

    async def paid_membership(starts, ends):
        order = Order(
            club_id=club_id,
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
            title_snapshot=plan.name,
            duration_days_snapshot=plan.duration_days,
        )
        db.add(item)
        db.add(
            Payment(
                order_id=order.id,
                amount=plan.dues_amount,
                method="test",
                status="confirmed",
                confirmed_at=starts,
            )
        )
        await db.flush()
        m = Membership(
            club_id=club_id,
            user_id=user.id,
            plan_id=plan.id,
            order_item_id=item.id,
            starts_at=starts,
            ends_at=ends,
            status="active",
        )
        db.add(m)
        await db.flush()
        return m

    soon = await paid_membership(now - timedelta(days=20), now + timedelta(days=5))
    await paid_membership(soon.ends_at, soon.ends_at + timedelta(days=30))
    await ann_svc.queue_renewal_reminders(db, within_days=14)
    keys = list(
        (
            await db.scalars(
                select(NotificationDelivery).where(NotificationDelivery.membership_id == soon.id)
            )
        ).all()
    )
    assert keys == []


async def test_scheduled_and_ended_role_state(client: AsyncClient, world, db: AsyncSession):
    headers = await login(client, world["admin"].email)
    club_id = world["club_a"].id
    future = (utcnow() + timedelta(days=7)).isoformat()
    assign = await client.post(
        f"/api/v1/clubs/{club_id}/role-assignments",
        headers=headers,
        json={
            "user_id": str(world["member"].id),
            "role_code": RoleCode.EVENT_ORGANIZER.value,
            "starts_at": future,
        },
    )
    assert assign.status_code == 200
    scheduled_id = assign.json()["id"]

    active = await client.post(
        f"/api/v1/clubs/{club_id}/role-assignments",
        headers=headers,
        json={
            "user_id": str(world["other"].id),
            "role_code": RoleCode.COMMUNICATIONS_OFFICER.value,
        },
    )
    assert active.status_code == 200
    active_id = active.json()["id"]
    ended = await client.post(
        f"/api/v1/clubs/{club_id}/role-assignments/{active_id}/end",
        headers=headers,
    )
    assert ended.status_code == 200

    listed = await client.get(
        f"/api/v1/clubs/{club_id}/role-assignments?include_history=true",
        headers=headers,
    )
    assert listed.status_code == 200
    states = {row["id"]: row["state"] for row in listed.json()}
    assert states[active_id] == "ended"
    assert states[scheduled_id] == "scheduled"


async def test_staff_preview_without_membership(client: AsyncClient, world, db: AsyncSession):
    ann = Announcement(
        club_id=world["club_a"].id,
        title="Draft preview",
        body="Draft body",
        visibility="members",
        status="draft",
        author_user_id=world["admin"].id,
    )
    db.add(ann)
    await db.flush()
    headers = await login(client, world["admin"].email)
    assert (
        (
            await client.get(
                f"/api/v1/clubs/{world['club_a'].id}/announcements/{ann.id}",
                headers=headers,
            )
        ).status_code
        == 404
    )
    ok = await client.get(
        f"/api/v1/clubs/{world['club_a'].id}/announcements/{ann.id}?preview=true",
        headers=headers,
    )
    assert ok.status_code == 200
    assert ok.json()["title"] == "Draft preview"


async def test_seed_refuses_production():
    """Await main_async — sync main() uses asyncio.run and would close the session loop."""
    get_settings.cache_clear()
    with patch("app.seed.get_settings") as gs:
        gs.return_value.is_production.return_value = True
        from app.seed import main_async

        with pytest.raises(SystemExit) as exc:
            await main_async()
        assert exc.value.code == 2
    get_settings.cache_clear()


async def _committed_club_with_deliveries(engine: AsyncEngine, n: int = 4) -> uuid.UUID:
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, autoflush=False, expire_on_commit=False
    )
    async with SessionLocal() as session:
        club = Club(slug=f"claim-{uuid.uuid4().hex[:8]}", name="Claim Club", description="c")
        session.add(club)
        await session.flush()
        for _ in range(n):
            session.add(
                NotificationDelivery(
                    club_id=club.id,
                    kind="announcement",
                    recipient_email=f"w-{uuid.uuid4().hex[:8]}@example.com",
                    subject="S",
                    body="B",
                    status="queued",
                    idempotency_key=f"claim-test-{uuid.uuid4().hex}",
                    meta={},
                )
            )
        await session.commit()
        return club.id


async def _cleanup_claim_club(engine: AsyncEngine, club_id: uuid.UUID) -> None:
    async with AsyncSession(engine, expire_on_commit=False, autoflush=False) as db:
        await db.execute(delete(NotificationDelivery).where(NotificationDelivery.club_id == club_id))
        await db.execute(delete(Club).where(Club.id == club_id))
        await db.commit()


async def test_concurrent_worker_claims(engine: AsyncEngine):
    club_id = await _committed_club_with_deliveries(engine, n=4)
    test_url, _ = resolve_test_database_url()
    async_url = normalize_async_database_url(test_url).url
    eng = create_async_engine(async_url, pool_size=4, pool_pre_ping=True)
    SessionLocal = async_sessionmaker(
        bind=eng, class_=AsyncSession, autoflush=False, expire_on_commit=False
    )
    claimed_ids: list[uuid.UUID] = []
    lock = asyncio.Lock()
    ready = asyncio.Event()
    started = 0
    started_lock = asyncio.Lock()

    async def worker(name: str):
        nonlocal started
        async with SessionLocal() as session:
            async with started_lock:
                started += 1
                if started == 2:
                    ready.set()
            await ready.wait()
            rows = await claim_deliveries(session, limit=2, worker_id=name)
            await session.commit()
            async with lock:
                claimed_ids.extend(r.id for r in rows)

    try:
        await asyncio.gather(worker("w1"), worker("w2"))
        assert len(claimed_ids) == len(set(claimed_ids))
        assert len(claimed_ids) == 4
    finally:
        await eng.dispose()
        await _cleanup_claim_club(engine, club_id)


async def _cleanup_handover_club(
    engine: AsyncEngine, *, club_id: uuid.UUID, user_ids: list[uuid.UUID]
) -> None:
    async with AsyncSession(engine, expire_on_commit=False, autoflush=False) as db:
        await db.execute(delete(ClubRoleAssignment).where(ClubRoleAssignment.club_id == club_id))
        await db.execute(delete(ClubMember).where(ClubMember.club_id == club_id))
        await db.execute(delete(Club).where(Club.id == club_id))
        if user_ids:
            await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()


async def test_concurrent_admin_handover_serialized(engine: AsyncEngine):
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, autoflush=False, expire_on_commit=False
    )
    async with SessionLocal() as session:
        for code, name in [
            (RoleCode.CLUB_ADMIN.value, "Admin"),
        ]:
            if await session.scalar(select(Role).where(Role.code == code)) is None:
                session.add(Role(code=code, name=name))
        await session.flush()
        admin_role = await session.scalar(select(Role).where(Role.code == RoleCode.CLUB_ADMIN.value))
        club = Club(slug=f"handover-{uuid.uuid4().hex[:8]}", name="H", description="h")
        session.add(club)
        await session.flush()

        async def make_user(prefix: str) -> User:
            u = User(
                email=f"{prefix}-{uuid.uuid4().hex[:8]}@test.edu",
                full_name=prefix,
                password_hash=hash_password(TEST_PASSWORD),
            )
            session.add(u)
            await session.flush()
            session.add(ClubMember(club_id=club.id, user_id=u.id))
            return u

        admin = await make_user("admin")
        member = await make_user("member")
        other = await make_user("other")
        asg = ClubRoleAssignment(
            club_id=club.id,
            user_id=admin.id,
            role_id=admin_role.id,
            starts_at=utcnow() - timedelta(days=1),
        )
        session.add(asg)
        await session.commit()
        club_id = club.id
        admin_id = admin.id
        member_id = member.id
        other_id = other.id
        asg_id = asg.id

    test_url, _ = resolve_test_database_url()
    async_url = normalize_async_database_url(test_url).url
    eng = create_async_engine(async_url, pool_size=4, pool_pre_ping=True)
    ThreadSession = async_sessionmaker(
        bind=eng, class_=AsyncSession, autoflush=False, expire_on_commit=False
    )
    results: list[str] = []
    lock = asyncio.Lock()
    ready = asyncio.Event()
    started = 0
    started_lock = asyncio.Lock()

    async def attempt(incoming_id: uuid.UUID):
        nonlocal started
        async with ThreadSession() as session:
            try:
                async with started_lock:
                    started += 1
                    if started == 2:
                        ready.set()
                await ready.wait()
                await handover_role(
                    session,
                    club_id=club_id,
                    actor_user_id=admin_id,
                    outgoing_assignment_id=asg_id,
                    incoming_user_id=incoming_id,
                )
                await session.commit()
                async with lock:
                    results.append("ok")
            except Exception:
                await session.rollback()
                async with lock:
                    results.append("err")

    try:
        await asyncio.gather(attempt(member_id), attempt(other_id))
        assert results.count("ok") == 1
        assert results.count("err") == 1
    finally:
        await eng.dispose()
        await _cleanup_handover_club(
            engine, club_id=club_id, user_ids=[admin_id, member_id, other_id]
        )
