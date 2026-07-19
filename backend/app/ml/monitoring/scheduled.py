"""Dramatiq-invoked scheduled monitoring orchestration with database locking."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.config.settings import Settings
from app.db.session import build_session_factory
from app.ml.composition import create_ai_model_registry
from app.ml.jobs import DramatiqTrainingJobQueue
from app.ml.jobs.service import TrainingJobService
from app.ml.monitoring import (
    DriftDetectionEngine,
    DriftSeverity,
    DriftThresholds,
    PredictionCaptureHealth,
)
from app.ml.monitoring.alert_service import MonitoringAlertService
from app.ml.monitoring.evaluation_models import (
    ModelMonitoringEvaluation,
    MonitoringEvaluationStatus,
    MonitoringEvaluationTrigger,
)
from app.ml.monitoring.evaluation_service import MonitoringEvaluationService
from app.ml.monitoring.service import PredictionMonitoringService
from app.ml.registry import BaseModelRegistry
from app.ml.retraining import RetrainingPolicyEvaluator, RetrainingTriggerType
from app.ml.retraining.exceptions import RetrainingError
from app.ml.retraining.service import PolicyDefaults, RetrainingService
from app.repositories.ai_governance import TrainingJobRepository
from app.repositories.ai_monitoring import PredictionMonitoringRepository
from app.repositories.ai_retraining import RetrainingRepository
from app.repositories.monitoring_alerts import MonitoringAlertRepository
from app.repositories.monitoring_evaluations import MonitoringEvaluationRepository
from app.utils.security import utc_now

logger = logging.getLogger(__name__)


class PersistedEvaluationRetrainingPolicy(Protocol):
    async def evaluate_monitoring_evaluation(
        self,
        *,
        evaluation: ModelMonitoringEvaluation,
        trigger_type: RetrainingTriggerType,
        submit_if_eligible: bool,
        requested_by_user_id: UUID,
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class ScheduledModelOutcome:
    registered_model_name: str
    model_version: str | None
    alias: str
    status: str
    evaluation_id: UUID | None
    safe_failure_code: str | None


@dataclass(frozen=True, slots=True)
class ScheduledMonitoringSummary:
    job_id: UUID
    window_start: datetime
    window_end: datetime
    evaluated: int
    skipped: int
    failed: int
    duration_ms: float
    outcomes: tuple[ScheduledModelOutcome, ...]


class ScheduledMonitoringService:
    def __init__(
        self,
        *,
        evaluation_repository: MonitoringEvaluationRepository,
        lock_repository: MonitoringAlertRepository,
        evaluation_service: MonitoringEvaluationService,
        model_registry: BaseModelRegistry,
        aliases: tuple[str, ...],
        window_hours: int,
        interval_seconds: int,
        lock_timeout_seconds: int,
        maximum_models: int,
        retraining_service: PersistedEvaluationRetrainingPolicy | None,
        retraining_actor_user_id: UUID | None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._evaluations = evaluation_repository
        self._locks = lock_repository
        self._service = evaluation_service
        self._registry = model_registry
        self._aliases = aliases
        self._window_hours = window_hours
        self._interval_seconds = interval_seconds
        self._lock_timeout_seconds = lock_timeout_seconds
        self._maximum_models = maximum_models
        self._retraining = retraining_service
        self._retraining_actor_user_id = retraining_actor_user_id
        self._clock = clock

    async def run(self) -> ScheduledMonitoringSummary:
        started_clock = perf_counter()
        job_id = uuid4()
        now = self._clock()
        end = _interval_boundary(now, self._interval_seconds)
        start = end - timedelta(hours=self._window_hours)
        lock_key = f"monitoring-evaluation:{end.isoformat()}"
        owner = str(job_id)
        try:
            acquired = await self._locks.acquire_lock(
                lock_key=lock_key,
                owner_id=owner,
                acquired_at=now,
                expires_at=now + timedelta(seconds=self._lock_timeout_seconds),
            )
            await self._locks.commit()
        except (IntegrityError, SQLAlchemyError):
            await self._locks.rollback()
            acquired = False
        if not acquired:
            return ScheduledMonitoringSummary(
                job_id, start, end, 0, 1, 0, _duration_ms(started_clock), ()
            )

        outcomes: list[ScheduledModelOutcome] = []
        seen_versions: set[tuple[str, str]] = set()
        try:
            names = await self._evaluations.list_registered_model_names(
                limit=self._maximum_models
            )
            for name in names:
                for alias in self._aliases:
                    try:
                        version = self._registry.resolve(name, alias)
                    except Exception:
                        outcomes.append(
                            ScheduledModelOutcome(
                                name,
                                None,
                                alias,
                                "failed",
                                None,
                                "model_resolution_failed",
                            )
                        )
                        continue
                    identity = (name, version.version)
                    if identity in seen_versions:
                        outcomes.append(
                            ScheduledModelOutcome(
                                name, version.version, alias, "skipped", None, None
                            )
                        )
                        continue
                    seen_versions.add(identity)
                    try:
                        evaluation = await self._service.evaluate(
                            registered_model_name=name,
                            version_or_alias=version.version,
                            window_start=start,
                            window_end=end,
                            trigger=MonitoringEvaluationTrigger.SCHEDULED,
                        )
                        await self._apply_retraining(evaluation)
                        outcomes.append(
                            ScheduledModelOutcome(
                                name,
                                version.version,
                                alias,
                                evaluation.overall_status.value,
                                evaluation.id,
                                None,
                            )
                        )
                    except Exception:
                        outcomes.append(
                            ScheduledModelOutcome(
                                name,
                                version.version,
                                alias,
                                "failed",
                                None,
                                "monitoring_evaluation_failed",
                            )
                        )
        finally:
            try:
                await self._locks.release_lock(lock_key=lock_key, owner_id=owner)
                await self._locks.commit()
            except SQLAlchemyError:
                await self._locks.rollback()

        failed = sum(item.status == "failed" for item in outcomes)
        skipped = sum(item.status == "skipped" for item in outcomes)
        summary = ScheduledMonitoringSummary(
            job_id=job_id,
            window_start=start,
            window_end=end,
            evaluated=len(outcomes) - failed - skipped,
            skipped=skipped,
            failed=failed,
            duration_ms=_duration_ms(started_clock),
            outcomes=tuple(outcomes),
        )
        for item in summary.outcomes:
            logger.info(
                "monitoring_model_outcome job_id=%s model_name=%s model_version=%s "
                "alias=%s window_start=%s window_end=%s outcome_status=%s "
                "duration_ms=%.3f skipped_reason=%s safe_failure_code=%s",
                job_id,
                item.registered_model_name,
                item.model_version,
                item.alias,
                start.isoformat(),
                end.isoformat(),
                item.status,
                summary.duration_ms,
                "duplicate_exact_version" if item.status == "skipped" else None,
                item.safe_failure_code,
            )
        logger.info(
            "monitoring_job_complete job_id=%s window_start=%s window_end=%s "
            "evaluated=%s skipped=%s failed=%s duration_ms=%.3f",
            job_id,
            start.isoformat(),
            end.isoformat(),
            summary.evaluated,
            summary.skipped,
            summary.failed,
            summary.duration_ms,
        )
        return summary

    async def _apply_retraining(self, evaluation: ModelMonitoringEvaluation) -> None:
        if self._retraining is None or self._retraining_actor_user_id is None:
            return
        trigger: RetrainingTriggerType | None = None
        if evaluation.feature_drift_status is MonitoringEvaluationStatus.CRITICAL:
            trigger = RetrainingTriggerType.FEATURE_DRIFT
        elif evaluation.prediction_drift_status is MonitoringEvaluationStatus.CRITICAL:
            trigger = RetrainingTriggerType.PREDICTION_DRIFT
        elif evaluation.data_quality_status is MonitoringEvaluationStatus.CRITICAL:
            trigger = RetrainingTriggerType.DATA_QUALITY
        if trigger is None:
            return
        try:
            await self._retraining.evaluate_monitoring_evaluation(
                evaluation=evaluation,
                trigger_type=trigger,
                submit_if_eligible=True,
                requested_by_user_id=self._retraining_actor_user_id,
            )
        except RetrainingError:
            logger.warning(
                "monitoring_retraining_policy_failed evaluation_id=%s "
                "safe_failure_code=retraining_policy_unavailable",
                evaluation.id,
            )


async def run_scheduled_monitoring(settings: Settings) -> ScheduledMonitoringSummary:
    """Build one worker-scoped service graph and run a bounded scheduled pass."""
    session_factory = build_session_factory(settings.database_url)
    registry = create_ai_model_registry(settings)
    async with session_factory() as session:
        prediction_repository = PredictionMonitoringRepository(session)
        monitoring = PredictionMonitoringService(
            repository=prediction_repository,
            model_registry=registry,
            drift_engine=DriftDetectionEngine(),
            capture_health=PredictionCaptureHealth(),
            minimum_sample_count=settings.monitoring_min_sample_count,
            maximum_window_days=settings.monitoring_max_window_days,
            maximum_events_per_window=settings.monitoring_max_events_per_window,
            thresholds=DriftThresholds(
                warning=settings.drift_psi_warning_threshold,
                critical=settings.drift_psi_critical_threshold,
                missing_rate_warning=settings.drift_missing_rate_warning_threshold,
                out_of_range_warning=settings.drift_out_of_range_warning_threshold,
            ),
        )
        evaluation_repository = MonitoringEvaluationRepository(session)
        alert_repository = MonitoringAlertRepository(session)
        evaluation_service = MonitoringEvaluationService(
            repository=evaluation_repository,
            monitoring_service=monitoring,
            model_registry=registry,
            alert_service=MonitoringAlertService(repository=alert_repository),
            minimum_sample_count=settings.monitoring_min_sample_count,
            maximum_window_days=settings.monitoring_max_window_days,
            failure_rate_warning_threshold=(
                settings.monitoring_failure_rate_warning_threshold
            ),
            failure_rate_critical_threshold=(
                settings.monitoring_failure_rate_critical_threshold
            ),
        )
        retraining: RetrainingService | None = None
        if settings.monitoring_automatic_retraining_enabled:
            retraining_repository = RetrainingRepository(session)
            retraining = RetrainingService(
                repository=retraining_repository,
                monitoring_service=monitoring,
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
        return await ScheduledMonitoringService(
            evaluation_repository=evaluation_repository,
            lock_repository=alert_repository,
            evaluation_service=evaluation_service,
            model_registry=registry,
            aliases=settings.monitoring_aliases,
            window_hours=settings.monitoring_window_hours,
            interval_seconds=settings.monitoring_evaluation_interval_seconds,
            lock_timeout_seconds=settings.monitoring_lock_timeout_seconds,
            maximum_models=settings.monitoring_max_models_per_run,
            retraining_service=retraining,
            retraining_actor_user_id=settings.monitoring_retraining_actor_user_id,
        ).run()


def _interval_boundary(value: datetime, interval_seconds: int) -> datetime:
    utc = value.astimezone(UTC)
    seconds = int(utc.timestamp())
    return datetime.fromtimestamp(seconds - seconds % interval_seconds, tz=UTC)


def _duration_ms(started_clock: float) -> float:
    return max((perf_counter() - started_clock) * 1000.0, 0.0)
