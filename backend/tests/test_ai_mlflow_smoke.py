"""Real isolated MLflow smoke tests for tracked training and prediction."""

from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np
from app.ml.artifacts import LocalArtifactManager
from app.ml.base import TrainerInput
from app.ml.composition import (
    create_random_forest_classification_plan,
    create_random_forest_classification_prediction_plan,
    create_random_forest_regression_plan,
    create_random_forest_regression_prediction_plan,
)
from app.ml.engine import TrainingEngine
from app.ml.factory import TrainerFactory, TrainerRegistry
from app.ml.registry import (
    MLflowModelRegistry,
    RegisteredModelVersion,
    build_registered_model_name,
)
from app.ml.services import (
    MLflowRegisteredModelLoader,
    PredictionService,
    RegisteredPredictionRequest,
    TrackedTrainingRequest,
    TrackedTrainingService,
)
from app.ml.tracking import ExperimentRunInfo, MLflowExperimentTracker
from app.ml.trainers.random_forest import (
    RANDOM_FOREST_CLASSIFIER_REGISTRATION,
    RANDOM_FOREST_REGRESSOR_REGISTRATION,
)
from app.ml.trainers.random_forest.types import (
    ClassificationTargetArray,
    FeatureArray,
    RegressionTargetArray,
)
from mlflow.artifacts import download_artifacts
from mlflow.tracking import MlflowClient
from sklearn.ensemble import (  # type: ignore[import-untyped]
    RandomForestClassifier,
    RandomForestRegressor,
)


def _components(
    tmp_path: Path,
) -> tuple[
    TrackedTrainingService,
    MLflowModelRegistry,
    MLflowRegisteredModelLoader,
    str,
]:
    tracking_uri = f"file:{tmp_path / 'mlruns'}"
    trainer_registry = TrainerRegistry()
    trainer_registry.register(RANDOM_FOREST_REGRESSOR_REGISTRATION)
    trainer_registry.register(RANDOM_FOREST_CLASSIFIER_REGISTRATION)
    model_registry = MLflowModelRegistry(tracking_uri=tracking_uri)
    service = TrackedTrainingService(
        training_engine=TrainingEngine(
            trainer_factory=TrainerFactory(trainer_registry),
            artifact_manager=LocalArtifactManager(tmp_path / "local-artifacts"),
        ),
        experiment_tracker=MLflowExperimentTracker(tracking_uri=tracking_uri),
        model_registry=model_registry,
    )
    return (
        service,
        model_registry,
        MLflowRegisteredModelLoader(tracking_uri=tracking_uri),
        tracking_uri,
    )


def _assert_mlflow_artifact_contract(
    *,
    tmp_path: Path,
    tracking_uri: str,
    tracking: ExperimentRunInfo,
    model_version: RegisteredModelVersion,
    model_registry: MLflowModelRegistry,
) -> Path:
    client = MlflowClient(tracking_uri=tracking_uri)
    run = client.get_run(tracking.run_id)
    logged_artifacts = client.list_artifacts(tracking.run_id, path="model")

    assert run.info.status == "FINISHED"
    assert model_version.run_id == tracking.run_id
    assert model_version.source_uri == tracking.artifact_uri
    assert model_version.source_uri.endswith("/model/model.joblib")
    assert [artifact.path for artifact in logged_artifacts] == ["model/model.joblib"]

    source_path = Path(unquote(urlparse(model_version.source_uri).path)).resolve()
    downloaded_path = Path(
        download_artifacts(
            artifact_uri=model_version.source_uri,
            tracking_uri=tracking_uri,
        ),
    ).resolve()
    assert source_path.is_file()
    assert downloaded_path.is_file()
    assert downloaded_path.name == "model.joblib"
    assert downloaded_path == source_path
    assert downloaded_path.is_relative_to(tmp_path.resolve())

    client.set_registered_model_alias(
        model_version.registered_model_name,
        "smoke",
        model_version.version,
    )
    resolved_alias = model_registry.resolve(
        model_version.registered_model_name,
        "smoke",
    )
    assert resolved_alias.version == model_version.version
    assert resolved_alias.aliases == ("smoke",)
    return downloaded_path


