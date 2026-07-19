"""Prediction domain models."""

from pydantic import BaseModel, ConfigDict, Field


class PredictionRequest(BaseModel):
    """Input required to request predictions from a model version."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    model_version: str = Field(
        min_length=1,
        description="Version of the model used for prediction.",
    )
    # TODO: Replace with a strongly typed feature-domain object.
    features: dict[str, object] = Field(
        description="Feature values supplied to the model.",
    )


class PredictionResult(BaseModel):
    """Raw predictions and timing returned by model inference."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    # TODO: Introduce task-specific outputs for classification and regression.
    predictions: list[float] = Field(description="Raw numeric model predictions.")
    inference_time_ms: float = Field(
        ge=0,
        description="Total inference duration in milliseconds.",
    )
