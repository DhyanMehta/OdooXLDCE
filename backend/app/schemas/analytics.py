from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class ClubSummaryOut(BaseModel):
    total_members: int
    active_memberships: int
    upcoming_events: int
    total_revenue: Decimal


class MembershipBreakdownOut(BaseModel):
    active: int
    expired: int
    revoked: int


class EventAttendanceOut(BaseModel):
    event_id: UUID
    title: str
    starts_at: datetime
    total_tickets: int
    checked_in: int
    check_in_rate: Decimal  # 0.0 to 100.0


class RevenueByTypeOut(BaseModel):
    item_kind: str  # "membership" | "ticket" | "merchandise"
    total_amount: Decimal
    order_count: int


class RecentActivityOut(BaseModel):
    id: UUID
    action: str
    entity_type: str
    actor_name: str | None
    created_at: datetime


class AnalyticsDashboardOut(BaseModel):
    """Composite response for the dashboard endpoint."""

    summary: ClubSummaryOut
    membership_breakdown: MembershipBreakdownOut
    event_attendance: list[EventAttendanceOut]
    revenue_by_type: list[RevenueByTypeOut]
    recent_activity: list[RecentActivityOut]
