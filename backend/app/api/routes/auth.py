"""Authentication routes."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.dependencies.rate_limit import enforce_auth_rate_limit
from app.dependencies.services import get_authentication_service
from app.observability.logging import emit_safe
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.user import UserResponse
from app.services.authentication import AuthenticationService
from app.services.exceptions import (
    DuplicateEmailError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
)

router = APIRouter(prefix="/auth", tags=["auth"])
security_logger = logging.getLogger("app.security.audit")

_RATE_LIMIT_RESPONSE = {
    "description": "Authentication request rate limit exceeded.",
    "headers": {
        "Retry-After": {
            "description": "Seconds until this client can retry.",
            "schema": {"type": "integer", "minimum": 1, "maximum": 3600},
        }
    },
}


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register an operator user",
    responses={
        status.HTTP_429_TOO_MANY_REQUESTS: _RATE_LIMIT_RESPONSE,
        status.HTTP_409_CONFLICT: {"description": "Email is already registered."},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "Invalid email or weak password.",
        },
    },
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def register(
    payload: RegisterRequest,
    authentication_service: Annotated[
        AuthenticationService,
        Depends(get_authentication_service),
    ],
) -> UserResponse:
    """Register a new operator user."""
    try:
        user = await authentication_service.register(
            email=payload.email,
            password=payload.password,
        )
    except DuplicateEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered.",
        ) from exc
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and issue JWTs",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid credentials."},
        status.HTTP_429_TOO_MANY_REQUESTS: _RATE_LIMIT_RESPONSE,
    },
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def login(
    payload: LoginRequest,
    authentication_service: Annotated[
        AuthenticationService,
        Depends(get_authentication_service),
    ],
) -> TokenResponse:
    """Authenticate a user and issue access and refresh tokens."""
    try:
        tokens = await authentication_service.login(
            email=payload.email,
            password=payload.password,
        )
    except InvalidCredentialsError as exc:
        emit_safe(
            security_logger,
            logging.WARNING,
            "security_audit",
            extra={
                "audit_event": "login",
                "outcome": "failure",
                "reason": "invalid_credentials",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except InactiveUserError as exc:
        emit_safe(
            security_logger,
            logging.WARNING,
            "security_audit",
            extra={
                "audit_event": "login",
                "outcome": "failure",
                "reason": "invalid_credentials",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    emit_safe(
        security_logger,
        logging.INFO,
        "security_audit",
        extra={"audit_event": "login", "outcome": "success"},
    )
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate refresh token and issue JWTs",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid refresh token."},
        status.HTTP_403_FORBIDDEN: {"description": "User account is inactive."},
        status.HTTP_429_TOO_MANY_REQUESTS: _RATE_LIMIT_RESPONSE,
    },
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def refresh(
    payload: RefreshTokenRequest,
    authentication_service: Annotated[
        AuthenticationService,
        Depends(get_authentication_service),
    ],
) -> TokenResponse:
    """Rotate a refresh token and issue a new access token."""
    try:
        tokens = await authentication_service.refresh(
            refresh_token=payload.refresh_token,
        )
    except InvalidRefreshTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is invalid.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except InactiveUserError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive.",
        ) from exc

    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a refresh token",
    responses={
        status.HTTP_204_NO_CONTENT: {"description": "Refresh token revoked."},
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid refresh token."},
    },
)
async def logout(
    payload: LogoutRequest,
    authentication_service: Annotated[
        AuthenticationService,
        Depends(get_authentication_service),
    ],
) -> Response:
    """Revoke a refresh token."""
    try:
        await authentication_service.logout(refresh_token=payload.refresh_token)
    except InvalidRefreshTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is invalid.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return Response(status_code=status.HTTP_204_NO_CONTENT)
