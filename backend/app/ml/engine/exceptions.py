"""Exceptions raised by typed local training orchestration."""


class TrainingEngineError(Exception):
    """Base exception for training-engine contract failures."""


class TrainingModelTypeMismatchError(TrainingEngineError):
    """Raised when a fitted model violates its execution plan type."""
