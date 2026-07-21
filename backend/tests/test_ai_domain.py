"""AI Core domain model tests."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import app.ml.domain as domain_contracts
import pytest
from app.ml.domain import (
    AlgorithmType,
    DatasetInfo,
    ModelContext,
    ModelStatus,
    PredictionRequest,
    PredictionResult,
    TaskType,
    TrainingRequest,
    TrainingResult,
)
from pydantic import ValidationError


def test_algorithm_type_contains_only_supported_values() -> None:
    """The AI domain exposes exactly the supported algorithms."""
    assert {algorithm.value for algorithm in AlgorithmType} == {
        "random_forest",
        "xgboost",
        "lightgbm",
        "catboost",
        "logistic_regression",
        "decision_tree",
        "extra_trees",
        "knn",
        "svm",
        "gradient_boosting",
        "linear_regression",
        "ridge",
        "lasso",
        "elastic_net",
    }


def test_task_type_contains_only_initial_supported_values() -> None:
    """Trainer tasks remain separate from algorithm identity."""
    assert {task_type.value for task_type in TaskType} == {
        "regression",
        "classification",
    }


def test_training_request_rejects_invalid_algorithm() -> None:
    """Training requests reject algorithms outside the domain enum."""
    with pytest.raises(ValidationError):
        TrainingRequest(
            experiment_id=uuid4(),
            algorithm="unsupported",
            target_column="quality_score",
            feature_columns=["temperature"],
            hyperparameters={},
        )


def test_model_status_contains_only_supported_values() -> None:
    """The AI domain exposes exactly the supported lifecycle states."""
    assert {status.value for status in ModelStatus} == {
        "created",
        "training",
        "trained",
        "failed",
        "deployed",
        "archived",
    }


def test_model_context_rejects_invalid_status() -> None:
    """Model contexts reject lifecycle states outside the domain enum."""
    with pytest.raises(ValidationError):
        ModelContext(
            model_name="quality-predictor",
            model_version="v1",
            algorithm=AlgorithmType.RANDOM_FOREST,
            status="pending",
            created_at=datetime.now(UTC),
            metrics={},
            parameters={},
        )


def test_valid_training_request() -> None:
    """A complete training request preserves its typed values."""
    experiment_id = uuid4()

    request = TrainingRequest(
        experiment_id=experiment_id,
        algorithm=AlgorithmType.XGBOOST,
        target_column="quality_score",
        feature_columns=["temperature", "pressure"],
        hyperparameters={"max_depth": 6},
        random_seed=42,
    )

    assert request.experiment_id == experiment_id
    assert request.algorithm is AlgorithmType.XGBOOST
    assert request.hyperparameters["max_depth"] == 6
    assert request.random_seed == 42


def test_training_request_rejects_empty_target_column() -> None:
    """A training request requires a non-empty target column."""
    with pytest.raises(ValidationError):
        TrainingRequest(
            experiment_id=uuid4(),
            algorithm=AlgorithmType.CATBOOST,
            target_column="",
            feature_columns=["temperature"],
            hyperparameters={},
        )


def test_training_request_rejects_empty_feature_columns() -> None:
    """A training request requires at least one feature column."""
    with pytest.raises(ValidationError):
        TrainingRequest(
            experiment_id=uuid4(),
            algorithm=AlgorithmType.LIGHTGBM,
            target_column="quality_score",
            feature_columns=[],
            hyperparameters={},
        )


def test_valid_training_result_preserves_artifact_path() -> None:
    """A successful training result preserves its artifact path type."""
    artifact_path = Path("artifacts/quality-predictor/v1")

    result = TrainingResult(
        success=True,
        model_version="v1",
        metrics={"rmse": 0.25},
        artifact_path=artifact_path,
        duration_seconds=12.5,
    )

    assert result.model_version == "v1"
    assert result.metrics == {"rmse": 0.25}
    assert result.artifact_path == artifact_path
    assert isinstance(result.artifact_path, Path)


def test_training_result_rejects_negative_duration() -> None:
    """Training workflow duration cannot be negative."""
    with pytest.raises(ValidationError):
        TrainingResult(
            success=True,
            metrics={},
            duration_seconds=-0.1,
        )


def test_valid_failure_shaped_training_result() -> None:
    """Failure details are valid without a model version or artifact."""
    result = TrainingResult(
        success=False,
        metrics={},
        duration_seconds=1.5,
        error_message="Training data was unavailable.",
    )

    assert result.success is False
    assert result.model_version is None
    assert result.artifact_path is None
    assert result.error_message == "Training data was unavailable."


def test_valid_prediction_request() -> None:
    """A prediction request preserves its model version and features."""
    request = PredictionRequest(
        model_version="v2",
        features={"temperature": 85.5, "pressure": 12.0},
    )

    assert request.model_version == "v2"
    assert request.features["temperature"] == 85.5


def test_prediction_request_rejects_empty_model_version() -> None:
    """A prediction request requires a non-empty model version."""
    with pytest.raises(ValidationError):
        PredictionRequest(model_version="", features={})


def test_valid_prediction_result() -> None:
    """A prediction result accepts raw numeric outputs and timing."""
    result = PredictionResult(predictions=[0.2, 0.8], inference_time_ms=3.4)

    assert result.predictions == [0.2, 0.8]
    assert result.inference_time_ms == 3.4


def test_prediction_result_rejects_negative_inference_time() -> None:
    """Prediction inference time cannot be negative."""
    with pytest.raises(ValidationError):
        PredictionResult(predictions=[0.5], inference_time_ms=-0.1)


def test_valid_dataset_info() -> None:
    """Complete dataset metadata is accepted."""
    dataset = DatasetInfo(
        dataset_name="press-sensor-features",
        dataset_version="2026-07-17",
        row_count=1_000,
        column_count=3,
        feature_columns=["temperature", "pressure"],
        target_column="quality_score",
    )

    assert dataset.row_count == 1_000
    assert dataset.column_count == 3


def test_dataset_info_rejects_negative_row_count() -> None:
    """Dataset row count cannot be negative."""
    with pytest.raises(ValidationError):
        DatasetInfo(
            dataset_name="press-sensor-features",
            dataset_version="v1",
            row_count=-1,
            column_count=2,
            feature_columns=["temperature"],
            target_column="quality_score",
        )


def test_dataset_info_rejects_zero_column_count() -> None:
    """Dataset column count must be positive."""
    with pytest.raises(ValidationError):
        DatasetInfo(
            dataset_name="press-sensor-features",
            dataset_version="v1",
            row_count=0,
            column_count=0,
            feature_columns=["temperature"],
            target_column="quality_score",
        )


@pytest.mark.parametrize("field_name", ["dataset_name", "dataset_version"])
def test_dataset_info_rejects_empty_name_or_version(field_name: str) -> None:
    """Dataset names and versions must be non-empty."""
    dataset_data: dict[str, object] = {
        "dataset_name": "press-sensor-features",
        "dataset_version": "v1",
        "row_count": 0,
        "column_count": 2,
        "feature_columns": ["temperature"],
        "target_column": "quality_score",
    }
    dataset_data[field_name] = ""

    with pytest.raises(ValidationError):
        DatasetInfo.model_validate(dataset_data)


def test_valid_model_context_preserves_artifact_path() -> None:
    """Model context accepts domain enums and preserves artifact paths."""
    created_at = datetime.now(UTC)
    artifact_location = Path("artifacts/quality-predictor/v1")

    context = ModelContext(
        model_name="quality-predictor",
        model_version="v1",
        algorithm=AlgorithmType.RANDOM_FOREST,
        status=ModelStatus.TRAINED,
        created_at=created_at,
        trained_at=created_at,
        metrics={"mae": 0.15},
        parameters={"n_estimators": 200},
        artifact_location=artifact_location,
    )

    assert context.algorithm is AlgorithmType.RANDOM_FOREST
    assert context.status is ModelStatus.TRAINED
    assert context.artifact_location == artifact_location
    assert isinstance(context.artifact_location, Path)


def test_domain_models_reject_unknown_fields() -> None:
    """Strict domain models reject inputs outside their declared fields."""
    with pytest.raises(ValidationError):
        PredictionRequest.model_validate(
            {
                "model_version": "v1",
                "features": {},
                "unexpected": True,
            },
        )


def test_domain_models_validate_assignment() -> None:
    """Domain constraints remain active when fields are reassigned."""
    request = PredictionRequest(model_version="v1", features={})

    with pytest.raises(ValidationError):
        request.model_version = ""


def test_all_public_domain_models_are_importable() -> None:
    """The domain package exposes its complete supported public API."""
    assert AlgorithmType.RANDOM_FOREST.value == "random_forest"
    assert TaskType.REGRESSION.value == "regression"
    assert ModelStatus.CREATED.value == "created"
    assert TrainingRequest.__name__ == "TrainingRequest"
    assert TrainingResult.__name__ == "TrainingResult"
    assert PredictionRequest.__name__ == "PredictionRequest"
    assert PredictionResult.__name__ == "PredictionResult"
    assert ModelContext.__name__ == "ModelContext"
    assert DatasetInfo.__name__ == "DatasetInfo"


def test_domain_package_public_exports_include_task_type() -> None:
    """Task identity is available from the stable domain package."""
    assert domain_contracts.__all__ == [
        "AlgorithmType",
        "TaskType",
        "ModelStatus",
        "TrainingRequest",
        "TrainingResult",
        "PredictionRequest",
        "PredictionResult",
        "ModelContext",
        "DatasetInfo",
    ]


def test_training_request_coerces_uuid_input() -> None:
    """Standard UUID inputs remain compatible with Pydantic validation."""
    experiment_id = uuid4()

    request = TrainingRequest(
        experiment_id=str(experiment_id),
        algorithm=AlgorithmType.RANDOM_FOREST,
        target_column="quality_score",
        feature_columns=["temperature"],
        hyperparameters={},
    )

    assert request.experiment_id == experiment_id
    assert isinstance(request.experiment_id, UUID)
