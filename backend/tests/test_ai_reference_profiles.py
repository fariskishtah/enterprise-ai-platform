"""Reference-profile ownership and non-retraining reconciliation tests."""

from dataclasses import dataclass
from uuid import uuid4

import numpy as np
import pytest
from app.ml.base import TrainerInput
from app.ml.domain import TaskType
from app.ml.jobs import RandomForestRegressionJobSpec, random_forest_key
from app.ml.monitoring.reconcile import rebuild_reference_profile
from app.ml.registry import (
    BaseModelRegistry,
    ModelRegistrationRequest,
    RegisteredModelVersion,
    RegisteredModelVersionStatus,
)
from app.ml.services import (
    BaseRegisteredModelLoader,
    PredictionService,
    RegisteredModelTypeMismatchError,
)
from app.ml.trainers.random_forest import (
    RandomForestRegressorTrainer,
)
from app.ml.trainers.random_forest.types import FeatureArray, RegressionTargetArray
from app.repositories.ai_monitoring import MissingReferenceProfileJob
from sklearn.ensemble import RandomForestRegressor  # type: ignore[import-untyped]


@dataclass
class FakeRegistry(BaseModelRegistry):
    """Resolve the already-registered exact version only."""

    version: RegisteredModelVersion

    def register(
        self,
        request: ModelRegistrationRequest,
    ) -> RegisteredModelVersion:
        _ = request
        raise AssertionError("Reconciliation must not register another version.")

    def resolve(
        self,
        registered_model_name: str,
        version_or_alias: str,
    ) -> RegisteredModelVersion:
        assert registered_model_name == self.version.registered_model_name
        assert version_or_alias == self.version.version
        return self.version


@dataclass
class FakeLoader(BaseRegisteredModelLoader):
    """Return the trusted fitted estimator already associated with the version."""

    model: RandomForestRegressor

    def load[
        ModelT
    ](
        self,
        model_version: RegisteredModelVersion,
        expected_type: type[ModelT],
    ) -> ModelT:
        _ = model_version
        if not isinstance(self.model, expected_type):
            raise RegisteredModelTypeMismatchError("wrong model")
        return self.model


def _specification() -> RandomForestRegressionJobSpec:
    return RandomForestRegressionJobSpec(
        training_features=((0.0,), (1.0,), (2.0,), (3.0,)),
        training_targets=(0.0, 1.0, 2.0, 3.0),
        evaluation_features=((0.5,), (2.5,)),
        evaluation_targets=(0.5, 2.5),
        hyperparameters={"n_estimators": 3, "n_jobs": 1},
        random_seed=17,
        experiment_name="Reference Reconciliation",
        registered_model_name="ai_core_random_forest_regression",
        tags={},
    )


def test_reconciliation_predicts_existing_version_without_retraining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The recoverable path loads and predicts; fit and registration stay forbidden."""
    features: FeatureArray = np.asarray(
        [[0.0], [1.0], [2.0], [3.0]],
        dtype=np.float64,
    )
    targets: RegressionTargetArray = np.asarray(
        [0.0, 1.0, 2.0, 3.0],
        dtype=np.float64,
    )
    model = (
        RandomForestRegressorTrainer()
        .fit(
            TrainerInput(
                features=features,
                targets=targets,
                hyperparameters={"n_estimators": 3, "n_jobs": 1},
                random_seed=17,
            ),
        )
        .model
    )
    version = RegisteredModelVersion(
        registered_model_name="ai_core_random_forest_regression",
        version="9",
        run_id="run-9",
        source_uri="file:///model.joblib",
        key=random_forest_key(TaskType.REGRESSION),
        status=RegisteredModelVersionStatus.READY,
        aliases=("candidate",),
    )

    def reject_fit(
        _trainer: RandomForestRegressorTrainer,
        _training_input: TrainerInput[FeatureArray, RegressionTargetArray],
    ) -> None:
        raise AssertionError("Reference reconciliation must not retrain.")

    monkeypatch.setattr(RandomForestRegressorTrainer, "fit", reject_fit)
    candidate = MissingReferenceProfileJob(
        id=uuid4(),
        key=version.key,
        registered_model_name=version.registered_model_name,
        registered_model_version=version.version,
        specification=_specification(),
    )

    profile = rebuild_reference_profile(
        candidate,
        prediction_service=PredictionService(
            model_registry=FakeRegistry(version),
            model_loader=FakeLoader(model),
        ),
        bin_count=10,
    )

    assert profile.model_version == "9"
    assert profile.training_job_id == candidate.id
    assert profile.sample_count == 2
    assert profile.features[0].profile.bin_counts
