"""Typed Random Forest parameter-model tests."""

from typing import assert_type

import pytest
from app.ml.trainers.random_forest.parameters import (
    RandomForestClassificationKwargs,
    RandomForestClassificationParameters,
    RandomForestRegressionKwargs,
    RandomForestRegressionParameters,
)
from pydantic import ValidationError


def test_regression_parameter_defaults() -> None:
    """Regression defaults match the intentional supported subset."""
    parameters = RandomForestRegressionParameters()

    assert parameters.n_estimators == 100
    assert parameters.criterion == "squared_error"
    assert parameters.max_depth is None
    assert parameters.min_samples_split == 2
    assert parameters.min_samples_leaf == 1
    assert parameters.max_features == 1.0
    assert parameters.bootstrap is True
    assert parameters.n_jobs is None
    assert parameters.random_state is None


def test_classification_parameter_defaults() -> None:
    """Classification uses its own criterion and feature defaults."""
    parameters = RandomForestClassificationParameters()

    assert parameters.n_estimators == 100
    assert parameters.criterion == "gini"
    assert parameters.max_features == "sqrt"
    assert parameters.random_state is None


def test_regression_parameters_accept_explicit_supported_values() -> None:
    """Regression accepts each intentionally exposed parameter."""
    parameters = RandomForestRegressionParameters(
        n_estimators=20,
        criterion="absolute_error",
        max_depth=4,
        min_samples_split=3,
        min_samples_leaf=2,
        max_features=0.75,
        bootstrap=False,
        n_jobs=-1,
        random_state=17,
    )

    assert parameters.n_estimators == 20
    assert parameters.criterion == "absolute_error"
    assert parameters.max_depth == 4
    assert parameters.min_samples_split == 3
    assert parameters.min_samples_leaf == 2
    assert parameters.max_features == 0.75
    assert parameters.bootstrap is False
    assert parameters.n_jobs == -1
    assert parameters.random_state == 17


def test_regression_parameters_accept_friedman_mse_criterion() -> None:
    """The task model includes each supported regression criterion."""
    parameters = RandomForestRegressionParameters(criterion="friedman_mse")

    assert parameters.criterion == "friedman_mse"


def test_classification_parameters_accept_explicit_supported_values() -> None:
    """Classification accepts only its task-specific criterion choices."""
    parameters = RandomForestClassificationParameters(
        n_estimators=15,
        criterion="log_loss",
        max_depth=3,
        min_samples_split=4,
        min_samples_leaf=2,
        max_features="log2",
        bootstrap=False,
        n_jobs=2,
        random_state=19,
    )

    assert parameters.criterion == "log_loss"
    assert parameters.max_features == "log2"


@pytest.mark.parametrize(
    ("model", "criterion"),
    [
        (RandomForestRegressionParameters, "gini"),
        (RandomForestClassificationParameters, "squared_error"),
        (RandomForestRegressionParameters, "unsupported"),
        (RandomForestClassificationParameters, "unsupported"),
    ],
)
def test_parameters_reject_invalid_or_cross_task_criterion(
    model: type[
        RandomForestRegressionParameters | RandomForestClassificationParameters
    ],
    criterion: str,
) -> None:
    """Criterion values cannot cross regression/classification boundaries."""
    with pytest.raises(ValidationError):
        model.model_validate({"criterion": criterion})


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("n_estimators", 0),
        ("n_estimators", -1),
        ("max_depth", 0),
        ("max_depth", -1),
        ("min_samples_split", 1),
        ("min_samples_leaf", 0),
        ("n_jobs", 0),
    ],
)
def test_parameters_reject_invalid_numeric_boundaries(
    field_name: str,
    value: int,
) -> None:
    """Numeric constraints reject values outside sklearn-safe boundaries."""
    with pytest.raises(ValidationError):
        RandomForestRegressionParameters.model_validate({field_name: value})


def test_parameters_keep_booleans_strict() -> None:
    """Integer truthiness is not accepted for boolean parameters."""
    with pytest.raises(ValidationError):
        RandomForestClassificationParameters.model_validate({"bootstrap": 1})


def test_parameters_reject_unknown_fields() -> None:
    """Unsupported sklearn parameters cannot leak through the boundary."""
    with pytest.raises(ValidationError):
        RandomForestRegressionParameters.model_validate({"warm_start": True})


def test_regression_parameters_export_typed_sklearn_kwargs() -> None:
    """Regression exports only validated estimator keyword arguments."""
    parameters = RandomForestRegressionParameters(
        n_estimators=12,
        criterion="poisson",
        max_depth=5,
        min_samples_split=3,
        min_samples_leaf=2,
        max_features="sqrt",
        bootstrap=False,
        n_jobs=-1,
        random_state=13,
    )

    kwargs = parameters.to_sklearn_kwargs(random_seed=None)

    assert_type(kwargs, RandomForestRegressionKwargs)
    assert kwargs == {
        "n_estimators": 12,
        "criterion": "poisson",
        "max_depth": 5,
        "min_samples_split": 3,
        "min_samples_leaf": 2,
        "max_features": "sqrt",
        "bootstrap": False,
        "n_jobs": -1,
        "random_state": 13,
    }


def test_classification_parameters_export_typed_sklearn_kwargs() -> None:
    """Classification exports only validated estimator keyword arguments."""
    parameters = RandomForestClassificationParameters(
        criterion="entropy",
        random_state=11,
    )

    kwargs = parameters.to_sklearn_kwargs(random_seed=None)

    assert_type(kwargs, RandomForestClassificationKwargs)
    assert kwargs["criterion"] == "entropy"
    assert kwargs["random_state"] == 11


def test_workflow_seed_takes_precedence_without_mutating_parameters() -> None:
    """Workflow seed overrides model seed only in exported estimator kwargs."""
    source: dict[str, object] = {"random_state": 11, "n_estimators": 8}
    parameters = RandomForestRegressionParameters.model_validate(source)

    workflow_kwargs = parameters.to_sklearn_kwargs(random_seed=23)
    parameter_kwargs = parameters.to_sklearn_kwargs(random_seed=None)

    assert workflow_kwargs["random_state"] == 23
    assert parameter_kwargs["random_state"] == 11
    assert parameters.random_state == 11
    assert source == {"random_state": 11, "n_estimators": 8}
