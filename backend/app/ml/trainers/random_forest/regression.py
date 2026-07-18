"""Concrete Random Forest regression trainer."""

from time import perf_counter

# scikit-learn 1.9 does not provide bundled typing metadata.
from sklearn.ensemble import RandomForestRegressor  # type: ignore[import-untyped]

from app.ml.base import BaseTrainer, TrainerInput, TrainerKey, TrainerOutput
from app.ml.domain import AlgorithmType, TaskType
from app.ml.factory import TrainerRegistration
from app.ml.trainers.random_forest.parameters import (
    RandomForestRegressionParameters,
)
from app.ml.trainers.random_forest.types import (
    FeatureArray,
    RegressionPredictionArray,
    RegressionTargetArray,
    validate_prediction_features,
    validate_regression_predictions,
    validate_regression_training_data,
)

_KEY = TrainerKey(
    algorithm=AlgorithmType.RANDOM_FOREST,
    task_type=TaskType.REGRESSION,
)


class RandomForestRegressorTrainer(
    BaseTrainer[
        FeatureArray,
        RegressionTargetArray,
        RandomForestRegressor,
        RegressionPredictionArray,
    ],
):
    """Fit Random Forest regressors from validated in-memory NumPy arrays."""

    @property
    def key(self) -> TrainerKey:
        """Return the Random Forest regression identity."""
        return _KEY

    def fit(
        self,
        trainer_input: TrainerInput[FeatureArray, RegressionTargetArray],
    ) -> TrainerOutput[RandomForestRegressor]:
        """Validate inputs, fit a regressor, and return the raw model result."""
        features, targets = validate_regression_training_data(
            trainer_input.features,
            trainer_input.targets,
        )
        parameters = RandomForestRegressionParameters.model_validate(
            dict(trainer_input.hyperparameters),
        )
        model = RandomForestRegressor(
            **parameters.to_sklearn_kwargs(random_seed=trainer_input.random_seed),
        )
        started_at = perf_counter()
        model.fit(features, targets)
        duration_seconds = perf_counter() - started_at
        return TrainerOutput(
            model=model,
            training_duration_seconds=duration_seconds,
        )

    def predict(
        self,
        model: RandomForestRegressor,
        features: FeatureArray,
    ) -> RegressionPredictionArray:
        """Validate features and return raw regression predictions."""
        validated_features = validate_prediction_features(features)
        return validate_regression_predictions(model.predict(validated_features))


def create_random_forest_regressor_trainer() -> RandomForestRegressorTrainer:
    """Create a fresh stateless Random Forest regression trainer."""
    return RandomForestRegressorTrainer()


RANDOM_FOREST_REGRESSOR_REGISTRATION = TrainerRegistration(
    key=_KEY,
    provider=create_random_forest_regressor_trainer,
)
