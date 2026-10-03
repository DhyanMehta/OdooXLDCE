"""Versioned API router aggregation."""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    announcements,
    auth,
    clubs,
    events,
    expenses,
    finance,
    health,
    memberships,
    merchandise,
    orders,
    projects,
    refunds,
    roles,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(clubs.router)
api_router.include_router(memberships.router)
api_router.include_router(orders.router)
api_router.include_router(events.router)
api_router.include_router(announcements.router)
api_router.include_router(roles.router)
api_router.include_router(merchandise.router)
api_router.include_router(projects.router)
api_router.include_router(expenses.router)
api_router.include_router(refunds.router)
api_router.include_router(finance.router)
