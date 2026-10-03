"""Import all models so Alembic and metadata see them."""

from app.models.commerce import Order, OrderItem, Payment, PaymentEvent
from app.models.communications import Announcement, MailingListSubscription, NotificationDelivery
from app.models.events import Event, Ticket, TicketCheckin, TicketPrice, TicketType
from app.models.identity import (
    AuditLog,
    Club,
    ClubMember,
    ClubRoleAssignment,
    AuthSession,
    Role,
    User,
)
from app.models.membership import Membership, MembershipPlan

__all__ = [
    "Announcement",
    "AuditLog",
    "Club",
    "ClubMember",
    "ClubRoleAssignment",
    "Event",
    "MailingListSubscription",
    "Membership",
    "MembershipPlan",
    "NotificationDelivery",
    "Order",
    "OrderItem",
    "Payment",
    "PaymentEvent",
    "AuthSession",
    "Role",
    "Ticket",
    "TicketCheckin",
    "TicketPrice",
    "TicketType",
    "User",
]
