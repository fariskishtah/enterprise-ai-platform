"""Exceptions raised by trainer registration and creation."""


class TrainerFactoryError(Exception):
    """Base exception for trainer registry and factory failures."""


class TrainerAlreadyRegisteredError(TrainerFactoryError):
    """Raised when an algorithm already has a registered provider."""


class TrainerNotRegisteredError(TrainerFactoryError):
    """Raised when an algorithm has no registered provider."""


class InvalidTrainerProviderError(TrainerFactoryError):
    """Raised when a provider does not create a trainer instance."""


class TrainerAlgorithmMismatchError(TrainerFactoryError):
    """Raised when a trainer reports a different registered algorithm."""
