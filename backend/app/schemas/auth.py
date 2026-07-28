"""Authentication API schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.schemas.user import UserResponse
from app.utils.passwords import validate_password_strength
from app.utils.safe_text import ensure_safe_single_line


class RegisterRequest(BaseModel):
    """Registration request body."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    email: EmailStr
    name: str = Field(min_length=2, max_length=160)
    company_name: str = Field(min_length=2, max_length=255)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        """Normalize email addresses before service-layer uniqueness checks."""
        return str(value).strip().lower()

    @field_validator("password", mode="after")
    @classmethod
    def validate_password(cls, value: str) -> str:
        """Validate password strength for new users."""
        validate_password_strength(value)
        return value

    @field_validator("name", "company_name", mode="after")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Value must contain at least 2 non-whitespace characters.")
        ensure_safe_single_line(normalized)
        return normalized


class RegistrationResponse(UserResponse):
    """New account state with an optional local-only verification credential."""

    local_verification_token: str | None = None


class LoginRequest(BaseModel):
    """Login request body."""

    model_config = ConfigDict(frozen=True)

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email", mode="after")
    @classmethod
    def normalize_email(cls, value: EmailStr) -> str:
        """Normalize email addresses before authentication."""
        return str(value).strip().lower()


class TokenResponse(BaseModel):
    """Short-lived access credential response."""

    model_config = ConfigDict(frozen=True)

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class PasswordResetRequestResponse(BaseModel):
    message: str
    local_reset_token: str | None = None


class PasswordResetCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=32, max_length=512)
    new_password: str = Field(min_length=12, max_length=128)

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        validate_password_strength(value)
        return value


class EmailVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=32, max_length=512)


class EmailVerificationResponse(BaseModel):
    status: Literal["verified", "already_verified"]
    message: str


class EmailVerificationStatusResponse(BaseModel):
    email: EmailStr
    is_verified: bool
    verified_at: datetime | None
    resend_available_in_seconds: int = Field(ge=0, le=3600)


class EmailVerificationResendResponse(BaseModel):
    message: str
    resend_available_in_seconds: int = Field(ge=0, le=3600)
    local_verification_token: str | None = None
