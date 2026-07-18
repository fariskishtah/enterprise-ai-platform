"""Background training job application errors."""


class TrainingJobError(Exception):
    """Base error for persistent training-job operations."""


class TrainingJobNotFoundError(TrainingJobError):
    """Raised when a job is absent from the authorized scope."""


class TrainingJobConflictError(TrainingJobError):
    """Raised for invalid lifecycle or idempotency operations."""


class TrainingJobEnqueueError(TrainingJobError):
    """Raised after a queue submission failure is persisted safely."""


class TrainingJobQueuePersistenceError(TrainingJobError):
    """Raised when an enqueued job needs message-ID reconciliation."""


class RetryableTrainingJobError(TrainingJobError):
    """Signal the queue framework to redeliver a released job."""
