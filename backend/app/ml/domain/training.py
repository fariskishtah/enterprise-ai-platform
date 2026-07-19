"""Training workflow domain models."""

from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.ml.domain.enums import AlgorithmType


class TrainingRequest(BaseModel):
    """Input required to start a model training workflow."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    experiment_id: UUID = Field(description="Experiment that owns the training run.")
    algorithm: AlgorithmType = Field(description="Algorithm to train.")
    target_column: str = Field(
        min_length=1,
        description="Dataset column the model will predict.",
    )
    feature_columns: list[str] = Field(
        min_length=1,
        description="Dataset columns used as model inputs.",
    )
    # TODO: Replace with a strongly typed hyperparameter-domain object.
    hyperparameters: dict[str, object] = Field(
        description="Algorithm hyperparameters for the training run.",
    )
    random_seed: int | None = Field(
        default=None,
        description="Optional seed used to make training reproducible.",
    )


class TrainingResult(BaseModel):
    """Result produced by the complete model training workflow."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    success: bool = Field(description="Whether the training workflow succeeded.")
    model_version: str | None = Field(
        default=None,
        min_length=1,
        description="Version assigned to the trained model, when available.",
    )
    # TODO: Replace with a strongly typed MetricsReport.
    metrics: dict[str, float] = Field(
        description="Evaluation metrics produced by the training workflow.",
    )
    artifact_path: Path | None = Field(
        default=None,
        description="Location of the model artifact, when available.",
    )
    duration_seconds: float = Field(
        ge=0,
        description="Total training workflow duration in seconds.",
    )
    error_message: str | None = Field(
        default=None,
        description="Failure details when the training workflow does not succeed.",
    )
