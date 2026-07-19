"""Typed regression and classification metrics tests."""

from dataclasses import FrozenInstanceError
from math import sqrt
from typing import Protocol, assert_type, cast

import numpy as np
import numpy.typing as npt
import pytest
from app.ml.metrics import (
    ClassificationMetricsEngine,
    ClassificationMetricsReport,
    MetricsDataValidationError,
    RegressionMetricsEngine,
    RegressionMetricsReport,
)

type FloatVector = npt.NDArray[np.float64]
type IntVector = npt.NDArray[np.int64]


class WritableMetricsMapping(Protocol):
    """Test-only writable view used to verify runtime immutability."""

    def __setitem__(self, key: str, value: float) -> None:
        """Assign one metric value."""


def _assign_attribute(instance: object, name: str, value: object) -> None:
    setattr(instance, name, value)


def _assign_metric(
    mapping: WritableMetricsMapping,
    key: str,
    value: float,
) -> None:
    mapping[key] = value


def test_regression_metrics_are_exact_and_typed() -> None:
    """Regression evaluation calculates MAE, MSE, RMSE, and R-squared."""
    targets: FloatVector = np.array([1.0, 2.0, 3.0], dtype=np.float64)
    predictions: FloatVector = np.array([1.0, 2.0, 4.0], dtype=np.float64)

    report = RegressionMetricsEngine().evaluate(targets, predictions)

    assert_type(report, RegressionMetricsReport)
    assert report.mae == pytest.approx(1.0 / 3.0)
    assert report.mse == pytest.approx(1.0 / 3.0)
    assert report.rmse == pytest.approx(sqrt(1.0 / 3.0))
    assert report.r2 == pytest.approx(0.5)


def test_regression_report_is_immutable_with_read_only_mapping() -> None:
    """Regression report fields and mapping exports cannot be mutated."""
    report = RegressionMetricsReport(mae=1.0, mse=2.0, rmse=sqrt(2.0), r2=-0.5)

    with pytest.raises(FrozenInstanceError):
        _assign_attribute(report, "mae", 2.0)
    with pytest.raises(TypeError):
        _assign_metric(
            cast(WritableMetricsMapping, report.to_mapping()),
            "mae",
            2.0,
        )

    assert report.to_mapping() == {
        "mae": 1.0,
        "mse": 2.0,
        "rmse": sqrt(2.0),
        "r2": -0.5,
    }


@pytest.mark.parametrize("field_name", ["mae", "mse", "rmse"])
def test_regression_report_rejects_negative_errors(field_name: str) -> None:
    """Only R-squared may be negative in a regression report."""
    values = {"mae": 1.0, "mse": 1.0, "rmse": 1.0, "r2": -2.0}
    values[field_name] = -0.1

    with pytest.raises(ValueError, match="non-negative"):
        RegressionMetricsReport(**values)


@pytest.mark.parametrize(
    ("targets", "predictions", "message"),
    [
        (
            cast(FloatVector, np.array([1, 2], dtype=np.int64)),
            np.array([1.0, 2.0], dtype=np.float64),
            "targets must use the float64 dtype",
        ),
        (
            np.array([[1.0, 2.0]], dtype=np.float64),
            np.array([1.0, 2.0], dtype=np.float64),
            "targets must be 1-dimensional",
        ),
        (
            np.empty((0,), dtype=np.float64),
            np.empty((0,), dtype=np.float64),
            "targets must not be empty",
        ),
        (
            np.array([1.0, 2.0], dtype=np.float64),
            np.array([1.0], dtype=np.float64),
            "target and prediction lengths must be equal",
        ),
    ],
)
def test_regression_metrics_reject_invalid_vectors(
    targets: FloatVector,
    predictions: FloatVector,
    message: str,
) -> None:
    """Regression metrics enforce the exact prepared vector contract."""
    with pytest.raises(MetricsDataValidationError, match=message):
        RegressionMetricsEngine().evaluate(targets, predictions)


def test_classification_metrics_use_macro_averaging() -> None:
    """Classification reports expose accuracy and macro aggregate scores."""
    targets: IntVector = np.array([0, 0, 1, 1], dtype=np.int64)
    predictions: IntVector = np.array([0, 1, 1, 1], dtype=np.int64)

    report = ClassificationMetricsEngine().evaluate(targets, predictions)

    assert_type(report, ClassificationMetricsReport)
    assert report.accuracy == pytest.approx(0.75)
    assert report.precision_macro == pytest.approx(5.0 / 6.0)
    assert report.recall_macro == pytest.approx(0.75)
    assert report.f1_macro == pytest.approx(11.0 / 15.0)


def test_classification_metrics_use_zero_for_undefined_scores() -> None:
    """Missing predicted classes use zero rather than warnings or exceptions."""
    targets: IntVector = np.array([0, 1], dtype=np.int64)
    predictions: IntVector = np.array([0, 0], dtype=np.int64)

    report = ClassificationMetricsEngine().evaluate(targets, predictions)

    assert report.accuracy == pytest.approx(0.5)
    assert report.precision_macro == pytest.approx(0.25)
    assert report.recall_macro == pytest.approx(0.5)
    assert report.f1_macro == pytest.approx(1.0 / 3.0)


def test_classification_report_is_immutable_with_read_only_mapping() -> None:
    """Classification report fields and exports cannot be mutated."""
    report = ClassificationMetricsReport(
        accuracy=0.75,
        precision_macro=0.8,
        recall_macro=0.7,
        f1_macro=0.74,
    )

    with pytest.raises(FrozenInstanceError):
        _assign_attribute(report, "accuracy", 1.0)
    with pytest.raises(TypeError):
        _assign_metric(
            cast(WritableMetricsMapping, report.to_mapping()),
            "accuracy",
            1.0,
        )

    assert report.to_mapping() == {
        "accuracy": 0.75,
        "precision_macro": 0.8,
        "recall_macro": 0.7,
        "f1_macro": 0.74,
    }


@pytest.mark.parametrize(
    "value",
    [-0.01, 1.01],
)
def test_classification_report_rejects_out_of_range_values(value: float) -> None:
    """Classification metrics must remain within the unit interval."""
    with pytest.raises(ValueError, match="between zero and one"):
        ClassificationMetricsReport(
            accuracy=value,
            precision_macro=0.5,
            recall_macro=0.5,
            f1_macro=0.5,
        )


@pytest.mark.parametrize(
    ("targets", "predictions", "message"),
    [
        (
            cast(IntVector, np.array([0.0, 1.0], dtype=np.float64)),
            np.array([0, 1], dtype=np.int64),
            "targets must use the int64 dtype",
        ),
        (
            np.array([[0, 1]], dtype=np.int64),
            np.array([0, 1], dtype=np.int64),
            "targets must be 1-dimensional",
        ),
        (
            np.empty((0,), dtype=np.int64),
            np.empty((0,), dtype=np.int64),
            "targets must not be empty",
        ),
        (
            np.array([0, 1], dtype=np.int64),
            np.array([0], dtype=np.int64),
            "target and prediction lengths must be equal",
        ),
    ],
)
def test_classification_metrics_reject_invalid_vectors(
    targets: IntVector,
    predictions: IntVector,
    message: str,
) -> None:
    """Classification metrics enforce the exact integer vector contract."""
    with pytest.raises(MetricsDataValidationError, match=message):
        ClassificationMetricsEngine().evaluate(targets, predictions)
