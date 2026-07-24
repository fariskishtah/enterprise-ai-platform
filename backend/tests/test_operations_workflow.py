"""Focused operational workflow, authorization, timeline, and audit coverage."""

from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.config.settings import Settings
from app.ml.monitoring.evaluation_models import (
    MonitoringAlertSeverity,
    MonitoringAlertStatus,
    MonitoringAlertType,
)
from app.models.manufacturing import Company, Factory, Machine
from app.models.monitoring_orchestration import MonitoringAlertEntity
from app.models.operations import (
    OperationalAction,
    OperationalActionPriority,
    OperationalActionStatus,
)
from app.models.pilot import MachineRiskAssessment
from app.models.user import User, UserRole
from app.repositories.users import UserRepository
from app.services.users import UserService
from app.utils.passwords import PasswordHasher
from app.utils.security import utc_now
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import (
    VALID_PASSWORD,
    ai_api_client,
    auth_headers,
)


async def _identity(
    session_factory: async_sessionmaker[AsyncSession], email: str
) -> User:
    async with session_factory() as session:
        user = await session.scalar(
            select(User)
            .where(User.email == email)
            .execution_options(skip_tenant_scope=True)
        )
        assert user is not None
        return user


@pytest.mark.anyio
async def test_action_alert_feedback_shift_timeline_and_audit_workflow(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    enabled = settings.model_copy(
        update={
            "simplified_experience_enabled": True,
            "operations_workflow_enabled": True,
        }
    )
    async with ai_api_client(enabled, session_factory, tmp_path=tmp_path) as (
        client,
        _application,
    ):
        admin_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="operations-admin@example.com",
        )
        engineer_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="operations-engineer@example.com",
        )
        operator_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="operations-operator@example.com",
        )
        other_operator_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="operations-other-operator@example.com",
        )
        operator = await _identity(session_factory, "operations-operator@example.com")

        company = await client.get("/users/me", headers=admin_headers)
        company_id = company.json()["company_id"]
        factory = await client.post(
            "/factories",
            headers=admin_headers,
            json={
                "company_id": company_id,
                "name": "Operations Factory",
                "location": "Alexandria",
            },
        )
        assert factory.status_code == 201, factory.text
        factory_id = UUID(factory.json()["id"])
        machine = await client.post(
            "/machines",
            headers=admin_headers,
            json={
                "factory_id": str(factory_id),
                "name": "Operations CNC",
                "serial_number": "OPS-001",
            },
        )
        assert machine.status_code == 201, machine.text
        machine_id = UUID(machine.json()["id"])

        now = utc_now()
        alert_id = uuid4()
        async with session_factory() as session:
            session.add(
                MonitoringAlertEntity(
                    id=alert_id,
                    company_id=operator.company_id,
                    factory_id=factory_id,
                    machine_id=machine_id,
                    alert_type=MonitoringAlertType.MACHINE_RISK,
                    severity=MonitoringAlertSeverity.CRITICAL,
                    registered_model_name="operations_risk_model",
                    model_version="1",
                    title="Inspect spindle before next cycle",
                    safe_summary="A critical machine risk indication requires review.",
                    deduplication_key=uuid4().hex,
                    status=MonitoringAlertStatus.OPEN,
                    first_detected_at=now,
                    last_detected_at=now,
                    occurrence_count=1,
                )
            )
            session.add(
                MachineRiskAssessment(
                    company_id=operator.company_id,
                    factory_id=factory_id,
                    machine_id=machine_id,
                    alert_id=alert_id,
                    registered_model_name="operations_risk_model",
                    model_version="1",
                    risk_state="critical",
                    risk_score=0.93,
                    sensor_values=[],
                    data_freshness_seconds=3.0,
                    recommended_action="Inspect spindle before the next cycle.",
                    monitoring_status="healthy",
                    assessed_at=now,
                )
            )
            await session.commit()

        created = await client.post(
            "/operations/actions",
            headers=admin_headers,
            json={
                "factory_id": str(factory_id),
                "machine_id": str(machine_id),
                "related_alert_id": str(alert_id),
                "title": "Inspect spindle bearings",
                "reason": "Critical vibration and temperature indication.",
                "recommended_action": "Inspect lubrication and bearing condition.",
                "priority": "critical",
                "assigned_user_id": str(operator.id),
                "due_at": (now + timedelta(hours=2)).isoformat(),
            },
        )
        assert created.status_code == 201, created.text
        action = created.json()
        action_id = action["id"]
        assert action["status"] == "assigned"

        admin_assignees = await client.get(
            "/operations/assignees", headers=admin_headers
        )
        assert admin_assignees.status_code == 200
        assert str(operator.id) in {item["id"] for item in admin_assignees.json()}
        engineer_assignees = await client.get(
            "/operations/assignees", headers=engineer_headers
        )
        assert engineer_assignees.status_code == 200
        operator_assignees = await client.get(
            "/operations/assignees", headers=operator_headers
        )
        assert operator_assignees.status_code == 403

        operator_list = await client.get(
            "/operations/actions", headers=operator_headers
        )
        assert operator_list.status_code == 200
        assert [item["id"] for item in operator_list.json()["items"]] == [action_id]
        hidden_from_other_operator = await client.get(
            f"/operations/actions/{action_id}", headers=other_operator_headers
        )
        assert hidden_from_other_operator.status_code == 404

        acknowledged = await client.post(
            f"/operations/actions/{action_id}/acknowledge",
            headers=operator_headers,
            json={
                "expected_version": action["version"],
                "note": "Beginning the inspection at the next safe stop.",
            },
        )
        assert acknowledged.status_code == 200, acknowledged.text
        started = await client.post(
            f"/operations/actions/{action_id}/transition",
            headers=operator_headers,
            json={
                "status": "in_progress",
                "expected_version": acknowledged.json()["version"],
            },
        )
        assert started.status_code == 200, started.text
        completed = await client.post(
            f"/operations/actions/{action_id}/transition",
            headers=operator_headers,
            json={
                "status": "completed",
                "expected_version": started.json()["version"],
                "summary": "Lubrication restored and bearing inspection completed.",
            },
        )
        assert completed.status_code == 200, completed.text
        invalid_return = await client.post(
            f"/operations/actions/{action_id}/transition",
            headers=operator_headers,
            json={
                "status": "in_progress",
                "expected_version": completed.json()["version"],
            },
        )
        assert invalid_return.status_code == 409

        appended_note = await client.post(
            f"/operations/actions/{action_id}/notes",
            headers=operator_headers,
            json={"body": "Final operator note retained separately from completion."},
        )
        assert appended_note.status_code == 201, appended_note.text

        feedback = await client.post(
            "/operations/maintenance-feedback",
            headers=operator_headers,
            json={
                "action_id": action_id,
                "alert_id": str(alert_id),
                "outcome": "maintenance_performed",
                "maintenance_category": "lubrication",
                "downtime_minutes": 18,
                "summary": "Spindle lubrication restored after inspection.",
            },
        )
        assert feedback.status_code == 201, feedback.text
        feedback_history = await client.get(
            "/operations/maintenance-feedback",
            headers=engineer_headers,
            params={"action_id": action_id},
        )
        assert feedback_history.status_code == 200, feedback_history.text
        assert feedback_history.json()["items"][0]["id"] == feedback.json()["id"]
        feedback_export = await client.get(
            "/operations/maintenance-feedback/export.csv",
            headers=engineer_headers,
            params={"action_id": action_id},
        )
        assert feedback_export.status_code == 200, feedback_export.text
        assert feedback_export.headers["content-type"].startswith("text/csv")
        assert "Spindle lubrication restored" in feedback_export.text
        operator_feedback_export = await client.get(
            "/operations/maintenance-feedback",
            headers=operator_headers,
            params={"action_id": action_id},
        )
        assert operator_feedback_export.status_code == 403

        assigned_alert = await client.post(
            f"/operations/alerts/{alert_id}/lifecycle",
            headers=admin_headers,
            json={
                "transition": "assign",
                "expected_version": 1,
                "assigned_user_id": str(operator.id),
            },
        )
        assert assigned_alert.status_code == 200, assigned_alert.text
        escalated_alert = await client.post(
            f"/operations/alerts/{alert_id}/lifecycle",
            headers=operator_headers,
            json={
                "transition": "escalate",
                "expected_version": assigned_alert.json()["lifecycle_version"],
                "note": "Escalating the critical spindle indication.",
            },
        )
        assert escalated_alert.status_code == 200, escalated_alert.text
        acknowledged_alert = await client.post(
            f"/operations/alerts/{alert_id}/lifecycle",
            headers=operator_headers,
            json={
                "transition": "acknowledge",
                "expected_version": escalated_alert.json()["lifecycle_version"],
                "note": "Machine is held for inspection.",
            },
        )
        assert acknowledged_alert.status_code == 200, acknowledged_alert.text
        started_alert = await client.post(
            f"/operations/alerts/{alert_id}/lifecycle",
            headers=operator_headers,
            json={
                "transition": "start",
                "expected_version": acknowledged_alert.json()["lifecycle_version"],
            },
        )
        assert started_alert.status_code == 200, started_alert.text
        operator_resolve = await client.post(
            f"/operations/alerts/{alert_id}/lifecycle",
            headers=operator_headers,
            json={
                "transition": "resolve",
                "expected_version": started_alert.json()["lifecycle_version"],
                "resolution_summary": "Inspection complete.",
                "resolution_classification": "maintenance_performed",
            },
        )
        assert operator_resolve.status_code == 403
        resolved_alert = await client.post(
            f"/operations/alerts/{alert_id}/lifecycle",
            headers=engineer_headers,
            json={
                "transition": "resolve",
                "expected_version": started_alert.json()["lifecycle_version"],
                "resolution_summary": "Verified lubrication and bearing condition.",
                "resolution_classification": "maintenance_performed",
            },
        )
        assert resolved_alert.status_code == 200, resolved_alert.text
        assert resolved_alert.json()["status"] == "resolved"
        reopened_alert = await client.post(
            f"/operations/alerts/{alert_id}/lifecycle",
            headers=admin_headers,
            json={
                "transition": "reopen",
                "expected_version": resolved_alert.json()["lifecycle_version"],
                "reopen_reason": "A follow-up vibration check remains due.",
            },
        )
        assert reopened_alert.status_code == 200, reopened_alert.text
        assert reopened_alert.json()["status"] == "open"

        shift = await client.post(
            "/operations/shifts",
            headers=operator_headers,
            json={"factory_id": str(factory_id), "team_label": "Day shift"},
        )
        assert shift.status_code == 201, shift.text
        duplicate_shift = await client.post(
            "/operations/shifts",
            headers=admin_headers,
            json={"factory_id": str(factory_id), "team_label": "Duplicate"},
        )
        assert duplicate_shift.status_code == 409
        ended_shift = await client.post(
            f"/operations/shifts/{shift.json()['id']}/end",
            headers=operator_headers,
            json={
                "handover_notes": "Inspection complete; repeat vibration check.",
                "unresolved_summary": "Follow-up alert remains open.",
            },
        )
        assert ended_shift.status_code == 200, ended_shift.text
        assert {
            "alerts_during_shift_count",
            "completed_action_count",
            "critical_machine_count",
            "open_action_count",
            "unresolved_alert_count",
        } == set(ended_shift.json()["snapshot"])
        assert ended_shift.json()["snapshot"]["critical_machine_count"] == 1
        acknowledged_shift = await client.post(
            f"/operations/shifts/{shift.json()['id']}/acknowledge",
            headers=other_operator_headers,
            json={"acknowledgement_note": "Night shift has accepted the handover."},
        )
        assert acknowledged_shift.status_code == 200, acknowledged_shift.text
        assert acknowledged_shift.json()["status"] == "acknowledged"

        timeline = await client.get(
            "/operations/timeline",
            headers=operator_headers,
            params={"machine_id": str(machine_id), "limit": 100},
        )
        assert timeline.status_code == 200, timeline.text
        event_types = {item["event_type"] for item in timeline.json()["items"]}
        assert {
            "action.created",
            "action.assigned",
            "action.acknowledged",
            "action.in_progress",
            "action.completed",
            "note.added",
            "maintenance.feedback_submitted",
            "machine_risk.assessed",
            "alert.created",
            "alert.assign",
            "alert.escalate",
            "alert.acknowledge",
            "alert.start",
            "alert.resolve",
            "alert.reopen",
        } <= event_types

        search = await client.get(
            "/operations/search",
            headers=operator_headers,
            params={"query": "Operations", "limit": 20},
        )
        assert search.status_code == 200, search.text
        assert {"factory", "machine"} <= {
            item["resource_type"] for item in search.json()["items"]
        }
        summary = await client.get("/operations/summary", headers=admin_headers)
        assert summary.status_code == 200, summary.text

        audit = await client.get(
            "/audit-events", headers=admin_headers, params={"limit": 100}
        )
        assert audit.status_code == 200
        audit_actions = {item["action"] for item in audit.json()["items"]}
        assert {
            "operational_action.created",
            "operational_action.assigned",
            "operational_action.acknowledged",
            "operational_action.in_progress",
            "operational_action.completed",
            "operational_note.added",
            "maintenance_feedback.submitted",
            "alert.assign",
            "alert.escalate",
            "alert.acknowledge",
            "alert.resolve",
            "alert.reopen",
            "shift.started",
            "shift.ended",
            "shift.handover_acknowledged",
        } <= audit_actions


