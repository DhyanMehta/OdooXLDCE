"""PostgreSQL merchandise inventory + project volunteer concurrency tests."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.errors import ConflictError
from app.core.permissions import RoleCode
from app.core.security import hash_password
from app.models import (
    Club,
    ClubMember,
    ClubRoleAssignment,
    InventoryMovement,
    Order,
    OrderItem,
    Payment,
    PaymentEvent,
    Product,
    ProductVariant,
    Project,
    Role,
    Task,
    TaskAssignment,
    User,
)
from app.services.membership_eligibility import utcnow
from app.services.merchandise_service import receive_stock
from app.services.project_service import signup_for_task
from app.services.purchase_service import (
    cancel_pending_order,
    confirm_payment,
    create_merchandise_order,
)
from tests.conftest import TEST_PASSWORD, login


async def _seed_roles(db: AsyncSession) -> dict[str, Role]:
    roles = {}
    for code, name in [
        (RoleCode.CLUB_ADMIN.value, "Admin"),
        (RoleCode.MEMBERSHIP_MANAGER.value, "Membership"),
        (RoleCode.EVENT_ORGANIZER.value, "Events"),
        (RoleCode.COMMUNICATIONS_OFFICER.value, "Comms"),
    ]:
        role = await db.scalar(select(Role).where(Role.code == code))
        if role is None:
            role = Role(code=code, name=name)
            db.add(role)
            await db.flush()
        roles[code] = role
    return roles


async def _seed_committed_world(engine: AsyncEngine):
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, autoflush=False, expire_on_commit=False
    )
    async with SessionLocal() as db:
        roles = await _seed_roles(db)
        club = Club(slug=f"m-{uuid.uuid4().hex[:10]}", name="Merch Club", description="")
        other = Club(slug=f"o-{uuid.uuid4().hex[:10]}", name="Other Club", description="")
        db.add_all([club, other])
        await db.flush()
        users = []
        for label in ("admin", "a", "b", "outsider"):
            u = User(
                email=f"{label}-{uuid.uuid4().hex[:8]}@merch.test",
                full_name=label,
                password_hash=hash_password(TEST_PASSWORD),
            )
            db.add(u)
            await db.flush()
            users.append(u)
        admin, user_a, user_b, outsider = users
        for u in (admin, user_a, user_b):
            db.add(ClubMember(club_id=club.id, user_id=u.id))
        db.add(ClubMember(club_id=other.id, user_id=outsider.id))
        db.add(
            ClubRoleAssignment(
                club_id=club.id,
                user_id=admin.id,
                role_id=roles[RoleCode.CLUB_ADMIN.value].id,
                starts_at=utcnow() - timedelta(days=1),
            )
        )
        await db.commit()
        return {
            "club_id": club.id,
            "other_club_id": other.id,
            "admin_id": admin.id,
            "user_a": user_a.id,
            "user_b": user_b.id,
            "outsider_id": outsider.id,
            "admin_email": admin.email,
            "member_email": user_a.email,
            "outsider_email": outsider.email,
        }


async def _cleanup(engine: AsyncEngine, *, club_ids: list[uuid.UUID], user_ids: list[uuid.UUID]) -> None:
    async with AsyncSession(engine, expire_on_commit=False, autoflush=False) as db:
        for club_id in club_ids:
            order_ids = (await db.scalars(select(Order.id).where(Order.club_id == club_id))).all()
            if order_ids:
                item_ids = (
                    await db.scalars(select(OrderItem.id).where(OrderItem.order_id.in_(order_ids)))
                ).all()
                if item_ids:
                    await db.execute(
                        delete(InventoryMovement).where(InventoryMovement.order_item_id.in_(item_ids))
                    )
                    await db.execute(delete(OrderItem).where(OrderItem.id.in_(item_ids)))
                pay_ids = (
                    await db.scalars(select(Payment.id).where(Payment.order_id.in_(order_ids)))
                ).all()
                if pay_ids:
                    await db.execute(delete(PaymentEvent).where(PaymentEvent.payment_id.in_(pay_ids)))
                    await db.execute(delete(Payment).where(Payment.id.in_(pay_ids)))
                await db.execute(delete(Order).where(Order.id.in_(order_ids)))

            product_ids = (
                await db.scalars(select(Product.id).where(Product.club_id == club_id))
            ).all()
            if product_ids:
                variant_ids = (
                    await db.scalars(
                        select(ProductVariant.id).where(ProductVariant.product_id.in_(product_ids))
                    )
                ).all()
                if variant_ids:
                    await db.execute(
                        delete(InventoryMovement).where(InventoryMovement.variant_id.in_(variant_ids))
                    )
                    await db.execute(delete(ProductVariant).where(ProductVariant.id.in_(variant_ids)))
                await db.execute(delete(Product).where(Product.id.in_(product_ids)))

            project_ids = (
                await db.scalars(select(Project.id).where(Project.club_id == club_id))
            ).all()
            if project_ids:
                task_ids = (
                    await db.scalars(select(Task.id).where(Task.project_id.in_(project_ids)))
                ).all()
                if task_ids:
                    await db.execute(delete(TaskAssignment).where(TaskAssignment.task_id.in_(task_ids)))
                    await db.execute(delete(Task).where(Task.id.in_(task_ids)))
                await db.execute(delete(Project).where(Project.id.in_(project_ids)))

            # Finance tables (RESTRICT on clubs) created by payment confirmation posting.
            await db.execute(
                text(
                    "DELETE FROM journal_lines WHERE entry_id IN "
                    "(SELECT id FROM journal_entries WHERE club_id = :c)"
                ),
                {"c": club_id},
            )
            await db.execute(text("DELETE FROM journal_entries WHERE club_id = :c"), {"c": club_id})
            await db.execute(text("DELETE FROM accounts WHERE club_id = :c"), {"c": club_id})
            await db.execute(text("DELETE FROM reimbursements WHERE club_id = :c"), {"c": club_id})
            await db.execute(
                text(
                    "DELETE FROM expense_approvals WHERE expense_id IN "
                    "(SELECT id FROM expenses WHERE club_id = :c)"
                ),
                {"c": club_id},
            )
            await db.execute(
                text(
                    "DELETE FROM expense_attachments WHERE expense_id IN "
                    "(SELECT id FROM expenses WHERE club_id = :c)"
                ),
                {"c": club_id},
            )
            await db.execute(text("DELETE FROM expenses WHERE club_id = :c"), {"c": club_id})
            await db.execute(text("DELETE FROM budgets WHERE club_id = :c"), {"c": club_id})
            await db.execute(text("DELETE FROM refunds WHERE club_id = :c"), {"c": club_id})

            await db.execute(delete(ClubMember).where(ClubMember.club_id == club_id))
            await db.execute(text("DELETE FROM club_role_assignments WHERE club_id = :c"), {"c": club_id})
            await db.execute(text("DELETE FROM audit_logs WHERE club_id = :c"), {"c": club_id})
            await db.execute(delete(Club).where(Club.id == club_id))

        if user_ids:
            await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.commit()


async def _make_variant(
    db: AsyncSession, *, club_id: uuid.UUID, admin_id: uuid.UUID, stock: int = 1
) -> ProductVariant:
    product = Product(
        club_id=club_id,
        name=f"P-{uuid.uuid4().hex[:6]}",
        description="",
        status="active",
    )
    db.add(product)
    await db.flush()
    variant = ProductVariant(
        product_id=product.id,
        label="M",
        sku=f"SKU-{uuid.uuid4().hex[:8]}",
        price=Decimal("50.00"),
        is_active=True,
        quantity_on_hand=0,
        quantity_reserved=0,
    )
    db.add(variant)
    await db.flush()
    if stock:
        await receive_stock(
            db,
            club_id=club_id,
            actor_user_id=admin_id,
            variant_id=variant.id,
            quantity=stock,
            note="test stock",
        )
    return variant


async def test_last_stock_race(engine: AsyncEngine):
    seeded = await _seed_committed_world(engine)
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, autoflush=False, expire_on_commit=False
    )
    async with SessionLocal() as db:
        variant = await _make_variant(
            db, club_id=seeded["club_id"], admin_id=seeded["admin_id"], stock=1
        )
        await db.commit()
        variant_id = variant.id
        club_id = seeded["club_id"]

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
            order = await create_merchandise_order(
                session,
                club_id=club_id,
                user_id=user_id,
                product_variant_id=variant_id,
                quantity=1,
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
        await asyncio.gather(worker(seeded["user_a"]), worker(seeded["user_b"]))
        async with SessionLocal() as verify:
            variant = await verify.get(ProductVariant, variant_id)
            assert variant is not None
            assert variant.quantity_on_hand == 0
            assert variant.quantity_reserved == 0
            paid = (
                await verify.scalars(
                    select(Order).where(Order.club_id == club_id, Order.status == "paid")
                )
            ).all()
            assert len(paid) == 1
            assert "paid" in results
            assert "inventory_insufficient" in results or results.count("paid") == 1
    finally:
        await _cleanup(
            engine,
            club_ids=[seeded["club_id"], seeded["other_club_id"]],
            user_ids=[
                seeded["admin_id"],
                seeded["user_a"],
                seeded["user_b"],
                seeded["outsider_id"],
            ],
        )


async def test_repeated_payment_sale_once(engine: AsyncEngine):
    seeded = await _seed_committed_world(engine)
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, autoflush=False, expire_on_commit=False
    )
    async with SessionLocal() as db:
        variant = await _make_variant(
            db, club_id=seeded["club_id"], admin_id=seeded["admin_id"], stock=2
        )
        order = await create_merchandise_order(
            db,
            club_id=seeded["club_id"],
            user_id=seeded["user_a"],
            product_variant_id=variant.id,
            quantity=1,
        )
        await db.commit()
        order_id = order.id
        variant_id = variant.id
        user_id = seeded["user_a"]

    try:
        async with SessionLocal() as db:
            await confirm_payment(db, order_id=order_id, actor_user_id=user_id, method="demo")
            await db.commit()
        async with SessionLocal() as db:
            again = await confirm_payment(db, order_id=order_id, actor_user_id=user_id, method="demo")
            await db.commit()
            assert again.status == "paid"
        async with SessionLocal() as verify:
            sales = (
                await verify.scalars(
                    select(InventoryMovement).where(
                        InventoryMovement.variant_id == variant_id,
                        InventoryMovement.reason == "sale",
                    )
                )
            ).all()
            assert len(sales) == 1
            variant = await verify.get(ProductVariant, variant_id)
            assert variant is not None
            assert variant.quantity_on_hand == 1
            assert variant.quantity_reserved == 0
    finally:
        await _cleanup(
            engine,
            club_ids=[seeded["club_id"], seeded["other_club_id"]],
            user_ids=[
                seeded["admin_id"],
                seeded["user_a"],
                seeded["user_b"],
                seeded["outsider_id"],
            ],
        )


async def test_reservation_release_on_cancel(engine: AsyncEngine):
    seeded = await _seed_committed_world(engine)
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, autoflush=False, expire_on_commit=False
    )
    try:
        async with SessionLocal() as db:
            variant = await _make_variant(
                db, club_id=seeded["club_id"], admin_id=seeded["admin_id"], stock=1
            )
            order = await create_merchandise_order(
                db,
                club_id=seeded["club_id"],
                user_id=seeded["user_a"],
                product_variant_id=variant.id,
                quantity=1,
            )
            await db.flush()
            variant_locked = await db.get(ProductVariant, variant.id)
            assert variant_locked is not None
            assert variant_locked.quantity_reserved == 1
            await cancel_pending_order(db, order_id=order.id, actor_user_id=seeded["user_a"])
            await db.commit()
            variant_id = variant.id

        async with SessionLocal() as verify:
            variant = await verify.get(ProductVariant, variant_id)
            assert variant is not None
            assert variant.quantity_reserved == 0
            assert variant.quantity_on_hand == 1
            releases = (
                await verify.scalars(
                    select(InventoryMovement).where(
                        InventoryMovement.variant_id == variant_id,
                        InventoryMovement.reason == "release",
                    )
                )
            ).all()
            assert len(releases) == 1
    finally:
        await _cleanup(
            engine,
            club_ids=[seeded["club_id"], seeded["other_club_id"]],
            user_ids=[
                seeded["admin_id"],
                seeded["user_a"],
                seeded["user_b"],
                seeded["outsider_id"],
            ],
        )


async def test_duplicate_signup_rejected(engine: AsyncEngine):
    seeded = await _seed_committed_world(engine)
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, autoflush=False, expire_on_commit=False
    )
    try:
        async with SessionLocal() as db:
            project = Project(
                club_id=seeded["club_id"],
                title="Proj",
                description="",
                status="open",
            )
            db.add(project)
            await db.flush()
            task = Task(
                project_id=project.id,
                title="Task",
                description="",
                status="open",
                capacity=5,
            )
            db.add(task)
            await db.commit()
            task_id = task.id
            club_id = seeded["club_id"]
            user_id = seeded["user_a"]

        async with SessionLocal() as db:
            await signup_for_task(db, club_id=club_id, user_id=user_id, task_id=task_id)
            await db.commit()
        async with SessionLocal() as db:
            with pytest.raises(ConflictError) as exc:
                await signup_for_task(db, club_id=club_id, user_id=user_id, task_id=task_id)
            assert exc.value.code == "already_assigned"
    finally:
        await _cleanup(
            engine,
            club_ids=[seeded["club_id"], seeded["other_club_id"]],
            user_ids=[
                seeded["admin_id"],
                seeded["user_a"],
                seeded["user_b"],
                seeded["outsider_id"],
            ],
        )


async def test_task_capacity_race(engine: AsyncEngine):
    seeded = await _seed_committed_world(engine)
    SessionLocal = async_sessionmaker(
        bind=engine, class_=AsyncSession, autoflush=False, expire_on_commit=False
    )
    async with SessionLocal() as db:
        project = Project(
            club_id=seeded["club_id"],
            title="CapProj",
            description="",
            status="open",
        )
        db.add(project)
        await db.flush()
        task = Task(
            project_id=project.id,
            title="OneSlot",
            description="",
            status="open",
            capacity=1,
        )
        db.add(task)
        await db.commit()
        task_id = task.id
        club_id = seeded["club_id"]

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
            await signup_for_task(session, club_id=club_id, user_id=user_id, task_id=task_id)
            await session.commit()
            async with lock:
                results.append("ok")
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            async with lock:
                results.append(getattr(exc, "code", None) or type(exc).__name__)
        finally:
            await session.close()

    try:
        await asyncio.gather(worker(seeded["user_a"]), worker(seeded["user_b"]))
        async with SessionLocal() as verify:
            active = (
                await verify.scalars(
                    select(TaskAssignment).where(
                        TaskAssignment.task_id == task_id, TaskAssignment.status == "active"
                    )
                )
            ).all()
            assert len(active) == 1
            assert "ok" in results
            assert "capacity_exhausted" in results or "already_assigned" in results or len(results) == 2
    finally:
        await _cleanup(
            engine,
            club_ids=[seeded["club_id"], seeded["other_club_id"]],
            user_ids=[
                seeded["admin_id"],
                seeded["user_a"],
                seeded["user_b"],
                seeded["outsider_id"],
            ],
        )


async def test_merch_and_project_auth_negatives(client: AsyncClient, world, db: AsyncSession):
    """HTTP happy path + service-level negatives (avoids login rate-limit churn)."""
    from app.core.errors import ForbiddenError, NotFoundError
    from app.services.merchandise_service import create_product, mark_collected, receive_stock
    from app.services.project_service import create_project, signup_for_task
    from app.services.purchase_service import create_merchandise_order

    club_a = world["club_a"]
    club_b = world["club_b"]
    admin = world["admin"]
    member = world["member"]
    other = world["other"]

    # Cookie jar holds one session — finish admin setup before member login.
    headers = await login(client, admin.email)
    r = await client.post(
        f"/api/v1/clubs/{club_a.id}/products",
        headers=headers,
        json={"name": "Mug", "description": "demo"},
    )
    assert r.status_code == 200, r.text
    product_id = r.json()["id"]

    r = await client.post(
        f"/api/v1/clubs/{club_a.id}/products/{product_id}/variants",
        headers=headers,
        json={"label": "Std", "sku": f"MUG-{uuid.uuid4().hex[:6]}", "price": "100.00"},
    )
    assert r.status_code == 200, r.text
    variant_id = uuid.UUID(r.json()["id"])

    r = await client.post(
        f"/api/v1/clubs/{club_a.id}/variants/{variant_id}/receive",
        headers=headers,
        json={"quantity": 3, "note": "in"},
    )
    assert r.status_code == 200, r.text

    r = await client.post(
        f"/api/v1/clubs/{club_a.id}/projects",
        headers=headers,
        json={"title": "Vol", "description": "", "status": "open"},
    )
    assert r.status_code == 200, r.text
    project_id = r.json()["id"]
    r = await client.post(
        f"/api/v1/clubs/{club_a.id}/projects/{project_id}/tasks",
        headers=headers,
        json={"title": "Help", "capacity": 2},
    )
    assert r.status_code == 200, r.text
    task_id = uuid.UUID(r.json()["id"])

    member_headers = await login(client, member.email)

    # Member cannot manage merch.
    r = await client.post(
        f"/api/v1/clubs/{club_a.id}/products",
        headers=member_headers,
        json={"name": "Nope", "description": ""},
    )
    assert r.status_code == 403

    # Cross-club receive: variant belongs to A, looked up under B.
    with pytest.raises((NotFoundError, ForbiddenError)):
        await receive_stock(
            db,
            club_id=club_b.id,
            actor_user_id=other.id,
            variant_id=variant_id,
            quantity=1,
        )

    # Cross-club purchase blocked at service layer.
    with pytest.raises(ForbiddenError):
        await create_merchandise_order(
            db,
            club_id=club_b.id,
            user_id=member.id,
            product_variant_id=variant_id,
            quantity=1,
        )

    # Happy path purchase on correct club.
    r = await client.post(
        f"/api/v1/clubs/{club_a.id}/orders/merchandise",
        headers=member_headers,
        json={"product_variant_id": str(variant_id), "quantity": 1},
    )
    assert r.status_code == 200, r.text
    order_id = r.json()["id"]
    item_id = r.json()["items"][0]["id"]
    assert r.json()["items"][0]["fulfillment_status"] == "reserved"

    r = await client.post(
        f"/api/v1/orders/{order_id}/pay/demo",
        headers=member_headers,
        json={"success": True},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid"

    r = await client.post(
        f"/api/v1/clubs/{club_a.id}/tasks/{task_id}/signup",
        headers=member_headers,
    )
    assert r.status_code == 200, r.text

    collected = await mark_collected(
        db, club_id=club_a.id, actor_user_id=admin.id, order_item_id=uuid.UUID(item_id)
    )
    assert collected.fulfillment_status == "collected"

    outsider = User(
        email=f"out-{uuid.uuid4().hex[:6]}@test.edu",
        full_name="Out",
        password_hash=hash_password(TEST_PASSWORD),
    )
    db.add(outsider)
    await db.flush()
    with pytest.raises(ForbiddenError):
        await signup_for_task(db, club_id=club_a.id, user_id=outsider.id, task_id=task_id)

    # Cross-club project management denied (admin has no role on B).
    with pytest.raises(ForbiddenError):
        await create_project(
            db,
            club_id=club_b.id,
            actor_user_id=admin.id,
            title="X",
            status="open",
        )

    # Member cannot create products via service either.
    with pytest.raises(ForbiddenError):
        await create_product(
            db, club_id=club_a.id, actor_user_id=member.id, name="Denied"
        )


async def test_expired_merch_pay_refund_required(db: AsyncSession, world):
    club = world["club_a"]
    admin = world["admin"]
    member = world["member"]
    variant = await _make_variant(db, club_id=club.id, admin_id=admin.id, stock=1)
    order = await create_merchandise_order(
        db, club_id=club.id, user_id=member.id, product_variant_id=variant.id, quantity=1
    )
    order.expires_at = utcnow() - timedelta(minutes=1)
    await db.flush()
    result = await confirm_payment(
        db, order_id=order.id, actor_user_id=member.id, method="demo", success=True
    )
    assert result.status == "refund_required"
    await db.refresh(variant)
    assert variant.quantity_reserved == 0
    assert variant.quantity_on_hand == 1
