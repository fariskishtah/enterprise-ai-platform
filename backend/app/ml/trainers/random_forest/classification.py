"""Concrete Random Forest classification trainer."""

from time import perf_counter

# scikit-learn 1.9 does not provide bundled typing metadata.
from sklearn.ensemble import RandomForestClassifier  # type: ignore[import-untyped]

from app.ml.base import BaseTrainer, TrainerInput, TrainerKey, TrainerOutput
from app.ml.domain import AlgorithmType, TaskType
from app.ml.factory import TrainerRegistration
from app.ml.trainers.random_forest.parameters import (
    RandomForestClassificationParameters,
)
from app.ml.trainers.random_forest.types import (
    ClassificationPredictionArray,
    ClassificationTargetArray,
    FeatureArray,
    validate_classification_predictions,
    validate_classification_training_data,
    validate_prediction_features,
)

_KEY = TrainerKey(
    algorithm=AlgorithmType.RANDOM_FOREST,
    task_type=TaskType.CLASSIFICATION,
)


class RandomForestClassifierTrainer(
    BaseTrainer[
        FeatureArray,
        ClassificationTargetArray,
        RandomForestClassifier,
        ClassificationPredictionArray,
    ],
):
    """Fit classifiers for single-output integer labels from NumPy arrays."""

    @property
    def key(self) -> TrainerKey:
        """Return the Random Forest classification identity."""
        return _KEY

    def fit(
        self,
        trainer_input: TrainerInput[FeatureArray, ClassificationTargetArray],
    ) -> TrainerOutput[RandomForestClassifier]:
        """Validate inputs, fit a classifier, and return the raw model result."""
        features, targets = validate_classification_training_data(
            trainer_input.features,
            trainer_input.targets,
        )
        parameters = RandomForestClassificationParameters.model_validate(
            dict(trainer_input.hyperparameters),
        )
        model = RandomForestClassifier(
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
        model: RandomForestClassifier,
        features: FeatureArray,
    ) -> ClassificationPredictionArray:
        """Validate features and return raw integer class predictions."""
        validated_features = validate_prediction_features(features)
        return validate_classification_predictions(model.predict(validated_features))


def create_random_forest_classifier_trainer() -> RandomForestClassifierTrainer:
    """Create a fresh stateless Random Forest classification trainer."""
    return RandomForestClassifierTrainer()


RANDOM_FOREST_CLASSIFIER_REGISTRATION = TrainerRegistration(
    key=_KEY,
    provider=create_random_forest_classifier_trainer,
)
