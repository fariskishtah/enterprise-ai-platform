"""Errors raised by AI Core training and prediction application services."""


class PredictionServiceError(Exception):
    """Base exception for registered-model prediction failures."""


class RegisteredModelLoadError(PredictionServiceError):
    """Raised when a registered model artifact cannot be loaded."""


class RegisteredModelTypeMismatchError(PredictionServiceError, TypeError):
    """Raised when a loaded model has an unexpected runtime type."""


class PredictionTrainerKeyMismatchError(PredictionServiceError):
    """Raised when a resolved model belongs to another trainer key."""
