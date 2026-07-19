"""Exceptions raised at metrics data boundaries."""


class MetricsDataValidationError(ValueError):
    """Raised when metric inputs violate the supported NumPy contract."""
