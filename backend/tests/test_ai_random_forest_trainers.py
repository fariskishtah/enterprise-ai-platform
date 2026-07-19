"""Concrete Random Forest trainer-family tests."""

from typing import assert_type, cast

import app.ml.trainers.random_forest as random_forest_contracts
import numpy as np
import pytest
from app.ml.base import BaseTrainer, TrainerInput, TrainerKey
from app.ml.domain import AlgorithmType, TaskType
from app.ml.factory import TrainerFactory, TrainerRegistration, TrainerRegistry
from app.ml.trainers.random_forest import (
    RANDOM_FOREST_CLASSIFIER_REGISTRATION,
    RANDOM_FOREST_REGRESSOR_REGISTRATION,
    RandomForestClassifierTrainer,
    RandomForestRegressorTrainer,
    TrainerDataValidationError,
)
from app.ml.trainers.random_forest.types import (
    ClassificationTargetArray,
    FeatureArray,
    RegressionTargetArray,
)
from pydantic import ValidationError
from sklearn.ensemble import (  # type: ignore[import-untyped]
    RandomForestClassifier,
    RandomForestRegressor,
)

REGRESSION_KEY = TrainerKey(
    algorithm=AlgorithmType.RANDOM_FOREST,
    task_type=TaskType.REGRESSION,
)
CLASSIFICATION_KEY = TrainerKey(
    algorithm=AlgorithmType.RANDOM_FOREST,
    task_type=TaskType.CLASSIFICATION,
)
REGRESSION_FEATURES: FeatureArray = np.array(
    [
        [0.0, 0.0],
        [1.0, 1.0],
        [2.0, 2.0],
        [3.0, 3.0],
        [4.0, 4.0],
        [5.0, 5.0],
    ],
    dtype=np.float64,
)
REGRESSION_TARGETS: RegressionTargetArray = np.array(
    [0.0, 1.0, 2.0, 3.0, 4.0, 5.0],
    dtype=np.float64,
)
CLASSIFICATION_FEATURES: FeatureArray = np.array(
    [
        [0.0, 0.0],
        [0.5, 0.5],
        [1.0, 1.0],
        [3.0, 3.0],
        [3.5, 3.5],
        [4.0, 4.0],
    ],
    dtype=np.float64,
)
CLASSIFICATION_TARGETS: ClassificationTargetArray = np.array(
    [0, 0, 0, 1, 1, 1],
    dtype=np.int64,
)

assert_type(
    RANDOM_FOREST_REGRESSOR_REGISTRATION,
    TrainerRegistration[RandomForestRegressorTrainer],
)
assert_type(
    RANDOM_FOREST_CLASSIFIER_REGISTRATION,
    TrainerRegistration[RandomForestClassifierTrainer],
)


def _regression_input(
    *,
    features: FeatureArray = REGRESSION_FEATURES,
    targets: RegressionTargetArray = REGRESSION_TARGETS,
    hyperparameters: dict[str, object] | None = None,
    random_seed: int | None = 7,
) -> TrainerInput[FeatureArray, RegressionTargetArray]:
    return TrainerInput(
        features=features,
        targets=targets,
        hyperparameters=(
            {"n_estimators": 5, "n_jobs": 1}
            if hyperparameters is None
            else hyperparameters
        ),
        random_seed=random_seed,
    )


def _classification_input(
    *,
    features: FeatureArray = CLASSIFICATION_FEATURES,
    targets: ClassificationTargetArray = CLASSIFICATION_TARGETS,
    hyperparameters: dict[str, object] | None = None,
    random_seed: int | None = 7,
) -> TrainerInput[FeatureArray, ClassificationTargetArray]:
    return TrainerInput(
        features=features,
        targets=targets,
        hyperparameters=(
            {"n_estimators": 5, "n_jobs": 1}
            if hyperparameters is None
            else hyperparameters
        ),
        random_seed=random_seed,
    )


def test_regression_trainer_exposes_composite_key() -> None:
    """The regressor keeps algorithm and task as separate identity fields."""
    assert RandomForestRegressorTrainer().key == REGRESSION_KEY


def test_regression_trainer_fits_and_predicts_typed_output() -> None:
    """Regression fit returns sklearn model, duration, and float predictions."""
    trainer = RandomForestRegressorTrainer()

    output = trainer.fit(_regression_input())
    predictions = trainer.predict(output.model, REGRESSION_FEATURES)

    assert_type(output.model, RandomForestRegressor)
    assert isinstance(output.model, RandomForestRegressor)
    assert output.training_duration_seconds >= 0.0
    assert predictions.shape == (REGRESSION_FEATURES.shape[0],)
    assert predictions.dtype == np.dtype(np.float64)


