"""Focused OpenAPI and executable AI Core example contract tests."""

import json
from pathlib import Path
from typing import Any, cast

import pytest
from app.config.settings import Settings
from app.core.application import create_app
from app.schemas.ai import (
    RandomForestClassificationTrainingRequest,
    RandomForestRegressionTrainingRequest,
    RegisteredModelPredictionRequest,
)
from pydantic import BaseModel

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_DIRECTORY = REPOSITORY_ROOT / "examples" / "ai-core"

REGRESSION_TRAINING_PATH = "/ai/training/random-forest/regression"
CLASSIFICATION_TRAINING_PATH = "/ai/training/random-forest/classification"
REGRESSION_PREDICTION_PATH = "/ai/predictions/random-forest/regression"
CLASSIFICATION_PREDICTION_PATH = "/ai/predictions/random-forest/classification"
MODEL_LOOKUP_PATH = "/ai/models/{registered_model_name}/versions/{version_or_alias}"

AI_OPERATIONS = {
    REGRESSION_TRAINING_PATH: "post",
    CLASSIFICATION_TRAINING_PATH: "post",
    REGRESSION_PREDICTION_PATH: "post",
    CLASSIFICATION_PREDICTION_PATH: "post",
    MODEL_LOOKUP_PATH: "get",
}


def _openapi(settings: Settings) -> dict[str, Any]:
    return create_app(settings).openapi()


def _operation(
    schema: dict[str, Any],
    path: str,
    method: str,
) -> dict[str, Any]:
    return cast(dict[str, Any], schema["paths"][path][method])


def _load_example(filename: str) -> dict[str, object]:
    raw: object = json.loads((EXAMPLE_DIRECTORY / filename).read_text())
    assert isinstance(raw, dict)
    return cast(dict[str, object], raw)


def _openapi_example(
    schema: dict[str, Any],
    *,
    path: str,
    name: str,
) -> dict[str, object]:
    operation = _operation(schema, path, "post")
    raw_value: object = operation["requestBody"]["content"]["application/json"][
        "examples"
    ][name]["value"]
    assert isinstance(raw_value, dict)
    return cast(dict[str, object], raw_value)


def test_ai_paths_and_success_responses_exist(settings: Settings) -> None:
    """Generated OpenAPI exposes each task separately with its actual status."""
    schema = _openapi(settings)

    for path, method in AI_OPERATIONS.items():
        assert path in schema["paths"]
        assert method in schema["paths"][path]

    assert "201" in _operation(schema, REGRESSION_TRAINING_PATH, "post")["responses"]
    assert (
        "201" in _operation(schema, CLASSIFICATION_TRAINING_PATH, "post")["responses"]
    )
    assert "200" in _operation(schema, REGRESSION_PREDICTION_PATH, "post")["responses"]
    assert (
        "200" in _operation(schema, CLASSIFICATION_PREDICTION_PATH, "post")["responses"]
    )
    assert "200" in _operation(schema, MODEL_LOOKUP_PATH, "get")["responses"]


def test_ai_operations_document_bearer_security_and_errors(
    settings: Settings,
) -> None:
    """Every AI operation documents authentication and its failure boundaries."""
    schema = _openapi(settings)

    for path, method in AI_OPERATIONS.items():
        operation = _operation(schema, path, method)
        assert operation["security"] == [{"HTTPBearer": []}]
        assert {"401", "403", "422", "502"} <= set(operation["responses"])
        assert "sanitized" in operation["responses"]["502"]["description"]

    for path in (REGRESSION_TRAINING_PATH, CLASSIFICATION_TRAINING_PATH):
        assert "409" in _operation(schema, path, "post")["responses"]

    for path, method in (
        (REGRESSION_PREDICTION_PATH, "post"),
        (CLASSIFICATION_PREDICTION_PATH, "post"),
        (MODEL_LOOKUP_PATH, "get"),
    ):
        assert {"404", "409"} <= set(_operation(schema, path, method)["responses"])


