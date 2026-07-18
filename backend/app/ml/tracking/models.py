"""Immutable experiment-tracking requests and results."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from types import MappingProxyType

from app.ml.artifacts import ArtifactFormat, ArtifactInfo
from app.ml.base import TrainerKey
from app.ml.tracking.exceptions import (
    ProtectedTrackingTagError,
    TrackingValidationError,
    UnsupportedTrackingParameterError,
)

type TrackingParameterValue = str | int | float | bool | None

PROTECTED_TRACKING_TAGS = frozenset(
    {
        "algorithm",
        "task_type",
        "platform_component",
        "model_format",
    },
)

_TRACKING_KEY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,249}$")


class ExperimentRunStatus(StrEnum):
    """Terminal statuses returned by the successful-run tracker contract."""

    FINISHED = "FINISHED"


@dataclass(frozen=True, slots=True)
class ExperimentRunRequest:
    """Typed values required to log one successful local execution."""

    experiment_name: str
    run_name: str | None
    key: TrainerKey
    parameters: Mapping[str, TrackingParameterValue]
    metrics: Mapping[str, float]
    artifact: ArtifactInfo
    tags: Mapping[str, str]

    def __post_init__(self) -> None:
        """Validate text fields and detach supplied mutable mappings."""
        _validate_text(self.experiment_name, name="experiment_name", max_length=255)
        if self.run_name is not None:
            _validate_text(self.run_name, name="run_name", max_length=255)
        if self.artifact.format is not ArtifactFormat.JOBLIB:
            raise TrackingValidationError(
                "Only Joblib artifacts can be logged by the AI Core tracker.",
            )

        parameters = normalize_tracking_parameters(self.parameters)
        metrics = normalize_tracking_metrics(self.metrics)
        tags = normalize_tracking_tags(self.tags)
        object.__setattr__(self, "parameters", parameters)
        object.__setattr__(self, "metrics", metrics)
        object.__setattr__(self, "tags", tags)


@dataclass(frozen=True, slots=True)
class ExperimentRunInfo:
    """Platform-owned metadata for a completed MLflow run."""

    experiment_id: str
    run_id: str
    artifact_uri: str
    status: ExperimentRunStatus

    def __post_init__(self) -> None:
        """Require the external identifiers returned by MLflow."""
        _validate_text(self.experiment_id, name="experiment_id", max_length=255)
        _validate_text(self.run_id, name="run_id", max_length=255)
        _validate_text(self.artifact_uri, name="artifact_uri", max_length=4096)


def normalize_tracking_parameters(
    parameters: Mapping[str, object],
) -> Mapping[str, TrackingParameterValue]:
    """Copy and runtime-check supported scalar parameter values."""
    normalized: dict[str, TrackingParameterValue] = {}
    for key, value in parameters.items():
        _validate_tracking_key(key, kind="parameter")
        if (
            value is None
            or isinstance(value, (str, bool, int))
            or (isinstance(value, float) and isfinite(value))
        ):
            normalized[key] = value
        else:
            raise UnsupportedTrackingParameterError(
                f"Tracking parameter '{key}' must be a finite scalar or null.",
            )
    return MappingProxyType(normalized)


def normalize_tracking_metrics(
    metrics: Mapping[str, float],
) -> Mapping[str, float]:
    """Copy metrics while requiring finite numeric values."""
    normalized: dict[str, float] = {}
    for key, value in metrics.items():
        _validate_tracking_key(key, kind="metric")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TrackingValidationError(
                f"Tracking metric '{key}' must be a finite float.",
            )
        normalized_value = float(value)
        if not isfinite(normalized_value):
            raise TrackingValidationError(
                f"Tracking metric '{key}' must be a finite float.",
            )
        normalized[key] = normalized_value
    return MappingProxyType(normalized)


def normalize_tracking_tags(tags: Mapping[str, str]) -> Mapping[str, str]:
    """Copy supplied tags and reject protected platform keys."""
    normalized: dict[str, str] = {}
    for key, value in tags.items():
        _validate_tracking_key(key, kind="tag")
        if key in PROTECTED_TRACKING_TAGS:
            raise ProtectedTrackingTagError(
                f"Tracking tag '{key}' is protected by the platform.",
            )
        if not isinstance(value, str) or not value or len(value) > 5000:
            raise TrackingValidationError(
                f"Tracking tag '{key}' must be a non-empty string.",
            )
        normalized[key] = value
    return MappingProxyType(normalized)


def format_tracking_parameter(value: TrackingParameterValue) -> str:
    """Return a stable MLflow parameter representation without object coercion."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, int):
        return str(value)
    return repr(value)


def _validate_tracking_key(key: str, *, kind: str) -> None:
    if not isinstance(key, str) or _TRACKING_KEY_PATTERN.fullmatch(key) is None:
        raise TrackingValidationError(
            f"Tracking {kind} names must use letters, numbers, dots, dashes, "
            "or underscores.",
        )


def _validate_text(value: str, *, name: str, max_length: int) -> None:
    if not value.strip() or len(value) > max_length:
        raise TrackingValidationError(
            f"{name} must be a non-empty string of at most {max_length} characters.",
        )
