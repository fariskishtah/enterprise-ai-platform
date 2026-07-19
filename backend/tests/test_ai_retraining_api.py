"""Retraining API RBAC, safe transport, and OpenAPI tests."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from app.config.settings import Settings
from app.dependencies.services import get_retraining_service
from app.ml.monitoring import DriftSeverity
from app.ml.retraining import (
    CooldownState,
    QuotaState,
    RetrainingAuditRecord,
    RetrainingDecision,
    RetrainingDecisionStatus,
    RetrainingEvaluationMode,
    RetrainingPolicy,
    RetrainingRequest,
    RetrainingTrigger,
    RetrainingTriggerType,
)
from app.ml.retraining.service import RetrainingEvaluationResult
from app.models.user import UserRole
from app.repositories.ai_retraining import RetrainingAuditPage, RetrainingRequestPage
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import ai_api_client, auth_headers

NOW = datetime(2026, 7, 18, 12, tzinfo=UTC)
POLICY_ID = UUID("00000000-0000-0000-0000-000000000301")
USER_ID = UUID("00000000-0000-0000-0000-000000000302")


def _policy() -> RetrainingPolicy:
    return RetrainingPolicy(
        id=POLICY_ID,
        registered_model_name="factory_quality",
        enabled=True,
        allowed_trigger_types=frozenset(RetrainingTriggerType),
        minimum_drift_status=DriftSeverity.CRITICAL,
        minimum_current_sample_count=20,
        cooldown_seconds=3600,
        maximum_requests_per_day=1,
        maximum_requests_per_week=3,
        maximum_active_requests=1,
        require_champion_source=True,
        allow_truncated_drift=True,
        created_by_user_id=USER_ID,
        created_at=NOW,
        updated_at=NOW,
    )


def _decision() -> RetrainingDecision:
    return RetrainingDecision(
        registered_model_name="factory_quality",
        source_model_version="3",
        requested_alias="champion",
        trigger=RetrainingTrigger(
            RetrainingTriggerType.FEATURE_DRIFT,
            "window:3:start:end",
            DriftSeverity.CRITICAL,
            25,
            25,
            25,
            False,
            None,
            {"psi_critical": 0.25},
        ),
        status=RetrainingDecisionStatus.BLOCKED_COOLDOWN,
        reasons=("The exact model is inside cooldown.",),
        evaluated_at=NOW,
        cooldown=CooldownState(True, NOW, NOW, 120),
        quota=QuotaState(0, 0, 0, 1, 3, 1),
    )


class FakeRetrainingService:
    async def put_policy(self, **arguments: object) -> RetrainingPolicy:
        _ = arguments
        return _policy()

    async def get_policy(self, registered_model_name: str) -> RetrainingPolicy:
        assert registered_model_name == "factory_quality"
        return _policy()

    async def list_policies(
        self, *, limit: int, offset: int
    ) -> tuple[RetrainingPolicy, ...]:
        _ = (limit, offset)
        return (_policy(),)

    async def evaluate_automatic(
        self, **arguments: object
    ) -> RetrainingEvaluationResult:
        _ = arguments
        return RetrainingEvaluationResult(_decision(), None)

    async def request_manual(self, **arguments: object) -> RetrainingEvaluationResult:
        _ = arguments
        raise AssertionError(
            "Engineer cooldown override must be rejected in transport."
        )

    async def list_requests(self, **arguments: object) -> RetrainingRequestPage:
        _ = arguments
        return RetrainingRequestPage((), 0)

    async def aggregate_status(self) -> tuple[int, int, int, int]:
        return 4, 1, 2, 1

    async def get_request(self, request_id: UUID) -> RetrainingRequest:
        _ = request_id
        raise AssertionError("Not used by this transport test.")

    async def list_audits(self, *, limit: int, offset: int) -> RetrainingAuditPage:
        _ = (limit, offset)
        audit = RetrainingAuditRecord(
            id=UUID("00000000-0000-0000-0000-000000000303"),
            decision=_decision(),
            policy_id=POLICY_ID,
            evaluated_by_user_id=USER_ID,
            evaluation_mode=RetrainingEvaluationMode.AUTOMATIC,
            override_used=False,
            override_reason=None,
            created_request_id=None,
        )
        return RetrainingAuditPage((audit,), 1)


@pytest.mark.anyio
async def test_retraining_api_enforces_roles_and_returns_bounded_decision(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    service = FakeRetrainingService()
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_retraining_service] = lambda: service
        admin_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="retraining-admin@example.com",
        )
        engineer_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="retraining-engineer@example.com",
        )
        operator_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="retraining-operator@example.com",
        )

        policy_update = await client.put(
            "/ai/retraining/policies/factory_quality",
            headers=admin_headers,
            json={},
        )
        engineer_policy_update = await client.put(
            "/ai/retraining/policies/factory_quality",
            headers=engineer_headers,
            json={},
        )
        evaluated = await client.post(
            "/ai/retraining/models/factory_quality/versions/champion/evaluate",
            headers=engineer_headers,
            json={"trigger_type": "feature_drift", "submit_if_eligible": True},
        )
        operator_evaluation = await client.post(
            "/ai/retraining/models/factory_quality/versions/champion/evaluate",
            headers=operator_headers,
            json={"trigger_type": "feature_drift"},
        )
        operator_status = await client.get(
            "/ai/retraining/status", headers=operator_headers
        )
        engineer_override = await client.post(
            "/ai/retraining/models/factory_quality/versions/3/requests",
            headers=engineer_headers,
            json={"reason": "controlled rerun", "override_cooldown": True},
        )
        engineer_audits = await client.get(
            "/ai/retraining/audits", headers=engineer_headers
        )
        admin_audits = await client.get("/ai/retraining/audits", headers=admin_headers)

    assert policy_update.status_code == 200
    assert policy_update.json()["minimum_drift_status"] == "critical"
    assert engineer_policy_update.status_code == 403
    assert evaluated.status_code == 200
    assert evaluated.json()["decision"]["decision_status"] == "blocked_cooldown"
    assert evaluated.json()["request"] is None
    assert "training_features" not in evaluated.text
    assert "idempotency_key" not in evaluated.text
    assert "artifact" not in evaluated.text
    assert operator_evaluation.status_code == 403
    assert operator_status.status_code == 200
    assert operator_status.json() == {
        "total_requests": 4,
        "active_requests": 1,
        "completed_requests": 2,
        "failed_requests": 1,
    }
    assert engineer_override.status_code == 403
    assert engineer_audits.status_code == 403
    assert admin_audits.status_code == 200
    assert admin_audits.json()["total"] == 1


def test_retraining_openapi_documents_governed_endpoints(settings: Settings) -> None:
    from app.core.application import create_app

    schema = create_app(settings).openapi()
    paths = schema["paths"]

    assert "/ai/retraining/policies/{registered_model_name}" in paths
    assert (
        "/ai/retraining/models/{registered_model_name}/versions/"
        "{version_or_alias}/evaluate"
    ) in paths
    assert "/ai/retraining/requests/{request_id}/comparison" in paths
    assert "403" in paths["/ai/retraining/audits"]["get"]["responses"]
