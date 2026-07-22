"""Liveness and dependency-readiness routes."""

import os
from pathlib import Path
from typing import Annotated

from anyio import to_thread
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.dependencies.database import get_db_session
from app.dependencies.operational import OperationalProbe, get_operational_probe
from app.models.rag import RAGKnowledgeBase
from app.rag.embeddings import DeterministicHashEmbeddingProvider
from app.rag.generation import LocalExtractiveGenerationProvider
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
    settings: Annotated[Settings, Depends(get_settings)],
) -> OperationalStatusResponse:
    """Report safe dependency status without changing liveness semantics."""
    database = "available"
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        database = "unavailable"
    redis, queue, worker = await probe.queue_and_worker()
    dataset_storage = await _dataset_storage_status(settings.dataset_storage_root)
    embedding_provider = _embedding_provider_status()
    generation_provider = _generation_provider_status()
    rag_index = "available"
    try:
        await session.scalar(select(func.count()).select_from(RAGKnowledgeBase))
    except SQLAlchemyError:
        rag_index = "unavailable"
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
        dataset_storage=dataset_storage,
        embedding_provider=embedding_provider,
        generation_provider=generation_provider,
        rag_index=rag_index,
        dataset_reconciliation_scheduler=(
            "enabled"
            if settings.dataset_reconciliation_scheduling_enabled
            else "disabled"
        ),
        rag_reconciliation_scheduler=(
            "enabled" if settings.rag_reconciliation_scheduling_enabled else "disabled"
        ),
        status=overall,
        timestamp=utc_now(),
    )


async def _dataset_storage_status(root: str) -> str:
    def probe() -> str:
        candidate = Path(root)
        descriptor: int | None = None
        try:
            candidate.mkdir(parents=True, exist_ok=True, mode=0o700)
            if candidate.is_symlink():
                return "unavailable"
            resolved = candidate.resolve(strict=True)
            if not resolved.is_dir() or not os.access(
                resolved, os.R_OK | os.W_OK | os.X_OK
            ):
                return "unavailable"
            descriptor = os.open(
                resolved,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            os.fstatvfs(descriptor)
        except OSError:
            return "unavailable"
        finally:
            if descriptor is not None:
                os.close(descriptor)
        return "available"

    return await to_thread.run_sync(probe)


def _embedding_provider_status() -> str:
    try:
        vector = DeterministicHashEmbeddingProvider().embed(("health",))[0]
    except (ValueError, ArithmeticError):
        return "unavailable"
    return "available" if len(vector) == 256 else "unavailable"


def _generation_provider_status() -> str:
    provider = LocalExtractiveGenerationProvider()
    return (
        "available"
        if provider.provider_name == "local_extractive"
        and provider.model_name == "grounded-extractive-v1"
        else "unavailable"
    )