@pytest.mark.anyio
async def test_operations_feature_flag_and_cross_company_scope(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        _application,
    ):
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="operations-disabled@example.com",
        )
        disabled = await client.get("/operations/actions", headers=headers)
        assert disabled.status_code == 404

    enabled = settings.model_copy(update={"operations_workflow_enabled": True})
    async with ai_api_client(enabled, session_factory, tmp_path=tmp_path) as (
        client,
        _application,
    ):
        tenant_a_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="operations-tenant-a@example.com",
        )
        async with session_factory() as session:
            company_b = Company(
                name="Operations Tenant B",
                normalized_name="operations tenant b",
            )
            session.add(company_b)
            await session.flush()
            tenant_b_admin = await UserService(
                repository=UserRepository(session),
                password_hasher=PasswordHasher(),
            ).create_user(
                email="operations-tenant-b@example.com",
                password=VALID_PASSWORD,
                role=UserRole.ADMIN,
                company_id=company_b.id,
            )
            factory_b = Factory(
                company_id=company_b.id,
                name="Tenant B Factory",
            )
            session.add(factory_b)
            await session.flush()
            machine_b = Machine(factory_id=factory_b.id, name="Tenant B Machine")
            session.add(machine_b)
            await session.flush()
            action_b = OperationalAction(
                company_id=company_b.id,
                factory_id=factory_b.id,
                machine_id=machine_b.id,
                title="Tenant B private action",
                reason="Tenant-isolation fixture.",
                recommended_action="Remain private.",
                priority=OperationalActionPriority.HIGH,
                status=OperationalActionStatus.ASSIGNED,
                assigned_user_id=tenant_b_admin.id,
                created_by=tenant_b_admin.id,
            )
            session.add(action_b)
            await session.commit()
            action_b_id = action_b.id

        hidden = await client.get(
            f"/operations/actions/{action_b_id}", headers=tenant_a_headers
        )
        assert hidden.status_code == 404
