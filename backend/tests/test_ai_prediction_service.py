"""Typed registered-model prediction service tests."""

from dataclasses import dataclass, field
from typing import assert_type

import numpy as np
import pytest
from app.ml.base import TrainerInput
from app.ml.composition import (
    create_random_forest_classification_prediction_plan,
    create_random_forest_regression_prediction_plan,
)
from app.ml.registry import (
    BaseModelRegistry,
    ModelRegistrationRequest,
    RegisteredModelVersion,
    RegisteredModelVersionNotFoundError,
    RegisteredModelVersionStatus,
)
from app.ml.services import (
    BaseRegisteredModelLoader,
    PredictionService,
    PredictionTrainerKeyMismatchError,
    RegisteredModelTypeMismatchError,
    RegisteredPredictionRequest,
    RegisteredPredictionResult,
)
from app.ml.trainers.random_forest import (
    RANDOM_FOREST_CLASSIFIER_REGISTRATION,
    RANDOM_FOREST_REGRESSOR_REGISTRATION,
    RandomForestClassifierTrainer,
    RandomForestRegressorTrainer,
    TrainerDataValidationError,
)
from app.ml.trainers.random_forest.types import (
    ClassificationPredictionArray,
    ClassificationTargetArray,
    FeatureArray,
    RegressionPredictionArray,
    RegressionTargetArray,
)
from sklearn.ensemble import (  # type: ignore[import-untyped]
    RandomForestClassifier,
    RandomForestRegressor,
)

FEATURES: FeatureArray = np.array(
    [[0.0], [1.0], [2.0], [3.0]],
    dtype=np.float64,
)
REGRESSION_TARGETS: RegressionTargetArray = np.array(
    [0.0, 1.0, 2.0, 3.0],
    dtype=np.float64,
)
CLASSIFICATION_TARGETS: ClassificationTargetArray = np.array(
    [0, 0, 1, 1],
    dtype=np.int64,
)


@dataclass
class FakePredictionRegistry(BaseModelRegistry):
    """Resolve one supplied model version and record lookup calls."""

    version: RegisteredModelVersion | None
    resolve_calls: list[tuple[str, str]] = field(default_factory=list)

    def register(
        self,
        request: ModelRegistrationRequest,
    ) -> RegisteredModelVersion:
        _ = request
        raise AssertionError("Prediction must not register models.")

    def resolve(
        self,
        registered_model_name: str,
        version_or_alias: str,
    ) -> RegisteredModelVersion:
        self.resolve_calls.append((registered_model_name, version_or_alias))
        if self.version is None:
            raise RegisteredModelVersionNotFoundError("model version not found")
        return self.version


@dataclass
class FakeModelLoader(BaseRegisteredModelLoader):
    """Return one in-memory model with the production runtime type check."""

    model: object
    load_calls: list[RegisteredModelVersion] = field(default_factory=list)

    def load[
        ModelT
    ](
        self,
        model_version: RegisteredModelVersion,
        expected_type: type[ModelT],
    ) -> ModelT:
        self.load_calls.append(model_version)
        if not isinstance(self.model, expected_type):
            raise RegisteredModelTypeMismatchError("wrong fitted model type")
        return self.model


def _version(
    *,
    classification: bool = False,
) -> RegisteredModelVersion:
    registration = (
        RANDOM_FOREST_CLASSIFIER_REGISTRATION
        if classification
        else RANDOM_FOREST_REGRESSOR_REGISTRATION
    )
    return RegisteredModelVersion(
        registered_model_name=(
            "ai_core_random_forest_classification"
            if classification
            else "ai_core_random_forest_regression"
        ),
        version="1",
        run_id="mlflow-run-1",
        source_uri="file:///model/model.joblib",
        key=registration.key,
        status=RegisteredModelVersionStatus.READY,
        aliases=(),
    )


def _regressor() -> RandomForestRegressor:
    return (
        RandomForestRegressorTrainer()
        .fit(
            TrainerInput(
                features=FEATURES,
                targets=REGRESSION_TARGETS,
                hyperparameters={"n_estimators": 3, "n_jobs": 1},
                random_seed=5,
            ),
        )
        .model
    )


def _classifier() -> RandomForestClassifier:
    return (
        RandomForestClassifierTrainer()
        .fit(
            TrainerInput(
                features=FEATURES,
                targets=CLASSIFICATION_TARGETS,
                hyperparameters={"n_estimators": 3, "n_jobs": 1},
                random_seed=5,
            ),
        )
        .model
    )


