"""MLOps experiment management API schemas."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StringConstraints,
    model_validator,
)

from app.models.mlops import TrainingRunStatus
from app.utils.json_validation import ensure_json_serializable

MLOpsName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
MLOpsShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]
MLOpsDescription = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]
ArtifactPath = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1024),
]
Sha256Checksum = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[A-Fa-f0-9]{64}$"),
]


class ExperimentSortField(StrEnum):
    """Experiment sortable fields."""

    NAME = "name"
    CREATED_AT = "created_at"


class TrainingRunSortField(StrEnum):
    """Training run sortable fields."""

    STARTED_AT = "started_at"
    FINISHED_AT = "finished_at"
    DATASET_VERSION = "dataset_version"
    ALGORITHM = "algorithm"
    STATUS = "status"


class ModelArtifactSortField(StrEnum):
    """Model artifact sortable fields."""

    FRAMEWORK = "framework"
    MODEL_TYPE = "model_type"
    VERSION = "version"


class ExperimentCreate(BaseModel):
    """Experiment creation request."""

    model_config = ConfigDict(frozen=True)

    name: MLOpsName
    description: MLOpsDescription | None = Field(default=None)


class ExperimentResponse(BaseModel):
    """Experiment response."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    name: str
    description: str | None
    created_by: UUID
    created_at: datetime


class TrainingRunCreate(BaseModel):
    """Training run creation request."""

    model_config = ConfigDict(frozen=True)

    dataset_version: MLOpsShortText
    algorithm: MLOpsShortText
    parameters: dict[str, object] = Field(default_factory=dict)
    metrics: dict[str, FiniteFloat] = Field(default_factory=dict)
    status: TrainingRunStatus = TrainingRunStatus.PENDING
    started_at: datetime | None = Field(default=None)
    finished_at: datetime | None = Field(default=None)

    @model_validator(mode="after")
    def validate_run_payload(self) -> Self:
        """Validate JSON payload and timestamp ordering."""
        ensure_json_serializable(self.parameters, field_name="parameters")
        ensure_json_serializable(self.metrics, field_name="metrics")
        if self.finished_at is not None and self.started_at is None:
            msg = "started_at is required when finished_at is provided."
            raise ValueError(msg)
        if (
            self.started_at is not None
            and self.finished_at is not None
            and self.finished_at < self.started_at
        ):
            msg = "finished_at must be greater than or equal to started_at."
            raise ValueError(msg)
        return self


class TrainingRunResponse(BaseModel):
    """Training run response."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    experiment_id: UUID
    dataset_version: str
    algorithm: str
    parameters: dict[str, object]
    metrics: dict[str, float]
    status: TrainingRunStatus
    started_at: datetime
    finished_at: datetime | None


class ModelArtifactCreate(BaseModel):
    """Model artifact registration request."""

    model_config = ConfigDict(frozen=True)

    framework: MLOpsShortText
    model_type: MLOpsShortText
    version: MLOpsShortText
    artifact_path: ArtifactPath
    checksum: Sha256Checksum


class ModelArtifactResponse(BaseModel):
    """Model artifact response."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    training_run_id: UUID
    framework: str
    model_type: str
    version: str
    artifact_path: str
    checksum: str
