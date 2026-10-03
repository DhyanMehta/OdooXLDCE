"""Import all models so Alembic and metadata see them."""

from app.models.commerce import Order, OrderItem, Payment, PaymentEvent
from app.models.finance import (
    Account,
    Budget,
    Expense,
    ExpenseApproval,
    ExpenseAttachment,
    JournalEntry,
    JournalLine,
    Reimbursement,
    Refund,
)
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
from app.models.merchandise import InventoryMovement, Product, ProductVariant
from app.models.projects import Project, Task, TaskAssignment

__all__ = [
    "Account",
    "Announcement",
    "AuditLog",
    "Budget",
    "Club",
    "ClubMember",
    "ClubRoleAssignment",
    "Event",
    "Expense",
    "ExpenseApproval",
    "ExpenseAttachment",
    "InventoryMovement",
    "JournalEntry",
    "JournalLine",
    "MailingListSubscription",
    "Membership",
    "MembershipPlan",
    "NotificationDelivery",
    "Order",
    "OrderItem",
    "Payment",
    "PaymentEvent",
    "Product",
    "ProductVariant",
    "Project",
    "Reimbursement",
    "Refund",
    "AuthSession",
    "Role",
    "Task",
    "TaskAssignment",
    "Ticket",
    "TicketCheckin",
    "TicketPrice",
    "TicketType",
    "User",
]
