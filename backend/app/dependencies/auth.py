"""Authentication and authorization dependencies."""

import logging
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config.settings import Settings, get_settings
from app.db.tenant_context import bind_tenant
from app.dependencies.services import get_user_service
from app.models.user import User, UserRole
from app.observability.logging import emit_safe
from app.services.users import UserService
from app.utils.jwt import TokenDecodeError, TokenType, decode_jwt_token

bearer_scheme = HTTPBearer(auto_error=False)
security_logger = logging.getLogger("app.security.audit")


def _unauthorized_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication credentials could not be validated.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    settings: Annotated[Settings, Depends(get_settings)],
    user_service: Annotated[UserService, Depends(get_user_service)],
) -> User:
    """Resolve the authenticated user from the access token."""
    if credentials is None:
        raise _unauthorized_exception()

    try:
        claims = decode_jwt_token(
            token=credentials.credentials,
            secret_key=settings.secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            expected_type=TokenType.ACCESS,
        )
    except TokenDecodeError as exc:
        raise _unauthorized_exception() from exc

    user = await user_service.get_by_id(claims.sub)
    if user is None:
        raise _unauthorized_exception()
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is inactive.",
        )
    bind_tenant(user.company_id)
    return user


def require_roles(*allowed_roles: UserRole) -> Callable[..., User]:
    """Return a dependency that enforces role membership."""

    def verify_role(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if current_user.role not in allowed_roles:
            emit_safe(
                security_logger,
                logging.WARNING,
                "security_audit",
                extra={
                    "audit_event": "privileged_authorization",
                    "outcome": "denied",
                    "reason": "insufficient_role",
                    "actor_role": current_user.role.value,
                    "required_roles": ",".join(role.value for role in allowed_roles),
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User does not have permission to perform this action.",
            )
        return current_user

    return verify_role
