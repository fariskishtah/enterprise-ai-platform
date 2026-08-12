"""Grounded executive dashboard, report export, and bounded schedules."""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import Settings, get_settings
from app.dependencies.auth import require_roles
from app.dependencies.database import get_db_session
from app.dependencies.datasets import get_dataset_storage
from app.dependencies.entitlements import (
    entitlement_http_error,
    get_entitlement_service,
    require_advanced_reports_entitlement,
)
from app.dependencies.rate_limit import enforce_mutation_rate_limit
from app.dependencies.services import get_audit_service
from app.ml.monitoring.evaluation_models import (
    MonitoringAlertSeverity,
    MonitoringAlertStatus,
)
from app.models.demo_experience import ReportJob, ReportSchedule, ReportStatus
from app.models.manufacturing import Company, Factory, Machine
from app.models.monitoring_orchestration import MonitoringAlertEntity
from app.models.operations import (
    MaintenanceFeedback,
    OperationalAction,
    OperationalActionStatus,
    OperationalNote,
    OperationalTimelineEvent,
    ShiftHandover,
)
from app.models.sensor import Sensor
from app.models.sensor_data import SensorReading
from app.models.user import User, UserRole
from app.schemas.demo_experience import (
    IncidentSummaryResponse,
    ReportCreate,
    ReportResponse,
    ReportScheduleCreate,
    ReportScheduleResponse,
)
from app.services.audit import AuditService
from app.services.entitlements import EntitlementError, EntitlementService
from app.services.reporting import report_payload
from app.utils.security import as_utc, utc_now

router = APIRouter(prefix="/reporting", tags=["reporting"])
MAX_REPORT_RANGE = timedelta(days=366)
DOWNLOAD_LIFETIME = timedelta(hours=1)


async def _factory_scope(
    session: AsyncSession, company_id: UUID, factory_id: UUID | None
) -> None:
    if factory_id is None:
        return
    exists = await session.scalar(
        select(Factory.id).where(
            Factory.id == factory_id,
            Factory.company_id == company_id,
            Factory.deleted_at.is_(None),
        )
    )
    if exists is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Factory not found.")


def _bounded_period(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    start_utc, end_utc = as_utc(start), as_utc(end)
    if start_utc >= end_utc or end_utc - start_utc > MAX_REPORT_RANGE:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Reporting periods must be positive and no longer than 366 days.",
        )
    return start_utc, end_utc


