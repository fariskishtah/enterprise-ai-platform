"""Role-safe operational actions, alerts, timeline, feedback, and shifts."""

from __future__ import annotations

import csv
from datetime import datetime
from io import StringIO
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_user, require_roles
from app.dependencies.database import get_db_session
from app.dependencies.features import require_feature
from app.dependencies.rate_limit import enforce_mutation_rate_limit
from app.dependencies.services import get_audit_service, get_operations_service
from app.ml.monitoring.evaluation_models import (
    MonitoringAlertSeverity,
    MonitoringAlertStatus,
)
from app.models.manufacturing import Factory, Machine
from app.models.monitoring_orchestration import MonitoringAlertEntity
from app.models.operations import (
    MaintenanceFeedbackOutcome,
    OperationalAction,
    OperationalActionPriority,
    OperationalActionStatus,
    ShiftHandover,
    ShiftStatus,
)
from app.models.pilot import MachineRiskAssessment
from app.models.sensor import Sensor
from app.models.sensor_data import SensorReading
from app.models.user import User, UserRole
from app.permissions import is_tenant_administrator
from app.schemas.operations import (
    AlertLifecycleRequest,
    MaintenanceFeedbackCreateRequest,
    MaintenanceFeedbackPageResponse,
    MaintenanceFeedbackResponse,
    OperationalActionAcknowledgeRequest,
    OperationalActionAssignRequest,
    OperationalActionCreateRequest,
    OperationalActionPageResponse,
    OperationalActionReopenRequest,
    OperationalActionResponse,
    OperationalActionTransitionRequest,
    OperationalAlertPageResponse,
    OperationalAlertResponse,
    OperationalAssigneeResponse,
    OperationalNoteCreateRequest,
    OperationalNoteResponse,
    OperationalSearchResponse,
    OperationalSearchResult,
    OperationalSummaryResponse,
    ShiftAcknowledgeRequest,
    ShiftEndRequest,
    ShiftHandoverResponse,
    ShiftPageResponse,
    ShiftStartRequest,
    TimelinePageResponse,
)
from app.services.audit import AuditService
from app.services.operations import (
    OperationsError,
    OperationsNotFoundError,
    OperationsPermissionError,
    OperationsService,
)
from app.utils.security import as_utc, utc_now

router = APIRouter(
    prefix="/operations",
    tags=["operations"],
    dependencies=[Depends(require_feature("operations_workflow_enabled"))],
)


def _translate(error: OperationsError) -> HTTPException:
    if isinstance(error, OperationsNotFoundError):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(error, OperationsPermissionError):
        code = status.HTTP_403_FORBIDDEN
    else:
        code = status.HTTP_409_CONFLICT
    return HTTPException(code, str(error))


