"""Process liveness health check (does not probe PostgreSQL)."""

from fastapi import APIRouter

from app.schemas.common import HealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def get_health() -> HealthOut:
    """Return API process status. Not a database readiness check."""
    return HealthOut(status="ok", service="campusos-api")
