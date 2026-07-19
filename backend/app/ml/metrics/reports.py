"""Immutable typed metric reports and workflow mapping exports."""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Protocol


class MetricsReport(Protocol):
    """Structural report boundary consumed by the training engine."""

    def to_mapping(self) -> Mapping[str, float]:
        """Return an immutable workflow-compatible metric mapping."""


@dataclass(frozen=True, slots=True)
class RegressionMetricsReport:
    """Regression evaluation values produced from raw predictions."""

    mae: float
    mse: float
    rmse: float
    r2: float

    def __post_init__(self) -> None:
        """Protect the non-negative error-metric invariants."""
        for name, value in (
            ("mae", self.mae),
            ("mse", self.mse),
            ("rmse", self.rmse),
        ):
            if not value >= 0:
                msg = f"{name} must be a non-negative value."
                raise ValueError(msg)

    def to_mapping(self) -> Mapping[str, float]:
        """Return an immutable mapping for workflow adaptation."""
        return MappingProxyType(
            {
                "mae": self.mae,
                "mse": self.mse,
                "rmse": self.rmse,
                "r2": self.r2,
            },
        )


@dataclass(frozen=True, slots=True)
class ClassificationMetricsReport:
    """Macro classification evaluation values from integer class labels."""

    accuracy: float
    precision_macro: float
    recall_macro: float
    f1_macro: float

    def __post_init__(self) -> None:
        """Require classification scores between zero and one."""
        for name, value in (
            ("accuracy", self.accuracy),
            ("precision_macro", self.precision_macro),
            ("recall_macro", self.recall_macro),
            ("f1_macro", self.f1_macro),
        ):
            if not 0 <= value <= 1:
                msg = f"{name} must be between zero and one."
                raise ValueError(msg)

    def to_mapping(self) -> Mapping[str, float]:
        """Return an immutable mapping for workflow adaptation."""
        return MappingProxyType(
            {
                "accuracy": self.accuracy,
                "precision_macro": self.precision_macro,
                "recall_macro": self.recall_macro,
                "f1_macro": self.f1_macro,
            },
        )
