"""Typed local-training composition for the Random Forest family."""

from sklearn.ensemble import (  # type: ignore[import-untyped]
    RandomForestClassifier,
    RandomForestRegressor,
)

from app.ml.base import BaseTrainer, TrainerInput
from app.ml.engine import (
    TrainingExecutionInput,
    TrainingExecutionPlan,
)
from app.ml.metrics import (
    ClassificationMetricsEngine,
    ClassificationMetricsReport,
    RegressionMetricsEngine,
    RegressionMetricsReport,
)
from app.ml.services import RegisteredPredictionPlan
from app.ml.trainers.random_forest import (
    RANDOM_FOREST_CLASSIFIER_REGISTRATION,
    RANDOM_FOREST_REGRESSOR_REGISTRATION,
    RandomForestClassifierTrainer,
    RandomForestRegressorTrainer,
)
from app.ml.trainers.random_forest.types import (
    ClassificationPredictionArray,
    ClassificationTargetArray,
    FeatureArray,
    RegressionPredictionArray,
    RegressionTargetArray,
    validate_prediction_features,
)


def create_random_forest_regression_plan(
    *,
    training_input: TrainerInput[FeatureArray, RegressionTargetArray],
    evaluation_features: FeatureArray,
    evaluation_targets: RegressionTargetArray,
) -> TrainingExecutionPlan[
    RandomForestRegressorTrainer,
    FeatureArray,
    RegressionTargetArray,
    RandomForestRegressor,
    RegressionPredictionArray,
    RegressionMetricsReport,
]:
    """Bind the regression registration, evaluator, and expected model type."""
    execution_input: TrainingExecutionInput[
        RandomForestRegressorTrainer,
        FeatureArray,
        RegressionTargetArray,
    ] = TrainingExecutionInput(
        registration=RANDOM_FOREST_REGRESSOR_REGISTRATION,
        training_input=training_input,
        evaluation_features=evaluation_features,
        evaluation_targets=evaluation_targets,
    )
    return TrainingExecutionPlan(
        execution_input=execution_input,
        trainer_contract=_regression_trainer_contract,
        metrics_engine=RegressionMetricsEngine(),
        expected_model_type=RandomForestRegressor,
    )


def create_random_forest_classification_plan(
    *,
    training_input: TrainerInput[FeatureArray, ClassificationTargetArray],
    evaluation_features: FeatureArray,
    evaluation_targets: ClassificationTargetArray,
) -> TrainingExecutionPlan[
    RandomForestClassifierTrainer,
    FeatureArray,
    ClassificationTargetArray,
    RandomForestClassifier,
    ClassificationPredictionArray,
    ClassificationMetricsReport,
]:
    """Bind classification registration, evaluator, and expected model type."""
    execution_input: TrainingExecutionInput[
        RandomForestClassifierTrainer,
        FeatureArray,
        ClassificationTargetArray,
    ] = TrainingExecutionInput(
        registration=RANDOM_FOREST_CLASSIFIER_REGISTRATION,
        training_input=training_input,
        evaluation_features=evaluation_features,
        evaluation_targets=evaluation_targets,
    )
    return TrainingExecutionPlan(
        execution_input=execution_input,
        trainer_contract=_classification_trainer_contract,
        metrics_engine=ClassificationMetricsEngine(),
        expected_model_type=RandomForestClassifier,
    )


def create_random_forest_regression_prediction_plan() -> RegisteredPredictionPlan[
    RandomForestRegressor,
    FeatureArray,
    RegressionPredictionArray,
]:
    """Bind the Random Forest regression model and prediction contract."""
    return RegisteredPredictionPlan(
        key=RANDOM_FOREST_REGRESSOR_REGISTRATION.key,
        expected_model_type=RandomForestRegressor,
        validate_features=validate_prediction_features,
        predict=_predict_regression,
    )


def create_random_forest_classification_prediction_plan() -> RegisteredPredictionPlan[
    RandomForestClassifier,
    FeatureArray,
    ClassificationPredictionArray,
]:
    """Bind the Random Forest classification model and prediction contract."""
    return RegisteredPredictionPlan(
        key=RANDOM_FOREST_CLASSIFIER_REGISTRATION.key,
        expected_model_type=RandomForestClassifier,
        validate_features=validate_prediction_features,
        predict=_predict_classification,
    )


def _regression_trainer_contract(
    trainer: RandomForestRegressorTrainer,
) -> BaseTrainer[
    FeatureArray,
    RegressionTargetArray,
    RandomForestRegressor,
    RegressionPredictionArray,
]:
    return trainer


def _classification_trainer_contract(
    trainer: RandomForestClassifierTrainer,
) -> BaseTrainer[
    FeatureArray,
    ClassificationTargetArray,
    RandomForestClassifier,
    ClassificationPredictionArray,
]:
    return trainer


def _predict_regression(
    model: RandomForestRegressor,
    features: FeatureArray,
) -> RegressionPredictionArray:
    return RandomForestRegressorTrainer().predict(model, features)


def _predict_classification(
    model: RandomForestClassifier,
    features: FeatureArray,
) -> ClassificationPredictionArray:
    return RandomForestClassifierTrainer().predict(model, features)
