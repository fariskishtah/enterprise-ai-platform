"""Service-layer exceptions."""


class DuplicateEmailError(ValueError):
    """Raised when an email is already registered."""


class InvalidCredentialsError(ValueError):
    """Raised when credentials are invalid."""


class InvalidRefreshTokenError(ValueError):
    """Raised when a refresh token is invalid or no longer usable."""


class InactiveUserError(ValueError):
    """Raised when an inactive user attempts an authenticated operation."""


class ResourceNotFoundError(ValueError):
    """Raised when a requested resource does not exist."""


class RelatedResourceNotFoundError(ValueError):
    """Raised when a referenced parent resource does not exist."""


class DuplicateCompanyNameError(ValueError):
    """Raised when a company name is already used."""


class DuplicateSensorNameError(ValueError):
    """Raised when a sensor name is already used inside a machine."""


class InvalidSensorRangeError(ValueError):
    """Raised when a sensor value range is invalid."""


class InvalidSensorReadingError(ValueError):
    """Raised when a sensor reading fails domain validation."""


class InvalidSensorDataUploadError(ValueError):
    """Raised when a sensor data upload cannot be processed."""


class InvalidFeatureDatasetError(ValueError):
    """Raised when a feature dataset cannot be generated."""


class DuplicateExperimentNameError(ValueError):
    """Raised when an experiment name is already used."""


class DuplicateModelArtifactVersionError(ValueError):
    """Raised when a model artifact version is already registered for a run."""


class InvalidTrainingRunError(ValueError):
    """Raised when a training run request is invalid."""


class InvalidMLOpsConfigurationError(ValueError):
    """Raised when an MLOps configuration file is invalid."""
