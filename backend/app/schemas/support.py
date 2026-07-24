"""Bounded authenticated support request contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from app.models.support import SupportRequestStatus

BoundedSubject = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=3, max_length=160)
]
BoundedMessage = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=10, max_length=5000)
]


class SupportCategory(StrEnum):
    TECHNICAL_PROBLEM = "technical_problem"
    DATA_IMPORT = "data_import"
    TRAINING = "training"
    PREDICTIONS = "predictions"
    ALERTS_AND_OPERATIONS = "alerts_and_operations"
    REPORTS = "reports"
    ACCOUNT_ACCESS = "account_access"
    OTHER = "other"


class SupportRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: BoundedSubject
    category: SupportCategory
    message: BoundedMessage
    current_page: str = Field(min_length=1, max_length=500)
    factory_id: UUID | None = None
    machine_id: UUID | None = None
    idempotency_key: str = Field(
        min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
    )

    @field_validator("subject")
    @classmethod
    def single_line_subject(cls, value: str) -> str:
        if "\r" in value or "\n" in value:
            raise ValueError("Subject must be a single line.")
        return value

    @field_validator("current_page")
    @classmethod
    def relative_current_page(cls, value: str) -> str:
        value = value.strip()
        if not value.startswith("/") or value.startswith("//"):
            raise ValueError("Current page must be an application-relative path.")
        return value


class SupportRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    category: str
    subject: str
    current_page: str
    factory_id: UUID | None
    machine_id: UUID | None
    status: SupportRequestStatus
    delivery_attempts: int
    created_at: datetime
    updated_at: datetime
    delivered_at: datetime | None
    delivery_message: str


class SupportRequestListResponse(BaseModel):
    items: list[SupportRequestResponse]
    total: int
    limit: int
    offset: int