def test_regression_results_are_deterministic_for_same_seed() -> None:
    """Equivalent fits produce equal raw predictions with the same seed."""
    first_trainer = RandomForestRegressorTrainer()
    second_trainer = RandomForestRegressorTrainer()

    first_output = first_trainer.fit(_regression_input(random_seed=31))
    second_output = second_trainer.fit(_regression_input(random_seed=31))

    np.testing.assert_array_equal(
        first_trainer.predict(first_output.model, REGRESSION_FEATURES),
        second_trainer.predict(second_output.model, REGRESSION_FEATURES),
    )


def test_regression_trainer_is_stateless_after_fit() -> None:
    """The fitted estimator is returned and not retained on the trainer."""
    trainer = RandomForestRegressorTrainer()

    trainer.fit(_regression_input())

    assert "model" not in vars(trainer)


@pytest.mark.parametrize(
    ("features", "targets", "message"),
    [
        (
            np.array([0.0, 1.0], dtype=np.float64),
            REGRESSION_TARGETS,
            "features must be 2-dimensional",
        ),
        (
            REGRESSION_FEATURES,
            np.array([[0.0], [1.0]], dtype=np.float64),
            "targets must be 1-dimensional",
        ),
        (
            REGRESSION_FEATURES,
            np.array([0.0, 1.0], dtype=np.float64),
            "feature row count must equal target value count",
        ),
        (
            np.empty((0, 2), dtype=np.float64),
            np.empty((0,), dtype=np.float64),
            "training data must contain at least one row",
        ),
        (
            np.empty((2, 0), dtype=np.float64),
            np.array([0.0, 1.0], dtype=np.float64),
            "features must contain at least one column",
        ),
    ],
)
def test_regression_trainer_rejects_invalid_array_structure(
    features: FeatureArray,
    targets: RegressionTargetArray,
    message: str,
) -> None:
    """Obvious regression array-shape violations fail before sklearn."""
    with pytest.raises(TrainerDataValidationError, match=message):
        RandomForestRegressorTrainer().fit(
            _regression_input(features=features, targets=targets),
        )


def test_regression_trainer_rejects_non_float64_targets() -> None:
    """Regression's initial target boundary is explicitly float64."""
    targets = cast(
        RegressionTargetArray,
        np.array([0, 1, 2, 3, 4, 5], dtype=np.int64),
    )

    with pytest.raises(
        TrainerDataValidationError,
        match="regression targets must use the float64 dtype",
    ):
        RandomForestRegressorTrainer().fit(_regression_input(targets=targets))


def test_regression_trainer_rejects_non_float64_features() -> None:
    """Regression does not automatically cast prepared feature arrays."""
    features = cast(
        FeatureArray,
        np.array([[0, 1], [2, 3]], dtype=np.int64),
    )
    targets: RegressionTargetArray = np.array([0.0, 1.0], dtype=np.float64)

    with pytest.raises(
        TrainerDataValidationError,
        match="features must use the float64 dtype",
    ):
        RandomForestRegressorTrainer().fit(
            _regression_input(features=features, targets=targets),
        )


def test_regression_trainer_rejects_non_array_features() -> None:
    """Prepared regression features must already be NumPy arrays."""
    features = cast(FeatureArray, ((0.0, 1.0),))

    with pytest.raises(
        TrainerDataValidationError,
        match="features must be a NumPy ndarray",
    ):
        RandomForestRegressorTrainer().fit(_regression_input(features=features))


def test_regression_prediction_rejects_invalid_feature_rank() -> None:
    """Prediction does not silently reshape regression features."""
    trainer = RandomForestRegressorTrainer()
    output = trainer.fit(_regression_input())
    invalid_features: FeatureArray = np.array([0.0, 1.0], dtype=np.float64)

    with pytest.raises(
        TrainerDataValidationError,
        match="features must be 2-dimensional",
    ):
        trainer.predict(output.model, invalid_features)


def test_regression_prediction_rejects_empty_feature_columns() -> None:
    """Prediction features must retain at least one prepared column."""
    trainer = RandomForestRegressorTrainer()
    output = trainer.fit(_regression_input())
    invalid_features: FeatureArray = np.empty((1, 0), dtype=np.float64)

    with pytest.raises(
        TrainerDataValidationError,
        match="features must contain at least one column",
    ):
        trainer.predict(output.model, invalid_features)


