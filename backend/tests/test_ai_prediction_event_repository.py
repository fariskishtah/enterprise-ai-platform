"""Prediction event and reference-profile repository tests."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import numpy as np
import pytest
from app.ml.base import TrainerKey
from app.ml.domain import AlgorithmType, TaskType
from app.ml.jobs import RandomForestRegressionJobSpec
from app.ml.jobs.service import TrainingJobService
from app.ml.monitoring import (
    PredictionEvent,
    PredictionEventStatus,
    build_model_reference_profile,
    feature_request_profiles,
    prediction_request_profile,
)
from app.ml.trainers.random_forest.types import FeatureArray, RegressionPredictionArray
from app.models.user import User, UserRole
from app.repositories.ai_governance import TrainingJobRepository
from app.repositories.ai_monitoring import PredictionMonitoringRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 7, 18, 12, tzinfo=UTC)
KEY = TrainerKey(AlgorithmType.RANDOM_FOREST, TaskType.REGRESSION)


class FakeQueue:
    """Queue boundary used only to create a valid persisted training job."""

    def enqueue(self, training_job_id: UUID) -> str:
        return f"monitoring-{training_job_id}"


def _specification() -> RandomForestRegressionJobSpec:
    return RandomForestRegressionJobSpec(
        training_features=((0.0,), (1.0,), (2.0,), (3.0,)),
        training_targets=(0.0, 1.0, 2.0, 3.0),
        evaluation_features=((0.5,), (2.5,)),
        evaluation_targets=(0.5, 2.5),
        hyperparameters={"n_estimators": 3, "n_jobs": 1},
        random_seed=17,
        experiment_name="Monitoring Repository",
        registered_model_name="ai_core_random_forest_regression",
        tags={},
    )


async def _user_and_job(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[User, UUID]:
    user = User(
        email=f"monitoring-{uuid4()}@example.com",
        hashed_password="not-used",
        role=UserRole.ENGINEER,
        is_active=True,
    )
    async with session_factory() as session:
        session.add(user)
        await session.commit()
        await session.refresh(user)
        submission = await TrainingJobService(
            repository=TrainingJobRepository(session),
            queue=FakeQueue(),
            max_attempts=3,
        ).submit(
            requested_by_user_id=user.id,
            key=KEY,
            specification=_specification(),
            idempotency_key=None,
        )
    return user, submission.job.id


def _event(
    user_id: UUID,
    *,
    event_id: UUID | None = None,
    created_at: datetime = NOW,
    status: PredictionEventStatus = PredictionEventStatus.SUCCEEDED,
    duration_ms: float = 10.0,
) -> PredictionEvent:
    features: FeatureArray = np.asarray([[0.5], [2.5]], dtype=np.float64)
    predictions: RegressionPredictionArray = np.asarray([0.5, 2.5], dtype=np.float64)
    succeeded = status is PredictionEventStatus.SUCCEEDED
    return PredictionEvent(
        id=event_id or uuid4(),
        requested_by_user_id=user_id,
        registered_model_name="ai_core_random_forest_regression",
        requested_model_reference="candidate",
        resolved_model_version="1",
        resolved_aliases=("candidate",),
        key=KEY,
        status=status,
        row_count=2,
        feature_count=1,
        duration_ms=duration_ms,
        feature_profile=feature_request_profiles(features, None),
        prediction_profile=(
            prediction_request_profile(predictions, key=KEY, reference=None)
            if succeeded
            else None
        ),
        error_code=None if succeeded else "model_load_failed",
        safe_error_message=(
            None if succeeded else "The registered model could not be loaded."
        ),
        correlation_id="correlation-1",
        created_at=created_at,
        completed_at=created_at + timedelta(milliseconds=duration_ms),
    )


@pytest.mark.anyio
async def test_repository_creates_reads_lists_and_aggregates_events(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Portable persistence returns typed records and exact operational totals."""
    user, _job_id = await _user_and_job(session_factory)
    success = _event(user.id, duration_ms=10.0)
    failure = _event(
        user.id,
        status=PredictionEventStatus.FAILED,
        duration_ms=30.0,
    )
    async with session_factory() as session:
        repository = PredictionMonitoringRepository(session)
        await repository.create_event(success)
        await repository.create_event(failure)
        await repository.commit()
        loaded = await repository.get_event(success.id)
        page = await repository.list_events(
            registered_model_name="ai_core_random_forest_regression",
            resolved_model_version=None,
            task_type=TaskType.REGRESSION,
            status=None,
            start_at=NOW - timedelta(hours=1),
            end_at=NOW + timedelta(hours=1),
            limit=10,
            offset=0,
        )
        aggregate = await repository.aggregate_operations(
            registered_model_name="ai_core_random_forest_regression",
            resolved_model_version="1",
            task_type=None,
            status=None,
            start_at=NOW - timedelta(hours=1),
            end_at=NOW + timedelta(hours=1),
        )
        durations = await repository.list_durations(
            registered_model_name="ai_core_random_forest_regression",
            resolved_model_version="1",
            task_type=None,
            status=None,
            start_at=NOW - timedelta(hours=1),
            end_at=NOW + timedelta(hours=1),
            limit=10,
        )

    assert loaded == success
    assert page.total == 2
    assert aggregate.request_count == 2
    assert aggregate.success_count == 1
    assert aggregate.failure_count == 1
    assert aggregate.total_predicted_rows == 4
    assert aggregate.failures_by_error_code == {"model_load_failed": 1}
    assert durations == (10.0, 30.0)


