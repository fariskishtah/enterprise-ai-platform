"""Pure regression and classification promotion-policy tests."""

import math

import pytest
from app.ml.domain import TaskType
from app.ml.jobs import random_forest_key
from app.ml.promotion import (
    ClassificationPromotionPolicy,
    PromotionCandidate,
    RegressionPromotionPolicy,
)


def _candidate(
    task_type: TaskType,
    version: str,
    metrics: dict[str, float],
) -> PromotionCandidate:
    return PromotionCandidate(
        registered_model_name=f"ai_core_random_forest_{task_type.value}",
        version=version,
        key=random_forest_key(task_type),
        metrics=metrics,
    )


def test_regression_policy_accepts_improvement_and_no_incumbent() -> None:
    """Lower RMSE and the R² safeguard drive regression recommendations."""
    policy = RegressionPromotionPolicy(
        minimum_r2=0.5,
        minimum_relative_rmse_improvement=0.1,
    )
    candidate = _candidate(
        TaskType.REGRESSION,
        "2",
        {"rmse": 0.7, "r2": 0.8},
    )
    incumbent = _candidate(
        TaskType.REGRESSION,
        "1",
        {"rmse": 1.0, "r2": 0.7},
    )

    improved = policy.evaluate(candidate, incumbent)
    first = policy.evaluate(candidate, None)

    assert improved.accepted is True
    assert improved.improvement == pytest.approx(0.3)
    assert first.accepted is True
    assert first.improvement is None


def test_regression_policy_rejects_threshold_r2_missing_and_nan() -> None:
    """Insufficient, missing, and non-finite regression metrics are rejected."""
    policy = RegressionPromotionPolicy(
        minimum_r2=0.5,
        minimum_relative_rmse_improvement=0.2,
    )
    incumbent = _candidate(
        TaskType.REGRESSION,
        "1",
        {"rmse": 1.0, "r2": 0.8},
    )

    assert (
        policy.evaluate(
            _candidate(
                TaskType.REGRESSION,
                "2",
                {"rmse": 0.9, "r2": 0.8},
            ),
            incumbent,
        ).accepted
        is False
    )
    assert (
        policy.evaluate(
            _candidate(
                TaskType.REGRESSION,
                "3",
                {"rmse": 0.5, "r2": 0.4},
            ),
            incumbent,
        ).accepted
        is False
    )
    assert (
        policy.evaluate(
            _candidate(TaskType.REGRESSION, "4", {"r2": 0.8}),
            incumbent,
        ).accepted
        is False
    )
    assert (
        policy.evaluate(
            _candidate(
                TaskType.REGRESSION,
                "5",
                {"rmse": math.nan, "r2": 0.8},
            ),
            incumbent,
        ).accepted
        is False
    )


def test_classification_policy_accepts_f1_improvement_and_first_model() -> None:
    """Higher macro-F1 and minimum accuracy drive classification policy."""
    policy = ClassificationPromotionPolicy(
        minimum_accuracy=0.7,
        minimum_f1_improvement=0.05,
    )
    candidate = _candidate(
        TaskType.CLASSIFICATION,
        "2",
        {"accuracy": 0.9, "f1_macro": 0.85},
    )
    incumbent = _candidate(
        TaskType.CLASSIFICATION,
        "1",
        {"accuracy": 0.8, "f1_macro": 0.75},
    )

    assert policy.evaluate(candidate, incumbent).accepted is True
    assert policy.evaluate(candidate, None).accepted is True


def test_classification_policy_rejects_accuracy_insufficient_and_nan() -> None:
    """Accuracy, improvement, missing, and finite-value boundaries are enforced."""
    policy = ClassificationPromotionPolicy(
        minimum_accuracy=0.8,
        minimum_f1_improvement=0.05,
    )
    incumbent = _candidate(
        TaskType.CLASSIFICATION,
        "1",
        {"accuracy": 0.9, "f1_macro": 0.8},
    )

    assert (
        policy.evaluate(
            _candidate(
                TaskType.CLASSIFICATION,
                "2",
                {"accuracy": 0.7, "f1_macro": 0.9},
            ),
            incumbent,
        ).accepted
        is False
    )
    assert (
        policy.evaluate(
            _candidate(
                TaskType.CLASSIFICATION,
                "3",
                {"accuracy": 0.9, "f1_macro": 0.82},
            ),
            incumbent,
        ).accepted
        is False
    )
    assert (
        policy.evaluate(
            _candidate(
                TaskType.CLASSIFICATION,
                "4",
                {"accuracy": 0.9, "f1_macro": math.nan},
            ),
            incumbent,
        ).accepted
        is False
    )