async def _metrics(
    session: AsyncSession,
    *,
    company_id: UUID,
    factory_id: UUID | None,
    start_at: datetime,
    end_at: datetime,
) -> dict[str, object]:
    """Return dashboard aggregates in one bounded database round trip."""
    machine_filters = [Factory.company_id == company_id, Machine.deleted_at.is_(None)]
    if factory_id:
        machine_filters.append(Factory.id == factory_id)
    machine_count = (
        select(func.count())
        .select_from(Machine)
        .join(Factory)
        .where(*machine_filters)
        .scalar_subquery()
    )
    alert_filters = [
        MonitoringAlertEntity.company_id == company_id,
        MonitoringAlertEntity.first_detected_at >= start_at,
        MonitoringAlertEntity.first_detected_at <= end_at,
    ]
    action_filters = [
        OperationalAction.company_id == company_id,
        OperationalAction.created_at >= start_at,
        OperationalAction.created_at <= end_at,
    ]
    if factory_id:
        alert_filters.append(MonitoringAlertEntity.factory_id == factory_id)
        action_filters.append(OperationalAction.factory_id == factory_id)

    open_alerts = (
        select(func.count())
        .select_from(MonitoringAlertEntity)
        .where(
            *alert_filters,
            MonitoringAlertEntity.status != MonitoringAlertStatus.RESOLVED,
        )
        .scalar_subquery()
    )
    critical_alerts = (
        select(func.count())
        .select_from(MonitoringAlertEntity)
        .where(
            *alert_filters,
            MonitoringAlertEntity.severity == MonitoringAlertSeverity.CRITICAL,
        )
        .scalar_subquery()
    )
    completed_actions = (
        select(func.count())
        .select_from(OperationalAction)
        .where(
            *action_filters,
            OperationalAction.status == OperationalActionStatus.COMPLETED,
        )
        .scalar_subquery()
    )
    now = utc_now()
    overdue_actions = (
        select(func.count())
        .select_from(OperationalAction)
        .where(
            *action_filters,
            OperationalAction.status.not_in(
                [OperationalActionStatus.COMPLETED, OperationalActionStatus.CANCELLED]
            ),
            OperationalAction.due_at < now,
        )
        .scalar_subquery()
    )
    acknowledgment_seconds = (
        select(
            func.avg(
                func.extract(
                    "epoch",
                    MonitoringAlertEntity.acknowledged_at
                    - MonitoringAlertEntity.first_detected_at,
                )
            )
        )
        .where(*alert_filters, MonitoringAlertEntity.acknowledged_at.is_not(None))
        .scalar_subquery()
    )
    resolution_seconds = (
        select(
            func.avg(
                func.extract(
                    "epoch",
                    MonitoringAlertEntity.resolved_at
                    - MonitoringAlertEntity.first_detected_at,
                )
            )
        )
        .where(*alert_filters, MonitoringAlertEntity.resolved_at.is_not(None))
        .scalar_subquery()
    )
    reading_filters = [Factory.company_id == company_id]
    if factory_id:
        reading_filters.append(Factory.id == factory_id)
    latest_reading = (
        select(func.max(SensorReading.timestamp))
        .join(Sensor, SensorReading.sensor_id == Sensor.id)
        .join(Machine, Sensor.machine_id == Machine.id)
        .join(Factory, Machine.factory_id == Factory.id)
        .where(*reading_filters)
        .scalar_subquery()
    )
    feedback_count = (
        select(func.count())
        .select_from(MaintenanceFeedback)
        .where(
            MaintenanceFeedback.company_id == company_id,
            MaintenanceFeedback.created_at >= start_at,
            MaintenanceFeedback.created_at <= end_at,
        )
        .scalar_subquery()
    )
    shift_count = (
        select(func.count())
        .select_from(ShiftHandover)
        .where(
            ShiftHandover.company_id == company_id,
            ShiftHandover.started_at >= start_at,
            ShiftHandover.started_at <= end_at,
        )
        .scalar_subquery()
    )
    row = (
        await session.execute(
            select(
                machine_count.label("machine_count"),
                open_alerts.label("open_alerts"),
                critical_alerts.label("critical_alerts"),
                overdue_actions.label("overdue_actions"),
                completed_actions.label("completed_actions"),
                acknowledgment_seconds.label("acknowledgment_seconds"),
                resolution_seconds.label("resolution_seconds"),
                latest_reading.label("latest_reading"),
                feedback_count.label("feedback_count"),
                shift_count.label("shift_count"),
            )
        )
    ).one()
    latest_reading_at = (
        row.latest_reading if isinstance(row.latest_reading, datetime) else None
    )
    return {
        "machine_count": int(row.machine_count or 0),
        "open_alerts": int(row.open_alerts or 0),
        "critical_alerts": int(row.critical_alerts or 0),
        "overdue_actions": int(row.overdue_actions or 0),
        "completed_actions": int(row.completed_actions or 0),
        "average_acknowledgement_seconds": (
            round(float(row.acknowledgment_seconds), 1)
            if row.acknowledgment_seconds
            else None
        ),
        "average_resolution_seconds": (
            round(float(row.resolution_seconds), 1) if row.resolution_seconds else None
        ),
        "data_freshness_at": (
            latest_reading_at.isoformat() if latest_reading_at else None
        ),
        "maintenance_feedback_count": int(row.feedback_count or 0),
        "shift_activity_count": int(row.shift_count or 0),
        "period_start": start_at.isoformat(),
        "period_end": end_at.isoformat(),
    }


@router.get("/executive-dashboard")
async def executive_dashboard(
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    factory_id: UUID | None = None,
    start_at: datetime | None = None,
    end_at: datetime | None = None,
) -> dict[str, object]:
    end = as_utc(end_at) if end_at else utc_now()
    start = as_utc(start_at) if start_at else end - timedelta(days=7)
    start, end = _bounded_period(start, end)
    await _factory_scope(session, user.company_id, factory_id)
    values = await _metrics(
        session,
        company_id=user.company_id,
        factory_id=factory_id,
        start_at=start,
        end_at=end,
    )
    definitions = {
        "open_alerts": "Alerts in the selected period that are not resolved.",
        "critical_alerts": "Critical-severity alerts first detected in the period.",
        "overdue_actions": "Incomplete actions whose due time has passed.",
        "completed_actions": "Actions completed in the selected period.",
        "average_acknowledgement_seconds": (
            "Mean alert detection-to-acknowledgement time."
        ),
        "average_resolution_seconds": "Mean alert detection-to-resolution time.",
    }
    return {
        "metrics": values,
        "definitions": definitions,
        "source": "Authorized company operational records",
        "time_range": {"start": start, "end": end},
        "drill_downs": {
            "open_alerts": "/monitoring/alerts",
            "overdue_actions": "/operations/actions",
            "machine_count": "/machines",
        },
        "limitations": (
            "No cost savings, ROI, avoided downtime, energy savings, or production "
            "efficiency is inferred."
        ),
    }


