"""Bounded prediction-event retention command tests."""

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.config.settings import Settings
from app.db.base import Base
from app.db.session import build_session_factory
from app.ml.base import TrainerKey
from app.ml.domain import AlgorithmType, TaskType
from app.ml.monitoring import PredictionEvent, PredictionEventStatus
from app.ml.monitoring.retention import retain_prediction_events
from app.models.user import User, UserRole
from app.repositories.ai_monitoring import PredictionMonitoringRepository
from app.utils.security import utc_now
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.mark.anyio
async def test_retention_dry_run_then_bounded_execute(
    settings: Settings,
    tmp_path: Path,
) -> None:
    """Dry-run is nondestructive and execute deletes only the configured batch."""
    database_path = tmp_path / "retention.db"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    command_settings = settings.model_copy(
        update={
            "database_url": database_url,
            "prediction_event_retention_days": 30,
            "prediction_event_retention_batch_size": 1,
        },
    )
    session_factory = build_session_factory(database_url)
    user = User(
        email="retention@example.com",
        hashed_password="not-used",
        role=UserRole.ADMIN,
    )
    now = utc_now()
    async with session_factory() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)
        repository = PredictionMonitoringRepository(session)
        for age in (60, 50):
            created_at = now - timedelta(days=age)
            await repository.create_event(
                PredictionEvent(
                    id=uuid4(),
                    requested_by_user_id=user.id,
                    registered_model_name="ai_core_random_forest_regression",
                    requested_model_reference="missing",
                    resolved_model_version=None,
                    resolved_aliases=(),
                    key=TrainerKey(
                        AlgorithmType.RANDOM_FOREST,
                        TaskType.REGRESSION,
                    ),
                    status=PredictionEventStatus.FAILED,
                    row_count=0,
                    feature_count=0,
                    duration_ms=1.0,
                    feature_profile=(),
                    prediction_profile=None,
                    error_code="model_version_not_found",
                    safe_error_message="The requested model version was not found.",
                    correlation_id=None,
                    created_at=created_at,
                    completed_at=created_at + timedelta(milliseconds=1),
                ),
            )
        await repository.commit()

    dry_run = await retain_prediction_events(command_settings, dry_run=True)
    executed = await retain_prediction_events(command_settings, dry_run=False)
    second = await retain_prediction_events(command_settings, dry_run=False)

    assert dry_run.eligible_count == 2
    assert dry_run.deleted_count == 0
    assert executed.eligible_count == 2
    assert executed.deleted_count == 1
    assert second.eligible_count == 1
    assert second.deleted_count == 1
