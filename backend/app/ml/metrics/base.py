"""Minimal generic contract for evaluating raw predictions."""

from abc import ABC, abstractmethod


class BaseMetricsEngine[TargetsT, PredictionsT, ReportT](ABC):
    """Calculate one typed metrics report from targets and predictions."""

    @abstractmethod
    def evaluate(
        self,
        targets: TargetsT,
        predictions: PredictionsT,
    ) -> ReportT:
        """Return evaluation metrics without mutating supplied values."""
