"""Manufacturing domain API schemas."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

EntityName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
OptionalText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1000),
]
OptionalShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]


class CompanySortField(StrEnum):
    """Company sortable fields."""

    NAME = "name"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class FactorySortField(StrEnum):
    """Factory sortable fields."""

    NAME = "name"
    LOCATION = "location"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class MachineSortField(StrEnum):
    """Machine sortable fields."""

    NAME = "name"
    SERIAL_NUMBER = "serial_number"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class _PatchModel(BaseModel):
    """Validation shared by PATCH request models."""

    @model_validator(mode="after")
    def require_fields(self) -> Self:
        """Require at least one field to update."""
        if not self.model_fields_set:
            msg = "At least one field must be provided."
            raise ValueError(msg)
        return self


class CompanyCreate(BaseModel):
    """Company creation request."""

    model_config = ConfigDict(frozen=True)

    name: EntityName
    description: OptionalText | None = Field(default=None)


class CompanyUpdate(_PatchModel):
    """Company update request."""

    name: EntityName | None = Field(default=None)
    description: OptionalText | None = Field(default=None)

    @model_validator(mode="after")
    def reject_null_name(self) -> Self:
        """Reject explicit null for non-nullable fields."""
        if "name" in self.model_fields_set and self.name is None:
            msg = "Name cannot be null."
            raise ValueError(msg)
        return self


class CompanyResponse(BaseModel):
    """Company response."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class FactoryCreate(BaseModel):
    """Factory creation request."""

    model_config = ConfigDict(frozen=True)

    company_id: UUID
    name: EntityName
    location: OptionalShortText | None = Field(default=None)
    description: OptionalText | None = Field(default=None)


class FactoryUpdate(_PatchModel):
    """Factory update request."""

    company_id: UUID | None = Field(default=None)
    name: EntityName | None = Field(default=None)
    location: OptionalShortText | None = Field(default=None)
    description: OptionalText | None = Field(default=None)

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> Self:
        """Reject explicit null for non-nullable fields."""
        if "company_id" in self.model_fields_set and self.company_id is None:
            msg = "Company ID cannot be null."
            raise ValueError(msg)
        if "name" in self.model_fields_set and self.name is None:
            msg = "Name cannot be null."
            raise ValueError(msg)
        return self


class FactoryResponse(BaseModel):
    """Factory response."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    company_id: UUID
    name: str
    location: str | None
    description: str | None
    created_at: datetime
    updated_at: datetime


class MachineCreate(BaseModel):
    """Machine creation request."""

    model_config = ConfigDict(frozen=True)

    factory_id: UUID
    name: EntityName
    serial_number: OptionalShortText | None = Field(default=None)
    manufacturer: OptionalShortText | None = Field(default=None)
    model: OptionalShortText | None = Field(default=None)


class MachineUpdate(_PatchModel):
    """Machine update request."""

    factory_id: UUID | None = Field(default=None)
    name: EntityName | None = Field(default=None)
    serial_number: OptionalShortText | None = Field(default=None)
    manufacturer: OptionalShortText | None = Field(default=None)
    model: OptionalShortText | None = Field(default=None)

    @model_validator(mode="after")
    def reject_null_required_fields(self) -> Self:
        """Reject explicit null for non-nullable fields."""
        if "factory_id" in self.model_fields_set and self.factory_id is None:
            msg = "Factory ID cannot be null."
            raise ValueError(msg)
        if "name" in self.model_fields_set and self.name is None:
            msg = "Name cannot be null."
            raise ValueError(msg)
        return self


class MachineResponse(BaseModel):
    """Machine response."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    factory_id: UUID
    name: str
    serial_number: str | None
    manufacturer: str | None
    model: str | None
    created_at: datetime
    updated_at: datetime