def test_ai_request_and_response_schemas_are_referenced(settings: Settings) -> None:
    """OpenAPI links operations to the real task-aware transport contracts."""
    schema = _openapi(settings)

    expected_request_refs = {
        REGRESSION_TRAINING_PATH: (
            "#/components/schemas/RandomForestRegressionTrainingRequest"
        ),
        CLASSIFICATION_TRAINING_PATH: (
            "#/components/schemas/RandomForestClassificationTrainingRequest"
        ),
        REGRESSION_PREDICTION_PATH: (
            "#/components/schemas/RegisteredModelPredictionRequest"
        ),
        CLASSIFICATION_PREDICTION_PATH: (
            "#/components/schemas/RegisteredModelPredictionRequest"
        ),
    }
    for path, expected_ref in expected_request_refs.items():
        operation = _operation(schema, path, "post")
        request_schema = operation["requestBody"]["content"]["application/json"][
            "schema"
        ]
        assert request_schema["$ref"] == expected_ref

    assert (
        expected_request_refs[REGRESSION_TRAINING_PATH]
        != expected_request_refs[CLASSIFICATION_TRAINING_PATH]
    )

    expected_response_refs = {
        (REGRESSION_TRAINING_PATH, "201"): ("#/components/schemas/AITrainingResponse"),
        (CLASSIFICATION_TRAINING_PATH, "201"): (
            "#/components/schemas/AITrainingResponse"
        ),
        (REGRESSION_PREDICTION_PATH, "200"): (
            "#/components/schemas/RegressionPredictionResponse"
        ),
        (CLASSIFICATION_PREDICTION_PATH, "200"): (
            "#/components/schemas/ClassificationPredictionResponse"
        ),
        (MODEL_LOOKUP_PATH, "200"): (
            "#/components/schemas/RegisteredModelVersionResponse"
        ),
    }
    for (path, response_status), expected_ref in expected_response_refs.items():
        method = AI_OPERATIONS[path]
        response_schema = _operation(schema, path, method)["responses"][
            response_status
        ]["content"]["application/json"]["schema"]
        assert response_schema["$ref"] == expected_ref


def test_training_response_never_documents_local_artifact_paths(
    settings: Settings,
) -> None:
    """The safe transport response excludes local artifact-manager paths."""
    schema = _openapi(settings)
    response_schema = schema["components"]["schemas"]["AITrainingResponse"]

    assert "local_artifact_path" not in response_schema["properties"]
    assert "local_artifact_path" not in json.dumps(response_schema)


def test_ai_descriptions_explain_roles_and_synchronous_boundaries(
    settings: Settings,
) -> None:
    """Descriptions remain specific enough to guide manual integration."""
    schema = _openapi(settings)

    for path in (REGRESSION_TRAINING_PATH, CLASSIFICATION_TRAINING_PATH):
        description = _operation(schema, path, "post")["description"]
        assert "synchronous" in description
        assert "admin" in description.lower()
        assert "engineer" in description.lower()
        assert "MLflow" in description

    for path in (REGRESSION_PREDICTION_PATH, CLASSIFICATION_PREDICTION_PATH):
        description = _operation(schema, path, "post")["description"]
        assert "synchronous" in description
        assert "operator" in description.lower()
        assert "TrainerKey" in description


@pytest.mark.parametrize(
    ("filename", "schema_type"),
    [
        (
            "regression-training-request.json",
            RandomForestRegressionTrainingRequest,
        ),
        (
            "classification-training-request.json",
            RandomForestClassificationTrainingRequest,
        ),
        ("regression-prediction-request.json", RegisteredModelPredictionRequest),
        (
            "classification-prediction-request.json",
            RegisteredModelPredictionRequest,
        ),
    ],
)
def test_json_examples_validate_against_transport_schemas(
    filename: str,
    schema_type: type[BaseModel],
) -> None:
    """Checked-in JSON payloads remain executable without value replacement."""
    payload = _load_example(filename)

    validated = schema_type.model_validate(payload)

    assert validated is not None


@pytest.mark.parametrize(
    ("path", "openapi_name", "filename", "schema_type"),
    [
        (
            REGRESSION_TRAINING_PATH,
            "small_regression",
            "regression-training-request.json",
            RandomForestRegressionTrainingRequest,
        ),
        (
            CLASSIFICATION_TRAINING_PATH,
            "small_classification",
            "classification-training-request.json",
            RandomForestClassificationTrainingRequest,
        ),
        (
            REGRESSION_PREDICTION_PATH,
            "exact_version",
            "regression-prediction-request.json",
            RegisteredModelPredictionRequest,
        ),
        (
            CLASSIFICATION_PREDICTION_PATH,
            "exact_version",
            "classification-prediction-request.json",
            RegisteredModelPredictionRequest,
        ),
    ],
)
def test_openapi_examples_match_files_and_validate(
    settings: Settings,
    path: str,
    openapi_name: str,
    filename: str,
    schema_type: type[BaseModel],
) -> None:
    """Swagger examples and executable files cannot drift independently."""
    payload = _openapi_example(_openapi(settings), path=path, name=openapi_name)

    assert payload == _load_example(filename)
    assert schema_type.model_validate(payload) is not None
