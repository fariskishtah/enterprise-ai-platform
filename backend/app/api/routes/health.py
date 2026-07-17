"""Health-check route."""

from fastapi import APIRouter, status

from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
)
async def health() -> HealthResponse:
    """Return service liveness status."""
    return HealthResponse(status="ok")
