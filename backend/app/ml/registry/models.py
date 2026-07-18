"""Immutable fitted-model registry requests and results."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from app.ml.base import TrainerKey
from app.ml.registry.exceptions import ModelRegistryValidationError
from app.ml.registry.naming import (
    validate_registered_model_name,
    validate_version_or_alias,
)

PROTECTED_MODEL_VERSION_TAGS = frozenset(
    {
        "algorithm",
        "task_type",
        "platform_component",
    },
)

_TAG_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,249}$")


class RegisteredModelVersionStatus(StrEnum):
    """MLflow model-version statuses exposed by the platform boundary."""

    PENDING_REGISTRATION = "PENDING_REGISTRATION"
    FAILED_REGISTRATION = "FAILED_REGISTRATION"
    READY = "READY"


@dataclass(frozen=True, slots=True)
class ModelRegistrationRequest:
    """Values required to register one completed tracked model artifact."""

    registered_model_name: str
    source_run_id: str
    artifact_uri: str
    key: TrainerKey
    description: str | None
    tags: Mapping[str, str]

    def __post_init__(self) -> None:
        """Validate registry identifiers and detach supplied mutable tags."""
        validate_registered_model_name(self.registered_model_name)
        _validate_text(self.source_run_id, name="source_run_id", max_length=255)
        _validate_text(self.artifact_uri, name="artifact_uri", max_length=4096)
        if self.description is not None:
            _validate_text(self.description, name="description", max_length=5000)
        object.__setattr__(self, "tags", _normalize_tags(self.tags))


@dataclass(frozen=True, slots=True)
class RegisteredModelVersion:
    """Platform-owned metadata for one registered fitted model version."""

    registered_model_name: str
    version: str
    run_id: str
    source_uri: str
    key: TrainerKey
    status: RegisteredModelVersionStatus
    aliases: tuple[str, ...]

    def __post_init__(self) -> None:
        """Require stable identifiers in resolved registry metadata."""
        validate_registered_model_name(self.registered_model_name)
        if not self.version.isdigit() or int(self.version) <= 0:
            raise ModelRegistryValidationError(
                "Registered model versions must be positive integer strings.",
            )
        _validate_text(self.run_id, name="run_id", max_length=255)
        _validate_text(self.source_uri, name="source_uri", max_length=4096)


@dataclass(frozen=True, slots=True)
class RegisteredModelAlias:
    """One registry alias and its exact immutable version holder."""

    alias: str
    version: str

    def __post_init__(self) -> None:
        """Require a safe alias and exact positive version."""
        if validate_version_or_alias(self.alias).isdigit():
            raise ModelRegistryValidationError("Model aliases must not be numeric.")
        if not self.version.isdigit() or int(self.version) <= 0:
            raise ModelRegistryValidationError(
                "Registered model versions must be positive integer strings.",
            )


def _normalize_tags(tags: Mapping[str, str]) -> Mapping[str, str]:
    normalized: dict[str, str] = {}
    for key, value in tags.items():
        if _TAG_NAME_PATTERN.fullmatch(key) is None:
            raise ModelRegistryValidationError(
                "Model-version tag names contain unsupported characters.",
            )
        if key in PROTECTED_MODEL_VERSION_TAGS:
            raise ModelRegistryValidationError(
                f"Model-version tag '{key}' is protected by the platform.",
            )
        if not isinstance(value, str) or not value or len(value) > 5000:
            raise ModelRegistryValidationError(
                f"Model-version tag '{key}' must be a non-empty string.",
            )
        normalized[key] = value
    return MappingProxyType(normalized)


def _validate_text(value: str, *, name: str, max_length: int) -> None:
    if not value.strip() or len(value) > max_length:
        raise ModelRegistryValidationError(
            f"{name} must be a non-empty string of at most {max_length} characters.",
        )
