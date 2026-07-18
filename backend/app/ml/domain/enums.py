"""Enumerations shared by AI domain models."""

from enum import StrEnum


class AlgorithmType(StrEnum):
    """Algorithms supported by the AI Core domain."""

    RANDOM_FOREST = "random_forest"
    XGBOOST = "xgboost"
    LIGHTGBM = "lightgbm"
    CATBOOST = "catboost"


class TaskType(StrEnum):
    """Initial machine-learning task families supported by AI Core."""

    REGRESSION = "regression"
    CLASSIFICATION = "classification"


class ModelStatus(StrEnum):
    """Lifecycle states for an AI model."""

    CREATED = "created"
    TRAINING = "training"
    TRAINED = "trained"
    FAILED = "failed"
    DEPLOYED = "deployed"
    ARCHIVED = "archived"
