"""Bounded, idempotent retraining checkpoint reconciliation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import UUID

from app.config.settings import Settings, get_settings
from app.db.session import build_session_factory
from app.ml.composition import create_ai_model_registry
from app.ml.jobs import TrainingJobStatus
from app.ml.jobs.queue import DramatiqTrainingJobQueue
from app.ml.jobs.service import TrainingJobService
from app.ml.monitoring import (
    DriftDetectionEngine,
    DriftSeverity,
    DriftThresholds,
    PredictionCaptureHealth,
)
from app.ml.monitoring.service import PredictionMonitoringService
from app.ml.retraining.comparison import compare_candidates
from app.ml.retraining.models import RetrainingRequestStatus
from app.ml.retraining.policy import RetrainingPolicyEvaluator
from app.ml.retraining.service import PolicyDefaults, RetrainingService
from app.repositories.ai_governance import TrainingJobRepository
from app.repositories.ai_monitoring import PredictionMonitoringRepository
from app.repositories.ai_retraining import RetrainingRepository
from app.utils.security import utc_now


@dataclass(frozen=True, slots=True)
class RetrainingReconciliationResult:
    """Safe bounded counts from one reconciliation pass."""

    inspected: int
    submitted: int
    synchronized: int
    failed: int


class RetrainingReconciliationService:
    """Resume missing submission and synchronize existing job terminal states."""

    def __init__(
        self,
        *,
        service: RetrainingService,
        repository: RetrainingRepository,
        batch_size: int,
    ) -> None:
        if batch_size <= 0 or batch_size > 1000:
            raise ValueError(
                "Retraining reconciliation batch size is outside [1, 1000]."
            )
        self._service = service
        self._repository = repository
        self._batch_size = batch_size

    async def reconcile(self) -> RetrainingReconciliationResult:
        """Advance each recoverable request once and never mutate registry aliases."""
        requests = await self._repository.list_reconcilable(limit=self._batch_size)
        submitted = synchronized = failed = 0
        for request in requests:
            if request.training_job_id is None:
                await self._service.resume_submission(request, None)
                submitted += 1
                continue
            outcome = await RetrainingCompletionService(
                repository=self._repository
            ).synchronize(request.training_job_id)
            if outcome == "failed":
                failed += 1
            elif outcome == "synchronized":
                synchronized += 1
        await self._repository.commit()
        return RetrainingReconciliationResult(
            len(requests), submitted, synchronized, failed
        )


class RetrainingCompletionService:
    """Synchronize one existing job without training, registration, or promotion."""

    def __init__(self, *, repository: RetrainingRepository) -> None:
        self._repository = repository

    async def synchronize(self, training_job_id: UUID) -> str:
        """Return a safe no-op/synchronized/failed outcome for one linked job."""
        request = await self._repository.get_by_training_job(training_job_id)
        job = await self._repository.get_training_job(training_job_id)
        if request is None or job is None:
            return "no_op"
        if request.request_status in {
            RetrainingRequestStatus.COMPLETED,
            RetrainingRequestStatus.FAILED,
            RetrainingRequestStatus.CANCELLED,
        }:
            return "no_op"
        now = utc_now()
        if job.status is TrainingJobStatus.RUNNING:
            await self._repository.update_execution(
                request_id=request.id,
                status=RetrainingRequestStatus.TRAINING,
                started_at=job.started_at,
                updated_at=now,
            )
            await self._repository.commit()
            return "synchronized"
        if job.status is TrainingJobStatus.SUCCEEDED:
            if (
                request.request_status is not RetrainingRequestStatus.CANDIDATE_CREATED
                or request.resulting_model_version is None
            ):
                await self._repository.update_execution(
                    request_id=request.id,
                    status=RetrainingRequestStatus.CANDIDATE_CREATED,
                    resulting_model_version=job.registered_model_version,
                    updated_at=now,
                )
                await self._repository.commit()
            source = await self._repository.get_training_job(
                request.source_training_job_id
            )
            comparison = None
            if (
                source is not None
                and source.metrics is not None
                and job.metrics is not None
                and job.registered_model_version is not None
            ):
                comparison = compare_candidates(
                    task_type=request.key.task_type,
                    source_metrics=source.metrics,
                    candidate_metrics=job.metrics,
                    source_model_version=request.source_model_version,
                    candidate_model_version=job.registered_model_version,
                    compared_at=now,
                )
            await self._repository.update_execution(
                request_id=request.id,
                status=RetrainingRequestStatus.COMPLETED,
                completed_at=job.finished_at or now,
                resulting_model_version=job.registered_model_version,
                comparison=comparison,
                updated_at=now,
            )
            await self._repository.commit()
            return "synchronized"
        if job.status in {TrainingJobStatus.FAILED, TrainingJobStatus.CANCELLED}:
            status = (
                RetrainingRequestStatus.CANCELLED
                if job.status is TrainingJobStatus.CANCELLED
                else RetrainingRequestStatus.FAILED
            )
            await self._repository.update_execution(
                request_id=request.id,
                status=status,
                completed_at=job.finished_at or job.cancelled_at or now,
                failure_code=job.error_code,
                failure_message=job.safe_error_message,
                updated_at=now,
            )
            await self._repository.commit()
            return "failed"
        return "no_op"


async def reconcile_retraining_requests(
    settings: Settings,
) -> RetrainingReconciliationResult:
    """Run one bounded reconciliation pass for scheduled or CLI invocation."""
    session_factory = build_session_factory(settings.database_url)
    registry = create_ai_model_registry(settings)
    async with session_factory() as session:
        retraining_repository = RetrainingRepository(session)
        service = RetrainingService(
            repository=retraining_repository,
            monitoring_service=PredictionMonitoringService(
                repository=PredictionMonitoringRepository(session),
                model_registry=registry,
                drift_engine=DriftDetectionEngine(),
                capture_health=PredictionCaptureHealth(),
                minimum_sample_count=settings.monitoring_min_sample_count,
                maximum_window_days=settings.monitoring_max_window_days,
                maximum_events_per_window=settings.monitoring_max_events_per_window,
                thresholds=DriftThresholds(
                    warning=settings.drift_psi_warning_threshold,
                    critical=settings.drift_psi_critical_threshold,
                    missing_rate_warning=(
                        settings.drift_missing_rate_warning_threshold
                    ),
                    out_of_range_warning=(
                        settings.drift_out_of_range_warning_threshold
                    ),
                ),
            ),
            model_registry=registry,
            training_job_service=TrainingJobService(
                repository=TrainingJobRepository(session),
                queue=DramatiqTrainingJobQueue(),
                max_attempts=settings.training_job_max_attempts,
            ),
            evaluator=RetrainingPolicyEvaluator(),
            defaults=PolicyDefaults(
                cooldown_seconds=settings.retraining_default_cooldown_seconds,
                maximum_requests_per_day=(
                    settings.retraining_default_max_requests_per_day
                ),
                maximum_requests_per_week=(
                    settings.retraining_default_max_requests_per_week
                ),
                maximum_active_requests=(
                    settings.retraining_default_max_active_requests
                ),
                minimum_drift_status=DriftSeverity(
                    settings.retraining_default_minimum_drift_status
                ),
                allow_truncated_drift=settings.retraining_allow_truncated_drift,
            ),
        )
        return await RetrainingReconciliationService(
            service=service,
            repository=retraining_repository,
            batch_size=settings.retraining_reconciliation_batch_size,
        ).reconcile()


def main() -> None:
    """Print bounded safe counters for one administrative reconciliation pass."""
    result = asyncio.run(reconcile_retraining_requests(get_settings()))
    print(
        f"inspected={result.inspected} submitted={result.submitted} "
        f"synchronized={result.synchronized} failed={result.failed}"
    )


if __name__ == "__main__":
    main()
