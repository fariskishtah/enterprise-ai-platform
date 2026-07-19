"""Model context domain models."""

from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.ml.domain.enums import AlgorithmType, ModelStatus


class ModelContext(BaseModel):
    """Metadata and lifecycle context for a versioned model."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    model_name: str = Field(
        min_length=1,
        description="Human-readable model name.",
    )
    model_version: str = Field(
        min_length=1,
        description="Version identifier for the model.",
    )
    algorithm: AlgorithmType = Field(description="Algorithm used by the model.")
    status: ModelStatus = Field(description="Current model lifecycle status.")
    created_at: datetime = Field(description="Time when the model context was created.")
    trained_at: datetime | None = Field(
        default=None,
        description="Time when model training completed, when available.",
    )
    # TODO: Replace with a strongly typed MetricsReport.
    metrics: dict[str, float] = Field(
        description="Evaluation metrics associated with the model.",
    )
    # TODO: Replace with a strongly typed parameter-domain object.
    parameters: dict[str, object] = Field(
        description="Parameters used to train the model.",
    )
    artifact_location: Path | None = Field(
        default=None,
        description="Location of the model artifact, when available.",
    )
