"""Company team invitation routes."""

from contextlib import suppress
from typing import Annotated
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.dependencies.auth import require_permissions
from app.dependencies.database import get_db_session
from app.dependencies.entitlements import (
    entitlement_http_error,
    get_entitlement_service,
)
from app.dependencies.rate_limit import (
    enforce_auth_rate_limit,
    enforce_mutation_rate_limit,
)
from app.dependencies.services import (
    get_audit_service,
    get_invitation_service,
    get_transactional_email_queue,
)
from app.email.queue import TransactionalEmailQueue
from app.models.email import EmailMessageType
from app.models.user import TeamInvitation, User
from app.permissions import Permission
from app.schemas.team import (
    InvitationAcceptRequest,
    InvitationAcceptResponse,
    InvitationCreateRequest,
    InvitationListResponse,
    InvitationResponse,
)
from app.schemas.user import UserResponse
from app.services.audit import AuditService
from app.services.email import transactional_email
from app.services.email_delivery import persist_email
from app.services.entitlements import EntitlementError, EntitlementService
from app.services.exceptions import (
    InvalidInvitationTokenError,
    InvitationLifecycleError,
)
from app.services.invitations import InvitationService, IssuedInvitation
from app.utils.security import hash_token

router = APIRouter(prefix="/team/invitations", tags=["team"])


def _expose_local_token(settings: Settings) -> bool:
    return settings.expose_local_team_invitation_token and settings.environment in {
        "local",
        "development",
        "test",
    }


def _response(
    invitation: TeamInvitation, *, local_token: str | None = None
) -> InvitationResponse:
    return InvitationResponse.model_validate(invitation).model_copy(
        update={"local_invitation_token": local_token}
    )


async def _queue_invitation_email(
    *,
    issued: IssuedInvitation,
    settings: Settings,
    session: AsyncSession,
    queue: TransactionalEmailQueue,
) -> None:
    if settings.email_from is None:
        return
    invitation = issued.invitation
    url = (
        f"{(settings.app_base_url or 'http://localhost:5173').rstrip('/')}"
        f"/accept-invitation?{urlencode({'token': issued.token})}"
    )
    email = transactional_email(
        EmailMessageType.TEAM_INVITATION,
        recipient=invitation.invited_email,
        from_address=str(settings.email_from),
        from_name=settings.email_from_name,
        reply_to=(str(settings.email_reply_to) if settings.email_reply_to else None),
        intro=(
            "You have been invited to join a company workspace as "
            f"{invitation.role.value}."
        ),
        details=(
            ("Invitation expires", f"{settings.team_invitation_expire_hours} hours"),
        ),
        action_label="Accept invitation",
        action_url=url,
        security_note=(
            "Only accept this invitation if you recognize the company. Do not "
            "forward this single-use link."
        ),
    )
    enqueued = await persist_email(
        session,
        company_id=invitation.company_id,
        message_type=EmailMessageType.TEAM_INVITATION,
        email=email,
        provider=settings.email_provider,
        max_retries=settings.email_max_retries,
        deduplication_key=(f"team-invitation:{invitation.id}:{invitation.send_count}"),
        related_resource_type="team_invitation",
        related_resource_id=invitation.id,
        payload_encryption_key=settings.secret_key.get_secret_value(),
    )
    await session.commit()
    if enqueued.created:
        with suppress(Exception):
            queue.enqueue(enqueued.message.id)