def test_regression_trainer_rejects_invalid_parameter_mapping() -> None:
    """Native Pydantic validation errors propagate from the trainer boundary."""
    with pytest.raises(ValidationError):
        RandomForestRegressorTrainer().fit(
            _regression_input(hyperparameters={"criterion": "gini"}),
        )


def test_workflow_seed_overrides_parameter_seed_during_regression_fit() -> None:
    """Trainer mapping conversion honors workflow random-seed precedence."""
    hyperparameters: dict[str, object] = {
        "n_estimators": 5,
        "n_jobs": 1,
        "random_state": 3,
    }

    output = RandomForestRegressorTrainer().fit(
        _regression_input(
            hyperparameters=hyperparameters,
            random_seed=29,
        ),
    )

    assert output.model.get_params()["random_state"] == 29
    assert hyperparameters == {
        "n_estimators": 5,
        "n_jobs": 1,
        "random_state": 3,
    }


def test_classification_trainer_exposes_composite_key() -> None:
    """The classifier shares the algorithm but has its own task identity."""
    assert RandomForestClassifierTrainer().key == CLASSIFICATION_KEY


def test_classification_trainer_fits_and_predicts_integer_classes() -> None:
    """Classification fit returns sklearn model and integer class predictions."""
    trainer = RandomForestClassifierTrainer()

    output = trainer.fit(_classification_input())
    predictions = trainer.predict(output.model, CLASSIFICATION_FEATURES)

    assert_type(output.model, RandomForestClassifier)
    assert isinstance(output.model, RandomForestClassifier)
    assert output.training_duration_seconds >= 0.0
    assert predictions.shape == (CLASSIFICATION_FEATURES.shape[0],)
    assert predictions.dtype == np.dtype(np.int64)
    assert set(predictions.tolist()) <= {0, 1}


def test_classification_results_are_deterministic_for_same_seed() -> None:
    """Equivalent classifier fits produce equal classes for the same seed."""
    first_trainer = RandomForestClassifierTrainer()
    second_trainer = RandomForestClassifierTrainer()

    first_output = first_trainer.fit(_classification_input(random_seed=37))
    second_output = second_trainer.fit(_classification_input(random_seed=37))

    np.testing.assert_array_equal(
        first_trainer.predict(first_output.model, CLASSIFICATION_FEATURES),
        second_trainer.predict(second_output.model, CLASSIFICATION_FEATURES),
    )


def test_classification_trainer_is_stateless_after_fit() -> None:
    """The classifier returns its fitted model without retaining it."""
    trainer = RandomForestClassifierTrainer()

    trainer.fit(_classification_input())

    assert "model" not in vars(trainer)


@pytest.mark.parametrize(
    ("features", "targets", "message"),
    [
        (
            np.array([0.0, 1.0], dtype=np.float64),
            CLASSIFICATION_TARGETS,
            "features must be 2-dimensional",
        ),
        (
            CLASSIFICATION_FEATURES,
            np.array([[0], [1]], dtype=np.int64),
            "targets must be 1-dimensional",
        ),
        (
            CLASSIFICATION_FEATURES,
            np.array([0, 1], dtype=np.int64),
            "feature row count must equal target value count",
        ),
        (
            np.empty((0, 2), dtype=np.float64),
            np.empty((0,), dtype=np.int64),
            "training data must contain at least one row",
        ),
        (
            np.empty((2, 0), dtype=np.float64),
            np.array([0, 1], dtype=np.int64),
            "features must contain at least one column",
        ),
    ],
)
def test_classification_trainer_rejects_invalid_array_structure(
    features: FeatureArray,
    targets: ClassificationTargetArray,
    message: str,
) -> None:
    """Obvious classification array-shape violations fail before sklearn."""
    with pytest.raises(TrainerDataValidationError, match=message):
        RandomForestClassifierTrainer().fit(
            _classification_input(features=features, targets=targets),
        )


def test_classification_trainer_rejects_non_int64_targets() -> None:
    """The initial classification label boundary accepts int64 only."""
    targets = cast(
        ClassificationTargetArray,
        np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0], dtype=np.float64),
    )

    with pytest.raises(
        TrainerDataValidationError,
        match="classification targets must use the int64 dtype",
    ):
        RandomForestClassifierTrainer().fit(_classification_input(targets=targets))


