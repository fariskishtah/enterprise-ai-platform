"""Shared synchronous and persisted background-training payload limits."""

import pytest
from app.ml.jobs import RandomForestRegressionJobSpec
from app.ml.training_limits import (
    MAX_EVALUATION_ROWS,
    MAX_FEATURE_COLUMNS,
    MAX_MODEL_DESCRIPTION_LENGTH,
    MAX_TOTAL_FEATURE_CELLS,
    MAX_TRAINING_ROWS,
    MAX_TRAINING_RUN_NAME_LENGTH,
    MAX_TRAINING_TAG_KEY_LENGTH,
    MAX_TRAINING_TAG_VALUE_LENGTH,
    MAX_TRAINING_TAGS,
    validate_training_matrix_limits,
)
from app.schemas.ai import RandomForestRegressionTrainingRequest
from pydantic import ValidationError


def _transport_payload(
    *,
    training_rows: int = 2,
    evaluation_rows: int = 1,
    feature_columns: int = 1,
    tags: dict[str, str] | None = None,
    run_name: str | None = "bounded-run",
    model_description: str | None = "bounded description",
) -> dict[str, object]:
    return {
        "training_features": [
            [float(column) for column in range(feature_columns)]
            for _ in range(training_rows)
        ],
        "training_targets": [float(row) for row in range(training_rows)],
        "evaluation_features": [
            [float(column) for column in range(feature_columns)]
            for _ in range(evaluation_rows)
        ],
        "evaluation_targets": [float(row) for row in range(evaluation_rows)],
        "hyperparameters": {"n_estimators": 2, "n_jobs": 1},
        "experiment_name": "Payload Limits",
        "run_name": run_name,
        "registered_model_name": "ai_core_random_forest_regression",
        "tags": tags or {},
        "model_description": model_description,
    }


def _job_specification(payload: dict[str, object]) -> RandomForestRegressionJobSpec:
    return RandomForestRegressionJobSpec.model_validate(payload)


def test_row_and_column_boundaries_match_transport_and_persisted_specs() -> None:
    """Both request layers accept exact bounds and reject the first excess value."""
    maximum_rows = _transport_payload(
        training_rows=MAX_TRAINING_ROWS,
        evaluation_rows=MAX_EVALUATION_ROWS,
    )
    assert (
        len(
            RandomForestRegressionTrainingRequest.model_validate(
                maximum_rows,
            ).training_features,
        )
        == MAX_TRAINING_ROWS
    )
    assert len(_job_specification(maximum_rows).evaluation_features) == (
        MAX_EVALUATION_ROWS
    )

    too_many_training_rows = _transport_payload(
        training_rows=MAX_TRAINING_ROWS + 1,
    )
    with pytest.raises(ValidationError):
        RandomForestRegressionTrainingRequest.model_validate(
            too_many_training_rows,
        )
    with pytest.raises(ValidationError):
        _job_specification(too_many_training_rows)

    too_many_columns = _transport_payload(feature_columns=MAX_FEATURE_COLUMNS + 1)
    with pytest.raises(ValidationError, match="columns"):
        RandomForestRegressionTrainingRequest.model_validate(too_many_columns)
    with pytest.raises(ValidationError, match="columns"):
        _job_specification(too_many_columns)


def test_total_feature_cell_limit_has_an_exact_boundary() -> None:
    """The shared aggregate rule accepts its limit and rejects one excess cell."""
    feature_columns = 100
    maximum_total_rows = MAX_TOTAL_FEATURE_CELLS // feature_columns
    validate_training_matrix_limits(
        training_rows=maximum_total_rows - 1,
        evaluation_rows=1,
        feature_columns=feature_columns,
    )
    with pytest.raises(ValueError, match="total cells"):
        validate_training_matrix_limits(
            training_rows=maximum_total_rows,
            evaluation_rows=1,
            feature_columns=feature_columns,
        )


def test_metadata_limits_apply_after_normalization_in_both_contracts() -> None:
    """Tag counts/text and optional names share explicit inclusive maxima."""
    maximum_tags = {
        f"tag-{index}": "v" * MAX_TRAINING_TAG_VALUE_LENGTH
        for index in range(MAX_TRAINING_TAGS)
    }
    maximum_tags["k" * MAX_TRAINING_TAG_KEY_LENGTH] = maximum_tags.pop("tag-0")
    boundary = _transport_payload(
        tags=maximum_tags,
        run_name="r" * MAX_TRAINING_RUN_NAME_LENGTH,
        model_description="d" * MAX_MODEL_DESCRIPTION_LENGTH,
    )
    assert (
        len(
            RandomForestRegressionTrainingRequest.model_validate(boundary).tags,
        )
        == MAX_TRAINING_TAGS
    )
    assert len(_job_specification(boundary).tags) == MAX_TRAINING_TAGS

    invalid_payloads = (
        _transport_payload(
            tags={f"tag-{index}": "value" for index in range(MAX_TRAINING_TAGS + 1)},
        ),
        _transport_payload(tags={"k" * (MAX_TRAINING_TAG_KEY_LENGTH + 1): "value"}),
        _transport_payload(
            tags={"key": "v" * (MAX_TRAINING_TAG_VALUE_LENGTH + 1)},
        ),
        _transport_payload(run_name="r" * (MAX_TRAINING_RUN_NAME_LENGTH + 1)),
        _transport_payload(
            model_description="d" * (MAX_MODEL_DESCRIPTION_LENGTH + 1),
        ),
    )
    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            RandomForestRegressionTrainingRequest.model_validate(payload)
        with pytest.raises(ValidationError):
            _job_specification(payload)
