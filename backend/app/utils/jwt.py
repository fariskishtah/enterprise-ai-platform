"""JWT creation and decoding utilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

import jwt
from pydantic import BaseModel, ConfigDict, ValidationError

from app.models.user import UserRole
from app.utils.security import utc_now


class TokenType(StrEnum):
    """Supported JWT token purposes."""

    ACCESS = "access"
    REFRESH = "refresh"


class TokenDecodeError(ValueError):
    """Raised when a JWT cannot be decoded or validated."""


class TokenClaims(BaseModel):
    """Validated JWT claims."""

    model_config = ConfigDict(frozen=True)

    sub: UUID
    jti: UUID
    typ: TokenType
    exp: int
    iat: int
    email: str | None = None
    role: UserRole | None = None


@dataclass(frozen=True)
class CreatedToken:
    """JWT plus server-side metadata needed for persistence."""

    token: str
    jti: UUID
    expires_in: int


def create_jwt_token(
    *,
    subject: UUID,
    token_type: TokenType,
    secret_key: str,
    algorithm: str,
    expires_delta: timedelta,
    additional_claims: dict[str, str] | None = None,
) -> CreatedToken:
    """Create a signed JWT."""
    now = utc_now()
    expires_at = now + expires_delta
    jti = uuid4()
    payload: dict[str, Any] = {
        "sub": str(subject),
        "jti": str(jti),
        "typ": token_type.value,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    if additional_claims is not None:
        payload.update(additional_claims)

    token = jwt.encode(payload, secret_key, algorithm=algorithm)
    return CreatedToken(
        token=token,
        jti=jti,
        expires_in=int(expires_delta.total_seconds()),
    )


def decode_jwt_token(
    *,
    token: str,
    secret_key: str,
    algorithm: str,
    expected_type: TokenType,
) -> TokenClaims:
    """Decode and validate a signed JWT."""
    try:
        payload = jwt.decode(token, secret_key, algorithms=[algorithm])
        claims = TokenClaims.model_validate(payload)
    except (jwt.PyJWTError, ValidationError) as exc:
        msg = "Invalid authentication token."
        raise TokenDecodeError(msg) from exc

    if claims.typ != expected_type:
        msg = "Authentication token has an invalid purpose."
        raise TokenDecodeError(msg)

    return claims