def test_classification_trainer_rejects_non_float64_features() -> None:
    """Classification does not automatically cast prepared feature arrays."""
    features = cast(
        FeatureArray,
        np.array([[0, 1], [2, 3]], dtype=np.int64),
    )
    targets: ClassificationTargetArray = np.array([0, 1], dtype=np.int64)

    with pytest.raises(
        TrainerDataValidationError,
        match="features must use the float64 dtype",
    ):
        RandomForestClassifierTrainer().fit(
            _classification_input(features=features, targets=targets),
        )


def test_classification_trainer_rejects_non_array_targets() -> None:
    """Prepared classification labels must already be NumPy arrays."""
    targets = cast(ClassificationTargetArray, (0, 0, 0, 1, 1, 1))

    with pytest.raises(
        TrainerDataValidationError,
        match="targets must be a NumPy ndarray",
    ):
        RandomForestClassifierTrainer().fit(_classification_input(targets=targets))


def test_classification_prediction_rejects_invalid_feature_rank() -> None:
    """Prediction does not silently reshape classification features."""
    trainer = RandomForestClassifierTrainer()
    output = trainer.fit(_classification_input())
    invalid_features: FeatureArray = np.array([0.0, 1.0], dtype=np.float64)

    with pytest.raises(
        TrainerDataValidationError,
        match="features must be 2-dimensional",
    ):
        trainer.predict(output.model, invalid_features)


def test_classification_prediction_rejects_empty_feature_columns() -> None:
    """Classification prediction requires at least one feature column."""
    trainer = RandomForestClassifierTrainer()
    output = trainer.fit(_classification_input())
    invalid_features: FeatureArray = np.empty((1, 0), dtype=np.float64)

    with pytest.raises(
        TrainerDataValidationError,
        match="features must contain at least one column",
    ):
        trainer.predict(output.model, invalid_features)


def test_classification_trainer_rejects_invalid_parameter_mapping() -> None:
    """Regression criteria cannot pass through the classifier boundary."""
    with pytest.raises(ValidationError):
        RandomForestClassifierTrainer().fit(
            _classification_input(
                hyperparameters={"criterion": "squared_error"},
            ),
        )


def test_base_trainer_does_not_add_probability_prediction() -> None:
    """Probabilities remain outside the generic raw prediction contract."""
    assert "predict_proba" not in BaseTrainer.__dict__


def test_random_forest_registration_tokens_coexist_and_preserve_types() -> None:
    """Explicit family tokens support both tasks without global state."""
    registry = TrainerRegistry()
    assert registry.registered_keys() == ()

    registry.register(RANDOM_FOREST_REGRESSOR_REGISTRATION)
    registry.register(RANDOM_FOREST_CLASSIFIER_REGISTRATION)
    factory = TrainerFactory(registry)

    regressor = factory.create(RANDOM_FOREST_REGRESSOR_REGISTRATION)
    classifier = factory.create(RANDOM_FOREST_CLASSIFIER_REGISTRATION)

    assert_type(regressor, RandomForestRegressorTrainer)
    assert_type(classifier, RandomForestClassifierTrainer)
    assert isinstance(regressor, RandomForestRegressorTrainer)
    assert isinstance(classifier, RandomForestClassifierTrainer)
    assert registry.registered_keys() == (CLASSIFICATION_KEY, REGRESSION_KEY)


def test_random_forest_factory_calls_create_distinct_trainers() -> None:
    """Registration providers create fresh stateless trainer instances."""
    registry = TrainerRegistry()
    registry.register(RANDOM_FOREST_REGRESSOR_REGISTRATION)
    factory = TrainerFactory(registry)

    first = factory.create(RANDOM_FOREST_REGRESSOR_REGISTRATION)
    second = factory.create(RANDOM_FOREST_REGRESSOR_REGISTRATION)

    assert first is not second


def test_random_forest_package_public_exports() -> None:
    """The family exposes contracts, trainers, tokens, and its focused error."""
    assert random_forest_contracts.__all__ == [
        "RANDOM_FOREST_CLASSIFIER_REGISTRATION",
        "RANDOM_FOREST_REGRESSOR_REGISTRATION",
        "RandomForestClassificationParameters",
        "RandomForestClassifierTrainer",
        "RandomForestRegressionParameters",
        "RandomForestRegressorTrainer",
        "TrainerDataValidationError",
    ]
