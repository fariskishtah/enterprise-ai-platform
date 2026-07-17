"""Feature engineering API schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FeatureDatasetExportRequest(BaseModel):
    """Feature dataset export request."""

    model_config = ConfigDict(frozen=True)

    sensor_id: UUID | None = Field(default=None)
    timestamp_from: datetime | None = Field(default=None)
    timestamp_to: datetime | None = Field(default=None)


class FeatureDatasetExportResponse(BaseModel):
    """Feature dataset export response."""

    model_config = ConfigDict(frozen=True)

    dataset_name: str
    version: int = Field(ge=1)
    file_path: str
    rows: int = Field(ge=0)
    columns: int = Field(ge=1)
    created_at: datetime
