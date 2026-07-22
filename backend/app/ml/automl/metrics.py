"""Allowlisted task-aware primary metrics for AutoML studies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from app.ml.domain import TaskType


class MetricDirection(StrEnum):
    """Supported optimization directions."""

    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"


@dataclass(frozen=True, slots=True)
class AutoMLMetricDefinition:
    """One finite metric that may rank compatible AutoML trials."""

    key: str
    label: str
    task_type: TaskType
    direction: MetricDirection
    requires_probabilities: bool = False


_DEFINITIONS = (
    AutoMLMetricDefinition(
        "accuracy", "Accuracy", TaskType.CLASSIFICATION, MetricDirection.MAXIMIZE
    ),
    AutoMLMetricDefinition(
        "precision_macro",
        "Precision Macro",
        TaskType.CLASSIFICATION,
        MetricDirection.MAXIMIZE,
    ),
    AutoMLMetricDefinition(
        "recall_macro",
        "Recall Macro",
        TaskType.CLASSIFICATION,
        MetricDirection.MAXIMIZE,
    ),
    AutoMLMetricDefinition(
        "f1_macro", "F1 Macro", TaskType.CLASSIFICATION, MetricDirection.MAXIMIZE
    ),
    AutoMLMetricDefinition(
        "roc_auc",
        "ROC AUC",
        TaskType.CLASSIFICATION,
        MetricDirection.MAXIMIZE,
        requires_probabilities=True,
    ),
    AutoMLMetricDefinition(
        "mae", "Mean Absolute Error", TaskType.REGRESSION, MetricDirection.MINIMIZE
    ),
    AutoMLMetricDefinition(
        "mse", "Mean Squared Error", TaskType.REGRESSION, MetricDirection.MINIMIZE
    ),
    AutoMLMetricDefinition(
        "rmse",
        "Root Mean Squared Error",
        TaskType.REGRESSION,
        MetricDirection.MINIMIZE,
    ),
    AutoMLMetricDefinition("r2", "R²", TaskType.REGRESSION, MetricDirection.MAXIMIZE),
    AutoMLMetricDefinition(
        "median_absolute_error",
        "Median Absolute Error",
        TaskType.REGRESSION,
        MetricDirection.MINIMIZE,
    ),
)

AUTOML_METRICS = MappingProxyType(
    {definition.key: definition for definition in _DEFINITIONS}
)


def require_automl_metric(
    key: str,
    *,
    task_type: TaskType,
    direction: MetricDirection,
) -> AutoMLMetricDefinition:
    """Return a compatible allowlisted metric or reject the study request."""
    definition = AUTOML_METRICS.get(key)
    if definition is None:
        raise ValueError("The primary metric is not available for AutoML.")
    if definition.task_type is not task_type:
        raise ValueError("The primary metric does not support the study task.")
    if definition.direction is not direction:
        raise ValueError("The metric direction does not match the primary metric.")
    return definition
