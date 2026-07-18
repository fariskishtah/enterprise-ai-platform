"""Minimal port for logging completed AI Core executions."""

from abc import ABC, abstractmethod

from app.ml.tracking.models import ExperimentRunInfo, ExperimentRunRequest


class BaseExperimentTracker(ABC):
    """Log successful executions without owning training or evaluation."""

    @abstractmethod
    def log_successful_run(
        self,
        request: ExperimentRunRequest,
    ) -> ExperimentRunInfo:
        """Log one completed execution and return platform metadata."""
