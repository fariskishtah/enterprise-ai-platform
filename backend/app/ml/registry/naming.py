"""Deterministic safe names for AI Core registered models."""

import re

from app.ml.base import TrainerKey
from app.ml.registry.exceptions import ModelRegistryValidationError

_MODEL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{2,127}$")
_MODEL_PREFIX_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_MODEL_ALIAS_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")


def build_registered_model_name(
    key: TrainerKey,
    *,
    prefix: str = "ai_core",
) -> str:
    """Build a deterministic name from a validated prefix and trainer key."""
    if _MODEL_PREFIX_PATTERN.fullmatch(prefix) is None:
        raise ModelRegistryValidationError(
            "Registered-model prefixes must use lower-case letters, numbers, "
            "or underscores.",
        )
    return validate_registered_model_name(
        f"{prefix}_{key.algorithm.value}_{key.task_type.value}",
    )


def validate_registered_model_name(name: str) -> str:
    """Return an already-safe registered model name without normalization."""
    if _MODEL_NAME_PATTERN.fullmatch(name) is None:
        raise ModelRegistryValidationError(
            "Registered model names must be 3-128 lower-case letters, numbers, "
            "or underscores and begin with a letter.",
        )
    return name


def validate_version_or_alias(value: str) -> str:
    """Validate an exact positive version or a safe MLflow alias."""
    if value.isdigit():
        if int(value) > 0:
            return value
    elif _MODEL_ALIAS_PATTERN.fullmatch(value) is not None:
        return value
    raise ModelRegistryValidationError(
        "version_or_alias must be a positive version or a safe alias.",
    )
