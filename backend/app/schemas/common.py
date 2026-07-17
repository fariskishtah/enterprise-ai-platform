"""Shared API schemas and query enums."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SortOrder(StrEnum):
    """Supported list sort orders."""

    ASC = "asc"
    DESC = "desc"


class PaginatedResponse[T](BaseModel):
    """Consistent paginated API response."""

    model_config = ConfigDict(frozen=True)

    items: list[T]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
