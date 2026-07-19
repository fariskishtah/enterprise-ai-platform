"""Controlled retraining orchestration and idempotency integration tests."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.ml.base import TrainerKey
from app.ml.domain import AlgorithmType, TaskType
from app.ml.jobs import (
    RandomForestRegressionJobSpec,
    random_forest_key,
)
from app.ml.jobs.service import TrainingJobService
from app.ml.monitoring import (
    DataQualityIssue,
    DataQualitySeverity,
    DriftSeverity,
    DriftThresholds,
    FeatureDriftResult,
    ModelDriftReport,
    PredictionDataQualityReport,
    ReferenceProfileSource,
    RegressionPredictionDrift,
)
from app.ml.monitoring.service import PredictionMonitoringService
from app.ml.registry import (
    BaseModelRegistry,
    ModelRegistrationRequest,
    RegisteredModelVersion,
    RegisteredModelVersionStatus,
)
from app.ml.retraining import (
    RetrainingDecisionStatus,
    RetrainingDependencyError,
    RetrainingPolicy,
    RetrainingPolicyEvaluator,
    RetrainingRequestStatus,
    RetrainingTriggerType,
)
from app.ml.retraining.service import (
    PolicyDefaults,
    RetrainingService,
    _automatic_trigger,
    _data_quality_trigger,
    _states,
)
from app.models.user import User, UserRole
from app.repositories.ai_governance import TrainingJobRepository
from app.repositories.ai_retraining import RetrainingRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

NOW = datetime(2026, 7, 18, 12, tzinfo=UTC)


class FakeQueue:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.job_ids: list[UUID] = []

    def enqueue(self, training_job_id: UUID) -> str:
        if self.fail:
            raise ConnectionError("redis private details")
        self.job_ids.append(training_job_id)
        return f"retraining-message-{training_job_id}"


class FakeRegistry(BaseModelRegistry):
    def __init__(self, version: RegisteredModelVersion) -> None:
        self.version = version

    def register(self, request: ModelRegistrationRequest) -> RegisteredModelVersion:
        _ = request
        raise AssertionError("Retraining orchestration must not register directly.")

    def resolve(
        self, registered_model_name: str, version_or_alias: str
    ) -> RegisteredModelVersion:
        assert registered_model_name == self.version.registered_model_name
        assert version_or_alias in {self.version.version, "champion"}
        return self.version

    def assign_alias(
        self, registered_model_name: str, alias: str, version: str
    ) -> RegisteredModelVersion:
        _ = (registered_model_name, alias, version)
        raise AssertionError("Retraining orchestration must not promote aliases.")


class FakeMonitoring(PredictionMonitoringService):
    def __init__(self, report: ModelDriftReport) -> None:
        self.report = report

    async def drift(
        self,
        *,
        registered_model_name: str,
        version_or_alias: str,
        start_at: datetime | None,
        end_at: datetime | None,
        minimum_sample_count: int | None,
    ) -> ModelDriftReport:
        _ = (registered_model_name, version_or_alias, minimum_sample_count)
        if start_at is None and end_at is None:
            return self.report
        return replace(
            self.report,
            start_at=start_at or self.report.start_at,
            end_at=end_at or self.report.end_at,
        )


def _specification() -> RandomForestRegressionJobSpec:
    return RandomForestRegressionJobSpec(
        training_features=((0.0,), (1.0,), (2.0,)),
        training_targets=(0.0, 1.0, 2.0),
        evaluation_features=((0.5,), (1.5,)),
        evaluation_targets=(0.5, 1.5),
        hyperparameters={"n_estimators": 3, "n_jobs": 1},
        experiment_name="Trusted Retraining Evidence",
        registered_model_name="factory_quality",
        tags={"purpose": "trusted-source"},
    )


def _version() -> RegisteredModelVersion:
    return RegisteredModelVersion(
        registered_model_name="factory_quality",
        version="3",
        run_id="source-run",
        source_uri="models:/factory_quality/3",
        key=TrainerKey(AlgorithmType.RANDOM_FOREST, TaskType.REGRESSION),
        status=RegisteredModelVersionStatus.READY,
        aliases=("champion",),
    )


def _report() -> ModelDriftReport:
    return ModelDriftReport(
        registered_model_name="factory_quality",
        model_version="3",
        key=random_forest_key(TaskType.REGRESSION),
        reference_source=ReferenceProfileSource.EVALUATION,
        reference_sample_count=20,
        current_sample_count=25,
        start_at=NOW - timedelta(days=1),
        end_at=NOW,
        feature_results=(
            FeatureDriftResult(
                feature_index=0,
                psi=0.4,
                reference_sample_count=20,
                current_sample_count=25,
                missing_rate_difference=0.0,
                out_of_reference_range_proportion=0.0,
                severity=DriftSeverity.CRITICAL,
            ),
        ),
        prediction_result=RegressionPredictionDrift(
            psi=0.3,
            mean_shift=0.2,
            standard_deviation_ratio=1.1,
            reference_sample_count=20,
            current_sample_count=25,
            severity=DriftSeverity.CRITICAL,
        ),
        aggregate_status=DriftSeverity.CRITICAL,
        thresholds=DriftThresholds(0.1, 0.25, 0.05, 0.1),
        generated_at=NOW,
        matched_event_count=25,
        analyzed_event_count=25,
        truncated=False,
        analysis_warning=None,
    )


def test_trigger_type_uses_its_own_drift_component_not_combined_status() -> None:
    report = _report()
    feature_stable = replace(
        report,
        feature_results=(
            replace(report.feature_results[0], severity=DriftSeverity.STABLE),
        ),
        aggregate_status=DriftSeverity.CRITICAL,
    )

    feature_trigger = _automatic_trigger(
        trigger_type=RetrainingTriggerType.FEATURE_DRIFT,
        version=_version(),
        report=feature_stable,
        start_at=None,
        end_at=None,
    )
    prediction_trigger = _automatic_trigger(
        trigger_type=RetrainingTriggerType.PREDICTION_DRIFT,
        version=_version(),
        report=feature_stable,
        start_at=None,
        end_at=None,
    )

    assert feature_trigger.aggregate_status is DriftSeverity.STABLE
    assert prediction_trigger.aggregate_status is DriftSeverity.CRITICAL


def test_data_quality_trigger_uses_bounded_issue_severity_and_counts() -> None:
    report = PredictionDataQualityReport(
        registered_model_name="factory_quality",
        model_version="3",
        start_at=NOW - timedelta(days=1),
        end_at=NOW,
        request_count=25,
        row_count=25,
        missing_value_count=1,
        non_finite_value_count=0,
        feature_count_mismatch_requests=0,
        empty_batch_requests=0,
        constant_column_occurrences=0,
        out_of_reference_range_count=0,
        finite_value_count=24,
        out_of_reference_range_proportion=0.0,
        issues=(
            DataQualityIssue(
                code="missing_values",
                severity=DataQualitySeverity.CRITICAL,
                count=1,
                proportion=0.04,
            ),
        ),
        matched_event_count=25,
        analyzed_event_count=25,
        truncated=False,
        analysis_warning=None,
    )

    trigger = _data_quality_trigger(report)

    assert trigger.trigger_type is RetrainingTriggerType.DATA_QUALITY
    assert trigger.aggregate_status is DriftSeverity.CRITICAL
    assert trigger.current_sample_count == 25
    assert trigger.reference.startswith("quality:3:")


def test_cooldown_expires_at_the_exact_boundary() -> None:
    policy = RetrainingPolicy(
        id=uuid4(),
        registered_model_name="factory_quality",
        enabled=True,
        allowed_trigger_types=frozenset(RetrainingTriggerType),
        minimum_drift_status=DriftSeverity.CRITICAL,
        minimum_current_sample_count=20,
        cooldown_seconds=3600,
        maximum_requests_per_day=1,
        maximum_requests_per_week=3,
        maximum_active_requests=1,
        require_champion_source=True,
        allow_truncated_drift=True,
        created_by_user_id=uuid4(),
        created_at=NOW,
        updated_at=NOW,
    )

    active, _ = _states(
        policy=policy,
        counts=(0, 0, 0, NOW - timedelta(seconds=3599)),
        now=NOW,
    )
    expired, _ = _states(
        policy=policy,
        counts=(0, 0, 0, NOW - timedelta(seconds=3600)),
        now=NOW,
    )

    assert active.active is True
    assert active.remaining_seconds == 1
    assert expired.active is False
    assert expired.remaining_seconds == 0


async def _source_evidence(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, UUID]:
    user = User(
        email=f"retraining-service-{uuid4()}@example.com",
        hashed_password="not-used",
        role=UserRole.ENGINEER,
        is_active=True,
    )
    async with session_factory() as session:
        session.add(user)
        await session.commit()
        repository = TrainingJobRepository(session)
        queued = await repository.create(
            job_id=uuid4(),
            requested_by_user_id=user.id,
            key=random_forest_key(TaskType.REGRESSION),
            specification=_specification(),
            idempotency_key="source-job",
            request_fingerprint=_specification().fingerprint(),
            max_attempts=3,
            queued_at=NOW - timedelta(days=2),
        )
        await repository.commit()
        running = await repository.claim_queued(job_id=queued.id, started_at=NOW)
        assert running is not None
        await repository.commit()
        succeeded = await repository.mark_succeeded(
            job_id=queued.id,
            expected_version=running.state_version,
            finished_at=NOW,
            local_execution_run_id=uuid4(),
            mlflow_experiment_id="experiment",
            mlflow_run_id="source-run",
            registered_model_version="3",
            metrics={"rmse": 1.0, "mae": 0.8, "r2": 0.5},
        )
        assert succeeded is not None
        await repository.commit()
    return user.id, queued.id


def _service(
    *,
    repository: RetrainingRepository,
    jobs: TrainingJobService,
) -> RetrainingService:
    return RetrainingService(
        repository=repository,
        monitoring_service=FakeMonitoring(_report()),
        model_registry=FakeRegistry(_version()),
        training_job_service=jobs,
        evaluator=RetrainingPolicyEvaluator(),
        defaults=PolicyDefaults(3600, 1, 3, 1, DriftSeverity.CRITICAL, True),
        clock=lambda: NOW,
    )


@pytest.mark.anyio
async def test_eligible_evaluation_checkpoints_and_reuses_background_job_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, source_job_id = await _source_evidence(session_factory)
    queue = FakeQueue()
    async with session_factory() as session:
        retraining_repository = RetrainingRepository(session)
        job_repository = TrainingJobRepository(session)
        service = _service(
            repository=retraining_repository,
            jobs=TrainingJobService(
                repository=job_repository, queue=queue, max_attempts=3
            ),
        )
        await service.put_policy(
            registered_model_name="factory_quality",
            created_by_user_id=user_id,
            enabled=True,
            allowed_trigger_types=frozenset(RetrainingTriggerType),
            minimum_drift_status=None,
            minimum_current_sample_count=20,
            cooldown_seconds=None,
            maximum_requests_per_day=None,
            maximum_requests_per_week=None,
            maximum_active_requests=None,
            require_champion_source=True,
            allow_truncated_drift=None,
        )
        result = await service.evaluate_automatic(
            registered_model_name="factory_quality",
            version_or_alias="champion",
            trigger_type=RetrainingTriggerType.FEATURE_DRIFT,
            start_at=None,
            end_at=None,
            minimum_sample_count=None,
            submit_if_eligible=True,
            requested_by_user_id=user_id,
        )
        repeated = await service.evaluate_automatic(
            registered_model_name="factory_quality",
            version_or_alias="champion",
            trigger_type=RetrainingTriggerType.FEATURE_DRIFT,
            start_at=None,
            end_at=None,
            minimum_sample_count=None,
            submit_if_eligible=True,
            requested_by_user_id=user_id,
        )
        assert result.request is not None
        assert repeated.request is not None
        training_job_id = result.request.training_job_id
        assert training_job_id is not None
        job = await job_repository.get_by_id(training_job_id)
        audits = await retraining_repository.list_audits(limit=10, offset=0)

    assert result.decision.status is RetrainingDecisionStatus.ELIGIBLE
    assert result.request.source_training_job_id == source_job_id
    assert result.request.request_status is RetrainingRequestStatus.SUBMITTED
    assert repeated.decision.status is RetrainingDecisionStatus.BLOCKED_DUPLICATE
    assert repeated.request.id == result.request.id
    assert len(queue.job_ids) == 1
    assert job is not None
    assert job.specification.tags["retraining"] == "true"
    assert job.specification.tags["retraining_request_id"] == str(result.request.id)
    assert job.specification.tags["source_model_version"] == "3"
    assert audits.total == 2


@pytest.mark.anyio
async def test_submission_failure_leaves_audited_recoverable_pending_request(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    user_id, _ = await _source_evidence(session_factory)
    queue = FakeQueue(fail=True)
    async with session_factory() as session:
        repository = RetrainingRepository(session)
        service = _service(
            repository=repository,
            jobs=TrainingJobService(
                repository=TrainingJobRepository(session),
                queue=queue,
                max_attempts=3,
            ),
        )
        await service.put_policy(
            registered_model_name="factory_quality",
            created_by_user_id=user_id,
            enabled=True,
            allowed_trigger_types=frozenset(RetrainingTriggerType),
            minimum_drift_status=None,
            minimum_current_sample_count=20,
            cooldown_seconds=None,
            maximum_requests_per_day=None,
            maximum_requests_per_week=None,
            maximum_active_requests=None,
            require_champion_source=True,
            allow_truncated_drift=None,
        )
        with pytest.raises(RetrainingDependencyError, match="reconciliation"):
            await service.evaluate_automatic(
                registered_model_name="factory_quality",
                version_or_alias="3",
                trigger_type=RetrainingTriggerType.PREDICTION_DRIFT,
                start_at=None,
                end_at=None,
                minimum_sample_count=None,
                submit_if_eligible=True,
                requested_by_user_id=user_id,
            )
        page = await repository.list_requests(
            registered_model_name="factory_quality", limit=10, offset=0
        )
        audits = await repository.list_audits(limit=10, offset=0)

    assert page.total == 1
    assert page.items[0].request_status is RetrainingRequestStatus.PENDING
    assert page.items[0].safe_failure_code == "training_submission_pending"
    assert audits.total == 1
