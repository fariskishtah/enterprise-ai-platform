"""Company-scoped user administration, password, and session routes."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.config.settings import Settings, get_settings
from app.dependencies.auth import get_current_user, require_roles
from app.dependencies.rate_limit import enforce_mutation_rate_limit
from app.dependencies.services import get_audit_service, get_user_service
from app.models.user import User, UserRole
from app.schemas.auth import PasswordResetRequestResponse
from app.schemas.user import (
    ChangePasswordRequest,
    RevokeOtherSessionsRequest,
    SessionListResponse,
    SessionResponse,
    UserCreateRequest,
    UserListResponse,
    UserResponse,
    UserUpdateRequest,
)
from app.services.audit import AuditService
from app.services.exceptions import AccountLifecycleError, DuplicateEmailError
from app.services.users import UserService

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def read_current_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.get("", response_model=UserListResponse)
async def list_users(
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[UserService, Depends(get_user_service)],
    role: UserRole | None = None,
    is_active: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> UserListResponse:
    items, total = await service.list_company_users(
        actor=current_user,
        role=role,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )
    return UserListResponse(
        items=[UserResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def create_user(
    payload: UserCreateRequest,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[UserService, Depends(get_user_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> UserResponse:
    try:
        user = await service.create_company_user(
            actor=current_user,
            email=str(payload.email),
            password=payload.password,
            role=payload.role,
        )
    except DuplicateEmailError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="user.created",
        resource_type="user",
        resource_id=user.id,
        result="success",
        metadata={"role": user.role.value},
    )
    return UserResponse.model_validate(user)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def update_user(
    user_id: UUID,
    payload: UserUpdateRequest,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[UserService, Depends(get_user_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> UserResponse:
    if not payload.model_fields_set:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "No update supplied.",
        )
    try:
        user = await service.update_company_user(
            actor=current_user,
            user_id=user_id,
            role=payload.role if "role" in payload.model_fields_set else None,
            is_active=(
                payload.is_active if "is_active" in payload.model_fields_set else None
            ),
        )
    except AccountLifecycleError as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if str(exc) == "User not found."
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(code, str(exc)) from exc
    action = (
        "user.role_changed"
        if "role" in payload.model_fields_set
        else "user.activation_changed"
    )
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action=action,
        resource_type="user",
        resource_id=user.id,
        result="success",
        metadata={"role": user.role.value, "is_active": user.is_active},
    )
    return UserResponse.model_validate(user)


@router.post(
    "/me/password",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[UserService, Depends(get_user_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> Response:
    try:
        await service.change_password(
            user=current_user,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except AccountLifecycleError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="password.changed",
        resource_type="user",
        resource_id=current_user.id,
        result="success",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{user_id}/password-reset",
    response_model=PasswordResetRequestResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def admin_reset_user_password(
    user_id: UUID,
    current_user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    service: Annotated[UserService, Depends(get_user_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> PasswordResetRequestResponse:
    target = await service.get_by_id(user_id)
    if target is None or target.company_id != current_user.company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    _, token = await service.initiate_password_reset(
        email=target.email, expiry_minutes=settings.password_reset_expire_minutes
    )
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="password.reset_initiated_by_admin",
        resource_type="user",
        resource_id=target.id,
        result="success",
    )
    expose = settings.expose_local_password_reset_token and settings.environment in {
        "local",
        "development",
        "test",
    }
    return PasswordResetRequestResponse(
        message="Password reset initiated.",
        local_reset_token=token if expose else None,
    )


@router.get("/me/sessions", response_model=SessionListResponse)
async def list_sessions(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[UserService, Depends(get_user_service)],
) -> SessionListResponse:
    sessions = await service.list_sessions(current_user.id)
    return SessionListResponse(
        items=[
            SessionResponse(
                id=item.id,
                created_at=item.created_at,
                expires_at=item.expires_at,
                last_seen_at=item.last_seen_at,
                user_agent_summary=item.user_agent_summary,
                source_ip=item.source_ip,
            )
            for item in sessions
        ]
    )


@router.delete(
    "/me/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def revoke_session(
    session_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[UserService, Depends(get_user_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> Response:
    if not await service.revoke_session(user_id=current_user.id, session_id=session_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found.")
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="session.revoked",
        resource_type="session",
        resource_id=session_id,
        result="success",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/me/sessions/revoke-others",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def revoke_other_sessions(
    payload: RevokeOtherSessionsRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[UserService, Depends(get_user_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> Response:
    try:
        await service.revoke_other_sessions(
            user_id=current_user.id,
            current_refresh_token=payload.refresh_token,
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