def test_real_mlflow_regression_training_registration_loading_and_prediction(
    tmp_path: Path,
) -> None:
    """Regression completes through the real isolated MLflow file store."""
    features: FeatureArray = np.array(
        [[0.0], [1.0], [2.0], [3.0]],
        dtype=np.float64,
    )
    targets: RegressionTargetArray = np.array(
        [0.0, 1.0, 2.0, 3.0],
        dtype=np.float64,
    )
    service, registry, loader, tracking_uri = _components(tmp_path)
    plan = create_random_forest_regression_plan(
        training_input=TrainerInput(
            features=features,
            targets=targets,
            hyperparameters={"n_estimators": 3, "n_jobs": 1},
            random_seed=17,
        ),
        evaluation_features=features,
        evaluation_targets=targets,
    )
    result = service.execute(
        TrackedTrainingRequest(
            plan=plan,
            experiment_name="Isolated Regression Smoke",
            run_name="regression-smoke",
            registered_model_name=build_registered_model_name(
                RANDOM_FOREST_REGRESSOR_REGISTRATION.key,
            ),
            tracking_parameters={"n_estimators": 3, "workflow_random_seed": 17},
            tracking_tags={"purpose": "real-smoke"},
            model_description=None,
        ),
    )
    resolved = registry.resolve(
        result.registered_model.registered_model_name,
        result.registered_model.version,
    )
    downloaded_path = _assert_mlflow_artifact_contract(
        tmp_path=tmp_path,
        tracking_uri=tracking_uri,
        tracking=result.tracking,
        model_version=resolved,
        model_registry=registry,
    )
    loaded = loader.load(resolved, RandomForestRegressor)
    prediction = PredictionService(
        model_registry=registry,
        model_loader=loader,
    ).predict(
        create_random_forest_regression_prediction_plan(),
        RegisteredPredictionRequest(
            resolved.registered_model_name,
            resolved.version,
            features,
        ),
    )

    assert isinstance(loaded, RandomForestRegressor)
    assert resolved.key == RANDOM_FOREST_REGRESSOR_REGISTRATION.key
    assert prediction.predictions.dtype == np.dtype(np.float64)
    assert prediction.predictions.shape == (4,)
    print(f"regression artifact file: {downloaded_path}")


def test_real_mlflow_classification_training_registration_loading_and_prediction(
    tmp_path: Path,
) -> None:
    """Classification completes through the real isolated MLflow file store."""
    features: FeatureArray = np.array(
        [[0.0], [0.5], [2.5], [3.0]],
        dtype=np.float64,
    )
    targets: ClassificationTargetArray = np.array(
        [0, 0, 1, 1],
        dtype=np.int64,
    )
    service, registry, loader, tracking_uri = _components(tmp_path)
    plan = create_random_forest_classification_plan(
        training_input=TrainerInput(
            features=features,
            targets=targets,
            hyperparameters={"n_estimators": 3, "n_jobs": 1},
            random_seed=19,
        ),
        evaluation_features=features,
        evaluation_targets=targets,
    )
    result = service.execute(
        TrackedTrainingRequest(
            plan=plan,
            experiment_name="Isolated Classification Smoke",
            run_name="classification-smoke",
            registered_model_name=build_registered_model_name(
                RANDOM_FOREST_CLASSIFIER_REGISTRATION.key,
            ),
            tracking_parameters={"n_estimators": 3, "workflow_random_seed": 19},
            tracking_tags={"purpose": "real-smoke"},
            model_description=None,
        ),
    )
    resolved = registry.resolve(
        result.registered_model.registered_model_name,
        result.registered_model.version,
    )
    downloaded_path = _assert_mlflow_artifact_contract(
        tmp_path=tmp_path,
        tracking_uri=tracking_uri,
        tracking=result.tracking,
        model_version=resolved,
        model_registry=registry,
    )
    loaded = loader.load(resolved, RandomForestClassifier)
    prediction = PredictionService(
        model_registry=registry,
        model_loader=loader,
    ).predict(
        create_random_forest_classification_prediction_plan(),
        RegisteredPredictionRequest(
            resolved.registered_model_name,
            resolved.version,
            features,
        ),
    )

    assert isinstance(loaded, RandomForestClassifier)
    assert resolved.key == RANDOM_FOREST_CLASSIFIER_REGISTRATION.key
    assert prediction.predictions.dtype == np.dtype(np.int64)
    assert set(prediction.predictions.tolist()) <= {0, 1}
    print(f"classification artifact file: {downloaded_path}")
