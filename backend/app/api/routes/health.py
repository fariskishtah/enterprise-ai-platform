"""Liveness and dependency-readiness routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.database import get_db_session
from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
)
async def health() -> HealthResponse:
    """Return service liveness status."""
    return HealthResponse(status="ok")


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
)
async def readiness(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReadinessResponse:
    """Report readiness only after the primary database accepts a query."""
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="A required service is unavailable.",
        ) from exc
    return ReadinessResponse(status="ready")
