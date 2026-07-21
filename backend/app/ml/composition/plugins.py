"""Generic model-plugin composition for background training."""

from collections.abc import Mapping

from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]

from app.ml.base import BaseTrainer, TrainerInput, TrainerKey
from app.ml.engine import TrainingExecutionInput, TrainingExecutionPlan
from app.ml.factory import TrainerRegistration
from app.ml.plugins import (
    FeatureArray,
    ModelPlugin,
    PluginMetricsEngine,
    PluginMetricsReport,
    PluginTrainer,
    create_default_plugin_registry,
)
from app.ml.plugins.core import PredictionArray, TargetArray
from app.ml.services import RegisteredPredictionPlan
from app.ml.trainers.random_forest.types import validate_prediction_features

PLUGIN_REGISTRY = create_default_plugin_registry()


def _registration(plugin: ModelPlugin) -> TrainerRegistration[PluginTrainer]:
    """Build one registration without losing the factory's return type."""

    def create() -> PluginTrainer:
        return PluginTrainer(plugin)

    return TrainerRegistration(plugin.key, create)


PLUGIN_TRAINING_PLAN_REGISTRATIONS: Mapping[
    TrainerKey, TrainerRegistration[PluginTrainer]
] = {plugin.key: _registration(plugin) for plugin in PLUGIN_REGISTRY.all()}
PLUGIN_TRAINER_REGISTRATIONS: Mapping[
    TrainerKey, TrainerRegistration[PluginTrainer]
] = {
    key: registration
    for key, registration in PLUGIN_TRAINING_PLAN_REGISTRATIONS.items()
    if key.algorithm.value != "random_forest"
}


def create_plugin_training_plan(
    *,
    key: TrainerKey,
    training_input: TrainerInput[FeatureArray, TargetArray],
    evaluation_features: FeatureArray,
    evaluation_targets: TargetArray,
) -> TrainingExecutionPlan[
    PluginTrainer,
    FeatureArray,
    TargetArray,
    Pipeline,
    PredictionArray,
    PluginMetricsReport,
]:
    """Bind one registered plugin to the existing typed training engine."""
    registration = PLUGIN_TRAINING_PLAN_REGISTRATIONS[key]
    return TrainingExecutionPlan(
        execution_input=TrainingExecutionInput(
            registration=registration,
            training_input=training_input,
            evaluation_features=evaluation_features,
            evaluation_targets=evaluation_targets,
        ),
        trainer_contract=_trainer_contract,
        metrics_engine=PluginMetricsEngine(key.task_type),
        expected_model_type=Pipeline,
    )


def create_plugin_prediction_plan(
    plugin_id: str,
) -> RegisteredPredictionPlan[Pipeline, FeatureArray, PredictionArray]:
    """Create a checked prediction contract for one generic pipeline plugin."""
    plugin = PLUGIN_REGISTRY.get(plugin_id)
    trainer = PluginTrainer(plugin)
    return RegisteredPredictionPlan(
        key=plugin.key,
        expected_model_type=Pipeline,
        validate_features=validate_prediction_features,
        predict=trainer.predict,
    )


def _trainer_contract(
    trainer: PluginTrainer,
) -> BaseTrainer[FeatureArray, TargetArray, Pipeline, PredictionArray]:
    return trainer
