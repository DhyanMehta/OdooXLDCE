from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.dependencies.auth import AuthContext, get_club, require_csrf
from app.models import Club
from app.schemas.analytics import AnalyticsDashboardOut
from app.services.analytics_service import get_dashboard_data
from app.services.rbac import require_permission

router = APIRouter(tags=["analytics"])


@router.get(
    "/clubs/{club_id}/analytics/dashboard",
    response_model=AnalyticsDashboardOut,
)
async def get_club_analytics_dashboard(
    club: Club = Depends(get_club),
    auth: AuthContext = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> AnalyticsDashboardOut:
    """Aggregated club metrics: summary cards, membership health, event check-in rates, revenue, and activity."""
    await require_permission(
        db, club_id=club.id, user_id=auth.user.id, permission="view_finance"
    )
    return await get_dashboard_data(db, club.id)
