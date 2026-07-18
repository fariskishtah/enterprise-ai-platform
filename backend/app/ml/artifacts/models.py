"""Immutable local artifact destination and metadata values."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from app.ml.base import TrainerKey


class ArtifactFormat(StrEnum):
    """Serialization formats supported by the local artifact boundary."""

    JOBLIB = "joblib"


@dataclass(frozen=True, slots=True)
class ArtifactDestination:
    """Typed inputs used to derive a deterministic model artifact path."""

    key: TrainerKey
    run_id: UUID


@dataclass(frozen=True, slots=True)
class ArtifactInfo:
    """Metadata describing one persisted model artifact."""

    path: Path
    size_bytes: int
    format: ArtifactFormat

    def __post_init__(self) -> None:
        """Protect the non-negative serialized-size invariant."""
        if self.size_bytes < 0:
            msg = "size_bytes must be greater than or equal to zero."
            raise ValueError(msg)
