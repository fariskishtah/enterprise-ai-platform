"""Dramatiq actor entrypoint for UUID-only training-job messages."""

import asyncio
import logging
from functools import lru_cache
from typing import Protocol, cast
from uuid import UUID

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import Retries
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
from app.observability.logging import configure_logging, emit_safe
from app.observability.tracing import TracingConfig, traced_operation
from app.observability.worker import WorkerPrometheusMiddleware
from app.observability.worker_logging import WorkerLoggingMiddleware

_settings = get_settings()
logger = logging.getLogger(__name__)
configure_logging(
    enabled=_settings.structured_logging_enabled,
    log_format=_settings.log_format,
    log_level=_settings.log_level,
    service=_settings.log_service_name,
    environment=_settings.log_environment,
    access_logging_enabled=False,
)


class _RedisBrokerFactory(Protocol):
    def __call__(self, *, url: str) -> RedisBroker: ...


_redis_broker_factory = cast(_RedisBrokerFactory, RedisBroker)
broker = _redis_broker_factory(url=_settings.redis_url)
broker.add_middleware(
    WorkerLoggingMiddleware(
        enabled=_settings.structured_logging_enabled,
        log_format=_settings.log_format,
        log_level=_settings.log_level,
        service=_settings.log_service_name,
        environment=_settings.log_environment,
        tracing_config=TracingConfig(
            enabled=_settings.tracing_enabled,
            service_name=_settings.otel_worker_service_name,
            service_namespace=_settings.otel_service_namespace,
            environment=_settings.otel_environment,
            service_version=_settings.app_version,
            otlp_endpoint=_settings.otel_exporter_otlp_endpoint,
            otlp_insecure=_settings.otel_exporter_otlp_insecure,
            sampler=_settings.otel_traces_sampler,
            sampler_arg=_settings.otel_traces_sampler_arg,
        ),
    ),
    before=Retries,
)
broker.add_middleware(
    WorkerPrometheusMiddleware(
        enabled=_settings.observability_metrics_enabled,
        service=_settings.observability_service_name,
        environment=_settings.observability_environment,
        port=_settings.observability_worker_metrics_port,
    )
)
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
@traced_operation(
    "training.execution",
    attributes={"algorithm": "random_forest", "trigger": "background"},
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
        emit_safe(
            logger,
            logging.ERROR,
            "retraining_request_synchronization_failed",
            extra={
                "job_name": "training",
                "lifecycle_status": "checkpoint_failed",
            },
            exc_info=True,
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
@traced_operation("monitoring.evaluation", attributes={"trigger": "scheduled"})
def execute_scheduled_monitoring() -> None:
    """Evaluate eligible aliases only when scheduling is explicitly enabled."""
    if not _settings.monitoring_scheduling_enabled:
        emit_safe(
            logger,
            logging.INFO,
            "scheduled_job_disabled",
            extra={
                "job_name": "monitoring_evaluation",
                "lifecycle_status": "skipped",
            },
        )
        return
    asyncio.run(run_scheduled_monitoring(_settings))


@dramatiq.actor(broker=broker, queue_name=_settings.monitoring_queue_name)
@traced_operation(
    "maintenance.prediction_event_retention",
    attributes={"trigger": "scheduled"},
)
def execute_prediction_event_retention() -> None:
    if not _settings.prediction_event_retention_scheduling_enabled:
        emit_safe(
            logger,
            logging.INFO,
            "scheduled_job_disabled",
            extra={
                "job_name": "prediction_event_retention",
                "lifecycle_status": "skipped",
            },
        )
        return
    asyncio.run(retain_prediction_events(_settings, dry_run=False))


@dramatiq.actor(broker=broker, queue_name=_settings.monitoring_queue_name)
@traced_operation(
    "maintenance.monitoring_evaluation_retention",
    attributes={"trigger": "scheduled"},
)
def execute_monitoring_evaluation_retention() -> None:
    if not _settings.monitoring_evaluation_retention_scheduling_enabled:
        emit_safe(
            logger,
            logging.INFO,
            "scheduled_job_disabled",
            extra={
                "job_name": "monitoring_evaluation_retention",
                "lifecycle_status": "skipped",
            },
        )
        return
    asyncio.run(retain_monitoring_evaluations(_settings, dry_run=False))


@dramatiq.actor(broker=broker, queue_name=_settings.monitoring_queue_name)
@traced_operation(
    "monitoring.reference_profile_reconciliation",
    attributes={"trigger": "scheduled"},
)
def execute_reference_profile_reconciliation() -> None:
    if not _settings.reference_profile_reconciliation_scheduling_enabled:
        emit_safe(
            logger,
            logging.INFO,
            "scheduled_job_disabled",
            extra={
                "job_name": "reference_profile_reconciliation",
                "lifecycle_status": "skipped",
            },
        )
        return
    asyncio.run(reconcile_missing_reference_profiles(_settings))


@dramatiq.actor(broker=broker, queue_name=_settings.monitoring_queue_name)
@traced_operation("retraining.reconciliation", attributes={"trigger": "scheduled"})
def execute_retraining_reconciliation() -> None:
    if not _settings.retraining_reconciliation_scheduling_enabled:
        emit_safe(
            logger,
            logging.INFO,
            "scheduled_job_disabled",
            extra={
                "job_name": "retraining_reconciliation",
                "lifecycle_status": "skipped",
            },
        )
        return
    asyncio.run(reconcile_retraining_requests(_settings))


@dramatiq.actor(broker=broker, queue_name=_settings.monitoring_queue_name)
@traced_operation("alert.reconciliation", attributes={"trigger": "scheduled"})
def execute_stale_alert_reconciliation() -> None:
    if not _settings.stale_alert_reconciliation_scheduling_enabled:
        emit_safe(
            logger,
            logging.INFO,
            "scheduled_job_disabled",
            extra={
                "job_name": "stale_alert_reconciliation",
                "lifecycle_status": "skipped",
            },
        )
        return
    asyncio.run(reconcile_stale_alerts(_settings))