@pytest.mark.anyio
async def test_bounded_analysis_selects_newest_events_with_deterministic_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The cap never selects lowest latency or an ambiguous timestamp tie."""
    user, _job_id = await _user_and_job(session_factory)
    oldest = _event(
        user.id,
        event_id=UUID("00000000-0000-0000-0000-000000000003"),
        created_at=NOW - timedelta(minutes=2),
        duration_ms=1.0,
    )
    tied_later_id = _event(
        user.id,
        event_id=UUID("00000000-0000-0000-0000-000000000002"),
        duration_ms=30.0,
    )
    tied_earlier_id = _event(
        user.id,
        event_id=UUID("00000000-0000-0000-0000-000000000001"),
        duration_ms=20.0,
    )
    async with session_factory() as session:
        repository = PredictionMonitoringRepository(session)
        for event in (oldest, tied_later_id, tied_earlier_id):
            await repository.create_event(event)
        await repository.commit()
        page = await repository.list_window_events(
            registered_model_name="ai_core_random_forest_regression",
            resolved_model_version="1",
            start_at=NOW - timedelta(hours=1),
            end_at=NOW + timedelta(hours=1),
            limit=2,
        )
        durations = await repository.list_durations(
            registered_model_name="ai_core_random_forest_regression",
            resolved_model_version="1",
            task_type=None,
            status=None,
            start_at=NOW - timedelta(hours=1),
            end_at=NOW + timedelta(hours=1),
            limit=2,
        )

    assert page.total == 3
    assert tuple(event.id for event in page.items) == (
        tied_earlier_id.id,
        tied_later_id.id,
    )
    assert durations == (20.0, 30.0)


@pytest.mark.anyio
async def test_reference_profile_is_idempotent_by_exact_model_version(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A second create returns the immutable first version-owned profile."""
    _user, job_id = await _user_and_job(session_factory)
    features: FeatureArray = np.asarray([[0.5], [2.5]], dtype=np.float64)
    predictions: RegressionPredictionArray = np.asarray([0.5, 2.5], dtype=np.float64)
    profile = build_model_reference_profile(
        profile_id=uuid4(),
        training_job_id=job_id,
        registered_model_name="ai_core_random_forest_regression",
        model_version="1",
        key=KEY,
        evaluation_features=features,
        predictions=predictions,
        bin_count=10,
        created_at=NOW,
    )
    async with session_factory() as session:
        repository = PredictionMonitoringRepository(session)
        first = await repository.create_reference_profile(profile)
        await repository.commit()
        second = await repository.create_reference_profile(
            build_model_reference_profile(
                profile_id=uuid4(),
                training_job_id=job_id,
                registered_model_name="ai_core_random_forest_regression",
                model_version="1",
                key=KEY,
                evaluation_features=features,
                predictions=predictions,
                bin_count=10,
                created_at=NOW + timedelta(minutes=1),
            ),
        )
        await repository.commit()

    assert first.id == profile.id
    assert second == first


@pytest.mark.anyio
async def test_retention_deletes_only_one_bounded_expired_event_batch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Retention leaves newer events and unrelated durable records untouched."""
    user, job_id = await _user_and_job(session_factory)
    old_one = _event(user.id, created_at=NOW - timedelta(days=100))
    old_two = _event(user.id, created_at=NOW - timedelta(days=99))
    current = _event(user.id, created_at=NOW)
    async with session_factory() as session:
        repository = PredictionMonitoringRepository(session)
        for event in (old_one, old_two, current):
            await repository.create_event(event)
        await repository.commit()
        eligible = await repository.count_events_before(NOW - timedelta(days=90))
        deleted = await repository.delete_events_before(
            cutoff=NOW - timedelta(days=90),
            limit=1,
        )
        await repository.commit()
        remaining = await repository.list_events(
            registered_model_name=None,
            resolved_model_version=None,
            task_type=None,
            status=None,
            start_at=None,
            end_at=None,
            limit=10,
            offset=0,
        )
        job = await TrainingJobRepository(session).get_by_id(job_id)

    assert eligible == 2
    assert deleted == 1
    assert remaining.total == 2
    assert job is not None
