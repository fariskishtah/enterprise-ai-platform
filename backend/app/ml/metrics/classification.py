"""Classification evaluation for the platform's int64 label boundary."""

from typing import TypeGuard

import numpy as np
import numpy.typing as npt
from sklearn.metrics import (  # type: ignore[import-untyped]
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
)

from app.ml.metrics.base import BaseMetricsEngine
from app.ml.metrics.exceptions import MetricsDataValidationError
from app.ml.metrics.reports import ClassificationMetricsReport

type ClassificationValues = npt.NDArray[np.int64]


class ClassificationMetricsEngine(
    BaseMetricsEngine[
        ClassificationValues,
        ClassificationValues,
        ClassificationMetricsReport,
    ],
):
    """Evaluate exact int64 one-dimensional classification vectors."""

    def evaluate(
        self,
        targets: ClassificationValues,
        predictions: ClassificationValues,
    ) -> ClassificationMetricsReport:
        """Calculate accuracy and macro precision, recall, and F1."""
        validated_targets = _validate_vector(targets, name="targets")
        validated_predictions = _validate_vector(
            predictions,
            name="predictions",
        )
        _validate_equal_lengths(validated_targets, validated_predictions)

        return ClassificationMetricsReport(
            accuracy=float(
                accuracy_score(validated_targets, validated_predictions),
            ),
            precision_macro=float(
                precision_score(
                    validated_targets,
                    validated_predictions,
                    average="macro",
                    zero_division=0,
                ),
            ),
            recall_macro=float(
                recall_score(
                    validated_targets,
                    validated_predictions,
                    average="macro",
                    zero_division=0,
                ),
            ),
            f1_macro=float(
                f1_score(
                    validated_targets,
                    validated_predictions,
                    average="macro",
                    zero_division=0,
                ),
            ),
        )


def _validate_vector(value: object, *, name: str) -> ClassificationValues:
    if not _is_int64_array(value):
        if not isinstance(value, np.ndarray):
            raise MetricsDataValidationError(f"{name} must be a NumPy ndarray.")
        raise MetricsDataValidationError(f"{name} must use the int64 dtype.")
    if value.ndim != 1:
        raise MetricsDataValidationError(f"{name} must be 1-dimensional.")
    if value.shape[0] == 0:
        raise MetricsDataValidationError(f"{name} must not be empty.")
    return value


def _validate_equal_lengths(
    targets: ClassificationValues,
    predictions: ClassificationValues,
) -> None:
    if targets.shape[0] != predictions.shape[0]:
        raise MetricsDataValidationError(
            "target and prediction lengths must be equal.",
        )


def _is_int64_array(value: object) -> TypeGuard[ClassificationValues]:
    return isinstance(value, np.ndarray) and value.dtype == np.dtype(np.int64)
