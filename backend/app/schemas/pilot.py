"""Governed feature input and operator pilot API contracts."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ml.domain import TaskType


class FeatureDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9_]*$")
    data_type: Literal["float", "integer"]
    required: bool = True
    unit: str | None = Field(default=None, max_length=32)
    minimum: float | None = None
    maximum: float | None = None
    missing_value_behavior: Literal["reject", "use_training_imputer"] = "reject"
    categorical_encoding: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def valid_range(self) -> "FeatureDefinition":
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("Feature minimum cannot exceed maximum.")
        return self


class FeatureSchemaUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    features: list[FeatureDefinition] = Field(min_length=1, max_length=256)
    algorithm: str = Field(min_length=3, max_length=64)
    task_type: TaskType
    target_name: str | None = Field(default=None, max_length=128)
    target_unit: str | None = Field(default=None, max_length=32)
    training_dataset_version_id: UUID | None = None

    @model_validator(mode="after")
    def unique_features(self) -> "FeatureSchemaUpsertRequest":
        names = [item.name for item in self.features]
        if len(names) != len(set(names)):
            raise ValueError("Feature names must be unique.")
        return self


class FeatureSchemaResponse(BaseModel):
    id: UUID
    company_id: UUID
    registered_model_name: str
    model_version: str
    features: list[FeatureDefinition]
    algorithm: str
    task_type: TaskType
    target_name: str | None
    target_unit: str | None
    training_dataset_version_id: UUID | None
    created_by_user_id: UUID
    created_at: datetime


class StructuredPredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, int | float | None]
    machine_id: UUID | None = None


class StructuredPredictionResponse(BaseModel):
    model_name: str
    model_version: str
    prediction: int | float
    feature_order: list[str]
    assessment_id: UUID | None = None
    risk_state: str | None = None


class MachineRiskResponse(BaseModel):
    id: UUID
    company_id: UUID
    factory_id: UUID
    machine_id: UUID
    prediction_event_id: UUID | None
    alert_id: UUID | None
    registered_model_name: str
    model_version: str
    risk_state: str
    risk_score: float | None
    sensor_values: list[dict[str, object]]
    data_freshness_seconds: float | None
    recommended_action: str
    monitoring_status: str
    assessed_at: datetime
    acknowledged_at: datetime | None
    acknowledged_by_user_id: UUID | None


class MachineRiskAcknowledgeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operator_note: str | None = Field(default=None, max_length=1000)
