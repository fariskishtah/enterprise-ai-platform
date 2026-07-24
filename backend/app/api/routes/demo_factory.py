"""Feature-gated deterministic demo simulator and 2D factory layout APIs."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies.auth import get_current_user, require_roles
from app.dependencies.database import get_db_session
from app.dependencies.features import require_feature
from app.dependencies.rate_limit import enforce_mutation_rate_limit
from app.dependencies.services import get_audit_service
from app.ml.monitoring.evaluation_models import (
    MonitoringAlertSeverity,
    MonitoringAlertStatus,
    MonitoringAlertType,
)
from app.models.demo_experience import (
    DemoScenarioRun,
    DemoScenarioStatus,
    FactoryLayout,
)
from app.models.manufacturing import Factory, Machine
from app.models.monitoring_orchestration import MonitoringAlertEntity
from app.models.operations import (
    OperationalAction,
    OperationalActionPriority,
    OperationalActionStatus,
    OperationalTimelineEvent,
)
from app.models.pilot import MachineRiskAssessment
from app.models.sensor import Sensor
from app.models.sensor_data import ReadingQuality, ReadingSource, SensorReading
from app.models.user import User, UserRole
from app.schemas.demo_experience import (
    DemoScenarioName,
    DemoScenarioResponse,
    DemoScenarioStart,
    FactoryLayoutResponse,
    FactoryLayoutUpdate,
)
from app.services.audit import AuditService
from app.utils.security import utc_now

router = APIRouter(
    prefix="/demo",
    tags=["demo"],
    dependencies=[Depends(require_feature("demo_tools_enabled"))],
)

SCENARIOS: dict[DemoScenarioName, tuple[tuple[float | None, str, str], ...]] = {
    DemoScenarioName.NORMAL: ((0.35, "normal", "Stable operation"),) * 4,
    DemoScenarioName.DEGRADATION: (
        (0.35, "normal", "Stable operation"),
        (0.5, "observe", "Early degradation"),
        (0.65, "warning", "Degradation requires review"),
        (0.78, "warning", "Maintenance should be planned"),
    ),
    DemoScenarioName.WARNING: (
        (0.55, "observe", "Condition changing"),
        (0.72, "warning", "Inspect the machine"),
        (0.74, "warning", "Warning persists"),
    ),
    DemoScenarioName.CRITICAL: (
        (0.72, "warning", "Inspect the machine"),
        (0.92, "critical", "Stop and inspect safely"),
        (0.95, "critical", "Critical condition persists"),
    ),
    DemoScenarioName.SENSOR_FAULT: (
        (0.4, "normal", "Stable operation"),
        (0.7, "warning", "Sensor signal is invalid"),
    ),
    DemoScenarioName.DATA_DROPOUT: (
        (0.4, "normal", "Stable operation"),
        (None, "insufficient_data", "No current sensor data"),
    ),
    DemoScenarioName.MAINTENANCE: (
        (0.78, "warning", "Maintenance in progress"),
        (0.5, "observe", "Verification after maintenance"),
        (0.32, "normal", "Maintenance completed"),
    ),
    DemoScenarioName.RECOVERY: (
        (0.9, "critical", "Recovery initiated"),
        (0.62, "warning", "Condition improving"),
        (0.45, "observe", "Continue observation"),
        (0.3, "normal", "Recovered to normal"),
    ),
}


async def _machine(
    session: AsyncSession, company_id: UUID, machine_id: UUID
) -> tuple[Machine, Factory]:
    row = (
        await session.execute(
            select(Machine, Factory)
            .join(Factory, Machine.factory_id == Factory.id)
            .where(
                Machine.id == machine_id,
                Factory.company_id == company_id,
                Machine.deleted_at.is_(None),
                Factory.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Machine not found.")
    return row[0], row[1]


async def _run(
    session: AsyncSession,
    company_id: UUID,
    run_id: UUID,
    *,
    for_update: bool = False,
) -> DemoScenarioRun:
    statement = select(DemoScenarioRun).where(
        DemoScenarioRun.id == run_id,
        DemoScenarioRun.company_id == company_id,
    )
    if for_update:
        statement = statement.with_for_update()
    value = await session.scalar(statement)
    if value is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Demo scenario not found.")
    return value


@router.get("/scenarios")
async def list_scenarios(
    _user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
) -> list[dict[str, object]]:
    return [
        {
            "id": name.value,
            "duration_steps": len(steps),
            "sequence": [
                {"risk_score": score, "risk_state": state, "expected_action": action}
                for score, state, action in steps
            ],
            "fixed_seed": 17,
        }
        for name, steps in SCENARIOS.items()
    ]


@router.post(
    "/runs",
    response_model=DemoScenarioResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def start_scenario(
    payload: DemoScenarioStart,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> DemoScenarioResponse:
    machine, factory = await _machine(session, user.company_id, payload.machine_id)
    if factory.id != payload.factory_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Machine not found.")
    existing = await session.scalar(
        select(DemoScenarioRun).where(
            DemoScenarioRun.company_id == user.company_id,
            DemoScenarioRun.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        return DemoScenarioResponse.model_validate(existing)
    active = await session.scalar(
        select(DemoScenarioRun).where(
            DemoScenarioRun.machine_id == machine.id,
            DemoScenarioRun.status.in_(
                [DemoScenarioStatus.RUNNING.value, DemoScenarioStatus.PAUSED.value]
            ),
        )
    )
    if active is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This machine already has an active demo scenario.",
        )
    now = utc_now()
    run = DemoScenarioRun(
        company_id=user.company_id,
        factory_id=factory.id,
        machine_id=machine.id,
        scenario=payload.scenario.value,
        status=DemoScenarioStatus.RUNNING.value,
        speed=payload.speed,
        state_snapshot={
            "risk_state": "normal",
            "expected_next_event": SCENARIOS[payload.scenario][0][2],
        },
        idempotency_key=payload.idempotency_key,
        created_by=user.id,
        started_at=now,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    await audit.record(
        company_id=user.company_id,
        actor=user,
        action="demo.scenario_started",
        resource_type="demo_scenario",
        resource_id=run.id,
        result="success",
        metadata={"scenario": run.scenario, "speed": run.speed},
    )
    return DemoScenarioResponse.model_validate(run)


@router.get("/runs/{run_id}", response_model=DemoScenarioResponse)
async def get_scenario(
    run_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DemoScenarioResponse:
    return DemoScenarioResponse.model_validate(
        await _run(session, user.company_id, run_id)
    )


@router.post(
    "/runs/{run_id}/advance",
    response_model=DemoScenarioResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def advance_scenario(
    run_id: UUID,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DemoScenarioResponse:
    run = await _run(session, user.company_id, run_id, for_update=True)
    if run.status != DemoScenarioStatus.RUNNING.value:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Only a running scenario can advance."
        )
    scenario = DemoScenarioName(run.scenario)
    steps = SCENARIOS[scenario]
    if run.current_step >= len(steps):
        run.status = DemoScenarioStatus.COMPLETED.value
        await session.commit()
        return DemoScenarioResponse.model_validate(run)
    score, risk_state, expected_action = steps[run.current_step]
    now = run.started_at + timedelta(seconds=run.current_step * 10)
    resources = list(run.generated_resources)
    sensors = list(
        (
            await session.scalars(
                select(Sensor).where(
                    Sensor.machine_id == run.machine_id, Sensor.deleted_at.is_(None)
                )
            )
        ).all()
    )
    if score is not None:
        for index, sensor in enumerate(sensors[:8]):
            value = sensor.min_value + (sensor.max_value - sensor.min_value) * min(
                0.95, max(0.05, score + index * 0.002)
            )
            reading = SensorReading(
                sensor_id=sensor.id,
                timestamp=now,
                value=value,
                quality=(
                    ReadingQuality.BAD
                    if scenario is DemoScenarioName.SENSOR_FAULT
                    else ReadingQuality.GOOD
                ),
                source=ReadingSource.SIMULATION,
            )
            session.add(reading)
            await session.flush()
            resources.append({"type": "sensor_reading", "id": str(reading.id)})
    risk = MachineRiskAssessment(
        company_id=run.company_id,
        factory_id=run.factory_id,
        machine_id=run.machine_id,
        registered_model_name="demo_deterministic_risk",
        model_version="1",
        risk_state=risk_state,
        risk_score=score,
        sensor_values=[],
        data_freshness_seconds=0 if score is not None else None,
        recommended_action=expected_action,
        monitoring_status="demo",
        assessed_at=now,
    )
    session.add(risk)
    await session.flush()
    resources.append({"type": "risk", "id": str(risk.id)})
    alert: MonitoringAlertEntity | None = None
    action: OperationalAction | None = None
    if risk_state in {"warning", "critical"} and not any(
        resource["type"] == "alert" for resource in resources
    ):
        severity = (
            MonitoringAlertSeverity.CRITICAL
            if risk_state == "critical"
            else MonitoringAlertSeverity.WARNING
        )
        alert = MonitoringAlertEntity(
            company_id=run.company_id,
            factory_id=run.factory_id,
            machine_id=run.machine_id,
            alert_type=MonitoringAlertType.MACHINE_RISK,
            severity=severity,
            registered_model_name="demo_deterministic_risk",
            model_version="1",
            title=f"Demo {risk_state} condition",
            safe_summary=expected_action,
            deduplication_key=hashlib.sha256(f"demo:{run.id}".encode()).hexdigest(),
            status=MonitoringAlertStatus.OPEN,
            first_detected_at=now,
            last_detected_at=now,
            occurrence_count=1,
        )
        session.add(alert)
        await session.flush()
        resources.append({"type": "alert", "id": str(alert.id)})
        action = OperationalAction(
            company_id=run.company_id,
            factory_id=run.factory_id,
            machine_id=run.machine_id,
            related_alert_id=alert.id,
            title=f"Respond to demo {risk_state} condition",
            reason="Deterministic demo scenario generated this condition.",
            recommended_action=expected_action,
            priority=(
                OperationalActionPriority.CRITICAL
                if risk_state == "critical"
                else OperationalActionPriority.HIGH
            ),
            status=OperationalActionStatus.OPEN,
            created_by=user.id,
            due_at=now + timedelta(hours=1),
        )
        session.add(action)
        await session.flush()
        resources.append({"type": "action", "id": str(action.id)})
    event = OperationalTimelineEvent(
        company_id=run.company_id,
        factory_id=run.factory_id,
        machine_id=run.machine_id,
        action_id=action.id if action else None,
        alert_id=alert.id if alert else None,
        actor_user_id=user.id,
        event_type="demo_scenario_advanced",
        title=f"Demo scenario: {risk_state}",
        detail=expected_action,
        safe_metadata={"demo_run_id": str(run.id), "step": run.current_step + 1},
        occurred_at=now,
    )
    session.add(event)
    await session.flush()
    resources.append({"type": "timeline", "id": str(event.id)})
    run.current_step += 1
    run.generated_readings += 0 if score is None else len(sensors[:8])
    run.generated_resources = resources
    run.state_snapshot = {
        "risk_state": risk_state,
        "risk_score": score,
        "alert_id": str(alert.id) if alert else None,
        "action_id": str(action.id) if action else None,
        "expected_next_event": (
            steps[run.current_step][2]
            if run.current_step < len(steps)
            else "Scenario complete"
        ),
    }
    if run.current_step >= len(steps):
        run.status = DemoScenarioStatus.COMPLETED.value
        run.stopped_at = now
    await session.commit()
    await session.refresh(run)
    return DemoScenarioResponse.model_validate(run)


@router.post("/runs/{run_id}/{command}", response_model=DemoScenarioResponse)
async def control_scenario(
    run_id: UUID,
    command: str,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DemoScenarioResponse:
    run = await _run(session, user.company_id, run_id, for_update=True)
    transitions = {
        ("running", "pause"): "paused",
        ("paused", "resume"): "running",
        ("running", "stop"): "stopped",
        ("paused", "stop"): "stopped",
    }
    target = transitions.get((run.status, command))
    if target is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Invalid demo scenario transition."
        )
    run.status = target
    if target == "stopped":
        run.stopped_at = utc_now()
    await session.commit()
    return DemoScenarioResponse.model_validate(run)


@router.delete("/runs/{run_id}/reset")
async def reset_scenario(
    run_id: UUID,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    audit: Annotated[AuditService, Depends(get_audit_service)],
) -> dict[str, int]:
    run = await _run(session, user.company_id, run_id, for_update=True)
    ids: dict[str, list[UUID]] = {}
    for resource in run.generated_resources:
        try:
            ids.setdefault(resource["type"], []).append(UUID(resource["id"]))
        except (KeyError, ValueError):
            continue
    deleted = 0
    for key, model in (
        ("timeline", OperationalTimelineEvent),
        ("action", OperationalAction),
        ("alert", MonitoringAlertEntity),
        ("risk", MachineRiskAssessment),
        ("sensor_reading", SensorReading),
    ):
        if ids.get(key):
            result = await session.execute(delete(model).where(model.id.in_(ids[key])))
            deleted += int(getattr(result, "rowcount", 0) or 0)
    await session.delete(run)
    await session.commit()
    await audit.record(
        company_id=user.company_id,
        actor=user,
        action="demo.scenario_reset",
        resource_type="demo_scenario",
        resource_id=run_id,
        result="success",
        metadata={"deleted_records": deleted},
    )
    return {"deleted_records": deleted}


@router.get(
    "/factories/{factory_id}/layout", response_model=FactoryLayoutResponse | None
)
async def get_layout(
    factory_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FactoryLayoutResponse | None:
    factory = await session.scalar(
        select(Factory).where(
            Factory.id == factory_id, Factory.company_id == user.company_id
        )
    )
    if factory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Factory not found.")
    layout = await session.scalar(
        select(FactoryLayout).where(FactoryLayout.factory_id == factory_id)
    )
    return FactoryLayoutResponse.model_validate(layout) if layout else None


@router.put(
    "/factories/{factory_id}/layout",
    response_model=FactoryLayoutResponse,
    dependencies=[Depends(enforce_mutation_rate_limit)],
)
async def save_layout(
    factory_id: UUID,
    payload: FactoryLayoutUpdate,
    user: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ENGINEER))],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> FactoryLayoutResponse:
    factory = await session.scalar(
        select(Factory).where(
            Factory.id == factory_id, Factory.company_id == user.company_id
        )
    )
    if factory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Factory not found.")
    machine_ids = set(
        (
            await session.scalars(
                select(Machine.id).where(
                    Machine.factory_id == factory_id, Machine.deleted_at.is_(None)
                )
            )
        ).all()
    )
    requested = {node.machine_id for node in payload.nodes}
    if not requested.issubset(machine_ids) or len(requested) != len(payload.nodes):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Layout nodes must reference unique machines in this factory.",
        )
    layout = await session.scalar(
        select(FactoryLayout).where(FactoryLayout.factory_id == factory_id)
    )
    nodes = [node.model_dump(mode="json") for node in payload.nodes]
    if layout is None:
        layout = FactoryLayout(
            company_id=user.company_id,
            factory_id=factory_id,
            nodes=nodes,
            updated_by=user.id,
        )
        session.add(layout)
    elif layout.nodes != nodes:
        layout.nodes = nodes
        layout.updated_by = user.id
        layout.version += 1
    await session.commit()
    await session.refresh(layout)
    return FactoryLayoutResponse.model_validate(layout)


@router.get("/factories/{factory_id}/tv")
async def tv_summary(
    factory_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict[str, object]:
    factory = await session.scalar(
        select(Factory).where(
            Factory.id == factory_id, Factory.company_id == user.company_id
        )
    )
    if factory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Factory not found.")
    machine_count = int(
        await session.scalar(
            select(func.count())
            .select_from(Machine)
            .where(Machine.factory_id == factory_id)
        )
        or 0
    )
    alerts = int(
        await session.scalar(
            select(func.count())
            .select_from(MonitoringAlertEntity)
            .where(
                MonitoringAlertEntity.company_id == user.company_id,
                MonitoringAlertEntity.factory_id == factory_id,
                MonitoringAlertEntity.status != MonitoringAlertStatus.RESOLVED,
            )
        )
        or 0
    )
    actions = int(
        await session.scalar(
            select(func.count())
            .select_from(OperationalAction)
            .where(
                OperationalAction.company_id == user.company_id,
                OperationalAction.factory_id == factory_id,
                OperationalAction.status != OperationalActionStatus.COMPLETED,
            )
        )
        or 0
    )
    return {
        "factory_id": factory.id,
        "factory_name": factory.name,
        "overall_state": "attention_required" if alerts else "normal",
        "machine_count": machine_count,
        "active_alerts": alerts,
        "urgent_actions": actions,
        "last_update": utc_now(),
        "read_only": True,
    }


@router.get("/factories/{factory_id}/map-state")
async def map_state(
    factory_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[dict[str, object]]:
    factory = await session.scalar(
        select(Factory).where(
            Factory.id == factory_id, Factory.company_id == user.company_id
        )
    )
    if factory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Factory not found.")
    machines = list(
        (
            await session.scalars(
                select(Machine).where(
                    Machine.factory_id == factory_id, Machine.deleted_at.is_(None)
                )
            )
        ).all()
    )
    result: list[dict[str, object]] = []
    for machine in machines:
        latest = await session.scalar(
            select(MachineRiskAssessment)
            .where(
                MachineRiskAssessment.company_id == user.company_id,
                MachineRiskAssessment.machine_id == machine.id,
            )
            .order_by(MachineRiskAssessment.assessed_at.desc())
            .limit(1)
        )
        alert_count = int(
            await session.scalar(
                select(func.count())
                .select_from(MonitoringAlertEntity)
                .where(
                    MonitoringAlertEntity.company_id == user.company_id,
                    MonitoringAlertEntity.machine_id == machine.id,
                    MonitoringAlertEntity.status != MonitoringAlertStatus.RESOLVED,
                )
            )
            or 0
        )
        action_count = int(
            await session.scalar(
                select(func.count())
                .select_from(OperationalAction)
                .where(
                    OperationalAction.company_id == user.company_id,
                    OperationalAction.machine_id == machine.id,
                    OperationalAction.status.not_in(
                        [
                            OperationalActionStatus.COMPLETED,
                            OperationalActionStatus.CANCELLED,
                        ]
                    ),
                )
            )
            or 0
        )
        result.append(
            {
                "machine_id": machine.id,
                "machine_name": machine.name,
                "state": latest.risk_state if latest else "insufficient_data",
                "alert_count": alert_count,
                "action_count": action_count,
                "assessed_at": latest.assessed_at if latest else None,
            }
        )
    return result
