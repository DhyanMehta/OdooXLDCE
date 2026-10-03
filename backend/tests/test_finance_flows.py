"""Checkpoint 2: expense HTTP flow, receipts, refunds, finance reports, concurrency."""

from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.errors import ConflictError
from app.core.permissions import RoleCode
from app.core.security import hash_password
from app.core.time import utcnow
from app.models import (
    ClubMember,
    ClubRoleAssignment,
    Event,
    InventoryMovement,
    JournalEntry,
    Membership,
    MembershipPlan,
    Order,
    Payment,
    ProductVariant,
    Role,
    Ticket,
    TicketCheckin,
    TicketPrice,
    TicketType,
    User,
)
from app.services.auth_service import create_session
from app.services.expense_service import (
    create_expense,
    decide_expense,
    record_reimbursement,
    submit_expense,
)
from app.services.finance_report_service import income_by_category
from app.services.merchandise_service import mark_collected
from app.services.purchase_service import (
    confirm_payment,
    create_membership_order,
    create_merchandise_order,
    create_ticket_order,
)
from app.services.refund_service import complete_manual_refund, decide_refund, request_refund
from tests.conftest import TEST_PASSWORD
from tests.test_merchandise_projects import _cleanup, _make_variant, _seed_committed_world

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
API = "/api/v1"


# ---------------------------------------------------------------- helpers


async def _as(client: AsyncClient, db: AsyncSession, user: User) -> dict[str, str]:
    """Authenticate the shared client as ``user`` without hitting the rate-limited login route."""
    settings = get_settings()
    session, raw = await create_session(db, user=user, settings=settings)
    client.cookies.clear()
    client.cookies.set(settings.session_cookie_name, raw)
    return {"X-CSRF-Token": session.csrf_token}


async def _new_user(db: AsyncSession, label: str, *, club_id: uuid.UUID | None = None) -> User:
    user = User(
        email=f"{label}-{uuid.uuid4().hex[:8]}@fin2.test",
        full_name=label.title(),
        password_hash=hash_password(TEST_PASSWORD),
    )
    db.add(user)
    await db.flush()
    if club_id is not None:
        db.add(ClubMember(club_id=club_id, user_id=user.id))
        await db.flush()
    return user


async def _grant(db: AsyncSession, *, club_id: uuid.UUID, user: User, code: str) -> None:
    role = await db.scalar(select(Role).where(Role.code == code))
    if role is None:
        role = Role(code=code, name=code)
        db.add(role)
        await db.flush()
    db.add(
        ClubRoleAssignment(
            club_id=club_id,
            user_id=user.id,
            role_id=role.id,
            starts_at=utcnow() - timedelta(days=1),
        )
    )
    await db.flush()


async def _plan(db: AsyncSession, club_id: uuid.UUID, amount: str = "100.00") -> MembershipPlan:
    plan = MembershipPlan(
        club_id=club_id,
        name=f"Plan-{uuid.uuid4().hex[:6]}",
        description="",
        dues_amount=Decimal(amount),
        duration_days=30,
        is_active=True,
    )
    db.add(plan)
    await db.flush()
    return plan


async def _refund_all_the_way(
    db: AsyncSession,
    *,
    club_id: uuid.UUID,
    order_id: uuid.UUID,
    buyer_id: uuid.UUID,
    staff_id: uuid.UUID,
    **complete_kwargs,
):
    refund = await request_refund(
        db, club_id=club_id, order_id=order_id, actor_user_id=buyer_id, reason="test"
    )
    await decide_refund(
        db, club_id=club_id, refund_id=refund.id, actor_user_id=staff_id, decision="approved"
    )
    return await complete_manual_refund(
        db,
        club_id=club_id,
        refund_id=refund.id,
        actor_user_id=staff_id,
        manual_reference="UPI-OUT-1",
        **complete_kwargs,
    )


# ---------------------------------------------------------------- expenses over HTTP


