"""Versioned API router aggregation."""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    announcements,
    auth,
    clubs,
    events,
    health,
    memberships,
    orders,
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
