"""Scheduled monitoring locking, failure isolation, and retention boundary tests."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from app.config.settings import Settings
from app.ml.base import TrainerKey
from app.ml.domain import AlgorithmType, TaskType
from app.ml.monitoring.evaluation_models import (
    ModelMonitoringEvaluation,
    MonitoringAlert,
    MonitoringAlertSeverity,
    MonitoringAlertStatus,
    MonitoringAlertType,
    MonitoringEvaluationStatus,
    MonitoringEvaluationTrigger,
)
from app.ml.monitoring.scheduled import ScheduledMonitoringService
from app.ml.registry import RegisteredModelVersion, RegisteredModelVersionStatus
from app.repositories.monitoring_alerts import MonitoringAlertRepository
from app.repositories.monitoring_evaluations import MonitoringEvaluationRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 7, 19, 12, 35, tzinfo=UTC)
KEY = TrainerKey(AlgorithmType.RANDOM_FOREST, TaskType.REGRESSION)
EVALUATION_ID = UUID("00000000-0000-0000-0000-000000000951")


def test_automatic_retraining_configuration_requires_an_actor_identity() -> None:
    with pytest.raises(ValueError, match="actor_user_id is required"):
        Settings(
            database_url="sqlite+aiosqlite://",
            redis_url="redis://localhost:6379/0",
            secret_key="test-secret-key-with-sufficient-entropy",
            environment="test",
            monitoring_automatic_retraining_enabled=True,
        )


def _evaluation(
    *,
    evaluation_id: UUID = EVALUATION_ID,
    created_at: datetime = NOW,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
) -> ModelMonitoringEvaluation:
    end = window_end or NOW
    start = window_start or end - timedelta(hours=24)
    return ModelMonitoringEvaluation(
        id=evaluation_id,
        registered_model_name="good_model",
        model_version="1",
        model_alias="champion",
        key=KEY,
        window_start=start,
        window_end=end,
        evaluated_sample_count=25,
        successful_prediction_count=5,
        failed_prediction_count=0,
        data_quality_status=MonitoringEvaluationStatus.HEALTHY,
        feature_drift_status=MonitoringEvaluationStatus.HEALTHY,
        prediction_drift_status=MonitoringEvaluationStatus.HEALTHY,
        operational_health_status=MonitoringEvaluationStatus.HEALTHY,
        overall_status=MonitoringEvaluationStatus.HEALTHY,
        report_schema_version="1.0",
        report={"availability": {"error_code": None}},
        warning_count=0,
        critical_count=0,
        trigger=MonitoringEvaluationTrigger.SCHEDULED,
        idempotency_key=str(evaluation_id),
        created_at=created_at,
        updated_at=created_at,
    )


class FakeEvaluationRepository:
    async def list_registered_model_names(self, *, limit: int) -> tuple[str, ...]:
        assert limit == 10
        return ("bad_model", "good_model")


class FakeLockRepository:
    def __init__(self, *, available: bool = True) -> None:
        self.available = available

    async def acquire_lock(self, **arguments: object) -> bool:
        _ = arguments
        return self.available

    async def release_lock(self, **arguments: object) -> bool:
        _ = arguments
        return True

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class FakeRegistry:
    def resolve(self, name: str, alias: str) -> RegisteredModelVersion:
        if name == "bad_model":
            raise RuntimeError("not exposed")
        return RegisteredModelVersion(
            registered_model_name=name,
            version="1",
            run_id="run-1",
            source_uri="models:/good_model/1",
            key=KEY,
            status=RegisteredModelVersionStatus.READY,
            aliases=(alias,),
        )


class FakeEvaluationService:
    def __init__(self) -> None:
        self.calls = 0

    async def evaluate(self, **arguments: object) -> ModelMonitoringEvaluation:
        _ = arguments
        self.calls += 1
        return _evaluation()


@pytest.mark.anyio
async def test_scheduled_job_isolates_failures_and_deduplicates_aliases() -> None:
    evaluations = FakeEvaluationService()
    service = ScheduledMonitoringService(
        evaluation_repository=FakeEvaluationRepository(),  # type: ignore[arg-type]
        lock_repository=FakeLockRepository(),  # type: ignore[arg-type]
        evaluation_service=evaluations,  # type: ignore[arg-type]
        model_registry=FakeRegistry(),  # type: ignore[arg-type]
        aliases=("champion", "candidate"),
        window_hours=24,
        interval_seconds=3600,
        lock_timeout_seconds=1800,
        maximum_models=10,
        retraining_service=None,
        retraining_actor_user_id=None,
        clock=lambda: NOW,
    )

    first = await service.run()
    repeated = await service.run()

    assert first.window_end == datetime(2026, 7, 19, 12, tzinfo=UTC)
    assert first.evaluated == 1
    assert first.skipped == 1
    assert first.failed == 2
    assert repeated.evaluated == 1
    assert {item.evaluation_id for item in first.outcomes if item.evaluation_id} == {
        EVALUATION_ID
    }
    assert evaluations.calls == 2


@pytest.mark.anyio
async def test_database_lock_prevents_concurrent_scheduled_run(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as first_session:
        first = MonitoringAlertRepository(first_session)
        assert await first.acquire_lock(
            lock_key="scheduled-window",
            owner_id="owner-1",
            acquired_at=NOW,
            expires_at=NOW + timedelta(minutes=30),
        )
        await first.commit()
    async with session_factory() as second_session:
        second = MonitoringAlertRepository(second_session)
        assert not await second.acquire_lock(
            lock_key="scheduled-window",
            owner_id="owner-2",
            acquired_at=NOW + timedelta(minutes=1),
            expires_at=NOW + timedelta(minutes=31),
        )
        await second.rollback()
        assert await second.acquire_lock(
            lock_key="scheduled-window",
            owner_id="owner-2",
            acquired_at=NOW + timedelta(minutes=31),
            expires_at=NOW + timedelta(minutes=61),
        )
        await second.commit()


@pytest.mark.anyio
async def test_monitoring_evaluation_retention_obeys_batch_boundary(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    old = NOW - timedelta(days=400)
    async with session_factory() as session:
        repository = MonitoringEvaluationRepository(session)
        for suffix in (1, 2, 3):
            identifier = UUID(f"00000000-0000-0000-0000-{suffix:012d}")
            await repository.create(
                _evaluation(
                    evaluation_id=identifier,
                    created_at=old + timedelta(minutes=suffix),
                    window_start=old - timedelta(hours=24, minutes=-suffix),
                    window_end=old + timedelta(minutes=suffix),
                )
            )
        await repository.create(
            _evaluation(evaluation_id=UUID("00000000-0000-0000-0000-000000000099"))
        )
        await repository.commit()

        cutoff = NOW - timedelta(days=365)
        assert await repository.count_before(cutoff) == 3
        assert await repository.delete_before(cutoff=cutoff, limit=2) == 2
        await repository.commit()
        assert await repository.count_before(cutoff) == 1


@pytest.mark.anyio
async def test_stale_alert_reconciliation_is_bounded_and_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    old = NOW - timedelta(days=30)
    cutoff = NOW - timedelta(days=7)
    async with session_factory() as session:
        repository = MonitoringAlertRepository(session)
        for suffix in (1, 2, 3):
            detected_at = old + timedelta(minutes=suffix)
            await repository.create(
                MonitoringAlert(
                    id=UUID(f"00000000-0000-0000-0001-{suffix:012d}"),
                    alert_type=MonitoringAlertType.INSUFFICIENT_DATA,
                    severity=MonitoringAlertSeverity.WARNING,
                    registered_model_name=f"stale_model_{suffix}",
                    model_version="1",
                    monitoring_evaluation_id=None,
                    title="Insufficient recent prediction data",
                    safe_summary="A safe aggregate condition was detected.",
                    deduplication_key=f"stale-alert-{suffix}",
                    status=MonitoringAlertStatus.OPEN,
                    first_detected_at=detected_at,
                    last_detected_at=detected_at,
                    occurrence_count=1,
                    acknowledged_at=None,
                    acknowledged_by_user_id=None,
                    resolved_at=None,
                    created_at=detected_at,
                    updated_at=detected_at,
                )
            )
        await repository.commit()

        assert (
            len(
                await repository.resolve_stale(
                    last_detected_before=cutoff,
                    limit=2,
                )
            )
            == 2
        )
        await repository.commit()
        assert (
            len(
                await repository.resolve_stale(
                    last_detected_before=cutoff,
                    limit=2,
                )
            )
            == 1
        )
        await repository.commit()
        assert (
            len(
                await repository.resolve_stale(
                    last_detected_before=cutoff,
                    limit=2,
                )
            )
            == 0
        )
