"""Composite identity for algorithm-specific task trainers."""

from dataclasses import dataclass

from app.ml.domain import AlgorithmType, TaskType


@dataclass(frozen=True, slots=True)
class TrainerKey:
    """Identify one trainer by algorithm and machine-learning task."""

    algorithm: AlgorithmType
    task_type: TaskType

    def __str__(self) -> str:
        """Return a deterministic compact trainer identifier."""
        return f"{self.algorithm.value}/{self.task_type.value}"
