"""Authenticated company-scoped support request delivery."""

from __future__ import annotations

from contextlib import suppress
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.dependencies.auth import get_current_user, require_roles
from app.dependencies.database import get_db_session
from app.dependencies.rate_limit import enforce_mutation_rate_limit
from app.dependencies.services import get_audit_service, get_transactional_email_queue
from app.email.queue import TransactionalEmailQueue
from app.models.email import EmailDeliveryStatus, EmailMessageType, OutboundEmailMessage
from app.models.manufacturing import Company, Factory, Machine
from app.models.support import SupportRequest, SupportRequestStatus
from app.models.user import User, UserRole
from app.schemas.support import (
    SupportRequestCreate,
    SupportRequestListResponse,
    SupportRequestResponse,
)
from app.services.audit import AuditService
from app.services.email import support_email
from app.services.email_delivery import persist_email

router = APIRouter(prefix="/support", tags=["support"])


def _delivery_message(item: SupportRequest) -> str:
    if item.status == SupportRequestStatus.DELIVERED.value:
        return "Your support request was delivered."
    if item.status == SupportRequestStatus.DELIVERY_FAILED.value:
        return (
            "Your request was saved, but email delivery failed. "
            "An administrator can retry it."
        )
    if item.status == SupportRequestStatus.CLOSED.value:
        return "This support request is closed."
    return "Your support request was saved and is awaiting delivery."


def _response(item: SupportRequest) -> SupportRequestResponse:
    return SupportRequestResponse(
        id=item.id,
        category=item.category,
        subject=item.subject,
        current_page=item.current_page,
        factory_id=item.factory_id,
        machine_id=item.machine_id,
        status=SupportRequestStatus(item.status),
        delivery_attempts=item.delivery_attempts,
        created_at=item.created_at,
        updated_at=item.updated_at,
        delivered_at=item.delivered_at,
        delivery_message=_delivery_message(item),
    )


