"""Sensor data platform API schemas."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StringConstraints

from app.models.sensor_data import ReadingQuality, ReadingSource, UploadJobStatus

UploadFilename = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class SensorReadingSortField(StrEnum):
    """Sensor reading sortable fields."""

    TIMESTAMP = "timestamp"
    CREATED_AT = "created_at"
    VALUE = "value"


class UploadJobSortField(StrEnum):
    """Upload job sortable fields."""

    CREATED_AT = "created_at"
    STARTED_AT = "started_at"
    FINISHED_AT = "finished_at"
    FILENAME = "filename"
    STATUS = "status"


class UploadJobCreate(BaseModel):
    """Upload job creation request."""

    model_config = ConfigDict(frozen=True)

    filename: UploadFilename
    source: ReadingSource = ReadingSource.CSV


class UploadJobResponse(BaseModel):
    """Upload job response."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    filename: str
    source: ReadingSource
    status: UploadJobStatus
    total_rows: int = Field(ge=0)
    valid_rows: int = Field(ge=0)
    invalid_rows: int = Field(ge=0)
    started_at: datetime | None
    finished_at: datetime | None
    created_by: UUID
    created_at: datetime


class SensorReadingCreate(BaseModel):
    """Sensor reading creation request."""

    model_config = ConfigDict(frozen=True)

    sensor_id: UUID
    timestamp: datetime
    value: FiniteFloat
    quality: ReadingQuality = ReadingQuality.GOOD
    source: ReadingSource = ReadingSource.API
    batch_id: UUID | None = Field(default=None)


class SensorReadingResponse(BaseModel):
    """Sensor reading response."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    sensor_id: UUID
    timestamp: datetime
    value: float
    quality: ReadingQuality
    source: ReadingSource
    batch_id: UUID | None
    created_at: datetime
