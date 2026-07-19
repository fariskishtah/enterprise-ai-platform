"""Exceptions raised by trainer registration and creation."""


class TrainerFactoryError(Exception):
    """Base exception for trainer registry and factory failures."""


class TrainerAlreadyRegisteredError(TrainerFactoryError):
    """Raised when a trainer key already has a registered provider."""


class TrainerNotRegisteredError(TrainerFactoryError):
    """Raised when a trainer key has no registered provider."""


class InvalidTrainerProviderError(TrainerFactoryError):
    """Raised when a provider does not create a trainer instance."""


class TrainerKeyMismatchError(TrainerFactoryError):
    """Raised when a trainer reports a different registered key."""
