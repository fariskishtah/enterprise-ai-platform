"""Safe application exceptions for controlled retraining."""


class RetrainingError(Exception):
    """Base retraining failure."""


class RetrainingValidationError(RetrainingError):
    """A retraining policy or request was invalid."""


class RetrainingNotFoundError(RetrainingError):
    """A policy, request, source version, or training proof was absent."""


class RetrainingConflictError(RetrainingError):
    """A direct submission conflicted with durable retraining state."""


class RetrainingPersistenceError(RetrainingError):
    """Retraining state could not be read or persisted safely."""


class RetrainingDependencyError(RetrainingError):
    """A monitoring, queue, or registry dependency failed safely."""


class RetrainingRegistryError(RetrainingDependencyError):
    """Exact-version registry resolution failed safely."""
