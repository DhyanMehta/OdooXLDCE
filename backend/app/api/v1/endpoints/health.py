"""Process liveness health check (does not probe PostgreSQL)."""

from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
def get_health() -> dict[str, str]:
    """Return API process status. Not a database readiness check."""
    return {"status": "ok", "service": "campusos-api"}