@router.get("/actions", response_model=OperationalActionPageResponse)
async def list_actions(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    priority: OperationalActionPriority | None = None,
    action_status: Annotated[
        OperationalActionStatus | None, Query(alias="status")
    ] = None,
    factory_id: UUID | None = None,
    machine_id: UUID | None = None,
    assigned_user_id: UUID | None = None,
    overdue: bool | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> OperationalActionPageResponse:
    items, total = await service.list_actions(
        actor=current_user,
        priority=priority,
        action_status=action_status,
        factory_id=factory_id,
        machine_id=machine_id,
        assignee_id=assigned_user_id,
        overdue=overdue,
        start_at=start_at,
        end_at=end_at,
        limit=limit,
        offset=offset,
    )
    return OperationalActionPageResponse(
        items=[OperationalActionResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/actions",
    response_model=OperationalActionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def create_action(
    payload: OperationalActionCreateRequest,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> OperationalActionResponse:
    try:
        action = await service.create_action(actor=current_user, **payload.model_dump())
    except OperationsError as exc:
        raise _translate(exc) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="operational_action.created",
        resource_type="operational_action",
        resource_id=action.id,
        result="success",
        metadata={
            "factory_id": str(action.factory_id),
            "machine_id": str(action.machine_id),
            "priority": action.priority.value,
        },
    )
    if action.assigned_user_id is not None:
        await audit.record(
            company_id=current_user.company_id,
            actor=current_user,
            action="operational_action.assigned",
            resource_type="operational_action",
            resource_id=action.id,
            result="success",
            metadata={"assigned_user_id": str(action.assigned_user_id)},
        )
    return OperationalActionResponse.model_validate(action)


@router.get(
    "/actions/{action_id}",
    response_model=OperationalActionResponse,
)
async def get_action(
    action_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OperationsService, Depends(get_operations_service)],
) -> OperationalActionResponse:
    try:
        return OperationalActionResponse.model_validate(
            await service.get_action(action_id, actor=current_user)
        )
    except OperationsError as exc:
        raise _translate(exc) from exc


@router.post(
    "/actions/{action_id}/assign",
    response_model=OperationalActionResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def assign_action(
    action_id: UUID,
    payload: OperationalActionAssignRequest,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> OperationalActionResponse:
    try:
        action = await service.assign_action(
            action_id,
            actor=current_user,
            assigned_user_id=payload.assigned_user_id,
            expected_version=payload.expected_version,
        )
    except OperationsError as exc:
        raise _translate(exc) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="operational_action.assigned",
        resource_type="operational_action",
        resource_id=action.id,
        result="success",
        metadata={"assigned_user_id": str(payload.assigned_user_id)},
    )
    return OperationalActionResponse.model_validate(action)


@router.post(
    "/actions/{action_id}/acknowledge",
    response_model=OperationalActionResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def acknowledge_action(
    action_id: UUID,
    payload: OperationalActionAcknowledgeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> OperationalActionResponse:
    try:
        action = await service.acknowledge_action(
            action_id,
            actor=current_user,
            expected_version=payload.expected_version,
            note=payload.note,
        )
    except OperationsError as exc:
        raise _translate(exc) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="operational_action.acknowledged",
        resource_type="operational_action",
        resource_id=action.id,
        result="success",
    )
    return OperationalActionResponse.model_validate(action)


@router.post(
    "/actions/{action_id}/transition",
    response_model=OperationalActionResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def transition_action(
    action_id: UUID,
    payload: OperationalActionTransitionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> OperationalActionResponse:
    try:
        action = await service.transition_action(
            action_id,
            actor=current_user,
            next_status=OperationalActionStatus(payload.status),
            expected_version=payload.expected_version,
            summary=payload.summary,
        )
    except OperationsError as exc:
        raise _translate(exc) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action=f"operational_action.{action.status.value}",
        resource_type="operational_action",
        resource_id=action.id,
        result="success",
        metadata={"status": action.status.value},
    )
    return OperationalActionResponse.model_validate(action)


@router.post(
    "/actions/{action_id}/reopen",
    response_model=OperationalActionResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def reopen_action(
    action_id: UUID,
    payload: OperationalActionReopenRequest,
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> OperationalActionResponse:
    try:
        action = await service.reopen_action(
            action_id,
            actor=current_user,
            expected_version=payload.expected_version,
            reason=payload.reason,
        )
    except OperationsError as exc:
        raise _translate(exc) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="operational_action.reopened",
        resource_type="operational_action",
        resource_id=action.id,
        result="success",
    )
    return OperationalActionResponse.model_validate(action)


@router.get(
    "/notes",
    response_model=list[OperationalNoteResponse],
)
async def list_notes(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    action_id: UUID | None = None,
    alert_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> list[OperationalNoteResponse]:
    if (action_id is None) == (alert_id is None):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Provide exactly one action_id or alert_id.",
        )
    try:
        notes = await service.list_notes(
            actor=current_user,
            action_id=action_id,
            alert_id=alert_id,
            limit=limit,
            offset=offset,
        )
    except OperationsError as exc:
        raise _translate(exc) from exc
    return [OperationalNoteResponse.model_validate(item) for item in notes]


@router.post(
    "/actions/{action_id}/notes",
    response_model=OperationalNoteResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def add_action_note(
    action_id: UUID,
    payload: OperationalNoteCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> OperationalNoteResponse:
    try:
        note = await service.add_action_note(
            action_id, actor=current_user, body=payload.body
        )
    except OperationsError as exc:
        raise _translate(exc) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="operational_note.added",
        resource_type="operational_action",
        resource_id=action_id,
        result="success",
        metadata={"kind": note.kind.value},
    )
    return OperationalNoteResponse.model_validate(note)


@router.post(
    "/alerts/{alert_id}/notes",
    response_model=OperationalNoteResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def add_alert_note(
    alert_id: UUID,
    payload: OperationalNoteCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> OperationalNoteResponse:
    try:
        note = await service.add_alert_note(
            alert_id, actor=current_user, body=payload.body
        )
    except OperationsError as exc:
        raise _translate(exc) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="operational_note.added",
        resource_type="monitoring_alert",
        resource_id=alert_id,
        result="success",
        metadata={"kind": note.kind.value},
    )
    return OperationalNoteResponse.model_validate(note)


@router.post(
    "/maintenance-feedback",
    response_model=MaintenanceFeedbackResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def submit_feedback(
    payload: MaintenanceFeedbackCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> MaintenanceFeedbackResponse:
    try:
        feedback = await service.submit_feedback(
            actor=current_user, **payload.model_dump()
        )
    except OperationsError as exc:
        raise _translate(exc) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="maintenance_feedback.submitted",
        resource_type="maintenance_feedback",
        resource_id=feedback.id,
        result="success",
        metadata={
            "machine_id": str(feedback.machine_id),
            "outcome": feedback.outcome.value,
        },
    )
    return MaintenanceFeedbackResponse.model_validate(feedback)


@router.get(
    "/maintenance-feedback",
    response_model=MaintenanceFeedbackPageResponse,
)
async def list_feedback(
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    action_id: UUID | None = None,
    alert_id: UUID | None = None,
    machine_id: UUID | None = None,
    outcome: MaintenanceFeedbackOutcome | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> MaintenanceFeedbackPageResponse:
    items, total = await service.list_feedback(
        actor=current_user,
        action_id=action_id,
        alert_id=alert_id,
        machine_id=machine_id,
        outcome=outcome,
        limit=limit,
        offset=offset,
    )
    return MaintenanceFeedbackPageResponse(
        items=[MaintenanceFeedbackResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/maintenance-feedback/export.csv", response_class=Response)
async def export_feedback(
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    action_id: UUID | None = None,
    alert_id: UUID | None = None,
    machine_id: UUID | None = None,
    outcome: MaintenanceFeedbackOutcome | None = None,
) -> Response:
    items, _ = await service.list_feedback(
        actor=current_user,
        action_id=action_id,
        alert_id=alert_id,
        machine_id=machine_id,
        outcome=outcome,
        limit=10_000,
        offset=0,
    )

    def safe_cell(value: object | None) -> str:
        text = "" if value is None else str(value)
        return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text

    output = StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        (
            "id",
            "factory_id",
            "machine_id",
            "action_id",
            "alert_id",
            "outcome",
            "maintenance_category",
            "replaced_component",
            "downtime_minutes",
            "summary",
            "submitted_by_user_id",
            "created_at",
        )
    )
    for item in items:
        writer.writerow(
            safe_cell(value)
            for value in (
                item.id,
                item.factory_id,
                item.machine_id,
                item.action_id,
                item.alert_id,
                item.outcome.value,
                item.maintenance_category,
                item.replaced_component,
                item.downtime_minutes,
                item.summary,
                item.submitted_by_user_id,
                item.created_at.isoformat(),
            )
        )
    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": (
                'attachment; filename="maintenance-feedback-export.csv"'
            )
        },
    )


@router.get("/timeline", response_model=TimelinePageResponse)
async def list_timeline(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    machine_id: UUID | None = None,
    factory_id: UUID | None = None,
    event_type: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> TimelinePageResponse:
    items, total = await service.list_timeline(
        actor=current_user,
        machine_id=machine_id,
        factory_id=factory_id,
        event_type=event_type,
        start_at=start_at,
        end_at=end_at,
        limit=limit,
        offset=offset,
    )
    return TimelinePageResponse(
        items=[item for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/alerts", response_model=OperationalAlertPageResponse)
async def list_operational_alerts(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    alert_status: Annotated[MonitoringAlertStatus | None, Query(alias="status")] = None,
    severity: MonitoringAlertSeverity | None = None,
    factory_id: UUID | None = None,
    machine_id: UUID | None = None,
    assigned_user_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> OperationalAlertPageResponse:
    items, total = await service.list_alerts(
        actor=current_user,
        alert_status=alert_status,
        severity=severity,
        factory_id=factory_id,
        machine_id=machine_id,
        assigned_user_id=assigned_user_id,
        limit=limit,
        offset=offset,
    )
    return OperationalAlertPageResponse(
        items=[OperationalAlertResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/alerts/{alert_id}", response_model=OperationalAlertResponse)
async def get_operational_alert(
    alert_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OperationsService, Depends(get_operations_service)],
) -> OperationalAlertResponse:
    try:
        alert = await service.get_alert(alert_id, actor=current_user)
    except OperationsError as exc:
        raise _translate(exc) from exc
    return OperationalAlertResponse.model_validate(alert)


@router.post(
    "/alerts/{alert_id}/lifecycle",
    response_model=OperationalAlertResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def transition_operational_alert(
    alert_id: UUID,
    payload: AlertLifecycleRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> OperationalAlertResponse:
    try:
        alert = await service.transition_alert(
            alert_id,
            actor=current_user,
            transition=payload.transition,
            expected_version=payload.expected_version,
            assigned_user_id=payload.assigned_user_id,
            note=payload.note,
            resolution_summary=payload.resolution_summary,
            resolution_classification=payload.resolution_classification,
            reopen_reason=payload.reopen_reason,
        )
    except OperationsError as exc:
        raise _translate(exc) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action=f"alert.{payload.transition}",
        resource_type="monitoring_alert",
        resource_id=alert.id,
        result="success",
        metadata={
            "status": alert.status.value,
            "machine_id": str(alert.machine_id) if alert.machine_id else None,
        },
    )
    return OperationalAlertResponse.model_validate(alert)


@router.get("/shifts", response_model=ShiftPageResponse)
async def list_shifts(
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    factory_id: UUID | None = None,
    shift_status: Annotated[ShiftStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> ShiftPageResponse:
    items, total = await service.list_shifts(
        actor=current_user,
        factory_id=factory_id,
        shift_status=shift_status,
        limit=limit,
        offset=offset,
    )
    return ShiftPageResponse(
        items=[ShiftHandoverResponse.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/shifts",
    response_model=ShiftHandoverResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def start_shift(
    payload: ShiftStartRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> ShiftHandoverResponse:
    try:
        shift = await service.start_shift(actor=current_user, **payload.model_dump())
    except OperationsError as exc:
        raise _translate(exc) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="shift.started",
        resource_type="shift_handover",
        resource_id=shift.id,
        result="success",
        metadata={"factory_id": str(shift.factory_id)},
    )
    return ShiftHandoverResponse.model_validate(shift)


@router.get("/shifts/{shift_id}", response_model=ShiftHandoverResponse)
async def get_shift(
    shift_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OperationsService, Depends(get_operations_service)],
) -> ShiftHandoverResponse:
    try:
        shift = await service.get_shift(shift_id, actor=current_user)
    except OperationsError as exc:
        raise _translate(exc) from exc
    return ShiftHandoverResponse.model_validate(shift)


@router.post(
    "/shifts/{shift_id}/end",
    response_model=ShiftHandoverResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def end_shift(
    shift_id: UUID,
    payload: ShiftEndRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> ShiftHandoverResponse:
    try:
        shift = await service.end_shift(
            shift_id, actor=current_user, **payload.model_dump()
        )
    except OperationsError as exc:
        raise _translate(exc) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="shift.ended",
        resource_type="shift_handover",
        resource_id=shift.id,
        result="success",
        metadata={"factory_id": str(shift.factory_id)},
    )
    return ShiftHandoverResponse.model_validate(shift)


@router.post(
    "/shifts/{shift_id}/acknowledge",
    response_model=ShiftHandoverResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def acknowledge_shift(
    shift_id: UUID,
    payload: ShiftAcknowledgeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    service: Annotated[OperationsService, Depends(get_operations_service)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> ShiftHandoverResponse:
    try:
        shift = await service.acknowledge_shift(
            shift_id, actor=current_user, **payload.model_dump()
        )
    except OperationsError as exc:
        raise _translate(exc) from exc
    await audit.record(
        company_id=current_user.company_id,
        actor=current_user,
        action="shift.handover_acknowledged",
        resource_type="shift_handover",
        resource_id=shift.id,
        result="success",
        metadata={"factory_id": str(shift.factory_id)},
    )
    return ShiftHandoverResponse.model_validate(shift)


@router.get("/summary", response_model=OperationalSummaryResponse)
async def get_operational_summary(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OperationalSummaryResponse:
    action_conditions = [OperationalAction.company_id == current_user.company_id]
    if current_user.role is UserRole.OPERATOR:
        action_conditions.append(
            or_(
                OperationalAction.assigned_user_id == current_user.id,
                OperationalAction.assigned_user_id.is_(None)
                & OperationalAction.priority.in_(
                    (
                        OperationalActionPriority.CRITICAL,
                        OperationalActionPriority.HIGH,
                    )
                ),
            )
        )
    action_rows = (
        await session.execute(
            select(OperationalAction.status, func.count())
            .where(*action_conditions)
            .group_by(OperationalAction.status)
        )
    ).all()
    alert_rows = (
        await session.execute(
            select(MonitoringAlertEntity.status, func.count())
            .where(
                MonitoringAlertEntity.company_id == current_user.company_id,
                MonitoringAlertEntity.machine_id.is_not(None),
            )
            .group_by(MonitoringAlertEntity.status)
        )
    ).all()
    latest_risk = (
        select(
            MachineRiskAssessment.machine_id,
            func.max(MachineRiskAssessment.assessed_at).label("latest_at"),
        )
        .where(MachineRiskAssessment.company_id == current_user.company_id)
        .group_by(MachineRiskAssessment.machine_id)
        .subquery()
    )
    risk_rows = (
        await session.execute(
            select(MachineRiskAssessment.risk_state, func.count())
            .join(
                latest_risk,
                (latest_risk.c.machine_id == MachineRiskAssessment.machine_id)
                & (latest_risk.c.latest_at == MachineRiskAssessment.assessed_at),
            )
            .where(MachineRiskAssessment.company_id == current_user.company_id)
            .group_by(MachineRiskAssessment.risk_state)
        )
    ).all()
    now = utc_now()
    overdue_actions = int(
        (
            await session.execute(
                select(func.count())
                .select_from(OperationalAction)
                .where(
                    *action_conditions,
                    OperationalAction.due_at.is_not(None),
                    OperationalAction.due_at < now,
                    OperationalAction.status.not_in(
                        (
                            OperationalActionStatus.COMPLETED,
                            OperationalActionStatus.CANCELLED,
                        )
                    ),
                )
            )
        ).scalar_one()
    )
    unassigned_urgent = int(
        (
            await session.execute(
                select(func.count())
                .select_from(OperationalAction)
                .where(
                    OperationalAction.company_id == current_user.company_id,
                    OperationalAction.assigned_user_id.is_(None),
                    OperationalAction.priority.in_(
                        (
                            OperationalActionPriority.CRITICAL,
                            OperationalActionPriority.HIGH,
                        )
                    ),
                    OperationalAction.status == OperationalActionStatus.OPEN,
                )
            )
        ).scalar_one()
    )
    active_shifts = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ShiftHandover)
                .where(
                    ShiftHandover.company_id == current_user.company_id,
                    ShiftHandover.status == ShiftStatus.ACTIVE,
                )
            )
        ).scalar_one()
    )
    latest_reading = (
        await session.execute(
            select(func.max(SensorReading.timestamp))
            .select_from(SensorReading)
            .join(Sensor, Sensor.id == SensorReading.sensor_id)
            .join(Machine, Machine.id == Sensor.machine_id)
            .join(Factory, Factory.id == Machine.factory_id)
            .where(Factory.company_id == current_user.company_id)
        )
    ).scalar_one_or_none()
    return OperationalSummaryResponse(
        action_counts={str(key.value): int(value) for key, value in action_rows},
        alert_counts={str(key.value): int(value) for key, value in alert_rows},
        risk_counts={str(key): int(value) for key, value in risk_rows},
        overdue_actions=overdue_actions,
        unassigned_urgent_actions=unassigned_urgent,
        active_shift_count=active_shifts,
        data_freshness_seconds=(
            max(0.0, (now - as_utc(latest_reading)).total_seconds())
            if latest_reading is not None
            else None
        ),
    )


@router.get(
    "/assignees",
    response_model=list[OperationalAssigneeResponse],
)
async def list_operational_assignees(
    current_user: Annotated[
        User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[OperationalAssigneeResponse]:
    users = (
        await session.execute(
            select(User)
            .where(
                User.company_id == current_user.company_id,
                User.is_active.is_(True),
            )
            .order_by(User.email.asc())
            .limit(100)
        )
    ).scalars()
    return [
        OperationalAssigneeResponse(
            id=item.id,
            email=item.email,
            role=item.role.value,
        )
        for item in users
    ]


@router.get("/search", response_model=OperationalSearchResponse)
async def search_operations(
    current_user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    query: Annotated[str, Query(min_length=2, max_length=100)],
    limit: Annotated[int, Query(ge=1, le=20)] = 12,
) -> OperationalSearchResponse:
    """Search indexed prefixes only; never scan model artifacts or documents."""
    pattern = f"{query.strip()}%"
    results: list[OperationalSearchResult] = []
    factories = (
        await session.execute(
            select(Factory)
            .where(
                Factory.company_id == current_user.company_id,
                Factory.deleted_at.is_(None),
                Factory.name.ilike(pattern),
            )
            .order_by(Factory.name.asc())
            .limit(limit)
        )
    ).scalars()
    results.extend(
        OperationalSearchResult(
            id=item.id,
            resource_type="factory",
            label=item.name,
            description=item.location,
            path=f"/factories/{item.id}",
        )
        for item in factories
    )
    machines = (
        await session.execute(
            select(Machine)
            .join(Factory, Factory.id == Machine.factory_id)
            .where(
                Factory.company_id == current_user.company_id,
                Machine.deleted_at.is_(None),
                Machine.name.ilike(pattern),
            )
            .order_by(Machine.name.asc())
            .limit(limit)
        )
    ).scalars()
    results.extend(
        OperationalSearchResult(
            id=item.id,
            resource_type="machine",
            label=item.name,
            description=item.serial_number,
            path=f"/factories/{item.factory_id}/machines/{item.id}",
        )
        for item in machines
    )
    sensors = (
        await session.execute(
            select(Sensor, Machine.factory_id)
            .join(Machine, Machine.id == Sensor.machine_id)
            .join(Factory, Factory.id == Machine.factory_id)
            .where(
                Factory.company_id == current_user.company_id,
                Sensor.deleted_at.is_(None),
                Sensor.name.ilike(pattern),
            )
            .order_by(Sensor.name.asc())
            .limit(limit)
        )
    ).all()
    results.extend(
        OperationalSearchResult(
            id=item.id,
            resource_type="sensor",
            label=item.name,
            description=item.sensor_type,
            path=(
                f"/factories/{factory_id}/machines/{item.machine_id}/"
                f"sensors/{item.id}"
            ),
        )
        for item, factory_id in sensors
    )
    alerts = (
        await session.execute(
            select(MonitoringAlertEntity)
            .where(
                MonitoringAlertEntity.company_id == current_user.company_id,
                MonitoringAlertEntity.machine_id.is_not(None),
                MonitoringAlertEntity.title.ilike(pattern),
            )
            .order_by(MonitoringAlertEntity.last_detected_at.desc())
            .limit(limit)
        )
    ).scalars()
    results.extend(
        OperationalSearchResult(
            id=item.id,
            resource_type="alert",
            label=item.title,
            description=item.safe_summary,
            path=f"/monitoring/alerts/{item.id}",
        )
        for item in alerts
    )
    actions = (
        await session.execute(
            select(OperationalAction)
            .where(
                OperationalAction.company_id == current_user.company_id,
                OperationalAction.title.ilike(pattern),
            )
            .order_by(OperationalAction.updated_at.desc())
            .limit(limit)
        )
    ).scalars()
    results.extend(
        OperationalSearchResult(
            id=item.id,
            resource_type="operational_action",
            label=item.title,
            description=item.reason,
            path=f"/operations/actions/{item.id}",
        )
        for item in actions
        if current_user.role is not UserRole.OPERATOR
        or item.assigned_user_id == current_user.id
        or (
            item.assigned_user_id is None
            and item.priority
            in (
                OperationalActionPriority.CRITICAL,
                OperationalActionPriority.HIGH,
            )
        )
    )
    if is_tenant_administrator(current_user.role):
        users = (
            await session.execute(
                select(User)
                .where(
                    User.company_id == current_user.company_id,
                    User.email.ilike(pattern),
                )
                .order_by(User.email.asc())
                .limit(limit)
            )
        ).scalars()
        results.extend(
            OperationalSearchResult(
                id=item.id,
                resource_type="user",
                label=item.email,
                description=item.role.value,
                path="/users",
            )
            for item in users
        )
    order = {
        "operational_action": 0,
        "alert": 1,
        "machine": 2,
        "factory": 3,
        "sensor": 4,
        "user": 5,
    }
    results.sort(key=lambda item: (order[item.resource_type], item.label.casefold()))
    return OperationalSearchResponse(items=results[:limit], limit=limit)
