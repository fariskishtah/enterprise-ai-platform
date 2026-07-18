"""Dramatiq actor entrypoint for UUID-only training-job messages."""

import asyncio
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

_settings = get_settings()


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
            )
        ),
        assign_candidate_alias=assign_candidate_alias,
    )
    outcome = asyncio.run(worker.execute(job_id))
    if outcome is WorkerExecutionState.RETRY:
        raise RetryableTrainingJobError(
            "The job was released for bounded queue retry.",
        )
