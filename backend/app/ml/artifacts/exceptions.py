"""Exceptions raised by local artifact persistence."""


class ArtifactManagerError(Exception):
    """Base exception for model artifact failures."""


class ArtifactAlreadyExistsError(ArtifactManagerError):
    """Raised when a save would overwrite an existing artifact."""


class ArtifactNotFoundError(ArtifactManagerError):
    """Raised when a requested artifact file does not exist."""


class ArtifactPathError(ArtifactManagerError):
    """Raised when an artifact path escapes its configured root."""


class ArtifactTypeMismatchError(ArtifactManagerError):
    """Raised when a loaded artifact has an unexpected model type."""
