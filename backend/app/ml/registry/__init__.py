"""Public fitted-model registry contracts and MLflow adapter."""

from app.ml.registry.base import BaseModelRegistry
from app.ml.registry.exceptions import (
    ModelRegistrationError,
    ModelRegistryError,
    ModelRegistryValidationError,
    RegisteredModelVersionNotFoundError,
    RegistryMetadataError,
)
from app.ml.registry.mlflow import MLflowModelRegistry
from app.ml.registry.models import (
    PROTECTED_MODEL_VERSION_TAGS,
    ModelRegistrationRequest,
    RegisteredModelVersion,
    RegisteredModelVersionStatus,
)
from app.ml.registry.naming import (
    build_registered_model_name,
    validate_registered_model_name,
    validate_version_or_alias,
)

__all__ = [
    "PROTECTED_MODEL_VERSION_TAGS",
    "BaseModelRegistry",
    "MLflowModelRegistry",
    "ModelRegistrationError",
    "ModelRegistrationRequest",
    "ModelRegistryError",
    "ModelRegistryValidationError",
    "RegisteredModelVersion",
    "RegisteredModelVersionNotFoundError",
    "RegisteredModelVersionStatus",
    "RegistryMetadataError",
    "build_registered_model_name",
    "validate_registered_model_name",
    "validate_version_or_alias",
]
