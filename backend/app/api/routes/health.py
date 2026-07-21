"""Liveness and dependency-readiness routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.database import get_db_session
from app.dependencies.operational import OperationalProbe, get_operational_probe
from app.schemas.health import (
    HealthResponse,
    OperationalStatusResponse,
    ReadinessResponse,
)
from app.utils.security import utc_now

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


@router.get(
    "/operational-status",
    response_model=OperationalStatusResponse,
    status_code=status.HTTP_200_OK,
)
async def operational_status(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    probe: Annotated[OperationalProbe, Depends(get_operational_probe)],
) -> OperationalStatusResponse:
    """Report safe dependency status without changing liveness semantics."""
    database = "available"
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        database = "unavailable"
    redis, queue, worker = await probe.queue_and_worker()
    overall = (
        "operational"
        if database == redis == queue == worker == "available"
        else "degraded"
    )
    return OperationalStatusResponse(
        database=database,
        redis=redis,
        queue=queue,
        training_worker=worker,
        status=overall,
        timestamp=utc_now(),
    )
