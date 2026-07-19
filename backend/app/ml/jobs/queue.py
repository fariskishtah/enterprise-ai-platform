"""Redis-backed task submission boundary for background training."""

from typing import Protocol
from uuid import UUID


class TrainingJobQueue(Protocol):
    """Enqueue only the stable identifier of a persisted training job."""

    def enqueue(self, training_job_id: UUID) -> str:
        """Return the broker's durable message identifier."""


class DramatiqTrainingJobQueue:
    """Submit UUID-only messages to the configured Dramatiq actor."""

    def enqueue(self, training_job_id: UUID) -> str:
        """Enqueue one job without copying its dataset into Redis."""
        from app.ml.jobs.tasks import execute_training_job

        message = execute_training_job.send(str(training_job_id))
        return message.message_id
