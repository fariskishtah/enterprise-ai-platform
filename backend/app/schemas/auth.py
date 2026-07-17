"""Authentication API schemas."""

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.utils.passwords import validate_password_strength


class RegisterRequest(BaseModel):
    """Registration request body."""

    model_config = ConfigDict(frozen=True)

    email: EmailStr
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


class RefreshTokenRequest(BaseModel):
    """Refresh token request body."""

    model_config = ConfigDict(frozen=True)

    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    """Logout request body."""

    model_config = ConfigDict(frozen=True)

    refresh_token: str = Field(min_length=1)


class TokenResponse(BaseModel):
    """JWT token pair response."""

    model_config = ConfigDict(frozen=True)

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
