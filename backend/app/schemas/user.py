"""User API schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.user import UserRole


class UserResponse(BaseModel):
    """Public user representation."""

    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    company_id: UUID
    email: EmailStr
    full_name: str | None
    role: UserRole
    is_active: bool
    is_email_verified: bool
    email_verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserListResponse(BaseModel):
    items: list[UserResponse]
    total: int
    limit: int
    offset: int


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    password: str = Field(min_length=12, max_length=128)
    role: UserRole

    @field_validator("password")
    @classmethod
    def strong_password(cls, value: str) -> str:
        from app.utils.passwords import validate_password_strength

        validate_password_strength(value)
        return value


class UserUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: UserRole | None = None
    is_active: bool | None = None


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=12, max_length=128)

    @field_validator("new_password")
    @classmethod
    def strong_new_password(cls, value: str) -> str:
        from app.utils.passwords import validate_password_strength

        validate_password_strength(value)
        return value


class SessionResponse(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime | None
    user_agent_summary: str | None
    source_ip: str | None


class SessionListResponse(BaseModel):
    items: list[SessionResponse]