@router.post(
    "/reports",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(enforce_mutation_rate_limit),
        Depends(require_advanced_reports_entitlement),
    ],
)
async def create_report(
    payload: ReportCreate,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> ReportResponse:
    start, end = _bounded_period(payload.period_start, payload.period_end)
    await _factory_scope(session, user.company_id, payload.factory_id)
    existing = await session.scalar(
        select(ReportJob).where(
            ReportJob.company_id == user.company_id,
            ReportJob.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        return ReportResponse.model_validate(existing)
    job = ReportJob(
        company_id=user.company_id,
        factory_id=payload.factory_id,
        created_by=user.id,
        report_type=payload.report_type.value,
        format=payload.format.value,
        status=ReportStatus.GENERATING.value,
        period_start=start,
        period_end=end,
        idempotency_key=payload.idempotency_key,
    )
    session.add(job)
    await session.flush()
    summary = await _metrics(
        session,
        company_id=user.company_id,
        factory_id=payload.factory_id,
        start_at=start,
        end_at=end,
    )
    company_name = await session.scalar(
        select(Company.name).where(Company.id == user.company_id)
    )
    factory_name = (
        await session.scalar(
            select(Factory.name).where(Factory.id == payload.factory_id)
        )
        if payload.factory_id is not None
        else None
    )
    title = payload.report_type.value.replace("_", " ").title()
    body = report_payload(
        payload.format.value,
        title=title,
        summary=summary,
        tables={},
        metadata=(
            ("Company", company_name or "Authorized company"),
            ("Factory", factory_name or "All authorized factories"),
            ("Reporting period", f"{start.isoformat()} to {end.isoformat()}"),
            ("Generated", utc_now().isoformat()),
        ),
    )
    stored = get_dataset_storage(settings.dataset_storage_root).write(
        io.BytesIO(body), maximum_bytes=settings.dataset_upload_max_bytes
    )
    job.storage_key = stored.key
    job.size_bytes = stored.size_bytes
    job.sha256_digest = stored.sha256_digest
    job.summary = summary
    job.status = ReportStatus.COMPLETED.value
    job.completed_at = utc_now()
    job.expires_at = job.completed_at + DOWNLOAD_LIFETIME
    await session.commit()
    await session.refresh(job)
    await audit.record(
        company_id=user.company_id,
        actor=user,
        action="report.generated",
        resource_type="report",
        resource_id=job.id,
        result="success",
        metadata={"report_type": job.report_type, "format": job.format},
    )
    return ReportResponse.model_validate(job)


@router.get("/reports", response_model=list[ReportResponse])
async def list_reports(
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> list[ReportResponse]:
    jobs = (
        await session.scalars(
            select(ReportJob)
            .where(ReportJob.company_id == user.company_id)
            .order_by(ReportJob.created_at.desc())
            .limit(limit)
        )
    ).all()
    return [ReportResponse.model_validate(item) for item in jobs]


@router.get("/reports/{report_id}", response_model=ReportResponse)
async def get_report(
    report_id: UUID,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReportResponse:
    return ReportResponse.model_validate(
        await _report(session, user.company_id, report_id)
    )


async def _report(
    session: AsyncSession, company_id: UUID, report_id: UUID
) -> ReportJob:
    job = await session.scalar(
        select(ReportJob).where(
            ReportJob.id == report_id, ReportJob.company_id == company_id
        )
    )
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found.")
    return job


@router.get("/reports/{report_id}/download")
async def download_report(
    report_id: UUID,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    job = await _report(session, user.company_id, report_id)
    if (
        job.status != ReportStatus.COMPLETED.value
        or not job.storage_key
        or not job.expires_at
        or as_utc(job.expires_at) <= utc_now()
    ):
        raise HTTPException(status.HTTP_410_GONE, "The report download has expired.")
    body = get_dataset_storage(settings.dataset_storage_root).read(
        job.storage_key, maximum_bytes=settings.dataset_upload_max_bytes
    )
    media = {
        "pdf": "application/pdf",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "csv": "text/csv",
    }[job.format]
    filename = f"{job.report_type}-{job.id}.{job.format}"
    return Response(
        body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.post(
    "/schedules",
    response_model=ReportScheduleResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def create_schedule(
    payload: ReportScheduleCreate,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
    entitlements: Annotated[EntitlementService, Depends(get_entitlement_service)],
) -> ReportScheduleResponse:
    try:
        await entitlements.require_capacity(user.company_id, "scheduled_reports")
    except EntitlementError as exc:
        raise entitlement_http_error(exc) from exc
    await _factory_scope(session, user.company_id, payload.factory_id)
    existing = await session.scalar(
        select(ReportSchedule).where(
            ReportSchedule.company_id == user.company_id,
            ReportSchedule.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        return ReportScheduleResponse.model_validate(existing)
    if payload.enabled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Scheduled email delivery is unavailable because no mail provider "
            "is configured.",
        )
    schedule = ReportSchedule(
        company_id=user.company_id,
        factory_id=payload.factory_id,
        created_by=user.id,
        report_type=payload.report_type.value,
        format=payload.format.value,
        period=payload.period,
        cadence=payload.cadence,
        timezone=payload.timezone,
        recipients=[str(item) for item in payload.recipients],
        enabled=False,
        idempotency_key=payload.idempotency_key,
        last_result="delivery_unavailable",
        last_error="No supported mail provider is configured.",
    )
    session.add(schedule)
    await session.commit()
    await session.refresh(schedule)
    await audit.record(
        company_id=user.company_id,
        actor=user,
        action="report.schedule_created",
        resource_type="report_schedule",
        resource_id=schedule.id,
        result="success",
        metadata={"cadence": schedule.cadence, "enabled": False},
    )
    return ReportScheduleResponse.model_validate(schedule)


@router.get("/schedules", response_model=list[ReportScheduleResponse])
async def list_schedules(
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[ReportScheduleResponse]:
    values = (
        await session.scalars(
            select(ReportSchedule)
            .where(ReportSchedule.company_id == user.company_id)
            .order_by(ReportSchedule.created_at.desc())
            .limit(100)
        )
    ).all()
    return [ReportScheduleResponse.model_validate(item) for item in values]


@router.get("/incidents/machines/{machine_id}", response_model=IncidentSummaryResponse)
async def incident_summary(
    machine_id: UUID,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> IncidentSummaryResponse:
    machine, factory = (
        await session.execute(
            select(Machine, Factory)
            .join(Factory)
            .where(Machine.id == machine_id, Factory.company_id == user.company_id)
        )
    ).one_or_none() or (None, None)
    if machine is None or factory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Machine not found.")
    events = list(
        (
            await session.scalars(
                select(OperationalTimelineEvent)
                .where(
                    OperationalTimelineEvent.company_id == user.company_id,
                    OperationalTimelineEvent.machine_id == machine_id,
                )
                .order_by(OperationalTimelineEvent.occurred_at.asc())
                .limit(100)
            )
        ).all()
    )
    actions = list(
        (
            await session.scalars(
                select(OperationalAction)
                .where(
                    OperationalAction.company_id == user.company_id,
                    OperationalAction.machine_id == machine_id,
                )
                .order_by(OperationalAction.created_at.asc())
                .limit(100)
            )
        ).all()
    )
    notes = list(
        (
            await session.scalars(
                select(OperationalNote)
                .where(
                    OperationalNote.company_id == user.company_id,
                    OperationalNote.machine_id == machine_id,
                )
                .order_by(OperationalNote.created_at.asc())
                .limit(100)
            )
        ).all()
    )
    first = events[0].occurred_at if events else None
    resolution = next(
        (
            action.completion_summary
            for action in reversed(actions)
            if action.completion_summary
        ),
        "Unknown — no recorded resolution summary.",
    )
    current_status = (
        actions[-1].status.value
        if actions
        else "Unknown — no recorded operational action."
    )
    return IncidentSummaryResponse(
        machine_id=machine_id,
        what_happened=(
            events[0].detail
            if events
            else "Unknown — no machine timeline event is recorded."
        ),
        first_detected=first,
        actions_taken=[
            action.title
            for action in actions
            if action.status == OperationalActionStatus.COMPLETED
        ],
        resolution=resolution,
        current_status=current_status,
        follow_up_recommendations=(
            [note.body for note in notes[-3:]]
            or [
                "Review the machine with an authorized engineer; no recommendation "
                "is recorded."
            ]
        ),
    )
