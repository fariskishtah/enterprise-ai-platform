"""Authentication routes."""

import logging
from contextlib import suppress
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.dependencies.auth import get_current_user
from app.dependencies.database import get_db_session
from app.dependencies.rate_limit import (
    enforce_auth_rate_limit,
    enforce_mutation_rate_limit,
)
from app.dependencies.services import (
    get_audit_service,
    get_authentication_service,
    get_transactional_email_queue,
    get_user_service,
)
from app.email.queue import TransactionalEmailQueue
from app.models.email import EmailMessageType
from app.models.user import User
from app.observability.logging import emit_safe
from app.schemas.auth import (
    EmailVerificationRequest,
    EmailVerificationResendResponse,
    EmailVerificationResponse,
    EmailVerificationStatusResponse,
    LoginRequest,
    PasswordResetCompleteRequest,
    PasswordResetRequest,
    PasswordResetRequestResponse,
    RegisterRequest,
    RegistrationResponse,
    TokenResponse,
)
from app.schemas.user import UserResponse
from app.security.cookie_auth import (
    clear_auth_cookies,
    issue_auth_cookies,
    require_cookie_auth,
)
from app.services.audit import AuditService
from app.services.authentication import AuthenticationService
from app.services.email import OutboundEmail, transactional_email
from app.services.email_delivery import persist_email
from app.services.exceptions import (
    AccountLifecycleError,
    DuplicateCompanyNameError,
    DuplicateEmailError,
    ExpiredEmailVerificationTokenError,
    ExpiredPasswordResetTokenError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidEmailVerificationTokenError,
    InvalidPasswordResetTokenError,
    InvalidRefreshTokenError,
    UsedEmailVerificationTokenError,
    UsedPasswordResetTokenError,
)
from app.services.users import UserService
from app.utils.security import hash_token

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


async def _persist_and_publish_email(
    *,
    session: AsyncSession,
    settings: Settings,
    queue: TransactionalEmailQueue,
    company_id: UUID,
    message_type: EmailMessageType,
    email: OutboundEmail,
    deduplication_key: str,
    related_resource_type: str,
    related_resource_id: UUID,
    encrypt_payload: bool = False,
) -> None:
    enqueued = await persist_email(
        session,
        company_id=company_id,
        message_type=message_type,
        email=email,
        provider=settings.email_provider,
        max_retries=settings.email_max_retries,
        deduplication_key=deduplication_key,
        related_resource_type=related_resource_type,
        related_resource_id=related_resource_id,
        payload_encryption_key=(
            settings.secret_key.get_secret_value() if encrypt_payload else None
        ),
    )
    await session.commit()
    if enqueued.created:
        with suppress(Exception):
            queue.enqueue(enqueued.message.id)


def _account_email(
    settings: Settings,
    *,
    message_type: EmailMessageType,
    recipient: str,
    intro: str,
    details: tuple[tuple[str, str], ...] = (),
    action_label: str | None = None,
    action_path: str | None = None,
    security_note: str | None = None,
) -> OutboundEmail | None:
    if settings.email_from is None:
        return None
    action_url = (
        f"{(settings.app_base_url or 'http://localhost:5173').rstrip('/')}{action_path}"
        if action_path is not None
        else None
    )
    return transactional_email(
        message_type,
        recipient=recipient,
        from_address=str(settings.email_from),
        from_name=settings.email_from_name,
        reply_to=(str(settings.email_reply_to) if settings.email_reply_to else None),
        intro=intro,
        details=details,
        action_label=action_label,
        action_url=action_url,
        security_note=security_note,
    )


