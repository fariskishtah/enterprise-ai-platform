"""Errors raised by experiment-tracking contracts and adapters."""


class ExperimentTrackingError(Exception):
    """Base exception for AI Core experiment-tracking failures."""


class TrackingValidationError(ExperimentTrackingError, ValueError):
    """Raised when a tracking request violates the platform boundary."""


class UnsupportedTrackingParameterError(TrackingValidationError):
    """Raised when a parameter value is not a supported tracking scalar."""


class ProtectedTrackingTagError(TrackingValidationError):
    """Raised when supplied tags attempt to replace a platform tag."""


class TrackingArtifactError(TrackingValidationError):
    """Raised when a successful execution artifact cannot be logged."""
