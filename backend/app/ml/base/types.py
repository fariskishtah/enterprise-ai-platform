"""Immutable data contracts used by model trainers."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TrainerInput[PreparedFeaturesT, PreparedTargetsT]:
    """Prepared in-memory data and configuration supplied to a trainer."""

    features: PreparedFeaturesT
    targets: PreparedTargetsT
    # TODO: Replace with algorithm-specific parameter types when they are designed.
    hyperparameters: Mapping[str, object]
    random_seed: int | None = None


@dataclass(frozen=True, slots=True)
class TrainerOutput[ModelT]:
    """Raw fitted model result produced directly by a trainer."""

    model: ModelT
    training_duration_seconds: float

    def __post_init__(self) -> None:
        """Protect the non-negative training-duration invariant."""
        if self.training_duration_seconds < 0:
            msg = "training_duration_seconds must be greater than or equal to zero."
            raise ValueError(msg)