@router.get("", response_model=InvitationListResponse)
async def list_invitations(
    actor: Annotated[User, Depends(require_permissions(Permission.TEAM_VIEW))],
    service: Annotated[InvitationService, Depends(get_invitation_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InvitationListResponse:
    items, total = await service.list_pending(actor=actor, limit=limit, offset=offset)
    return InvitationListResponse(
        items=[_response(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def create_invitation(
    payload: InvitationCreateRequest,
    actor: Annotated[User, Depends(require_permissions(Permission.TEAM_MANAGE))],
    service: Annotated[InvitationService, Depends(get_invitation_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    queue: Annotated[TransactionalEmailQueue, Depends(get_transactional_email_queue)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    entitlements: Annotated[EntitlementService, Depends(get_entitlement_service)],
) -> InvitationResponse:
    try:
        await entitlements.require_capacity(actor.company_id, "team_members")
        issued = await service.create(
            actor=actor,
            email=str(payload.email),
            role=payload.role,
            expiry_hours=settings.team_invitation_expire_hours,
            cooldown_seconds=settings.team_invitation_resend_cooldown_seconds,
        )
    except InvitationLifecycleError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except EntitlementError as exc:
        raise entitlement_http_error(exc) from exc
    await _queue_invitation_email(
        issued=issued, settings=settings, session=session, queue=queue
    )
    await audit.record(
        company_id=actor.company_id,
        actor=actor,
        action="team.invitation_created",
        resource_type="team_invitation",
        resource_id=issued.invitation.id,
        result="success",
        metadata={"role": issued.invitation.role.value},
    )
    return _response(
        issued.invitation,
        local_token=issued.token if _expose_local_token(settings) else None,
    )


@router.post(
    "/{invitation_id}/resend",
    response_model=InvitationResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def resend_invitation(
    invitation_id: UUID,
    actor: Annotated[User, Depends(require_permissions(Permission.TEAM_MANAGE))],
    service: Annotated[InvitationService, Depends(get_invitation_service)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    queue: Annotated[TransactionalEmailQueue, Depends(get_transactional_email_queue)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> InvitationResponse:
    try:
        issued = await service.resend(
            actor=actor,
            invitation_id=invitation_id,
            expiry_hours=settings.team_invitation_expire_hours,
            cooldown_seconds=settings.team_invitation_resend_cooldown_seconds,
        )
    except InvitationLifecycleError as exc:
        message = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if message == "Invitation not found."
            else (
                status.HTTP_429_TOO_MANY_REQUESTS
                if "resent in" in message
                else status.HTTP_409_CONFLICT
            )
        )
        raise HTTPException(code, message) from exc
    await _queue_invitation_email(
        issued=issued, settings=settings, session=session, queue=queue
    )
    await audit.record(
        company_id=actor.company_id,
        actor=actor,
        action="team.invitation_resent",
        resource_type="team_invitation",
        resource_id=issued.invitation.id,
        result="success",
    )
    return _response(
        issued.invitation,
        local_token=issued.token if _expose_local_token(settings) else None,
    )


@router.delete(
    "/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def revoke_invitation(
    invitation_id: UUID,
    actor: Annotated[User, Depends(require_permissions(Permission.TEAM_MANAGE))],
    service: Annotated[InvitationService, Depends(get_invitation_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> Response:
    try:
        invitation = await service.revoke(actor=actor, invitation_id=invitation_id)
    except InvitationLifecycleError as exc:
        code = (
            status.HTTP_404_NOT_FOUND
            if str(exc) == "Invitation not found."
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(code, str(exc)) from exc
    await audit.record(
        company_id=actor.company_id,
        actor=actor,
        action="team.invitation_revoked",
        resource_type="team_invitation",
        resource_id=invitation.id,
        result="success",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/accept",
    response_model=InvitationAcceptResponse,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def accept_invitation(
    payload: InvitationAcceptRequest,
    service: Annotated[InvitationService, Depends(get_invitation_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    entitlements: Annotated[EntitlementService, Depends(get_entitlement_service)],
) -> InvitationAcceptResponse:
    try:
        pending = await session.scalar(
            select(TeamInvitation).where(
                TeamInvitation.token_hash == hash_token(payload.token)
            )
        )
        if pending is not None:
            await entitlements.require_capacity(
                pending.company_id, "team_members", increment=0
            )
        invitation, user, created = await service.accept(
            token=payload.token,
            full_name=payload.full_name,
            password=payload.password,
        )
    except InvalidInvitationTokenError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except InvitationLifecycleError as exc:
        code = (
            status.HTTP_410_GONE if "expired" in str(exc) else status.HTTP_409_CONFLICT
        )
        raise HTTPException(code, str(exc)) from exc
    except EntitlementError as exc:
        raise entitlement_http_error(exc) from exc
    await audit.record(
        company_id=invitation.company_id,
        actor=user,
        action="team.invitation_accepted",
        resource_type="team_invitation",
        resource_id=invitation.id,
        result="success",
        metadata={"created_account": created, "role": user.role.value},
    )
    return InvitationAcceptResponse(user=UserResponse.model_validate(user))
