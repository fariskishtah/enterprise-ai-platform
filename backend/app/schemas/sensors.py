"""Sensor API schemas."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.manufacturing import EntityName, OptionalShortText, OptionalText

SensorUnit = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]


class SensorSortField(StrEnum):
    """Sensor sortable fields."""

    NAME = "name"
    SENSOR_TYPE = "sensor_type"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class SensorCreate(BaseModel):
    """Sensor creation request."""

    model_config = ConfigDict(frozen=True)

    machine_id: UUID
    name: EntityName
    sensor_type: OptionalShortText | None = Field(default=None)
    unit: SensorUnit | None = Field(default=None)
    sampling_rate: float = Field(gt=0)
    min_value: float
    max_value: float
    description: OptionalText | None = Field(default=None)

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        """Validate configured sensor range."""
        if self.min_value >= self.max_value:
            msg = "Minimum value must be less than maximum value."
            raise ValueError(msg)
        return self


class SensorUpdate(BaseModel):
    """Sensor update request."""

    machine_id: UUID | None = Field(default=None)
    name: EntityName | None = Field(default=None)
    sensor_type: OptionalShortText | None = Field(default=None)
    unit: SensorUnit | None = Field(default=None)
    sampling_rate: float | None = Field(default=None, gt=0)
    min_value: float | None = Field(default=None)
    max_value: float | None = Field(default=None)
    description: OptionalText | None = Field(default=None)

    @model_validator(mode="after")
    def validate_update(self) -> Self:
        """Validate update payload shape and explicit nulls."""
        if not self.model_fields_set:
            msg = "At least one field must be provided."
            raise ValueError(msg)
        required_fields = (
            "machine_id",
            "name",
            "sampling_rate",
            "min_value",
            "max_value",
        )
        for field_name in required_fields:
            if (
                field_name in self.model_fields_set
                and getattr(self, field_name) is None
            ):
                msg = f"{field_name} cannot be null."
                raise ValueError(msg)
        if (
            "min_value" in self.model_fields_set
            and "max_value" in self.model_fields_set
            and self.min_value is not None
            and self.max_value is not None
            and self.min_value >= self.max_value
        ):
            msg = "Minimum value must be less than maximum value."
            raise ValueError(msg)
        return self


class SensorResponse(BaseModel):
    """Sensor response."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    machine_id: UUID
    name: str
    sensor_type: str | None
    unit: str | None
    sampling_rate: float
    min_value: float
    max_value: float
    description: str | None
    created_at: datetime
    updated_at: datetime
