"""Team invitation API schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.user import UserRole
from app.schemas.user import UserResponse
from app.utils.passwords import validate_password_strength


class InvitationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: UserRole


class InvitationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    company_id: UUID
    invited_email: EmailStr
    role: UserRole
    inviter_user_id: UUID
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    last_sent_at: datetime
    send_count: int
    created_at: datetime
    local_invitation_token: str | None = None


class InvitationListResponse(BaseModel):
    items: list[InvitationResponse]
    total: int
    limit: int
    offset: int


class InvitationAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=32, max_length=512)
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    password: str | None = Field(default=None, min_length=12, max_length=128)

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str | None) -> str | None:
        if value is not None:
            validate_password_strength(value)
        return value


class InvitationAcceptResponse(BaseModel):
    status: str = "accepted"
    user: UserResponse
