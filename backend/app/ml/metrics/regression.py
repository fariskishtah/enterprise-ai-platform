"""Regression evaluation for the platform's float64 vector boundary."""

from math import sqrt
from typing import TypeGuard

import numpy as np
import numpy.typing as npt
from sklearn.metrics import (  # type: ignore[import-untyped]
    mean_absolute_error,
    mean_squared_error,
    r2_score,
)

from app.ml.metrics.base import BaseMetricsEngine
from app.ml.metrics.exceptions import MetricsDataValidationError
from app.ml.metrics.reports import RegressionMetricsReport

type RegressionValues = npt.NDArray[np.float64]


class RegressionMetricsEngine(
    BaseMetricsEngine[
        RegressionValues,
        RegressionValues,
        RegressionMetricsReport,
    ],
):
    """Evaluate exact float64 one-dimensional regression vectors."""

    def evaluate(
        self,
        targets: RegressionValues,
        predictions: RegressionValues,
    ) -> RegressionMetricsReport:
        """Calculate MAE, MSE, explicit RMSE, and R-squared."""
        validated_targets = _validate_vector(targets, name="targets")
        validated_predictions = _validate_vector(
            predictions,
            name="predictions",
        )
        _validate_equal_lengths(validated_targets, validated_predictions)

        mae = float(mean_absolute_error(validated_targets, validated_predictions))
        mse = float(mean_squared_error(validated_targets, validated_predictions))
        r2 = float(r2_score(validated_targets, validated_predictions))
        return RegressionMetricsReport(
            mae=mae,
            mse=mse,
            rmse=sqrt(mse),
            r2=r2,
        )


def _validate_vector(value: object, *, name: str) -> RegressionValues:
    if not _is_float64_array(value):
        if not isinstance(value, np.ndarray):
            raise MetricsDataValidationError(f"{name} must be a NumPy ndarray.")
        raise MetricsDataValidationError(f"{name} must use the float64 dtype.")
    if value.ndim != 1:
        raise MetricsDataValidationError(f"{name} must be 1-dimensional.")
    if value.shape[0] == 0:
        raise MetricsDataValidationError(f"{name} must not be empty.")
    return value


def _validate_equal_lengths(
    targets: RegressionValues,
    predictions: RegressionValues,
) -> None:
    if targets.shape[0] != predictions.shape[0]:
        raise MetricsDataValidationError(
            "target and prediction lengths must be equal.",
        )


def _is_float64_array(value: object) -> TypeGuard[RegressionValues]:
    return isinstance(value, np.ndarray) and value.dtype == np.dtype(np.float64)
