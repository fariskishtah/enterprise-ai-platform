"""Safe monitoring-domain and service exceptions."""


class PredictionMonitoringError(Exception):
    """Base exception for prediction monitoring failures."""


class MonitoringDataError(PredictionMonitoringError):
    """Raised when persisted monitoring JSON violates the typed contract."""


class MonitoringNotFoundError(PredictionMonitoringError):
    """Raised when an authorized event or reference profile is absent."""


class MonitoringPreconditionError(PredictionMonitoringError):
    """Raised when a report cannot be produced from the available data."""


class MonitoringWindowValidationError(PredictionMonitoringError):
    """Raised when a requested monitoring window is unsafe or invalid."""


class MonitoringPersistenceError(PredictionMonitoringError):
    """Raised when durable monitoring state cannot be read or written."""
