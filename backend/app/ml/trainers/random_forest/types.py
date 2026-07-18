"""Intentionally restricted NumPy contracts for Random Forest trainers.

The initial platform boundary accepts float64 two-dimensional features, float64
one-dimensional regression targets and predictions, and int64 one-dimensional
classification labels and predictions. These contracts are narrower than the
complete array surface accepted by scikit-learn and never cast implicitly.
"""

from typing import TypeGuard

import numpy as np
import numpy.typing as npt

type FeatureArray = npt.NDArray[np.float64]
type RegressionTargetArray = npt.NDArray[np.float64]
type RegressionPredictionArray = npt.NDArray[np.float64]
type ClassificationTargetArray = npt.NDArray[np.int64]
type ClassificationPredictionArray = npt.NDArray[np.int64]


class TrainerDataValidationError(ValueError):
    """Raised when prepared trainer data violates an obvious array invariant."""


def validate_regression_training_data(
    features: object,
    targets: object,
) -> tuple[FeatureArray, RegressionTargetArray]:
    """Validate prepared regression arrays without reshaping or casting."""
    validated_features = _validate_features(features, require_rows=True)
    if not _is_float64_array(targets):
        if not isinstance(targets, np.ndarray):
            raise TrainerDataValidationError("targets must be a NumPy ndarray.")
        raise TrainerDataValidationError(
            "regression targets must use the float64 dtype.",
        )
    _validate_targets(validated_features, targets)
    return validated_features, targets


def validate_classification_training_data(
    features: object,
    targets: object,
) -> tuple[FeatureArray, ClassificationTargetArray]:
    """Validate prepared single-output integer classification arrays."""
    validated_features = _validate_features(features, require_rows=True)
    if not _is_int64_array(targets):
        if not isinstance(targets, np.ndarray):
            raise TrainerDataValidationError("targets must be a NumPy ndarray.")
        raise TrainerDataValidationError(
            "classification targets must use the int64 dtype.",
        )
    _validate_targets(validated_features, targets)
    return validated_features, targets


def validate_prediction_features(features: object) -> FeatureArray:
    """Validate prepared prediction features without requiring non-empty rows."""
    return _validate_features(features, require_rows=False)


def validate_regression_predictions(
    predictions: object,
) -> RegressionPredictionArray:
    """Narrow sklearn regression output to the public numeric array type."""
    if not _is_float64_array(predictions) or predictions.ndim != 1:
        raise TrainerDataValidationError(
            "regression predictions must be a 1-dimensional float64 array.",
        )
    return predictions


def validate_classification_predictions(
    predictions: object,
) -> ClassificationPredictionArray:
    """Narrow sklearn class output to the supported integer-label array type."""
    if not _is_int64_array(predictions) or predictions.ndim != 1:
        raise TrainerDataValidationError(
            "classification predictions must be a 1-dimensional int64 array.",
        )
    return predictions


def _validate_features(features: object, *, require_rows: bool) -> FeatureArray:
    if not _is_float64_array(features):
        if not isinstance(features, np.ndarray):
            raise TrainerDataValidationError("features must be a NumPy ndarray.")
        raise TrainerDataValidationError(
            "features must use the float64 dtype.",
        )
    if features.ndim != 2:
        raise TrainerDataValidationError("features must be 2-dimensional.")
    if require_rows and features.shape[0] == 0:
        raise TrainerDataValidationError(
            "training data must contain at least one row.",
        )
    if features.shape[1] == 0:
        raise TrainerDataValidationError(
            "features must contain at least one column.",
        )
    return features


def _validate_targets(
    features: FeatureArray,
    targets: RegressionTargetArray | ClassificationTargetArray,
) -> None:
    if targets.ndim != 1:
        raise TrainerDataValidationError("targets must be 1-dimensional.")
    if features.shape[0] != targets.shape[0]:
        raise TrainerDataValidationError(
            "feature row count must equal target value count.",
        )


def _is_float64_array(value: object) -> TypeGuard[FeatureArray]:
    return isinstance(value, np.ndarray) and value.dtype == np.dtype(np.float64)


def _is_int64_array(value: object) -> TypeGuard[ClassificationTargetArray]:
    return isinstance(value, np.ndarray) and value.dtype == np.dtype(np.int64)