async def _related_resources(
    session: AsyncSession,
    *,
    company_id: UUID,
    factory_id: UUID | None,
    machine_id: UUID | None,
) -> tuple[str | None, str | None]:
    factory_name: str | None = None
    if factory_id is not None:
        factory_name = await session.scalar(
            select(Factory.name).where(
                Factory.id == factory_id,
                Factory.company_id == company_id,
                Factory.deleted_at.is_(None),
            )
        )
        if factory_name is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Factory not found.")
    machine_name: str | None = None
    if machine_id is not None:
        machine_row = (
            await session.execute(
                select(Machine.name, Machine.factory_id)
                .join(Factory, Machine.factory_id == Factory.id)
                .where(
                    Machine.id == machine_id,
                    Factory.company_id == company_id,
                    Machine.deleted_at.is_(None),
                    Factory.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        if machine_row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Machine not found.")
        machine_name = machine_row[0]
        if factory_id is not None and machine_row[1] != factory_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Machine does not belong to the selected factory.",
            )
        if factory_name is None:
            factory_name = await session.scalar(
                select(Factory.name).where(Factory.id == machine_row[1])
            )
    return factory_name, machine_name


async def _queue_delivery(
    item: SupportRequest,
    *,
    session: AsyncSession,
    settings: Settings,
    queue: TransactionalEmailQueue,
    factory_name: str | None,
    machine_name: str | None,
) -> None:
    if settings.support_email_to is None or settings.email_from is None:
        item.status = SupportRequestStatus.DELIVERY_FAILED.value
        item.last_error = "email_not_configured"
        await session.commit()
        await session.refresh(item)
        return
    enqueued = await persist_email(
        session,
        company_id=item.company_id,
        message_type=EmailMessageType.SUPPORT_REQUEST_RECEIVED,
        email=support_email(
            item,
            destination=str(settings.support_email_to),
            from_address=str(settings.email_from),
            from_name=settings.email_from_name,
            factory_name=factory_name,
            machine_name=machine_name,
        ),
        provider=settings.email_provider,
        max_retries=settings.email_max_retries,
        deduplication_key=f"support-request:{item.id}",
        related_resource_type="support_request",
        related_resource_id=item.id,
    )
    await session.commit()
    await session.refresh(item)
    if enqueued.created:
        try:
            queue.enqueue(enqueued.message.id)
        except Exception:
            # The durable queued row remains authoritative for reconciliation.
            return


@router.post(
    "/requests",
    response_model=SupportRequestResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def create_support_request(
    payload: SupportRequestCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[TransactionalEmailQueue, Depends(get_transactional_email_queue)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> SupportRequestResponse:
    existing = await session.scalar(
        select(SupportRequest).where(
            SupportRequest.company_id == user.company_id,
            SupportRequest.created_by == user.id,
            SupportRequest.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        return _response(existing)
    factory_name, machine_name = await _related_resources(
        session,
        company_id=user.company_id,
        factory_id=payload.factory_id,
        machine_id=payload.machine_id,
    )
    company_name = await session.scalar(
        select(Company.name).where(Company.id == user.company_id)
    )
    if company_name is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Company context is unavailable.")
    item = SupportRequest(
        company_id=user.company_id,
        created_by=user.id,
        factory_id=payload.factory_id,
        machine_id=payload.machine_id,
        requester_name=user.full_name or user.email,
        requester_email=user.email,
        requester_role=user.role.value,
        company_name=company_name,
        category=payload.category.value,
        subject=payload.subject,
        message=payload.message,
        current_page=payload.current_page,
        idempotency_key=payload.idempotency_key,
        status=SupportRequestStatus.SUBMITTED.value,
    )
    session.add(item)
    await session.flush()
    await session.refresh(item)
    await _queue_delivery(
        item,
        session=session,
        settings=settings,
        queue=queue,
        factory_name=factory_name,
        machine_name=machine_name,
    )
    await audit.record(
        company_id=user.company_id,
        actor=user,
        action="support.request_submitted",
        resource_type="support_request",
        resource_id=item.id,
        result="success",
        metadata={
            "category": item.category,
            "delivery_status": item.status,
            "delivery_attempts": item.delivery_attempts,
        },
    )
    await session.refresh(item)
    return _response(item)


@router.get("/requests", response_model=SupportRequestListResponse)
async def list_support_requests(
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SupportRequestListResponse:
    filters = (SupportRequest.company_id == user.company_id,)
    total = int(
        await session.scalar(
            select(func.count()).select_from(SupportRequest).where(*filters)
        )
        or 0
    )
    items = (
        await session.scalars(
            select(SupportRequest)
            .where(*filters)
            .order_by(SupportRequest.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return SupportRequestListResponse(
        items=[_response(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/requests/{request_id}/resend",
    response_model=SupportRequestResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def resend_support_request(
    request_id: UUID,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[TransactionalEmailQueue, Depends(get_transactional_email_queue)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> SupportRequestResponse:
    item = await session.scalar(
        select(SupportRequest)
        .where(
            SupportRequest.id == request_id,
            SupportRequest.company_id == user.company_id,
        )
        .with_for_update()
    )
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Support request not found.")
    if item.status == SupportRequestStatus.DELIVERED.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Support request is already delivered."
        )
    if item.status == SupportRequestStatus.CLOSED.value:
        raise HTTPException(status.HTTP_409_CONFLICT, "Support request is closed.")
    message = await session.scalar(
        select(OutboundEmailMessage)
        .where(
            OutboundEmailMessage.related_resource_type == "support_request",
            OutboundEmailMessage.related_resource_id == item.id,
        )
        .with_for_update()
    )
    if message is None:
        factory_name, machine_name = await _related_resources(
            session,
            company_id=user.company_id,
            factory_id=item.factory_id,
            machine_id=item.machine_id,
        )
        await _queue_delivery(
            item,
            session=session,
            settings=settings,
            queue=queue,
            factory_name=factory_name,
            machine_name=machine_name,
        )
    else:
        if message.status not in {EmailDeliveryStatus.FAILED.value}:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Support request delivery is already active.",
            )
        message.status = EmailDeliveryStatus.QUEUED.value
        message.retry_count = 0
        message.attempt_count = 0
        message.next_attempt_at = None
        message.last_error = None
        message.failed_at = None
        item.status = SupportRequestStatus.SUBMITTED.value
        item.last_error = None
        await session.commit()
        with suppress(Exception):
            queue.enqueue(message.id)
    await audit.record(
        company_id=user.company_id,
        actor=user,
        action="support.request_resent",
        resource_type="support_request",
        resource_id=item.id,
        result="success",
        metadata={
            "delivery_status": item.status,
            "delivery_attempts": item.delivery_attempts,
        },
    )
    await session.refresh(item)
    return _response(item)
