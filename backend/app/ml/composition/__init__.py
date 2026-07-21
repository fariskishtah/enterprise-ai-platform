"""Explicit typed composition helpers for local AI execution plans."""

from app.ml.composition.plugins import (
    PLUGIN_REGISTRY,
    create_plugin_prediction_plan,
    create_plugin_training_plan,
)
from app.ml.composition.random_forest import (
    create_random_forest_classification_plan,
    create_random_forest_classification_prediction_plan,
    create_random_forest_regression_plan,
    create_random_forest_regression_prediction_plan,
)
from app.ml.composition.runtime import (
    create_ai_model_registry,
    create_ai_tracked_training_service,
    create_ai_trainer_registry,
)

__all__ = [
    "create_ai_model_registry",
    "create_ai_tracked_training_service",
    "create_ai_trainer_registry",
    "create_plugin_training_plan",
    "create_plugin_prediction_plan",
    "create_random_forest_classification_prediction_plan",
    "create_random_forest_classification_plan",
    "create_random_forest_regression_prediction_plan",
    "create_random_forest_regression_plan",
    "PLUGIN_REGISTRY",
]
