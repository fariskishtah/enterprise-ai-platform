"""Persisted monitoring API RBAC, pagination, and OpenAPI tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from app.config.settings import Settings
from app.dependencies.services import (
    get_monitoring_alert_service,
    get_monitoring_evaluation_service,
)
from app.ml.base import TrainerKey
from app.ml.domain import AlgorithmType, TaskType
from app.ml.monitoring.evaluation_models import (
    ModelMonitoringEvaluation,
    MonitoringAlert,
    MonitoringAlertPage,
    MonitoringAlertSeverity,
    MonitoringAlertStatus,
    MonitoringAlertType,
    MonitoringEvaluationPage,
    MonitoringEvaluationStatus,
    MonitoringEvaluationTrigger,
)
from app.models.user import UserRole
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import ai_api_client, auth_headers

NOW = datetime(2026, 7, 19, 12, tzinfo=UTC)
EVALUATION_ID = UUID("00000000-0000-0000-0000-000000000901")
ALERT_ID = UUID("00000000-0000-0000-0000-000000000902")


def _evaluation() -> ModelMonitoringEvaluation:
    return ModelMonitoringEvaluation(
        id=EVALUATION_ID,
        registered_model_name="factory_quality",
        model_version="1",
        model_alias=None,
        key=TrainerKey(AlgorithmType.RANDOM_FOREST, TaskType.REGRESSION),
        window_start=NOW - timedelta(hours=24),
        window_end=NOW,
        evaluated_sample_count=25,
        successful_prediction_count=5,
        failed_prediction_count=0,
        data_quality_status=MonitoringEvaluationStatus.HEALTHY,
        feature_drift_status=MonitoringEvaluationStatus.HEALTHY,
        prediction_drift_status=MonitoringEvaluationStatus.HEALTHY,
        operational_health_status=MonitoringEvaluationStatus.HEALTHY,
        overall_status=MonitoringEvaluationStatus.HEALTHY,
        report_schema_version="1.0",
        report={"availability": {"error_code": None}},
        warning_count=0,
        critical_count=0,
        trigger=MonitoringEvaluationTrigger.MANUAL,
        idempotency_key="not-exposed",
        created_at=NOW,
        updated_at=NOW,
    )


def _alert() -> MonitoringAlert:
    return MonitoringAlert(
        id=ALERT_ID,
        alert_type=MonitoringAlertType.FEATURE_DRIFT,
        severity=MonitoringAlertSeverity.CRITICAL,
        registered_model_name="factory_quality",
        model_version="1",
        monitoring_evaluation_id=EVALUATION_ID,
        title="Critical feature drift detected",
        safe_summary="A safe aggregate condition was detected.",
        deduplication_key="not-exposed",
        status=MonitoringAlertStatus.OPEN,
        first_detected_at=NOW,
        last_detected_at=NOW,
        occurrence_count=1,
        acknowledged_at=None,
        acknowledged_by_user_id=None,
        resolved_at=None,
        created_at=NOW,
        updated_at=NOW,
    )


class FakeEvaluationService:
    async def evaluate(self, **arguments: object) -> ModelMonitoringEvaluation:
        _ = arguments
        return _evaluation()

    async def list(self, **arguments: object) -> MonitoringEvaluationPage:
        _ = arguments
        return MonitoringEvaluationPage((_evaluation(),), 1)

    async def get(self, evaluation_id: UUID) -> ModelMonitoringEvaluation:
        assert evaluation_id == EVALUATION_ID
        return _evaluation()

    async def latest(self, **arguments: object) -> ModelMonitoringEvaluation:
        _ = arguments
        return _evaluation()


class FakeAlertService:
    async def list(self, **arguments: object) -> MonitoringAlertPage:
        _ = arguments
        return MonitoringAlertPage((_alert(),), 1)

    async def get(self, alert_id: UUID) -> MonitoringAlert:
        assert alert_id == ALERT_ID
        return _alert()

    async def acknowledge(self, alert_id: UUID, actor_id: UUID) -> MonitoringAlert:
        _ = (alert_id, actor_id)
        return _alert()

    async def resolve(self, alert_id: UUID) -> MonitoringAlert:
        _ = alert_id
        return _alert()


@pytest.mark.anyio
async def test_monitoring_orchestration_api_enforces_roles_and_safe_responses(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_monitoring_evaluation_service] = (
            FakeEvaluationService
        )
        application.dependency_overrides[get_monitoring_alert_service] = (
            FakeAlertService
        )
        admin = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="monitoring-orchestration-admin@example.com",
        )
        engineer = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="monitoring-orchestration-engineer@example.com",
        )
        operator = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="monitoring-orchestration-operator@example.com",
        )

        triggered = await client.post(
            "/ai/monitoring/models/factory_quality/versions/1/evaluations",
            headers=engineer,
            json={
                "window_start": (NOW - timedelta(hours=24)).isoformat(),
                "window_end": NOW.isoformat(),
            },
        )
        operator_trigger = await client.post(
            "/ai/monitoring/models/factory_quality/versions/1/evaluations",
            headers=operator,
            json={},
        )
        operator_list = await client.get(
            "/ai/monitoring/evaluations?limit=10&offset=0", headers=operator
        )
        operator_alerts = await client.get("/ai/monitoring/alerts", headers=operator)
        operator_outcome = await client.put(
            f"/ai/monitoring/prediction-events/{EVALUATION_ID}/outcome",
            headers=operator,
            json={
                "actual_value": 1,
                "observed_at": NOW.isoformat(),
                "source": "governed_test",
                "label_maturity_at": NOW.isoformat(),
            },
        )
        admin_alerts = await client.get("/ai/monitoring/alerts", headers=admin)
        anonymous = await client.get("/ai/monitoring/evaluations")

    assert triggered.status_code == 200
    assert triggered.json()["model_version"] == "1"
    assert "idempotency_key" not in triggered.text
    assert operator_trigger.status_code == 403
    assert operator_list.status_code == 200
    assert operator_list.json()["total"] == 1
    assert operator_alerts.status_code == 403
    assert operator_outcome.status_code == 403
    assert admin_alerts.status_code == 200
    assert "deduplication_key" not in admin_alerts.text
    assert anonymous.status_code == 401


def test_monitoring_orchestration_openapi_has_all_governed_paths(
    settings: Settings,
) -> None:
    from app.core.application import create_app

    paths = create_app(settings).openapi()["paths"]
    assert "/ai/monitoring/evaluations" in paths
    assert "/ai/monitoring/evaluations/{evaluation_id}" in paths
    assert (
        "/ai/monitoring/models/{registered_model_name}/versions/"
        "{model_version}/status/latest"
    ) in paths
    assert "/ai/monitoring/alerts/{alert_id}/acknowledge" in paths
    assert "/ai/monitoring/alerts/{alert_id}/resolve" in paths
    assert "/ai/monitoring/prediction-events/{prediction_event_id}/outcome" in paths
    assert (
        "/ai/monitoring/models/{registered_model_name}/versions/"
        "{model_version}/performance"
    ) in paths
