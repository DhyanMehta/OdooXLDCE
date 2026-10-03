"""Repeatable development seed.

Run (venv active, migrations applied):
  campusos-seed
  python -m app.seed

Refuses to run when APP_ENV is production/prod.
Membership dates use a fixed SEED_EPOCH so re-runs do not create duplicates.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.core.config import get_settings
from app.core.permissions import RoleCode
from app.core.security import generate_token, hash_password, hash_token
from app.core.time import utcnow
from app.core.tokens import seal_token, unseal_token
from app.db.session import dispose_engine, get_session_factory

from app.models import (
    Announcement,
    Club,
    ClubMember,
    ClubRoleAssignment,
    Event,
    InventoryMovement,
    MailingListSubscription,
    Membership,
    MembershipPlan,
    Order,
    OrderItem,
    Payment,
    Product,
    ProductVariant,
    Project,
    Role,
    Task,
    Ticket,
    TicketPrice,
    TicketType,
    User,
)
from app.services.ledger_service import post_payment_confirmation

DEMO_PASSWORD = "Password123!"
# Stable calendar anchor — membership lookups use these exact timestamps, not "now".
SEED_EPOCH = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


async def _user(db: AsyncSession, email: str, name: str) -> User:
    user = await db.scalar(select(User).where(User.email == email))
    if user:
        return user
    password_hash = await asyncio.to_thread(hash_password, DEMO_PASSWORD)
    user = User(email=email, full_name=name, password_hash=password_hash)
    db.add(user)
    await db.flush()
    return user


async def _role(db: AsyncSession, code: str, name: str) -> Role:
    role = await db.scalar(select(Role).where(Role.code == code))
    if role:
        return role
    role = Role(code=code, name=name)
    db.add(role)
    await db.flush()
    return role


async def _assign(db: AsyncSession, club_id, user_id, role_id, starts_at, ends_at=None, assigned_by=None):
    existing = await db.scalar(
        select(ClubRoleAssignment).where(
            ClubRoleAssignment.club_id == club_id,
            ClubRoleAssignment.user_id == user_id,
            ClubRoleAssignment.role_id == role_id,
            ClubRoleAssignment.starts_at == starts_at,
        )
    )
    if existing:
        return existing
    if ends_at is None:
        open_row = await db.scalar(
            select(ClubRoleAssignment).where(
                ClubRoleAssignment.club_id == club_id,
                ClubRoleAssignment.user_id == user_id,
                ClubRoleAssignment.role_id == role_id,
                ClubRoleAssignment.ends_at.is_(None),
            )
        )
        if open_row:
            return open_row
    row = ClubRoleAssignment(
        club_id=club_id,
        user_id=user_id,
        role_id=role_id,
        starts_at=starts_at,
        ends_at=ends_at,
        assigned_by_user_id=assigned_by,
    )
    db.add(row)
    await db.flush()
    return row


async def main_async() -> None:
    settings = get_settings()
    if settings.is_production():
        print("Refusing to seed: APP_ENV is production.", file=sys.stderr)
        raise SystemExit(2)

    now = utcnow()
    factory = get_session_factory()
    async with factory() as db:
        roles = {
            RoleCode.CLUB_ADMIN.value: await _role(db, RoleCode.CLUB_ADMIN.value, "Club Administrator"),
            RoleCode.MEMBERSHIP_MANAGER.value: await _role(
                db, RoleCode.MEMBERSHIP_MANAGER.value, "Membership Manager"
            ),
            RoleCode.EVENT_ORGANIZER.value: await _role(
                db, RoleCode.EVENT_ORGANIZER.value, "Event Organizer"
            ),
            RoleCode.COMMUNICATIONS_OFFICER.value: await _role(
                db, RoleCode.COMMUNICATIONS_OFFICER.value, "Communications Officer"
            ),
            RoleCode.FINANCE_OFFICER.value: await _role(
                db, RoleCode.FINANCE_OFFICER.value, "Finance Officer"
            ),
        }

        tech = await db.scalar(select(Club).where(Club.slug == "tech-club"))
        if tech is None:
            tech = Club(
                slug="tech-club",
                name="Tech Club",
                description="Builds software, hosts hack nights, and runs campus tech events.",
            )
            db.add(tech)
            await db.flush()
        arts = await db.scalar(select(Club).where(Club.slug == "arts-club"))
        if arts is None:
            arts = Club(
                slug="arts-club",
                name="Arts Club",
                description="Creative community for design, music, and exhibitions.",
            )
            db.add(arts)
            await db.flush()

        admin = await _user(db, "admin@techclub.edu", "Asha Admin")
        membership_mgr = await _user(db, "membership@techclub.edu", "Milan Membership")
        events_mgr = await _user(db, "events@techclub.edu", "Evan Events")
        comms = await _user(db, "comms@techclub.edu", "Cora Comms")
        finance_officer = await _user(db, "finance@techclub.edu", "Fiona Finance")
        member = await _user(db, "member@techclub.edu", "Ordinary Member")
        expired_user = await _user(db, "expired@techclub.edu", "Expired Member")
        outsider = await _user(db, "buyer@example.com", "Public Buyer")
        arts_admin = await _user(db, "admin@artsclub.edu", "Arts Admin")

        for club, users in (
            (
                tech,
                [admin, membership_mgr, events_mgr, comms, finance_officer, member, expired_user, outsider],
            ),
            (arts, [arts_admin, outsider]),
        ):
            for u in users:
                if (
                    await db.scalar(
                        select(ClubMember).where(
                            ClubMember.club_id == club.id, ClubMember.user_id == u.id
                        )
                    )
                    is None
                ):
                    db.add(ClubMember(club_id=club.id, user_id=u.id))

        await _assign(
            db,
            tech.id,
            admin.id,
            roles[RoleCode.CLUB_ADMIN.value].id,
            SEED_EPOCH - timedelta(days=90),
        )
        # Historical leadership for handover demos (stable dates).
        await _assign(
            db,
            tech.id,
            membership_mgr.id,
            roles[RoleCode.MEMBERSHIP_MANAGER.value].id,
            SEED_EPOCH - timedelta(days=60),
            ends_at=SEED_EPOCH - timedelta(days=1),
            assigned_by=admin.id,
        )
        await _assign(
            db,
            tech.id,
            membership_mgr.id,
            roles[RoleCode.MEMBERSHIP_MANAGER.value].id,
            SEED_EPOCH - timedelta(days=1),
            assigned_by=admin.id,
        )
        await _assign(
            db,
            tech.id,
            events_mgr.id,
            roles[RoleCode.EVENT_ORGANIZER.value].id,
            SEED_EPOCH - timedelta(days=30),
        )
        await _assign(
            db,
            tech.id,
            comms.id,
            roles[RoleCode.COMMUNICATIONS_OFFICER.value].id,
            SEED_EPOCH - timedelta(days=30),
        )
        await _assign(
            db,
            tech.id,
            finance_officer.id,
            roles[RoleCode.FINANCE_OFFICER.value].id,
            SEED_EPOCH - timedelta(days=30),
            assigned_by=admin.id,
        )
        await _assign(
            db,
            arts.id,
            arts_admin.id,
            roles[RoleCode.CLUB_ADMIN.value].id,
            SEED_EPOCH - timedelta(days=20),
        )

        annual = await db.scalar(
            select(MembershipPlan).where(
                MembershipPlan.club_id == tech.id, MembershipPlan.name == "Annual"
            )
        )
        if annual is None:
            annual = MembershipPlan(
                club_id=tech.id,
                name="Annual",
                description="12-month membership. Benefit: discounted member event tickets.",
                dues_amount=Decimal("500.00"),
                duration_days=365,
                is_active=True,
            )
            db.add(annual)
            await db.flush()
        semester = await db.scalar(
            select(MembershipPlan).where(
                MembershipPlan.club_id == tech.id, MembershipPlan.name == "Semester"
            )
        )
        if semester is None:
            semester = MembershipPlan(
                club_id=tech.id,
                name="Semester",
                description="Semester membership with member ticket pricing.",
                dues_amount=Decimal("250.00"),
                duration_days=120,
                is_active=True,
            )
            db.add(semester)
            await db.flush()

        async def ensure_membership(user, plan, starts: datetime, ends: datetime, status="active"):
            """Idempotent by (user, club, plan, starts_at) — starts_at must be stable."""
            existing = await db.scalar(
                select(Membership).where(
                    Membership.user_id == user.id,
                    Membership.club_id == tech.id,
                    Membership.plan_id == plan.id,
                    Membership.starts_at == starts,
                )
            )
            if existing:
                return existing
            order = Order(
                club_id=tech.id,
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
                fixed_expires_on_snapshot=plan.fixed_expires_on,
            )
            db.add(item)
            payment = Payment(
                order_id=order.id,
                amount=plan.dues_amount,
                method="manual",
                status="confirmed",
                confirmed_at=starts,
                confirmed_by_user_id=membership_mgr.id,
                provider_ref="seed-membership",
            )
            db.add(payment)
            await db.flush()
            order_loaded = (
                await db.scalars(
                    select(Order)
                    .options(joinedload(Order.items))
                    .where(Order.id == order.id)
                )
            ).unique().one()
            # Cash-basis ledger: seed dues as recorded manual collection (not demo_clearing).
            await post_payment_confirmation(db, order=order_loaded, payment=payment)
            m = Membership(
                club_id=tech.id,
                user_id=user.id,
                plan_id=plan.id,
                order_item_id=item.id,
                starts_at=starts,
                ends_at=ends,
                status=status,
            )
            db.add(m)
            await db.flush()
            return m

        # Active through late 2026 / early 2027 relative to SEED_EPOCH.
        await ensure_membership(
            member, annual, SEED_EPOCH - timedelta(days=30), SEED_EPOCH + timedelta(days=335)
        )
        await ensure_membership(
            admin, annual, SEED_EPOCH - timedelta(days=20), SEED_EPOCH + timedelta(days=345)
        )
        await ensure_membership(
            events_mgr,
            semester,
            SEED_EPOCH - timedelta(days=10),
            SEED_EPOCH + timedelta(days=110),
        )
        # Always expired relative to Oct 2026+.
        await ensure_membership(
            expired_user,
            semester,
            datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
            datetime(2025, 5, 1, 12, 0, tzinfo=timezone.utc),
            status="active",
        )

        meetup = await db.scalar(
            select(Event).where(Event.club_id == tech.id, Event.title == "Spring Hack Night")
        )
        if meetup is None:
            meetup = Event(
                club_id=tech.id,
                title="Spring Hack Night",
                description="Build with friends. Members get discounted tickets.",
                venue="Innovation Lab",
                starts_at=now + timedelta(days=14),
                ends_at=now + timedelta(days=14, hours=4),
                capacity=100,
                status="published",
                sales_opens_at=now - timedelta(days=7),
                sales_closes_at=now + timedelta(days=13),
                created_by_user_id=events_mgr.id,
            )
            db.add(meetup)
            await db.flush()
            tt = TicketType(event_id=meetup.id, name="General Admission", description="Entry")
            db.add(tt)
            await db.flush()
            db.add(TicketPrice(ticket_type_id=tt.id, audience="member", amount=Decimal("100.00")))
            db.add(TicketPrice(ticket_type_id=tt.id, audience="public", amount=Decimal("200.00")))

        limited = await db.scalar(
            select(Event).where(Event.club_id == tech.id, Event.title == "Tiny Workshop")
        )
        if limited is None:
            limited = Event(
                club_id=tech.id,
                title="Tiny Workshop",
                description="Capacity-limited workshop for concurrency demos.",
                venue="Room 12",
                starts_at=now + timedelta(days=7),
                ends_at=now + timedelta(days=7, hours=2),
                capacity=2,
                status="published",
                sales_opens_at=now - timedelta(days=1),
                sales_closes_at=now + timedelta(days=6),
                created_by_user_id=events_mgr.id,
            )
            db.add(limited)
            await db.flush()
            tt = TicketType(event_id=limited.id, name="Seat", description="One seat")
            db.add(tt)
            await db.flush()
            db.add(TicketPrice(ticket_type_id=tt.id, audience="member", amount=Decimal("50.00")))
            db.add(TicketPrice(ticket_type_id=tt.id, audience="public", amount=Decimal("80.00")))

        # Live demo event inside the default check-in window (no override needed).
        live = await db.scalar(
            select(Event).where(Event.club_id == tech.id, Event.title == "CampusOS Live Check-in")
        )
        if live is None:
            live = Event(
                club_id=tech.id,
                title="CampusOS Live Check-in",
                description="Seeded for mentor demos: already open for check-in (no window override).",
                venue="Demo Hall",
                starts_at=now - timedelta(minutes=30),
                ends_at=now + timedelta(hours=3),
                capacity=50,
                status="published",
                sales_opens_at=now - timedelta(days=1),
                sales_closes_at=now + timedelta(hours=2),
                created_by_user_id=events_mgr.id,
            )
            db.add(live)
            await db.flush()
            tt = TicketType(event_id=live.id, name="Demo Entry", description="Check-in demo")
            db.add(tt)
            await db.flush()
            db.add(TicketPrice(ticket_type_id=tt.id, audience="member", amount=Decimal("10.00")))
            db.add(TicketPrice(ticket_type_id=tt.id, audience="public", amount=Decimal("20.00")))

        live_price = await db.scalar(
            select(TicketPrice)
            .join(TicketType)
            .where(TicketType.event_id == live.id, TicketPrice.audience == "member")
        )
        if live_price and await db.scalar(
            select(Ticket).where(Ticket.user_id == member.id, Ticket.event_id == live.id)
        ) is None:
            order = Order(
                club_id=tech.id,
                user_id=member.id,
                status="paid",
                total_amount=live_price.amount,
                currency="INR",
            )
            db.add(order)
            await db.flush()
            item = OrderItem(
                order_id=order.id,
                item_kind="ticket",
                ticket_price_id=live_price.id,
                quantity=1,
                unit_price_snapshot=live_price.amount,
                title_snapshot="CampusOS Live Check-in — Demo Entry",
                duration_days_snapshot=None,
                fixed_expires_on_snapshot=None,
            )
            db.add(item)
            payment = Payment(
                order_id=order.id,
                amount=live_price.amount,
                method="manual",
                status="confirmed",
                confirmed_at=now,
                provider_ref="seed-live-ticket",
            )
            db.add(payment)
            await db.flush()
            order_loaded = (
                await db.scalars(
                    select(Order).options(joinedload(Order.items)).where(Order.id == order.id)
                )
            ).unique().one()
            await post_payment_confirmation(db, order=order_loaded, payment=payment)
            raw = generate_token(24)
            ticket = Ticket(
                order_item_id=item.id,
                unit_index=0,
                event_id=live.id,
                club_id=tech.id,
                user_id=member.id,
                ticket_type_id=live_price.ticket_type_id,
                status="valid",
                qr_token_hash=hash_token(raw),
                qr_token_sealed=seal_token(raw),
            )
            db.add(ticket)
            await db.flush()
            # No pre-check-in: mentor walkthrough can scan twice (OK then duplicate).

        # Always print the live demo QR on re-seed (unseal existing ticket when present).
        live_ticket = await db.scalar(
            select(Ticket).where(Ticket.user_id == member.id, Ticket.event_id == live.id)
        )
        if live_ticket and live_ticket.qr_token_sealed:
            raw_live = unseal_token(live_ticket.qr_token_sealed)
            if raw_live:
                print(
                    f"Seed LIVE check-in QR (member@techclub.edu, CampusOS Live Check-in, "
                    f"status={live_ticket.status}): {raw_live}"
                )

        if (
            await db.scalar(
                select(Announcement).where(
                    Announcement.club_id == tech.id, Announcement.title == "Welcome"
                )
            )
            is None
        ):
            db.add(
                Announcement(
                    club_id=tech.id,
                    title="Welcome",
                    body="Public welcome to Tech Club. Join the mailing list for updates.",
                    visibility="public",
                    status="published",
                    author_user_id=comms.id,
                    published_at=SEED_EPOCH - timedelta(days=3),
                )
            )
            db.add(
                Announcement(
                    club_id=tech.id,
                    title="Members: Office Hours",
                    body="Members-only office hours this Friday in the lab.",
                    visibility="members",
                    status="published",
                    author_user_id=comms.id,
                    published_at=SEED_EPOCH - timedelta(days=1),
                )
            )

        for email in ("fan@example.com", "member@techclub.edu"):
            if (
                await db.scalar(
                    select(MailingListSubscription).where(
                        MailingListSubscription.club_id == tech.id,
                        MailingListSubscription.email == email,
                    )
                )
                is None
            ):
                token = generate_token(24)
                db.add(
                    MailingListSubscription(
                        club_id=tech.id,
                        email=email,
                        status="active",
                        consent_at=SEED_EPOCH - timedelta(days=5),
                        unsubscribe_token_hash=hash_token(token),
                    )
                )

        # Stable merchandise sample (keyed by SKU).
        hoodie = await db.scalar(
            select(Product).where(Product.club_id == tech.id, Product.name == "Tech Club Hoodie")
        )
        if hoodie is None:
            hoodie = Product(
                club_id=tech.id,
                name="Tech Club Hoodie",
                description="CampusOS demo merch — soft fleece hoodie.",
                status="active",
            )
            db.add(hoodie)
            await db.flush()
        for label, sku, price, stock in (
            ("M", "TECH-HOODIE-M", Decimal("799.00"), 10),
            ("L", "TECH-HOODIE-L", Decimal("799.00"), 5),
        ):
            variant = await db.scalar(
                select(ProductVariant).where(
                    ProductVariant.product_id == hoodie.id, ProductVariant.sku == sku
                )
            )
            if variant is None:
                variant = ProductVariant(
                    product_id=hoodie.id,
                    label=label,
                    sku=sku,
                    price=price,
                    is_active=True,
                    quantity_on_hand=0,
                    quantity_reserved=0,
                )
                db.add(variant)
                await db.flush()
            if variant.quantity_on_hand == 0 and stock > 0:
                key = f"seed-receive:{sku}"
                if await db.scalar(
                    select(InventoryMovement).where(InventoryMovement.idempotency_key == key)
                ) is None:
                    variant.quantity_on_hand = stock
                    db.add(
                        InventoryMovement(
                            variant_id=variant.id,
                            delta_on_hand=stock,
                            delta_reserved=0,
                            reason="receive",
                            actor_user_id=admin.id,
                            note="Seed stock",
                            idempotency_key=key,
                        )
                    )

        # Stable volunteer project + tasks.
        project = await db.scalar(
            select(Project).where(
                Project.club_id == tech.id, Project.title == "Open Source Sprint"
            )
        )
        if project is None:
            project = Project(
                club_id=tech.id,
                title="Open Source Sprint",
                description="Help ship CampusOS demo polish with the tech club.",
                status="open",
            )
            db.add(project)
            await db.flush()
        for title, capacity in (
            ("Docs polish", 3),
            ("Booth setup", 2),
        ):
            if (
                await db.scalar(
                    select(Task).where(Task.project_id == project.id, Task.title == title)
                )
                is None
            ):
                db.add(
                    Task(
                        project_id=project.id,
                        title=title,
                        description=f"Volunteer task: {title}",
                        deadline=SEED_EPOCH + timedelta(days=30),
                        capacity=capacity,
                        status="open",
                    )
                )

        await db.commit()
        print("Seed complete.")
        print("Demo password for all users:", DEMO_PASSWORD)
        print("Tech club slug: tech-club")
        print("Accounts: admin@techclub.edu, membership@techclub.edu, events@techclub.edu,")
        print("          comms@techclub.edu, finance@techclub.edu, member@techclub.edu,")
        print("          expired@techclub.edu,")
        print("          buyer@example.com, admin@artsclub.edu")

    await dispose_engine()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
