"""Errors raised by fitted-model registry contracts and adapters."""


class ModelRegistryError(Exception):
    """Base exception for AI Core fitted-model registry failures."""


class ModelRegistryValidationError(ModelRegistryError, ValueError):
    """Raised when a registry request violates a platform boundary."""


class RegisteredModelVersionNotFoundError(ModelRegistryError, LookupError):
    """Raised when a registered model version or alias cannot be resolved."""


class ModelRegistrationError(ModelRegistryError):
    """Raised when MLflow cannot register a completed model artifact."""


class RegistryMetadataError(ModelRegistryError):
    """Raised when a resolved version lacks required platform metadata."""
