"""Authentication routes."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.config.settings import Settings, get_settings
from app.dependencies.rate_limit import enforce_auth_rate_limit
from app.dependencies.services import (
    get_audit_service,
    get_authentication_service,
    get_user_service,
)
from app.observability.logging import emit_safe
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    PasswordResetCompleteRequest,
    PasswordResetRequest,
    PasswordResetRequestResponse,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.user import UserResponse
from app.services.audit import AuditService
from app.services.authentication import AuthenticationService
from app.services.exceptions import (
    DuplicateEmailError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidPasswordResetTokenError,
    InvalidRefreshTokenError,
)
from app.services.users import UserService

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
    audit: Annotated[AuditService, Depends(get_audit_service)],
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
    await audit.record(
        company_id=user.company_id,
        actor=user,
        action="user.registered",
        resource_type="user",
        resource_id=user.id,
        result="success",
    )
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
    request: Request,
    authentication_service: Annotated[
        AuthenticationService,
        Depends(get_authentication_service),
    ],
    users: Annotated[UserService, Depends(get_user_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> TokenResponse:
    """Authenticate a user and issue access and refresh tokens."""
    try:
        tokens = await authentication_service.login(
            email=payload.email,
            password=payload.password,
            user_agent=request.headers.get("user-agent"),
            source_ip=request.client.host if request.client else None,
        )
    except InvalidCredentialsError as exc:
        known_user = await users.get_by_email(str(payload.email))
        if known_user is not None:
            await audit.record(
                company_id=known_user.company_id,
                actor=known_user,
                action="auth.login",
                resource_type="session",
                result="failure",
                source_ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                metadata={"reason": "invalid_credentials"},
            )
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
        known_user = await users.get_by_email(str(payload.email))
        if known_user is not None:
            await audit.record(
                company_id=known_user.company_id,
                actor=known_user,
                action="auth.login",
                resource_type="session",
                result="failure",
                source_ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                metadata={"reason": "inactive_or_invalid_credentials"},
            )
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
    await audit.record(
        company_id=tokens.user.company_id,
        actor=tokens.user,
        action="auth.login",
        resource_type="session",
        result="success",
        source_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
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
    audit: Annotated[AuditService, Depends(get_audit_service)],
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

    await audit.record(
        company_id=tokens.user.company_id,
        actor=tokens.user,
        action="auth.refresh_rotated",
        resource_type="session",
        result="success",
    )
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
    request: Request,
    authentication_service: Annotated[
        AuthenticationService,
        Depends(get_authentication_service),
    ],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> Response:
    """Revoke a refresh token."""
    try:
        user = await authentication_service.logout(refresh_token=payload.refresh_token)
    except InvalidRefreshTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is invalid.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    await audit.record(
        company_id=user.company_id,
        actor=user,
        action="auth.logout",
        resource_type="session",
        result="success",
        source_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password-reset/request",
    response_model=PasswordResetRequestResponse,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def request_password_reset(
    payload: PasswordResetRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    users: Annotated[UserService, Depends(get_user_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> PasswordResetRequestResponse:
    """Create a privacy-safe reset request without revealing account existence."""
    user, token = await users.initiate_password_reset(
        email=str(payload.email),
        expiry_minutes=settings.password_reset_expire_minutes,
    )
    if user is not None:
        await audit.record(
            company_id=user.company_id,
            actor=None,
            action="password.reset_requested",
            resource_type="user",
            resource_id=user.id,
            result="success",
        )
        emit_safe(
            security_logger,
            logging.INFO,
            "password_reset_delivery_requested",
            extra={"delivery": "redacted", "outcome": "accepted"},
        )
    expose = settings.expose_local_password_reset_token and settings.environment in {
        "local",
        "development",
        "test",
    }
    return PasswordResetRequestResponse(
        message="If the account exists, password reset instructions are available.",
        local_reset_token=token if expose else None,
    )


@router.post("/password-reset/complete", status_code=status.HTTP_204_NO_CONTENT)
async def complete_password_reset(
    payload: PasswordResetCompleteRequest,
    users: Annotated[UserService, Depends(get_user_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> Response:
    try:
        user = await users.complete_password_reset(
            token=payload.token, new_password=payload.new_password
        )
    except InvalidPasswordResetTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Password reset token is invalid or expired.",
        ) from exc
    await audit.record(
        company_id=user.company_id,
        actor=user,
        action="password.reset_completed",
        resource_type="user",
        resource_id=user.id,
        result="success",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
