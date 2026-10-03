"""Repeatable development seed.

Run (venv active, migrations applied):
  campusos-seed
  python -m app.seed
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.core.permissions import RoleCode
from app.core.security import generate_token, hash_password, hash_token
from app.core.tokens import seal_token
from app.db.session import SessionLocal
from app.models import (
    Announcement,
    Club,
    ClubMember,
    ClubRoleAssignment,
    Event,
    MailingListSubscription,
    Membership,
    MembershipPlan,
    Order,
    OrderItem,
    Payment,
    Role,
    Ticket,
    TicketCheckin,
    TicketPrice,
    TicketType,
    User,
)
from app.services.membership_eligibility import utcnow

DEMO_PASSWORD = "Password123!"


def _user(db, email: str, name: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user:
        return user
    user = User(email=email, full_name=name, password_hash=hash_password(DEMO_PASSWORD))
    db.add(user)
    db.flush()
    return user


def _role(db, code: str, name: str) -> Role:
    role = db.scalar(select(Role).where(Role.code == code))
    if role:
        return role
    role = Role(code=code, name=name)
    db.add(role)
    db.flush()
    return role


def _assign(db, club_id, user_id, role_id, starts_at, ends_at=None, assigned_by=None):
    existing = db.scalar(
        select(ClubRoleAssignment).where(
            ClubRoleAssignment.club_id == club_id,
            ClubRoleAssignment.user_id == user_id,
            ClubRoleAssignment.role_id == role_id,
            ClubRoleAssignment.ends_at.is_(None),
        )
    )
    if existing:
        return existing
    row = ClubRoleAssignment(
        club_id=club_id,
        user_id=user_id,
        role_id=role_id,
        starts_at=starts_at,
        ends_at=ends_at,
        assigned_by_user_id=assigned_by,
    )
    db.add(row)
    db.flush()
    return row


def main() -> None:
    now = utcnow()
    with SessionLocal() as db:
        roles = {
            RoleCode.CLUB_ADMIN.value: _role(db, RoleCode.CLUB_ADMIN.value, "Club Administrator"),
            RoleCode.MEMBERSHIP_MANAGER.value: _role(
                db, RoleCode.MEMBERSHIP_MANAGER.value, "Membership Manager"
            ),
            RoleCode.EVENT_ORGANIZER.value: _role(
                db, RoleCode.EVENT_ORGANIZER.value, "Event Organizer"
            ),
            RoleCode.COMMUNICATIONS_OFFICER.value: _role(
                db, RoleCode.COMMUNICATIONS_OFFICER.value, "Communications Officer"
            ),
        }

        tech = db.scalar(select(Club).where(Club.slug == "tech-club"))
        if tech is None:
            tech = Club(
                slug="tech-club",
                name="Tech Club",
                description="Builds software, hosts hack nights, and runs campus tech events.",
            )
            db.add(tech)
            db.flush()
        arts = db.scalar(select(Club).where(Club.slug == "arts-club"))
        if arts is None:
            arts = Club(
                slug="arts-club",
                name="Arts Club",
                description="Creative community for design, music, and exhibitions.",
            )
            db.add(arts)
            db.flush()

        admin = _user(db, "admin@techclub.edu", "Asha Admin")
        membership_mgr = _user(db, "membership@techclub.edu", "Milan Membership")
        events_mgr = _user(db, "events@techclub.edu", "Evan Events")
        comms = _user(db, "comms@techclub.edu", "Cora Comms")
        member = _user(db, "member@techclub.edu", "Ordinary Member")
        expired_user = _user(db, "expired@techclub.edu", "Expired Member")
        outsider = _user(db, "buyer@example.com", "Public Buyer")
        arts_admin = _user(db, "admin@artsclub.edu", "Arts Admin")

        for club, users in (
            (tech, [admin, membership_mgr, events_mgr, comms, member, expired_user, outsider]),
            (arts, [arts_admin, outsider]),
        ):
            for u in users:
                if db.scalar(
                    select(ClubMember).where(ClubMember.club_id == club.id, ClubMember.user_id == u.id)
                ) is None:
                    db.add(ClubMember(club_id=club.id, user_id=u.id))

        _assign(db, tech.id, admin.id, roles[RoleCode.CLUB_ADMIN.value].id, now - timedelta(days=90))
        # Historical leadership for handover demos.
        _assign(
            db,
            tech.id,
            membership_mgr.id,
            roles[RoleCode.MEMBERSHIP_MANAGER.value].id,
            now - timedelta(days=60),
            ends_at=now - timedelta(days=1),
            assigned_by=admin.id,
        )
        _assign(
            db,
            tech.id,
            membership_mgr.id,
            roles[RoleCode.MEMBERSHIP_MANAGER.value].id,
            now - timedelta(days=1),
            assigned_by=admin.id,
        )
        _assign(db, tech.id, events_mgr.id, roles[RoleCode.EVENT_ORGANIZER.value].id, now - timedelta(days=30))
        _assign(
            db, tech.id, comms.id, roles[RoleCode.COMMUNICATIONS_OFFICER.value].id, now - timedelta(days=30)
        )
        _assign(db, arts.id, arts_admin.id, roles[RoleCode.CLUB_ADMIN.value].id, now - timedelta(days=20))

        annual = db.scalar(
            select(MembershipPlan).where(MembershipPlan.club_id == tech.id, MembershipPlan.name == "Annual")
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
            db.flush()
        semester = db.scalar(
            select(MembershipPlan).where(MembershipPlan.club_id == tech.id, MembershipPlan.name == "Semester")
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
            db.flush()

        def ensure_membership(user, plan, starts, ends, status="active"):
            existing = db.scalar(
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
            db.flush()
            item = OrderItem(
                order_id=order.id,
                item_kind="membership",
                membership_plan_id=plan.id,
                quantity=1,
                unit_price_snapshot=plan.dues_amount,
                title_snapshot=plan.name,
            )
            db.add(item)
            db.add(
                Payment(
                    order_id=order.id,
                    amount=plan.dues_amount,
                    method="seed",
                    status="confirmed",
                    confirmed_at=starts,
                    confirmed_by_user_id=membership_mgr.id,
                )
            )
            db.flush()
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
            db.flush()
            return m

        ensure_membership(member, annual, now - timedelta(days=30), now + timedelta(days=335))
        # Staff accounts also get paid membership so member-price demos work while logged in as admin.
        ensure_membership(admin, annual, now - timedelta(days=20), now + timedelta(days=345))
        ensure_membership(events_mgr, semester, now - timedelta(days=10), now + timedelta(days=110))
        ensure_membership(
            expired_user, semester, now - timedelta(days=150), now - timedelta(days=10), status="expired"
        )

        meetup = db.scalar(select(Event).where(Event.club_id == tech.id, Event.title == "Spring Hack Night"))
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
            db.flush()
            tt = TicketType(event_id=meetup.id, name="General Admission", description="Entry")
            db.add(tt)
            db.flush()
            db.add(TicketPrice(ticket_type_id=tt.id, audience="member", amount=Decimal("100.00")))
            db.add(TicketPrice(ticket_type_id=tt.id, audience="public", amount=Decimal("200.00")))

        limited = db.scalar(select(Event).where(Event.club_id == tech.id, Event.title == "Tiny Workshop"))
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
            db.flush()
            tt = TicketType(event_id=limited.id, name="Seat", description="One seat")
            db.add(tt)
            db.flush()
            db.add(TicketPrice(ticket_type_id=tt.id, audience="member", amount=Decimal("50.00")))
            db.add(TicketPrice(ticket_type_id=tt.id, audience="public", amount=Decimal("80.00")))

        # Issued ticket + check-in example for member.
        ga_price = db.scalar(
            select(TicketPrice)
            .join(TicketType)
            .where(TicketType.event_id == meetup.id, TicketPrice.audience == "member")
        )
        if ga_price and db.scalar(select(Ticket).where(Ticket.user_id == member.id, Ticket.event_id == meetup.id)) is None:
            order = Order(
                club_id=tech.id,
                user_id=member.id,
                status="paid",
                total_amount=ga_price.amount,
                currency="INR",
            )
            db.add(order)
            db.flush()
            item = OrderItem(
                order_id=order.id,
                item_kind="ticket",
                ticket_price_id=ga_price.id,
                quantity=1,
                unit_price_snapshot=ga_price.amount,
                title_snapshot="Spring Hack Night — GA",
            )
            db.add(item)
            db.add(
                Payment(
                    order_id=order.id,
                    amount=ga_price.amount,
                    method="seed",
                    status="confirmed",
                    confirmed_at=now,
                )
            )
            db.flush()
            raw = generate_token(24)
            ticket = Ticket(
                order_item_id=item.id,
                event_id=meetup.id,
                club_id=tech.id,
                user_id=member.id,
                ticket_type_id=ga_price.ticket_type_id,
                status="valid",
                qr_token_hash=hash_token(raw),
                qr_token_sealed=seal_token(raw),
            )
            db.add(ticket)
            db.flush()
            db.add(
                TicketCheckin(
                    ticket_id=ticket.id,
                    event_id=meetup.id,
                    checked_in_by_user_id=events_mgr.id,
                    checked_in_at=now - timedelta(hours=2),
                )
            )
            print(f"Seed check-in sample QR token for member ticket: {raw}")

        if db.scalar(select(Announcement).where(Announcement.club_id == tech.id, Announcement.title == "Welcome")) is None:
            db.add(
                Announcement(
                    club_id=tech.id,
                    title="Welcome",
                    body="Public welcome to Tech Club. Join the mailing list for updates.",
                    visibility="public",
                    status="published",
                    author_user_id=comms.id,
                    published_at=now - timedelta(days=3),
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
                    published_at=now - timedelta(days=1),
                )
            )

        for email in ("fan@example.com", "member@techclub.edu"):
            if db.scalar(
                select(MailingListSubscription).where(
                    MailingListSubscription.club_id == tech.id,
                    MailingListSubscription.email == email,
                )
            ) is None:
                token = generate_token(24)
                db.add(
                    MailingListSubscription(
                        club_id=tech.id,
                        email=email,
                        status="active",
                        consent_at=now - timedelta(days=5),
                        unsubscribe_token_hash=hash_token(token),
                    )
                )

        db.commit()
        print("Seed complete.")
        print("Demo password for all users:", DEMO_PASSWORD)
        print("Tech club slug: tech-club")
        print("Accounts: admin@techclub.edu, membership@techclub.edu, events@techclub.edu,")
        print("          comms@techclub.edu, member@techclub.edu, expired@techclub.edu,")
        print("          buyer@example.com, admin@artsclub.edu")


if __name__ == "__main__":
    main()