def test_regression_prediction_resolves_loads_and_returns_typed_output() -> None:
    """Regression prediction uses the exact resolved and checked model."""
    version = _version()
    registry = FakePredictionRegistry(version)
    loader = FakeModelLoader(_regressor())
    request = RegisteredPredictionRequest(
        version.registered_model_name,
        "1",
        FEATURES,
    )

    result = PredictionService(
        model_registry=registry,
        model_loader=loader,
    ).predict(create_random_forest_regression_prediction_plan(), request)

    assert_type(
        result,
        RegisteredPredictionResult[RegressionPredictionArray],
    )
    assert result.model_version is version
    assert result.predictions.dtype == np.dtype(np.float64)
    assert result.predictions.shape == (4,)
    assert registry.resolve_calls == [(version.registered_model_name, "1")]
    assert loader.load_calls == [version]


def test_classification_prediction_returns_typed_integer_labels() -> None:
    """Classification prediction preserves the int64 platform boundary."""
    version = _version(classification=True)
    result = PredictionService(
        model_registry=FakePredictionRegistry(version),
        model_loader=FakeModelLoader(_classifier()),
    ).predict(
        create_random_forest_classification_prediction_plan(),
        RegisteredPredictionRequest(
            version.registered_model_name,
            "1",
            FEATURES,
        ),
    )

    assert_type(
        result,
        RegisteredPredictionResult[ClassificationPredictionArray],
    )
    assert result.predictions.dtype == np.dtype(np.int64)
    assert set(result.predictions.tolist()) <= {0, 1}


def test_prediction_rejects_resolved_trainer_key_mismatch() -> None:
    """A known task mismatch prevents model deserialization entirely."""
    version = _version(classification=True)
    loader = FakeModelLoader(object())

    with pytest.raises(PredictionTrainerKeyMismatchError, match="expected"):
        PredictionService(
            model_registry=FakePredictionRegistry(version),
            model_loader=loader,
        ).predict(
            create_random_forest_regression_prediction_plan(),
            RegisteredPredictionRequest(
                version.registered_model_name,
                "1",
                FEATURES,
            ),
        )

    assert loader.load_calls == []


def test_prediction_loader_rejects_wrong_runtime_model_type() -> None:
    """Runtime model validation occurs before raw prediction."""
    version = _version()

    with pytest.raises(RegisteredModelTypeMismatchError, match="wrong"):
        PredictionService(
            model_registry=FakePredictionRegistry(version),
            model_loader=FakeModelLoader(_classifier()),
        ).predict(
            create_random_forest_regression_prediction_plan(),
            RegisteredPredictionRequest(
                version.registered_model_name,
                "1",
                FEATURES,
            ),
        )


def test_prediction_rejects_invalid_prepared_features() -> None:
    """Prediction does not reshape or cast invalid prepared arrays."""
    invalid_features: FeatureArray = np.array([0.0, 1.0], dtype=np.float64)
    version = _version()

    with pytest.raises(TrainerDataValidationError, match="2-dimensional"):
        PredictionService(
            model_registry=FakePredictionRegistry(version),
            model_loader=FakeModelLoader(_regressor()),
        ).predict(
            create_random_forest_regression_prediction_plan(),
            RegisteredPredictionRequest(
                version.registered_model_name,
                "1",
                invalid_features,
            ),
        )


def test_missing_registered_model_version_propagates() -> None:
    """The prediction service preserves the registry lookup error boundary."""
    with pytest.raises(RegisteredModelVersionNotFoundError, match="not found"):
        PredictionService(
            model_registry=FakePredictionRegistry(None),
            model_loader=FakeModelLoader(_regressor()),
        ).predict(
            create_random_forest_regression_prediction_plan(),
            RegisteredPredictionRequest(
                "ai_core_random_forest_regression",
                "champion",
                FEATURES,
            ),
        )


def test_prediction_does_not_retrain_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prediction composition invokes only the trainer's raw predict contract."""
    version = _version()
    fitted_model = _regressor()

    def fail_fit(
        _trainer: RandomForestRegressorTrainer,
        _trainer_input: TrainerInput[FeatureArray, RegressionTargetArray],
    ) -> None:
        raise AssertionError("Prediction must not fit a model.")

    monkeypatch.setattr(RandomForestRegressorTrainer, "fit", fail_fit)
    result = PredictionService(
        model_registry=FakePredictionRegistry(version),
        model_loader=FakeModelLoader(fitted_model),
    ).predict(
        create_random_forest_regression_prediction_plan(),
        RegisteredPredictionRequest(
            version.registered_model_name,
            "1",
            FEATURES,
        ),
    )

    assert result.predictions.shape == (4,)
