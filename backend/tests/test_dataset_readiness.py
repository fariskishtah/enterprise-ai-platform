"""Unicode naming and numeric training-readiness guidance coverage."""

import pytest
from app.datasets.ingestion import ingest_csv
from app.datasets.naming import normalize_dataset_name
from app.schemas.datasets import DatasetCreateRequest
from pydantic import ValidationError


def test_dataset_name_preserves_safe_unicode_punctuation() -> None:
    request = DatasetCreateRequest.model_validate(
        {
            "name": "PRESS-02 – Failure Risk",
            "kind": "tabular",
        }
    )

    assert request.name == "PRESS-02 – Failure Risk"
    assert normalize_dataset_name(request.name) == "press-02 – failure risk"


def test_invalid_dataset_name_reports_the_name_field() -> None:
    with pytest.raises(ValidationError) as raised:
        DatasetCreateRequest.model_validate(
            {
                "name": "unsafe/path",
                "kind": "tabular",
            }
        )

    assert raised.value.errors()[0]["loc"] == ("name",)
    assert "path separators" in raised.value.errors()[0]["msg"]


def test_training_readiness_describes_numeric_columns_and_class_distribution() -> None:
    result = ingest_csv(
        (
            b"temperature,machine_state,failure_next_24h\n"
            b"60.0,steady,0\n"
            b"62.0,steady,0\n"
            b"90.0,warning,1\n"
            b"92.0,warning,1\n"
        ),
        maximum_rows=100,
        maximum_columns=20,
        maximum_cell_characters=100,
        target_column="failure_next_24h",
        split_column=None,
    )

    readiness = result.schema_snapshot["training_readiness"]
    assert isinstance(readiness, dict)
    assert readiness["numeric_feature_columns"] == ["temperature"]
    assert readiness["non_numeric_feature_columns"] == ["machine_state"]
    assert readiness["class_distribution"] == {"0": 2, "1": 2}
    assert readiness["classification_candidate"] is False
    assert readiness["ready_for_numeric_training"] is False
    assert "require numeric feature columns" in str(readiness["blocking_reasons"])


def test_single_class_target_is_not_reported_ready_for_training() -> None:
    result = ingest_csv(
        b"temperature,target\n60,0\n61,0\n62,0\n63,0\n",
        maximum_rows=100,
        maximum_columns=20,
        maximum_cell_characters=100,
        target_column="target",
        split_column=None,
    )

    readiness = result.schema_snapshot["training_readiness"]
    assert isinstance(readiness, dict)
    assert readiness["ready_for_numeric_training"] is False
    assert readiness["class_distribution"] == {"0": 4}
    assert any("only one class" in warning for warning in readiness["warnings"])
    assert any(
        "No positive target examples" in warning for warning in readiness["warnings"]
    )
