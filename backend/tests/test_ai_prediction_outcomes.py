"""Ground-truth outcome validation, maturity, idempotency, and metrics tests."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import numpy as np
import pytest
from app.ml.base import TrainerKey
from app.ml.domain import AlgorithmType, TaskType
from app.ml.monitoring import (
    PredictionEvent,
    PredictionEventStatus,
    feature_request_profiles,
    prediction_request_profile,
)
from app.ml.monitoring.evaluation_models import (
    ClassificationPerformanceSummary,
    RegressionPerformanceSummary,
)
from app.ml.monitoring.exceptions import MonitoringPreconditionError
from app.ml.monitoring.outcome_service import PredictionOutcomeService
from app.ml.trainers.random_forest.types import (
    ClassificationPredictionArray,
    FeatureArray,
    RegressionPredictionArray,
)
from app.models.user import User, UserRole
from app.repositories.ai_monitoring import PredictionMonitoringRepository
from app.repositories.prediction_outcomes import PredictionOutcomeRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 7, 19, 12, tzinfo=UTC)


async def _user(
    session_factory: async_sessionmaker[AsyncSession],
) -> UUID:
    async with session_factory() as session:
        user = User(
            email=f"outcome-{uuid4()}@example.com",
            hashed_password="not-used",
            role=UserRole.ENGINEER,
            is_active=True,
        )
        session.add(user)
        await session.commit()
        return user.id


def _event(
    user_id: UUID,
    *,
    task: TaskType,
    prediction: float | int,
    version: str,
) -> PredictionEvent:
    key = TrainerKey(AlgorithmType.RANDOM_FOREST, task)
    features: FeatureArray = np.asarray([[1.0]], dtype=np.float64)
    predictions: RegressionPredictionArray | ClassificationPredictionArray
    if task is TaskType.REGRESSION:
        predictions = np.asarray([prediction], dtype=np.float64)
    else:
        predictions = np.asarray([prediction], dtype=np.int64)
    return PredictionEvent(
        id=uuid4(),
        requested_by_user_id=user_id,
        registered_model_name="factory_quality",
        requested_model_reference=version,
        resolved_model_version=version,
        resolved_aliases=(),
        key=key,
        status=PredictionEventStatus.SUCCEEDED,
        row_count=1,
        feature_count=1,
        duration_ms=2.0,
        feature_profile=feature_request_profiles(features, None),
        prediction_profile=prediction_request_profile(
            predictions, key=key, reference=None
        ),
        error_code=None,
        safe_error_message=None,
        correlation_id=None,
        created_at=NOW - timedelta(hours=2),
        completed_at=NOW - timedelta(hours=2) + timedelta(milliseconds=2),
    )


def _service(session: AsyncSession) -> PredictionOutcomeService:
    return PredictionOutcomeService(
        repository=PredictionOutcomeRepository(session),
        monitoring_repository=PredictionMonitoringRepository(session),
        maximum_outcomes_per_summary=100,
        clock=lambda: NOW,
    )


async def _persist_events(
    session: AsyncSession, events: tuple[PredictionEvent, ...]
) -> None:
    repository = PredictionMonitoringRepository(session)
    for event in events:
        await repository.create_event(event)
    await repository.commit()


@pytest.mark.anyio
async def test_regression_outcomes_upsert_and_ignore_immature_labels(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _user(session_factory)
    events = (
        _event(user_id, task=TaskType.REGRESSION, prediction=2.0, version="1"),
        _event(user_id, task=TaskType.REGRESSION, prediction=4.0, version="1"),
        _event(user_id, task=TaskType.REGRESSION, prediction=9.0, version="1"),
    )
    async with session_factory() as session:
        await _persist_events(session, events)
        service = _service(session)
        first = await service.upsert(
            prediction_event_id=events[0].id,
            actual_value=0.0,
            observed_at=NOW - timedelta(hours=1),
            source="quality-system",
            label_maturity_at=NOW - timedelta(minutes=30),
            safe_metadata={"line": "a"},
            external_reference_key="outcome-1",
        )
        updated = await service.upsert(
            prediction_event_id=events[0].id,
            actual_value=1.0,
            observed_at=NOW - timedelta(hours=1),
            source="quality-system",
            label_maturity_at=NOW - timedelta(minutes=30),
            safe_metadata={"line": "a"},
            external_reference_key="outcome-1",
        )
        await service.upsert(
            prediction_event_id=events[1].id,
            actual_value=5.0,
            observed_at=NOW - timedelta(hours=1),
            source="quality-system",
            label_maturity_at=NOW - timedelta(minutes=30),
            safe_metadata={},
            external_reference_key="outcome-2",
        )
        await service.upsert(
            prediction_event_id=events[2].id,
            actual_value=9.0,
            observed_at=NOW - timedelta(hours=1),
            source="quality-system",
            label_maturity_at=NOW + timedelta(hours=1),
            safe_metadata={},
            external_reference_key="outcome-future",
        )
        summary = await service.performance_summary(
            registered_model_name="factory_quality", model_version="1"
        )

    assert first.id == updated.id
    assert updated.actual_value == 1.0
    assert isinstance(summary, RegressionPerformanceSummary)
    assert summary.evaluated_sample_count == 2
    assert summary.mae == pytest.approx(1.0)
    assert summary.rmse == pytest.approx(1.0)
    assert summary.mean_prediction_bias == pytest.approx(0.0)


@pytest.mark.anyio
async def test_binary_classification_metrics_and_type_validation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _user(session_factory)
    predictions = (1, 0, 1, 0)
    actuals = (1, 0, 0, 1)
    events = tuple(
        _event(user_id, task=TaskType.CLASSIFICATION, prediction=value, version="2")
        for value in predictions
    )
    async with session_factory() as session:
        await _persist_events(session, events)
        service = _service(session)
        for index, (event, actual) in enumerate(zip(events, actuals, strict=True)):
            await service.upsert(
                prediction_event_id=event.id,
                actual_value=actual,
                observed_at=NOW - timedelta(hours=1),
                source="inspection",
                label_maturity_at=NOW - timedelta(minutes=1),
                safe_metadata={},
                external_reference_key=f"class-{index}",
            )
        with pytest.raises(MonitoringPreconditionError, match="integer label"):
            await service.upsert(
                prediction_event_id=events[0].id,
                actual_value=1.5,
                observed_at=NOW - timedelta(hours=1),
                source="inspection",
                label_maturity_at=NOW,
                safe_metadata={},
                external_reference_key="invalid-class",
            )
        summary = await service.performance_summary(
            registered_model_name="factory_quality", model_version="2"
        )

    assert isinstance(summary, ClassificationPerformanceSummary)
    assert summary.evaluated_sample_count == 4
    assert summary.accuracy == pytest.approx(0.5)
    assert summary.precision == pytest.approx(0.5)
    assert summary.recall == pytest.approx(0.5)
    assert summary.f1 == pytest.approx(0.5)
    assert summary.false_negative_rate == pytest.approx(0.5)
    assert (
        summary.true_positive_count,
        summary.true_negative_count,
        summary.false_positive_count,
        summary.false_negative_count,
    ) == (1, 1, 1, 1)
