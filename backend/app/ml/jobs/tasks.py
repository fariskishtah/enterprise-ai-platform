"""Dramatiq actor entrypoint for UUID-only training-job messages."""

import asyncio
import logging
from functools import lru_cache
from typing import Protocol, cast
from uuid import UUID

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import get_settings
from app.db.session import build_session_factory
from app.ml.composition import (
    create_ai_model_registry,
    create_ai_tracked_training_service,
)
from app.ml.jobs.exceptions import RetryableTrainingJobError
from app.ml.jobs.worker import (
    TrainingJobWorker,
    WorkerExecutionState,
    execute_tracked_training_specification,
)
from app.ml.monitoring.maintenance import (
    reconcile_stale_alerts,
    retain_monitoring_evaluations,
)
from app.ml.monitoring.reconcile import reconcile_missing_reference_profiles
from app.ml.monitoring.retention import retain_prediction_events
from app.ml.monitoring.scheduled import run_scheduled_monitoring
from app.ml.retraining.reconcile import reconcile_retraining_requests

_settings = get_settings()
logger = logging.getLogger(__name__)


class _RedisBrokerFactory(Protocol):
    def __call__(self, *, url: str) -> RedisBroker: ...


_redis_broker_factory = cast(_RedisBrokerFactory, RedisBroker)
broker = _redis_broker_factory(url=_settings.redis_url)
dramatiq.set_broker(broker)


@lru_cache
def _worker_session_factory(
    database_url: str,
) -> async_sessionmaker[AsyncSession]:
    """Build the process-local database pool lazily after worker fork."""
    return build_session_factory(database_url)


@dramatiq.actor(
    broker=broker,
    queue_name=_settings.training_queue_name,
    max_retries=_settings.training_job_max_attempts - 1,
    min_backoff=int(_settings.training_job_retry_base_seconds * 1000),
)
def execute_training_job(training_job_id: str) -> None:
    """Load and execute the authoritative persisted job specification."""
    try:
        job_id = UUID(training_job_id)
    except ValueError:
        return
    model_registry = create_ai_model_registry(_settings)
    training_service = create_ai_tracked_training_service(
        _settings,
        model_registry=model_registry,
    )

    def assign_candidate_alias(model_name: str, version: str) -> None:
        model_registry.assign_alias(model_name, "candidate", version)

    worker = TrainingJobWorker(
        session_factory=_worker_session_factory(_settings.database_url),
        execute_specification=lambda specification: (
            execute_tracked_training_specification(
                specification,
                service=training_service,
                profile_bin_count=_settings.monitoring_profile_bin_count,
            )
        ),
        assign_candidate_alias=assign_candidate_alias,
    )
    outcome = asyncio.run(worker.execute(job_id))
    try:
        asyncio.run(_synchronize_retraining_request(job_id))
    except Exception:
        logger.exception(
            "Retraining request synchronization failed for training job %s; "
            "bounded reconciliation is required.",
            job_id,
        )
    if outcome is WorkerExecutionState.RETRY:
        raise RetryableTrainingJobError(
            "The job was released for bounded queue retry.",
        )


async def _synchronize_retraining_request(training_job_id: UUID) -> None:
    """Noncritical targeted checkpoint update after the authoritative worker."""
    from app.ml.retraining.reconcile import RetrainingCompletionService
    from app.repositories.ai_retraining import RetrainingRepository

    async with _worker_session_factory(_settings.database_url)() as session:
        await RetrainingCompletionService(
            repository=RetrainingRepository(session)
        ).synchronize(training_job_id)


@dramatiq.actor(
    broker=broker,
    queue_name=_settings.monitoring_queue_name,
    max_retries=_settings.training_job_max_attempts - 1,
    min_backoff=int(_settings.training_job_retry_base_seconds * 1000),
)
def execute_scheduled_monitoring() -> None:
    """Evaluate eligible aliases only when scheduling is explicitly enabled."""
    if not _settings.monitoring_scheduling_enabled:
        logger.info("monitoring_job_skipped skipped_reason=scheduling_disabled")
        return
    summary = asyncio.run(run_scheduled_monitoring(_settings))
    logger.info(
        "monitoring_job_summary job_id=%s evaluated=%s skipped=%s failed=%s",
        summary.job_id,
        summary.evaluated,
        summary.skipped,
        summary.failed,
    )


@dramatiq.actor(broker=broker, queue_name=_settings.monitoring_queue_name)
def execute_prediction_event_retention() -> None:
    if not _settings.prediction_event_retention_scheduling_enabled:
        logger.info("prediction_event_retention_skipped skipped_reason=disabled")
        return
    result = asyncio.run(retain_prediction_events(_settings, dry_run=False))
    logger.info(
        "prediction_event_retention_complete eligible=%s deleted=%s skipped=%s "
        "failed=0",
        result.eligible_count,
        result.deleted_count,
        result.eligible_count - result.deleted_count,
    )


@dramatiq.actor(broker=broker, queue_name=_settings.monitoring_queue_name)
def execute_monitoring_evaluation_retention() -> None:
    if not _settings.monitoring_evaluation_retention_scheduling_enabled:
        logger.info("monitoring_evaluation_retention_skipped skipped_reason=disabled")
        return
    result = asyncio.run(retain_monitoring_evaluations(_settings, dry_run=False))
    logger.info(
        "monitoring_evaluation_retention_complete eligible=%s deleted=%s skipped=%s "
        "failed=0",
        result.eligible_count,
        result.deleted_count,
        result.eligible_count - result.deleted_count,
    )


@dramatiq.actor(broker=broker, queue_name=_settings.monitoring_queue_name)
def execute_reference_profile_reconciliation() -> None:
    if not _settings.reference_profile_reconciliation_scheduling_enabled:
        logger.info("reference_profile_reconciliation_skipped skipped_reason=disabled")
        return
    result = asyncio.run(reconcile_missing_reference_profiles(_settings))
    logger.info(
        "reference_profile_reconciliation_complete examined=%s created=%s "
        "skipped=%s repaired=%s failed=%s",
        result.examined,
        result.created,
        result.examined - result.created - result.failed,
        result.created,
        result.failed,
    )


@dramatiq.actor(broker=broker, queue_name=_settings.monitoring_queue_name)
def execute_retraining_reconciliation() -> None:
    if not _settings.retraining_reconciliation_scheduling_enabled:
        logger.info("retraining_reconciliation_skipped skipped_reason=disabled")
        return
    result = asyncio.run(reconcile_retraining_requests(_settings))
    logger.info(
        "retraining_reconciliation_complete inspected=%s submitted=%s "
        "synchronized=%s repaired=%s skipped=%s failed=%s",
        result.inspected,
        result.submitted,
        result.synchronized,
        result.submitted + result.synchronized,
        result.inspected - result.submitted - result.synchronized - result.failed,
        result.failed,
    )


@dramatiq.actor(broker=broker, queue_name=_settings.monitoring_queue_name)
def execute_stale_alert_reconciliation() -> None:
    if not _settings.stale_alert_reconciliation_scheduling_enabled:
        logger.info("stale_alert_reconciliation_skipped skipped_reason=disabled")
        return
    result = asyncio.run(reconcile_stale_alerts(_settings))
    logger.info(
        "stale_alert_reconciliation_complete resolved=%s repaired=%s "
        "skipped=0 failed=0",
        result.resolved_count,
        result.resolved_count,
    )