async def test_expense_http_flow_receipts_and_acl(
    client: AsyncClient, db: AsyncSession, world, tmp_path, monkeypatch
):
    settings = get_settings()
    monkeypatch.setattr(settings, "receipt_storage_dir", tmp_path)
    club_a, club_b = world["club_a"], world["club_b"]
    admin, member, other = world["admin"], world["member"], world["other"]
    finance = await _new_user(db, "finance", club_id=club_a.id)
    await _grant(db, club_id=club_a.id, user=finance, code=RoleCode.FINANCE_OFFICER.value)
    stranger = await _new_user(db, "stranger")  # member of no club

    # Member files an expense.
    h = await _as(client, db, member)
    r = await client.post(
        f"{API}/clubs/{club_a.id}/expenses",
        headers=h,
        json={
            "amount": "80.00",
            "expense_date": date.today().isoformat(),
            "category": "Supplies",
            "description": "Poster paper",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    expense_id = body["id"]
    assert body["status"] == "draft" and body["category"] == "supplies"
    base = f"{API}/clubs/{club_a.id}/expenses/{expense_id}"

    r = await client.patch(base, headers=h, json={"description": "Poster paper (A2)"})
    assert r.status_code == 200 and r.json()["description"] == "Poster paper (A2)"

    # Receipt upload: good, bad type, spoofed contents, oversize.
    r = await client.post(
        f"{base}/attachments", headers=h, files={"file": ("receipt.png", PNG, "image/png")}
    )
    assert r.status_code == 200, r.text
    att = r.json()
    assert "storage_key" not in att and att["byte_size"] == len(PNG)
    att_id = att["id"]
    r = await client.post(
        f"{base}/attachments",
        headers=h,
        files={"file": ("x.exe", b"MZ" + b"\x00" * 30, "application/x-msdownload")},
    )
    assert r.status_code == 415
    r = await client.post(
        f"{base}/attachments", headers=h, files={"file": ("fake.png", b"not a png", "image/png")}
    )
    assert r.status_code == 415
    monkeypatch.setattr(settings, "receipt_max_bytes", 50)
    r = await client.post(
        f"{base}/attachments", headers=h, files={"file": ("big.png", PNG, "image/png")}
    )
    assert r.status_code == 413
    monkeypatch.setattr(settings, "receipt_max_bytes", 5_000_000)
    assert len(list(tmp_path.rglob("*.png"))) == 1  # rejected uploads left nothing on disk

    # Other users cannot attach to someone else's expense.
    ho = await _as(client, db, other)
    r = await client.post(
        f"{base}/attachments", headers=ho, files={"file": ("r.png", PNG, "image/png")}
    )
    assert r.status_code in (403, 404)

    # Submit; financial fields freeze.
    h = await _as(client, db, member)
    r = await client.post(f"{base}/submit", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "submitted"
    r = await client.patch(base, headers=h, json={"amount": "90.00"})
    assert r.status_code == 409

    # Receipt ACL: submitter ok; plain member of the club, non-member: 403; wrong club: 404.
    dl = f"{base}/attachments/{att_id}/download"
    r = await client.get(dl)
    assert r.status_code == 200 and r.content == PNG
    assert r.headers["content-type"].startswith("image/png")
    ho = await _as(client, db, other)  # member of A without finance role
    assert (await client.get(dl)).status_code == 403
    assert (await client.get(base)).status_code == 403
    await _as(client, db, stranger)
    assert (await client.get(dl)).status_code == 403
    await _as(client, db, other)  # belongs to club B as well
    wrong_club = f"{API}/clubs/{club_b.id}/expenses/{expense_id}"
    assert (await client.get(wrong_club)).status_code == 404
    assert (await client.get(f"{wrong_club}/attachments/{att_id}/download")).status_code == 404
    r = await client.post(f"{wrong_club}/decide", headers=ho, json={"decision": "approved"})
    assert r.status_code in (403, 404)

    # Finance officer reviews: queue, approve (no ledger yet), reimburse.
    hf = await _as(client, db, finance)
    r = await client.get(f"{API}/clubs/{club_a.id}/expenses/queue")
    assert r.status_code == 200 and [e["id"] for e in r.json()] == [expense_id]
    assert (await client.get(dl)).status_code == 200
    r = await client.post(f"{base}/decide", headers=hf, json={"decision": "rejected"})
    assert r.status_code == 400  # reason required
    r = await client.post(f"{base}/decide", headers=hf, json={"decision": "approved"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    pending = await client.get(f"{API}/clubs/{club_a.id}/finance/pending-reimbursements")
    assert pending.status_code == 200 and pending.json()["total"] == "80.00"

    r = await client.post(f"{base}/reimburse", headers=hf, json={"payment_reference": "UPI-777"})
    assert r.status_code == 200, r.text
    reimb_id = r.json()["id"]
    assert r.json()["amount"] == "80.00"
    r = await client.post(f"{base}/reimburse", headers=hf, json={"payment_reference": "UPI-888"})
    assert r.status_code == 409

    # Journal line exists and balances (cash credit / expense debit).
    lines = (
        await db.execute(
            text(
                """
                SELECT a.code, jl.debit, jl.credit
                FROM journal_lines jl
                JOIN journal_entries je ON je.id = jl.entry_id
                JOIN accounts a ON a.id = jl.account_id
                WHERE je.source_event_key = :k
                """
            ),
            {"k": f"reimbursement:{reimb_id}"},
        )
    ).all()
    assert len(lines) == 2
    assert {row.code for row in lines} == {"expense_general", "cash"}
    assert sum(row.debit for row in lines) == sum(row.credit for row in lines) == Decimal("80.00")

    # Reports (cash basis) for a viewer; denied for an ordinary member.
    r = await client.get(f"{API}/clubs/{club_a.id}/finance/spending")
    assert r.status_code == 200
    assert r.json()["basis"] == "cash"
    assert [(x["category"], x["amount"]) for x in r.json()["rows"]] == [("supplies", "80.00")]
    r = await client.post(
        f"{API}/clubs/{club_a.id}/finance/budgets",
        headers=hf,
        json={
            "category": "supplies",
            "period_start": date.today().replace(day=1).isoformat(),
            "period_end": (date.today() + timedelta(days=60)).isoformat(),
            "limit_amount": "200.00",
        },
    )
    assert r.status_code == 200, r.text
    r = await client.get(f"{API}/clubs/{club_a.id}/finance/budget-vs-actual")
    row = r.json()["rows"][0]
    assert row["actual_amount"] == "80.00" and row["remaining_amount"] == "120.00"
    assert row["percent_used"] == "40.00"

    h = await _as(client, db, member)
    r = await client.get(base)
    assert r.status_code == 200
    assert r.json()["status"] == "reimbursed" and r.json()["reimbursement"]["id"] == reimb_id
    assert (await client.get(f"{API}/clubs/{club_a.id}/finance/spending")).status_code == 403
    r = await client.post(
        f"{API}/clubs/{club_a.id}/finance/budgets",
        headers=h,
        json={
            "category": "x",
            "period_start": "2026-01-01",
            "period_end": "2026-12-31",
            "limit_amount": "1.00",
        },
    )
    assert r.status_code == 403
    r = await client.get(f"{API}/clubs/{club_a.id}/expenses/queue")
    assert r.status_code == 403
    assert admin.id != member.id


async def test_expense_self_approval_forbidden_over_http(
    client: AsyncClient, db: AsyncSession, world
):
    club = world["club_a"]
    admin = world["admin"]
    h = await _as(client, db, admin)
    r = await client.post(
        f"{API}/clubs/{club.id}/expenses",
        headers=h,
        json={
            "amount": "25.00",
            "expense_date": date.today().isoformat(),
            "description": "Own purchase",
        },
    )
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    r = await client.post(f"{API}/clubs/{club.id}/expenses/{eid}/submit", headers=h)
    assert r.status_code == 200
    r = await client.post(
        f"{API}/clubs/{club.id}/expenses/{eid}/decide", headers=h, json={"decision": "approved"}
    )
    assert r.status_code == 403
    assert "Self-approval" in r.json()["message"]
    # Still submitted; no journal posted.
    detail = await client.get(f"{API}/clubs/{club.id}/expenses/{eid}")
    assert detail.json()["status"] == "submitted"


# ---------------------------------------------------------------- refunds over HTTP


async def test_membership_refund_http_revokes_entitlement_and_reverses_ledger(
    client: AsyncClient, db: AsyncSession, world
):
    club_a, club_b = world["club_a"], world["club_b"]
    admin, member, other = world["admin"], world["member"], world["other"]
    plan = await _plan(db, club_a.id, "100.00")

    hm = await _as(client, db, member)
    r = await client.post(
        f"{API}/clubs/{club_a.id}/orders/membership", headers=hm, json={"plan_id": str(plan.id)}
    )
    assert r.status_code == 200, r.text
    order_id = uuid.UUID(r.json()["id"])

    ha = await _as(client, db, admin)
    r = await client.post(
        f"{API}/orders/{order_id}/pay/manual", headers=ha, json={"provider_ref": "CASH-1"}
    )
    assert r.status_code == 200 and r.json()["status"] == "paid"
    membership = await db.scalar(
        select(Membership).where(Membership.club_id == club_a.id, Membership.user_id == member.id)
    )
    assert membership is not None and membership.status == "active"
    income = (await client.get(f"{API}/clubs/{club_a.id}/finance/income")).json()
    assert [(x["category"], x["amount"]) for x in income["rows"]] == [("membership_income", "100.00")]

    # Buyer requests; nothing changes yet.
    hm = await _as(client, db, member)
    r = await client.post(
        f"{API}/clubs/{club_a.id}/refunds",
        headers=hm,
        json={"order_id": str(order_id), "reason": "changed my mind"},
    )
    assert r.status_code == 200, r.text
    refund = r.json()
    refund_id = refund["id"]
    assert refund["status"] == "requested" and refund["amount"] == "100.00"
    await db.refresh(membership)
    assert membership.status == "active"
    r = await client.post(
        f"{API}/clubs/{club_a.id}/refunds", headers=hm, json={"order_id": str(order_id)}
    )
    assert r.status_code == 409
    mine = await client.get(f"{API}/clubs/{club_a.id}/refunds/mine")
    assert [x["id"] for x in mine.json()] == [refund_id]

    # Buyer cannot decide/complete/list; outsiders cannot even request.
    base = f"{API}/clubs/{club_a.id}/refunds/{refund_id}"
    assert (await client.post(f"{base}/decide", headers=hm, json={"decision": "approved"})).status_code == 403
    done_body = {"manual_reference": "UPI-REFUND-1", "idempotency_key": "key-1"}
    assert (await client.post(f"{base}/complete", headers=hm, json=done_body)).status_code == 403
    assert (await client.get(f"{API}/clubs/{club_a.id}/refunds")).status_code == 403
    ho = await _as(client, db, other)
    r = await client.post(
        f"{API}/clubs/{club_a.id}/refunds", headers=ho, json={"order_id": str(order_id)}
    )
    assert r.status_code == 403
    # Cross-club: the order is not visible under club B.
    r = await client.post(
        f"{API}/clubs/{club_b.id}/refunds", headers=ho, json={"order_id": str(order_id)}
    )
    assert r.status_code == 404

    # Staff: cannot complete before approval; request alone never completes.
    ha = await _as(client, db, admin)
    assert (await client.post(f"{base}/complete", headers=ha, json=done_body)).status_code == 409
    listed = await client.get(f"{API}/clubs/{club_a.id}/refunds", params={"status": "requested"})
    assert [x["id"] for x in listed.json()] == [refund_id]
    r = await client.post(f"{base}/decide", headers=ha, json={"decision": "approved"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    r = await client.post(f"{base}/complete", headers=ha, json={"manual_reference": " "})
    assert r.status_code == 400 and r.json()["code"] == "reference_required"
    r = await client.post(f"{base}/complete", headers=ha, json=done_body)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed" and r.json()["manual_reference"] == "UPI-REFUND-1"
    # Same key replays; a different key conflicts.
    assert (await client.post(f"{base}/complete", headers=ha, json=done_body)).status_code == 200
    r = await client.post(
        f"{base}/complete", headers=ha, json={"manual_reference": "X", "idempotency_key": "key-2"}
    )
    assert r.status_code == 409

    # Entitlements, order, payment, ledger.
    await db.refresh(membership)
    assert membership.status == "revoked"
    order = await db.get(Order, order_id)
    payment = await db.scalar(select(Payment).where(Payment.order_id == order_id))
    await db.refresh(order)
    await db.refresh(payment)
    assert order.status == "refunded" and payment.status == "refunded"
    reversal = await db.scalar(
        select(JournalEntry).where(JournalEntry.source_event_key == f"refund_completed:{refund_id}")
    )
    assert reversal is not None and reversal.status == "posted"
    original = await db.scalar(
        select(JournalEntry).where(JournalEntry.source_event_key == f"payment_confirmed:{payment.id}")
    )
    await db.refresh(original)
    assert original.status == "reversed" and reversal.reverses_entry_id == original.id

    income = (await client.get(f"{API}/clubs/{club_a.id}/finance/income")).json()
    assert [(x["category"], x["amount"]) for x in income["rows"]] == [("membership_income", "0.00")]
    cash = (await client.get(f"{API}/clubs/{club_a.id}/finance/cash-balances")).json()
    balances = {b["code"]: (b["balance"], b["simulated"]) for b in cash["balances"]}
    assert balances["cash"] == ("0.00", False)
    assert cash["basis"] == "cash"


# ---------------------------------------------------------------- refunds at service level


async def test_ticket_refund_requires_ack_for_used_ticket(db: AsyncSession, world):
    club, admin, member = world["club_a"], world["admin"], world["member"]
    now = utcnow()
    event = Event(
        club_id=club.id,
        title="Hack Night",
        description="",
        venue="Lab",
        starts_at=now + timedelta(days=1),
        ends_at=now + timedelta(days=1, hours=2),
        capacity=10,
        status="published",
        created_by_user_id=admin.id,
    )
    db.add(event)
    await db.flush()
    ttype = TicketType(event_id=event.id, name="General", description="")
    db.add(ttype)
    await db.flush()
    price = TicketPrice(ticket_type_id=ttype.id, audience="public", amount=Decimal("40.00"))
    db.add(price)
    await db.flush()

    order = await create_ticket_order(
        db, club_id=club.id, user_id=member.id, ticket_price_id=price.id, quantity=2
    )
    paid = await confirm_payment(
        db, order_id=order.id, actor_user_id=member.id, method="demo", success=True
    )
    assert paid.status == "paid"
    item_id = paid.items[0].id
    tickets = list(
        (await db.scalars(select(Ticket).where(Ticket.order_item_id == item_id).order_by(Ticket.unit_index))).all()
    )
    assert [t.status for t in tickets] == ["valid", "valid"]
    tickets[0].status = "used"
    db.add(TicketCheckin(ticket_id=tickets[0].id, event_id=event.id, checked_in_by_user_id=admin.id))
    await db.flush()

    refund = await request_refund(
        db, club_id=club.id, order_id=order.id, actor_user_id=member.id, reason="cannot attend"
    )
    await decide_refund(
        db, club_id=club.id, refund_id=refund.id, actor_user_id=admin.id, decision="approved"
    )
    with pytest.raises(ConflictError) as ei:
        await complete_manual_refund(
            db,
            club_id=club.id,
            refund_id=refund.id,
            actor_user_id=admin.id,
            manual_reference="UPI-T-1",
        )
    assert ei.value.code == "used_ticket_ack_required"
    await db.refresh(order)
    await db.refresh(refund)
    assert order.status == "paid" and refund.status == "approved"
    assert all(t.status != "cancelled" for t in tickets)

    done = await complete_manual_refund(
        db,
        club_id=club.id,
        refund_id=refund.id,
        actor_user_id=admin.id,
        manual_reference="UPI-T-1",
        acknowledge_used=True,
    )
    assert done.status == "completed" and done.acknowledge_used is True
    for t in tickets:
        await db.refresh(t)
        assert t.status == "cancelled"
    await db.refresh(order)
    assert order.status == "refunded"
    # Demo collections stay out of income unless explicitly included.
    default = await income_by_category(db, club_id=club.id)
    assert default == []
    demo = await income_by_category(db, club_id=club.id, include_demo=True)
    assert [(r.category, r.amount) for r in demo] == [("ticket_income", Decimal("0.00"))]


async def test_merch_refund_restock_rules(db: AsyncSession, world):
    club, admin, member = world["club_a"], world["admin"], world["member"]
    variant = await _make_variant(db, club_id=club.id, admin_id=admin.id, stock=5)

    async def buy() -> Order:
        order = await create_merchandise_order(
            db, club_id=club.id, user_id=member.id, product_variant_id=variant.id, quantity=1
        )
        return await confirm_payment(
            db, order_id=order.id, actor_user_id=member.id, method="demo", success=True
        )

    async def on_hand() -> int:
        await db.refresh(variant)
        return variant.quantity_on_hand

    # Awaiting collection → cancelled and restocked.
    o1 = await buy()
    assert await on_hand() == 4
    await _refund_all_the_way(
        db, club_id=club.id, order_id=o1.id, buyer_id=member.id, staff_id=admin.id
    )
    assert await on_hand() == 5
    await db.refresh(o1.items[0])
    assert o1.items[0].fulfillment_status == "cancelled"
    movement = await db.scalar(
        select(InventoryMovement).where(
            InventoryMovement.order_item_id == o1.items[0].id, InventoryMovement.reason == "adjust"
        )
    )
    assert movement is not None and movement.note == "refund return" and movement.delta_on_hand == 1

    # Collected, no physical return → cancelled, not restocked.
    o2 = await buy()
    await mark_collected(db, club_id=club.id, actor_user_id=admin.id, order_item_id=o2.items[0].id)
    assert await on_hand() == 4
    await _refund_all_the_way(
        db, club_id=club.id, order_id=o2.id, buyer_id=member.id, staff_id=admin.id
    )
    assert await on_hand() == 4
    await db.refresh(o2.items[0])
    assert o2.items[0].fulfillment_status == "cancelled"

    # Collected with physical return → restocked.
    o3 = await buy()
    await mark_collected(db, club_id=club.id, actor_user_id=admin.id, order_item_id=o3.items[0].id)
    assert await on_hand() == 3
    await _refund_all_the_way(
        db,
        club_id=club.id,
        order_id=o3.id,
        buyer_id=member.id,
        staff_id=admin.id,
        physical_return=True,
    )
    assert await on_hand() == 4


async def test_refund_required_payment_is_journaled_then_reversed(db: AsyncSession, world):
    club, admin, member = world["club_a"], world["admin"], world["member"]
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
    await db.flush()  # sessions here run with autoflush off; requests normally commit first
    payment = await db.scalar(select(Payment).where(Payment.order_id == order.id))
    assert payment.status == "refund_required"

    refund = await _refund_all_the_way(
        db, club_id=club.id, order_id=order.id, buyer_id=member.id, staff_id=admin.id
    )
    await db.refresh(order)
    await db.refresh(payment)
    assert order.status == "refunded" and payment.status == "refunded"
    keys = {
        e.source_event_key: e.status
        for e in (
            await db.scalars(select(JournalEntry).where(JournalEntry.club_id == club.id))
        ).all()
    }
    assert keys[f"payment_confirmed:{payment.id}"] == "reversed"
    assert keys[f"refund_completed:{refund.id}"] == "posted"
    await db.refresh(variant)
    assert variant.quantity_on_hand == 1  # nothing was ever sold, nothing to restock


async def test_refund_validation_rules(db: AsyncSession, world):
    club, admin, member = world["club_a"], world["admin"], world["member"]
    plan = await _plan(db, club.id, "60.00")
    pending = await create_membership_order(db, club_id=club.id, user_id=member.id, plan_id=plan.id)
    # Unpaid orders are not refundable.
    with pytest.raises(ConflictError) as ei:
        await request_refund(db, club_id=club.id, order_id=pending.id, actor_user_id=member.id)
    assert ei.value.code == "order_not_refundable"

    await confirm_payment(
        db, order_id=pending.id, actor_user_id=member.id, method="demo", success=True
    )
    refund = await request_refund(db, club_id=club.id, order_id=pending.id, actor_user_id=member.id)
    # Buyer is not staff, and staff may not approve a refund they requested.
    from app.core.errors import AppError, ForbiddenError

    with pytest.raises(ForbiddenError):
        await decide_refund(
            db, club_id=club.id, refund_id=refund.id, actor_user_id=member.id, decision="approved"
        )
    with pytest.raises(AppError) as ae:
        await decide_refund(
            db, club_id=club.id, refund_id=refund.id, actor_user_id=admin.id, decision="rejected"
        )
    assert ae.value.code == "reason_required"
    rejected = await decide_refund(
        db,
        club_id=club.id,
        refund_id=refund.id,
        actor_user_id=admin.id,
        decision="rejected",
        reason="outside window",
    )
    assert rejected.status == "rejected"
    with pytest.raises(ConflictError):
        await complete_manual_refund(
            db,
            club_id=club.id,
            refund_id=refund.id,
            actor_user_id=admin.id,
            manual_reference="X",
        )
    # A rejected request frees the payment for a new one.
    again = await request_refund(db, club_id=club.id, order_id=pending.id, actor_user_id=member.id)
    assert again.id != refund.id and again.status == "requested"
    await db.refresh(pending)
    assert pending.status == "paid"


# ---------------------------------------------------------------- concurrency (committed data)


async def _cleanup_finance(
    engine: AsyncEngine, *, club_ids: list[uuid.UUID], user_ids: list[uuid.UUID]
) -> None:
    async with AsyncSession(engine, expire_on_commit=False, autoflush=False) as db:
        for c in club_ids:
            params = {"c": c}
            for stmt in (
                "DELETE FROM refunds WHERE club_id = :c",
                "DELETE FROM memberships WHERE club_id = :c",
                "DELETE FROM journal_lines WHERE entry_id IN "
                "(SELECT id FROM journal_entries WHERE club_id = :c)",
                "DELETE FROM journal_entries WHERE club_id = :c",
                "DELETE FROM accounts WHERE club_id = :c",
                "DELETE FROM reimbursements WHERE club_id = :c",
                "DELETE FROM expense_approvals WHERE expense_id IN "
                "(SELECT id FROM expenses WHERE club_id = :c)",
                "DELETE FROM expense_attachments WHERE expense_id IN "
                "(SELECT id FROM expenses WHERE club_id = :c)",
                "DELETE FROM expenses WHERE club_id = :c",
                "DELETE FROM payment_events WHERE payment_id IN "
                "(SELECT p.id FROM payments p JOIN orders o ON o.id = p.order_id WHERE o.club_id = :c)",
                "DELETE FROM payments WHERE order_id IN (SELECT id FROM orders WHERE club_id = :c)",
                "DELETE FROM order_items WHERE order_id IN (SELECT id FROM orders WHERE club_id = :c)",
                "DELETE FROM orders WHERE club_id = :c",
                "DELETE FROM membership_plans WHERE club_id = :c",
            ):
                await db.execute(text(stmt), params)
        await db.commit()
    await _cleanup(engine, club_ids=club_ids, user_ids=user_ids)


async def _run_two(factory, fn_a, fn_b) -> list[str]:
    results: list[str] = []
    ready = asyncio.Event()
    started = 0
    guard = asyncio.Lock()

    async def runner(fn):
        nonlocal started
        session = factory()
        try:
            async with guard:
                started += 1
                if started == 2:
                    ready.set()
            await ready.wait()
            await fn(session)
            await session.commit()
            results.append("ok")
        except Exception as exc:  # noqa: BLE001
            await session.rollback()
            results.append(getattr(exc, "code", None) or type(exc).__name__)
        finally:
            await session.close()

    await asyncio.gather(runner(fn_a), runner(fn_b))
    return results


async def test_concurrent_double_reimburse_one_wins(engine: AsyncEngine):
    seeded = await _seed_committed_world(engine)
    Session = async_sessionmaker(
        bind=engine, class_=AsyncSession, autoflush=False, expire_on_commit=False
    )
    club_id, admin_id, user_a = seeded["club_id"], seeded["admin_id"], seeded["user_a"]
    try:
        async with Session() as db:
            expense = await create_expense(
                db,
                club_id=club_id,
                submitter_user_id=user_a,
                amount=Decimal("45.00"),
                currency="INR",
                expense_date=date.today(),
                category="food",
                description="Snacks",
            )
            await submit_expense(db, club_id=club_id, expense_id=expense.id, actor_user_id=user_a)
            await decide_expense(
                db,
                club_id=club_id,
                expense_id=expense.id,
                actor_user_id=admin_id,
                decision="approved",
            )
            await db.commit()
            expense_id = expense.id

        def pay(ref: str):
            async def _go(session: AsyncSession) -> None:
                await record_reimbursement(
                    session,
                    club_id=club_id,
                    expense_id=expense_id,
                    actor_user_id=admin_id,
                    payment_reference=ref,
                )

            return _go

        results = await _run_two(Session, pay("UPI-A"), pay("UPI-B"))
        assert results.count("ok") == 1, results
        async with Session() as verify:
            count = await verify.scalar(
                text("SELECT count(*) FROM reimbursements WHERE expense_id = :e"), {"e": expense_id}
            )
            entries = await verify.scalar(
                text(
                    "SELECT count(*) FROM journal_entries "
                    "WHERE club_id = :c AND source_type = 'reimbursement'"
                ),
                {"c": club_id},
            )
        assert count == 1 and entries == 1
    finally:
        await _cleanup_finance(
            engine,
            club_ids=[seeded["club_id"], seeded["other_club_id"]],
            user_ids=[seeded[k] for k in ("admin_id", "user_a", "user_b", "outsider_id")],
        )


async def test_concurrent_double_refund_complete_one_wins(engine: AsyncEngine):
    seeded = await _seed_committed_world(engine)
    Session = async_sessionmaker(
        bind=engine, class_=AsyncSession, autoflush=False, expire_on_commit=False
    )
    club_id, admin_id, user_a = seeded["club_id"], seeded["admin_id"], seeded["user_a"]
    try:
        async with Session() as db:
            plan = await _plan(db, club_id, "75.00")
            order = await create_membership_order(
                db, club_id=club_id, user_id=user_a, plan_id=plan.id
            )
            await confirm_payment(
                db, order_id=order.id, actor_user_id=user_a, method="demo", success=True
            )
            refund = await request_refund(
                db, club_id=club_id, order_id=order.id, actor_user_id=user_a
            )
            await decide_refund(
                db,
                club_id=club_id,
                refund_id=refund.id,
                actor_user_id=admin_id,
                decision="approved",
            )
            await db.commit()
            refund_id, order_id = refund.id, order.id

        def finish(key: str):
            async def _go(session: AsyncSession) -> None:
                await complete_manual_refund(
                    session,
                    club_id=club_id,
                    refund_id=refund_id,
                    actor_user_id=admin_id,
                    manual_reference=f"REF-{key}",
                    idempotency_key=key,
                )

            return _go

        results = await _run_two(Session, finish("k-one"), finish("k-two"))
        assert sorted(results) == ["ok", "refund_already_completed"], results
        async with Session() as verify:
            reversals = await verify.scalar(
                text(
                    "SELECT count(*) FROM journal_entries "
                    "WHERE club_id = :c AND source_type = 'refund_completed'"
                ),
                {"c": club_id},
            )
            status = await verify.scalar(select(Order.status).where(Order.id == order_id))
            revoked = await verify.scalar(
                text("SELECT count(*) FROM memberships WHERE club_id = :c AND status = 'revoked'"),
                {"c": club_id},
            )
            completed = await verify.scalar(
                text("SELECT count(*) FROM refunds WHERE id = :r AND status = 'completed'"),
                {"r": refund_id},
            )
        assert reversals == 1 and status == "refunded" and revoked == 1 and completed == 1
    finally:
        await _cleanup_finance(
            engine,
            club_ids=[seeded["club_id"], seeded["other_club_id"]],
            user_ids=[seeded[k] for k in ("admin_id", "user_a", "user_b", "outsider_id")],
        )