@router.post(
    "/register",
    response_model=RegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a company workspace and its first administrator",
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
    users: Annotated[UserService, Depends(get_user_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    queue: Annotated[TransactionalEmailQueue, Depends(get_transactional_email_queue)],
) -> RegistrationResponse:
    """Create an isolated company and its server-assigned administrator."""
    try:
        user = await authentication_service.register(
            email=payload.email,
            password=payload.password,
            full_name=payload.name,
            company_name=payload.company_name,
        )
    except DuplicateEmailError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email is already registered.",
        ) from exc
    except DuplicateCompanyNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Company name is already registered.",
        ) from exc
    await audit.record(
        company_id=user.company_id,
        actor=user,
        action="user.registered",
        resource_type="user",
        resource_id=user.id,
        result="success",
    )
    token, entity, cooldown = await users.initiate_email_verification(
        user=user,
        expiry_hours=settings.email_verification_expire_hours,
        cooldown_seconds=settings.email_verification_resend_cooldown_seconds,
    )
    if token is not None and entity is not None:
        email = _account_email(
            settings,
            message_type=EmailMessageType.EMAIL_VERIFICATION,
            recipient=user.email,
            intro="Confirm that this email address belongs to you.",
            details=(
                ("Link expires", f"{settings.email_verification_expire_hours} hours"),
            ),
            action_label="Verify email",
            action_path=f"/verify-email?{urlencode({'token': token})}",
            security_note=(
                "If you did not create this FactoryMind workspace, you can ignore "
                "this email. Do not forward the verification link."
            ),
        )
        if email is not None:
            await _persist_and_publish_email(
                session=session,
                settings=settings,
                queue=queue,
                company_id=user.company_id,
                message_type=EmailMessageType.EMAIL_VERIFICATION,
                email=email,
                deduplication_key=f"email-verification:{entity.id}",
                related_resource_type="user",
                related_resource_id=user.id,
                encrypt_payload=True,
            )
        await audit.record(
            company_id=user.company_id,
            actor=user,
            action="email.verification_requested",
            resource_type="user",
            resource_id=user.id,
            result="success",
            metadata={"resend_available_in_seconds": cooldown},
        )
    expose = (
        settings.expose_local_email_verification_token
        and settings.environment
        in {
            "local",
            "development",
            "test",
        }
    )
    return RegistrationResponse(
        **UserResponse.model_validate(user).model_dump(),
        local_verification_token=token if expose else None,
    )


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
    response: Response,
    authentication_service: Annotated[
        AuthenticationService,
        Depends(get_authentication_service),
    ],
    users: Annotated[UserService, Depends(get_user_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse:
    """Authenticate and issue an access token plus protected refresh cookie."""
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
    issue_auth_cookies(response, refresh_token=tokens.refresh_token, settings=settings)
    return TokenResponse(
        access_token=tokens.access_token,
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
    request: Request,
    response: Response,
    authentication_service: Annotated[
        AuthenticationService,
        Depends(get_authentication_service),
    ],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenResponse | Response:
    """Rotate a refresh token and issue a new access token."""
    refresh_token = require_cookie_auth(request, settings=settings)
    try:
        tokens = await authentication_service.refresh(
            refresh_token=refresh_token,
        )
    except InvalidRefreshTokenError:
        clear_auth_cookies(response, settings=settings)
        response.status_code = status.HTTP_401_UNAUTHORIZED
        response.headers["WWW-Authenticate"] = "Bearer"
        return response
    except InactiveUserError:
        clear_auth_cookies(response, settings=settings)
        response.status_code = status.HTTP_403_FORBIDDEN
        return response

    await audit.record(
        company_id=tokens.user.company_id,
        actor=tokens.user,
        action="auth.refresh_rotated",
        resource_type="session",
        result="success",
    )
    issue_auth_cookies(response, refresh_token=tokens.refresh_token, settings=settings)
    return TokenResponse(
        access_token=tokens.access_token,
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
    request: Request,
    response: Response,
    authentication_service: Annotated[
        AuthenticationService,
        Depends(get_authentication_service),
    ],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Revoke a refresh token."""
    refresh_token = require_cookie_auth(request, settings=settings)
    try:
        user = await authentication_service.logout(refresh_token=refresh_token)
    except InvalidRefreshTokenError:
        clear_auth_cookies(response, settings=settings)
        response.status_code = status.HTTP_401_UNAUTHORIZED
        response.headers["WWW-Authenticate"] = "Bearer"
        return response

    await audit.record(
        company_id=user.company_id,
        actor=user,
        action="auth.logout",
        resource_type="session",
        result="success",
        source_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    clear_auth_cookies(response, settings=settings)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post(
    "/sessions/revoke-others",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke every refresh session except the cookie session",
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def revoke_other_sessions(
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    users: Annotated[UserService, Depends(get_user_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    refresh_token = require_cookie_auth(request, settings=settings)
    try:
        await users.revoke_other_sessions(
            user_id=current_user.id,
            current_refresh_token=refresh_token,
        )
    except AccountLifecycleError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="session.other_sessions_revoked",
        resource_type="session",
        result="success",
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
    session: Annotated[AsyncSession, Depends(get_db_session)],
    queue: Annotated[TransactionalEmailQueue, Depends(get_transactional_email_queue)],
) -> PasswordResetRequestResponse:
    """Create a privacy-safe reset request without revealing account existence."""
    user, token = await users.initiate_password_reset(
        email=str(payload.email),
        expiry_minutes=settings.password_reset_expire_minutes,
        cooldown_seconds=settings.password_reset_resend_cooldown_seconds,
    )
    if user is not None:
        if token is not None:
            email = _account_email(
                settings,
                message_type=EmailMessageType.PASSWORD_RESET,
                recipient=user.email,
                intro="A password reset was requested for your account.",
                details=(
                    (
                        "Link expires",
                        f"{settings.password_reset_expire_minutes} minutes",
                    ),
                ),
                action_label="Reset password",
                action_path=f"/reset-password?{urlencode({'token': token})}",
                security_note=(
                    "If you did not request a password reset, ignore this email. "
                    "Your password will not change. Do not forward the reset link."
                ),
            )
            if email is not None:
                await _persist_and_publish_email(
                    session=session,
                    settings=settings,
                    queue=queue,
                    company_id=user.company_id,
                    message_type=EmailMessageType.PASSWORD_RESET,
                    email=email,
                    deduplication_key=f"password-reset:{hash_token(token)}",
                    related_resource_type="user",
                    related_resource_id=user.id,
                    encrypt_payload=True,
                )
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


@router.get(
    "/email-verification/status",
    response_model=EmailVerificationStatusResponse,
)
async def email_verification_status(
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    users: Annotated[UserService, Depends(get_user_service)],
) -> EmailVerificationStatusResponse:
    return EmailVerificationStatusResponse(
        email=user.email,
        is_verified=user.is_email_verified,
        verified_at=user.email_verified_at,
        resend_available_in_seconds=await users.verification_resend_after(
            user=user,
            cooldown_seconds=settings.email_verification_resend_cooldown_seconds,
        ),
    )


@router.post(
    "/email-verification/resend",
    response_model=EmailVerificationResendResponse,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def resend_email_verification(
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings)],
    users: Annotated[UserService, Depends(get_user_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    queue: Annotated[TransactionalEmailQueue, Depends(get_transactional_email_queue)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> EmailVerificationResendResponse:
    token, entity, cooldown = await users.initiate_email_verification(
        user=user,
        expiry_hours=settings.email_verification_expire_hours,
        cooldown_seconds=settings.email_verification_resend_cooldown_seconds,
    )
    if token is not None and entity is not None:
        email = _account_email(
            settings,
            message_type=EmailMessageType.EMAIL_VERIFICATION,
            recipient=user.email,
            intro="Confirm that this email address belongs to you.",
            details=(
                ("Link expires", f"{settings.email_verification_expire_hours} hours"),
            ),
            action_label="Verify email",
            action_path=f"/verify-email?{urlencode({'token': token})}",
            security_note=(
                "If you did not request this verification email, you can ignore it. "
                "Do not forward the verification link."
            ),
        )
        if email is not None:
            await _persist_and_publish_email(
                session=session,
                settings=settings,
                queue=queue,
                company_id=user.company_id,
                message_type=EmailMessageType.EMAIL_VERIFICATION,
                email=email,
                deduplication_key=f"email-verification:{entity.id}",
                related_resource_type="user",
                related_resource_id=user.id,
                encrypt_payload=True,
            )
        await audit.record(
            company_id=user.company_id,
            actor=user,
            action="email.verification_resent",
            resource_type="user",
            resource_id=user.id,
            result="success",
        )
    expose = (
        settings.expose_local_email_verification_token
        and settings.environment
        in {
            "local",
            "development",
            "test",
        }
    )
    return EmailVerificationResendResponse(
        message=(
            "Your email is already verified."
            if user.is_email_verified
            else "If eligible, a verification email has been queued."
        ),
        resend_available_in_seconds=cooldown,
        local_verification_token=token if expose else None,
    )


@router.post(
    "/email-verification/verify",
    response_model=EmailVerificationResponse,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def verify_email(
    payload: EmailVerificationRequest,
    settings: Annotated[Settings, Depends(get_settings)],
    users: Annotated[UserService, Depends(get_user_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    queue: Annotated[TransactionalEmailQueue, Depends(get_transactional_email_queue)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> EmailVerificationResponse:
    try:
        user, changed = await users.verify_email(payload.token)
    except InvalidEmailVerificationTokenError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except ExpiredEmailVerificationTokenError as exc:
        raise HTTPException(status.HTTP_410_GONE, str(exc)) from exc
    except UsedEmailVerificationTokenError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if changed:
        await audit.record(
            company_id=user.company_id,
            actor=user,
            action="email.verified",
            resource_type="user",
            resource_id=user.id,
            result="success",
        )
        welcome = _account_email(
            settings,
            message_type=EmailMessageType.WELCOME,
            recipient=user.email,
            intro="Your email is verified. Welcome to the AI Manufacturing Platform.",
            action_label="Open platform",
            action_path="/",
        )
        if welcome is not None:
            await _persist_and_publish_email(
                session=session,
                settings=settings,
                queue=queue,
                company_id=user.company_id,
                message_type=EmailMessageType.WELCOME,
                email=welcome,
                deduplication_key=f"welcome:{user.id}",
                related_resource_type="user",
                related_resource_id=user.id,
            )
    return EmailVerificationResponse(
        status="verified" if changed else "already_verified",
        message=(
            "Your email has been verified."
            if changed
            else "Your email was already verified."
        ),
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
    except ExpiredPasswordResetTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Password reset token has expired.",
        ) from exc
    except UsedPasswordResetTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Password reset token has already been used.",
        ) from exc
    except InvalidPasswordResetTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Password reset token is invalid.",
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
