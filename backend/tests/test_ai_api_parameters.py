"""Parity tests for duplicated HTTP and internal Random Forest contracts."""

from collections.abc import Mapping

import pytest
from app.ml.trainers.random_forest import (
    RandomForestClassificationParameters,
    RandomForestRegressionParameters,
)
from app.schemas.ai import (
    RandomForestClassificationHyperparameters,
    RandomForestRegressionHyperparameters,
)
from pydantic import BaseModel, ValidationError

type ParameterModel = type[BaseModel]

REGRESSION_MODELS = (
    RandomForestRegressionHyperparameters,
    RandomForestRegressionParameters,
)
CLASSIFICATION_MODELS = (
    RandomForestClassificationHyperparameters,
    RandomForestClassificationParameters,
)
ALL_MODEL_PAIRS = (REGRESSION_MODELS, CLASSIFICATION_MODELS)


def _assert_contract_parity(
    models: tuple[ParameterModel, ParameterModel],
    values: Mapping[str, object],
    *,
    valid: bool,
) -> None:
    api_model, internal_model = models
    if valid:
        assert api_model.model_validate(values).model_dump() == (
            internal_model.model_validate(values).model_dump()
        )
        return
    with pytest.raises(ValidationError):
        api_model.model_validate(values)
    with pytest.raises(ValidationError):
        internal_model.model_validate(values)


@pytest.mark.parametrize("models", ALL_MODEL_PAIRS)
def test_api_and_internal_parameter_defaults_match(
    models: tuple[ParameterModel, ParameterModel],
) -> None:
    """Every public transport default equals its internal trainer default."""
    _assert_contract_parity(models, {}, valid=True)


@pytest.mark.parametrize(
    "criterion",
    ["squared_error", "absolute_error", "friedman_mse", "poisson"],
)
def test_regression_criteria_match(criterion: str) -> None:
    """Regression criteria accepted over HTTP match the trainer contract."""
    _assert_contract_parity(REGRESSION_MODELS, {"criterion": criterion}, valid=True)


@pytest.mark.parametrize("criterion", ["gini", "entropy", "log_loss"])
def test_classification_criteria_match(criterion: str) -> None:
    """Classification criteria accepted over HTTP match the trainer contract."""
    _assert_contract_parity(
        CLASSIFICATION_MODELS,
        {"criterion": criterion},
        valid=True,
    )


@pytest.mark.parametrize("models", ALL_MODEL_PAIRS)
def test_unsupported_criteria_are_rejected_by_both_contracts(
    models: tuple[ParameterModel, ParameterModel],
) -> None:
    """Neither boundary accepts criteria outside its task-specific literals."""
    _assert_contract_parity(models, {"criterion": "unsupported"}, valid=False)


@pytest.mark.parametrize("models", ALL_MODEL_PAIRS)
@pytest.mark.parametrize("value", ["sqrt", "log2", 0.25, 1.0])
def test_max_features_supported_values_match(
    models: tuple[ParameterModel, ParameterModel],
    value: str | float,
) -> None:
    """Both boundaries accept only supported strings or fractional floats."""
    _assert_contract_parity(models, {"max_features": value}, valid=True)


@pytest.mark.parametrize("models", ALL_MODEL_PAIRS)
@pytest.mark.parametrize("value", ["auto", 0.0, 1.1, 1, True, None])
def test_max_features_invalid_values_match(
    models: tuple[ParameterModel, ParameterModel],
    value: object,
) -> None:
    """Out-of-range, integer, boolean, null, and unknown values are rejected."""
    _assert_contract_parity(models, {"max_features": value}, valid=False)


@pytest.mark.parametrize("models", ALL_MODEL_PAIRS)
@pytest.mark.parametrize(
    ("field", "valid_value", "invalid_value"),
    [
        ("n_estimators", 1, 0),
        ("max_depth", 1, 0),
        ("min_samples_split", 2, 1),
        ("min_samples_leaf", 1, 0),
        ("n_jobs", -1, 0),
    ],
)
def test_integer_constraints_match(
    models: tuple[ParameterModel, ParameterModel],
    field: str,
    valid_value: int,
    invalid_value: int,
) -> None:
    """Integer range and n_jobs zero constraints cannot drift silently."""
    _assert_contract_parity(models, {field: valid_value}, valid=True)
    _assert_contract_parity(models, {field: invalid_value}, valid=False)


@pytest.mark.parametrize("models", ALL_MODEL_PAIRS)
@pytest.mark.parametrize(
    "field",
    [
        "n_estimators",
        "max_depth",
        "min_samples_split",
        "min_samples_leaf",
        "n_jobs",
    ],
)
def test_integer_fields_reject_boolean_values(
    models: tuple[ParameterModel, ParameterModel],
    field: str,
) -> None:
    """Strict integer fields reject Python booleans at both boundaries."""
    _assert_contract_parity(models, {field: True}, valid=False)


@pytest.mark.parametrize("models", ALL_MODEL_PAIRS)
@pytest.mark.parametrize("value", [True, False])
def test_bootstrap_accepts_only_strict_booleans(
    models: tuple[ParameterModel, ParameterModel],
    value: bool,
) -> None:
    """Real booleans are accepted consistently."""
    _assert_contract_parity(models, {"bootstrap": value}, valid=True)


@pytest.mark.parametrize("models", ALL_MODEL_PAIRS)
@pytest.mark.parametrize("value", [1, 0, "true", "false"])
def test_bootstrap_rejects_boolean_coercion(
    models: tuple[ParameterModel, ParameterModel],
    value: object,
) -> None:
    """Numeric and string values cannot be coerced into booleans."""
    _assert_contract_parity(models, {"bootstrap": value}, valid=False)


@pytest.mark.parametrize("models", ALL_MODEL_PAIRS)
def test_unknown_fields_are_rejected_by_both_contracts(
    models: tuple[ParameterModel, ParameterModel],
) -> None:
    """Both independently defined models retain extra='forbid'."""
    _assert_contract_parity(models, {"unexpected": "value"}, valid=False)
