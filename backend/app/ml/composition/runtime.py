"""Shared explicit construction for API and worker AI integrations."""

from pathlib import Path

from app.config.settings import Settings
from app.ml.artifacts import LocalArtifactManager
from app.ml.composition.plugins import PLUGIN_TRAINER_REGISTRATIONS
from app.ml.engine import TrainingEngine
from app.ml.factory import TrainerFactory, TrainerRegistry
from app.ml.registry import MLflowModelRegistry
from app.ml.services import TrackedTrainingService
from app.ml.tracking import MLflowExperimentTracker
from app.ml.trainers.random_forest import (
    RANDOM_FOREST_CLASSIFIER_REGISTRATION,
    RANDOM_FOREST_REGRESSOR_REGISTRATION,
)


def create_ai_trainer_registry() -> TrainerRegistry:
    """Return a fresh registry containing the explicit supported trainers."""
    registry = TrainerRegistry()
    registry.register(RANDOM_FOREST_REGRESSOR_REGISTRATION)
    registry.register(RANDOM_FOREST_CLASSIFIER_REGISTRATION)
    for registration in PLUGIN_TRAINER_REGISTRATIONS.values():
        registry.register(registration)
    return registry


def create_ai_model_registry(settings: Settings) -> MLflowModelRegistry:
    """Return the configured fitted-model registry adapter."""
    return MLflowModelRegistry(tracking_uri=settings.mlflow_tracking_uri)


def create_ai_tracked_training_service(
    settings: Settings,
    *,
    model_registry: MLflowModelRegistry | None = None,
) -> TrackedTrainingService:
    """Construct the complete tracked-training graph without FastAPI dependencies."""
    registry = create_ai_trainer_registry()
    resolved_model_registry = model_registry or create_ai_model_registry(settings)
    return TrackedTrainingService(
        training_engine=TrainingEngine(
            trainer_factory=TrainerFactory(registry),
            artifact_manager=LocalArtifactManager(Path(settings.ai_artifact_root)),
        ),
        experiment_tracker=MLflowExperimentTracker(
            tracking_uri=settings.mlflow_tracking_uri,
        ),
        model_registry=resolved_model_registry,
    )
