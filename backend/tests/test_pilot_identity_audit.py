"""Focused acceptance coverage for the controlled-pilot foundations."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest
from app.config.settings import Settings
from app.dependencies.services import get_ai_monitored_prediction_service
from app.ml.domain import TaskType
from app.ml.jobs import RandomForestRegressionJobSpec, random_forest_key
from app.ml.registry import RegisteredModelVersion, RegisteredModelVersionStatus
from app.ml.services import RegisteredPredictionResult
from app.models.manufacturing import Company
from app.models.user import AuditEvent, PasswordResetToken, User, UserRole
from app.repositories.ai_governance import TrainingJobRepository
from app.repositories.users import UserRepository
from app.services.audit import safe_audit_metadata
from app.services.users import UserService
from app.utils.passwords import PasswordHasher
from app.utils.security import utc_now
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import VALID_PASSWORD, ai_api_client, auth_headers

NEW_PASSWORD = "ChangedPassword2!"
MODEL_NAME = "pilot_machine_risk"


async def _login(client, email: str, password: str = VALID_PASSWORD) -> dict[str, str]:
    response = await client.post(
        "/auth/login", json={"email": email, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _second_tenant_admin(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[Company, User]:
    async with session_factory() as session:
        company = Company(
            name="Isolated Pilot Company",
            normalized_name="isolated pilot company",
            description="Negative authorization boundary fixture.",
        )
        session.add(company)
        await session.flush()
        user = await UserService(
            repository=UserRepository(session),
            password_hasher=PasswordHasher(),
        ).create_user(
            email="tenant-b-admin@example.com",
            password=VALID_PASSWORD,
            role=UserRole.ADMIN,
            company_id=company.id,
        )
        return company, user


@pytest.mark.anyio
async def test_company_user_password_session_and_audit_lifecycle(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    exposed_settings = settings.model_copy(
        update={"expose_local_password_reset_token": True}
    )
    async with ai_api_client(exposed_settings, session_factory, tmp_path=tmp_path) as (
        client,
        _application,
    ):
        admin_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="tenant-a-admin@example.com",
        )
        company_b, user_b = await _second_tenant_admin(session_factory)

        created = await client.post(
            "/users",
            headers=admin_headers,
            json={
                "email": "tenant-a-engineer@example.com",
                "password": VALID_PASSWORD,
                "role": "engineer",
            },
        )
        assert created.status_code == 201, created.text
        engineer_id = created.json()["id"]
        tokens = await _login(client, "tenant-a-engineer@example.com")
        engineer_headers = {"Authorization": f"Bearer {tokens['access_token']}"}

        sessions = await client.get("/users/me/sessions", headers=engineer_headers)
        assert sessions.status_code == 200
        assert len(sessions.json()["items"]) == 1

        changed = await client.post(
            "/users/me/password",
            headers=engineer_headers,
            json={
                "current_password": VALID_PASSWORD,
                "new_password": NEW_PASSWORD,
            },
        )
        assert changed.status_code == 204, changed.text
        revoked_refresh = await client.post(
            "/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert revoked_refresh.status_code == 401
        await _login(client, "tenant-a-engineer@example.com", NEW_PASSWORD)

        reset = await client.post(
            f"/users/{engineer_id}/password-reset", headers=admin_headers
        )
        assert reset.status_code == 200, reset.text
        reset_token = reset.json()["local_reset_token"]
        assert isinstance(reset_token, str)
        completed = await client.post(
            "/auth/password-reset/complete",
            json={"token": reset_token, "new_password": VALID_PASSWORD},
        )
        assert completed.status_code == 204, completed.text
        reused = await client.post(
            "/auth/password-reset/complete",
            json={"token": reset_token, "new_password": NEW_PASSWORD},
        )
        assert reused.status_code == 422

        cross_company_update = await client.patch(
            f"/users/{user_b.id}",
            headers=admin_headers,
            json={"is_active": False},
        )
        assert cross_company_update.status_code == 404
        admin = await client.get("/users/me", headers=admin_headers)
        last_admin = await client.patch(
            f"/users/{admin.json()['id']}",
            headers=admin_headers,
            json={"role": "operator"},
        )
        assert last_admin.status_code == 409

        audit = await client.get("/audit-events?limit=100", headers=admin_headers)
        assert audit.status_code == 200, audit.text
        actions = {item["action"] for item in audit.json()["items"]}
        assert {
            "user.created",
            "password.changed",
            "password.reset_initiated_by_admin",
            "password.reset_completed",
        } <= actions
        assert str(company_b.id) not in audit.text
        assert reset_token not in audit.text
        assert "hashed_password" not in audit.text

    async with session_factory() as session:
        persisted = (
            await session.execute(
                select(PasswordResetToken).where(
                    PasswordResetToken.user_id == UUID(engineer_id)
                )
            )
        ).scalar_one()
        assert persisted.token_hash != reset_token
        assert persisted.used_at is not None
        assert (
            await session.scalar(
                select(AuditEvent.id).where(AuditEvent.company_id == company_b.id)
            )
            is None
        )


@pytest.mark.anyio
async def test_reset_privacy_expiry_session_revocation_and_deactivation(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    private_settings = settings.model_copy(
        update={"expose_local_password_reset_token": False}
    )
    async with ai_api_client(private_settings, session_factory, tmp_path=tmp_path) as (
        client,
        _application,
    ):
        admin_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="lifecycle-admin@example.com",
        )
        created = await client.post(
            "/users",
            headers=admin_headers,
            json={
                "email": "lifecycle-operator@example.com",
                "password": VALID_PASSWORD,
                "role": "operator",
            },
        )
        assert created.status_code == 201, created.text
        user_id = UUID(created.json()["id"])

        known_reset = await client.post(
            "/auth/password-reset/request",
            json={"email": "lifecycle-operator@example.com"},
        )
        unknown_reset = await client.post(
            "/auth/password-reset/request",
            json={"email": "missing-lifecycle@example.com"},
        )
        assert known_reset.status_code == unknown_reset.status_code == 200
        assert known_reset.json() == unknown_reset.json()
        assert known_reset.json()["local_reset_token"] is None

        service: UserService
        async with session_factory() as session:
            service = UserService(
                repository=UserRepository(session),
                password_hasher=PasswordHasher(),
            )
            _, expired_token = await service.initiate_password_reset(
                email="lifecycle-operator@example.com", expiry_minutes=10
            )
            assert expired_token is not None
            entity = (
                (
                    await session.execute(
                        select(PasswordResetToken)
                        .where(PasswordResetToken.user_id == user_id)
                        .order_by(PasswordResetToken.created_at.desc())
                    )
                )
                .scalars()
                .first()
            )
            assert entity is not None
            entity.expires_at = utc_now() - timedelta(seconds=1)
            await session.commit()
        expired = await client.post(
            "/auth/password-reset/complete",
            json={"token": expired_token, "new_password": NEW_PASSWORD},
        )
        assert expired.status_code == 422

        first = await _login(client, "lifecycle-operator@example.com")
        second = await _login(client, "lifecycle-operator@example.com")
        second_headers = {"Authorization": f"Bearer {second['access_token']}"}
        sessions = await client.get("/users/me/sessions", headers=second_headers)
        assert sessions.status_code == 200
        assert len(sessions.json()["items"]) == 2
        revoked_others = await client.post(
            "/users/me/sessions/revoke-others",
            headers=second_headers,
            json={"refresh_token": second["refresh_token"]},
        )
        assert revoked_others.status_code == 204
        assert (
            await client.post(
                "/auth/refresh", json={"refresh_token": first["refresh_token"]}
            )
        ).status_code == 401

        deactivated = await client.patch(
            f"/users/{user_id}",
            headers=admin_headers,
            json={"is_active": False},
        )
        assert deactivated.status_code == 200
        assert (
            await client.post(
                "/auth/refresh", json={"refresh_token": second["refresh_token"]}
            )
        ).status_code == 401

    assert safe_audit_metadata(
        {
            "new_password": "NeverPersistThis1!",
            "api_token_value": "never-persist-this-token",
            "client_secret_hint": "never-persist-this-secret",
            "authorization_header": "Bearer never-persist-this",
            "safe_count": 3,
        }
    ) == {"safe_count": 3}


@pytest.mark.anyio
async def test_audit_api_is_scoped_filterable_exportable_and_append_only(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        _application,
    ):
        admin_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="audit-admin@example.com",
        )
        operator_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="audit-operator@example.com",
        )
        created = await client.post(
            "/users",
            headers=admin_headers,
            json={
                "email": "audited-user@example.com",
                "password": VALID_PASSWORD,
                "role": "engineer",
            },
        )
        assert created.status_code == 201, created.text
        user_id = created.json()["id"]

        filtered = await client.get(
            "/audit-events",
            headers=admin_headers,
            params={
                "action": "user.created",
                "result": "success",
                "resource_type": "user",
                "resource_id": user_id,
                "limit": 1,
                "offset": 0,
            },
        )
        assert filtered.status_code == 200, filtered.text
        assert filtered.json()["total"] == 1
        assert filtered.json()["items"][0]["resource_id"] == user_id

        actor_filtered = await client.get(
            "/audit-events",
            headers=admin_headers,
            params={
                "actor_user_id": filtered.json()["items"][0]["actor_user_id"],
                "start_at": "2020-01-01T00:00:00Z",
                "end_at": "2100-01-01T00:00:00Z",
                "limit": 100,
            },
        )
        assert actor_filtered.status_code == 200
        occurred = [item["occurred_at"] for item in actor_filtered.json()["items"]]
        assert occurred == sorted(occurred, reverse=True)

        csv_export = await client.get(
            "/audit-events/export?export_format=csv", headers=admin_headers
        )
        assert csv_export.status_code == 200
        assert csv_export.headers["content-type"].startswith("text/csv")
        assert "user.created" in csv_export.text
        json_export = await client.get(
            "/audit-events/export?export_format=json", headers=admin_headers
        )
        assert json_export.status_code == 200
        assert any(item["action"] == "user.created" for item in json_export.json())

        event_id = filtered.json()["items"][0]["id"]
        assert (
            await client.patch(
                f"/audit-events/{event_id}",
                headers=admin_headers,
                json={"result": "failure"},
            )
        ).status_code == 404
        assert (
            await client.delete(
                f"/audit-events/{event_id}",
                headers=admin_headers,
            )
        ).status_code == 404
        assert (
            await client.get("/audit-events", headers=operator_headers)
        ).status_code == 403


class _PredictionDouble:
    async def predict(self, _plan, request, _context):
        score = 0.9 if float(request.features[0][0]) >= 80 else 0.1
        version = RegisteredModelVersion(
            registered_model_name=MODEL_NAME,
            version="1",
            run_id="pilot-run",
            source_uri="file:///pilot-model",
            key=random_forest_key(TaskType.REGRESSION),
            status=RegisteredModelVersionStatus.READY,
            aliases=("challenger",),
        )
        return RegisteredPredictionResult(
            model_version=version,
            predictions=np.asarray([score], dtype=np.float64),
        )


async def _create_succeeded_model_job(
    session_factory: async_sessionmaker[AsyncSession], user_id: UUID
) -> None:
    specification = RandomForestRegressionJobSpec(
        training_features=((64.0, 1.8), (70.0, 2.5), (78.0, 4.8), (84.0, 7.4)),
        training_targets=(0.08, 0.18, 0.62, 0.91),
        evaluation_features=((68.0, 2.2), (82.0, 6.5)),
        evaluation_targets=(0.13, 0.84),
        hyperparameters={"n_estimators": 3, "n_jobs": 1},
        random_seed=17,
        experiment_name="Pilot model",
        registered_model_name=MODEL_NAME,
        tags={"purpose": "pilot-test"},
    )
    async with session_factory() as session:
        repository = TrainingJobRepository(session)
        job_id = uuid4()
        created = await repository.create(
            job_id=job_id,
            requested_by_user_id=user_id,
            key=random_forest_key(TaskType.REGRESSION),
            specification=specification,
            idempotency_key="pilot-model-v1",
            request_fingerprint=specification.fingerprint(),
            max_attempts=1,
            queued_at=utc_now(),
        )
        claimed = await repository.claim_queued(job_id=created.id, started_at=utc_now())
        assert claimed is not None
        completed = await repository.mark_succeeded(
            job_id=created.id,
            expected_version=claimed.state_version,
            finished_at=utc_now() + timedelta(seconds=1),
            local_execution_run_id=uuid4(),
            mlflow_experiment_id="pilot-experiment",
            mlflow_run_id="pilot-run",
            registered_model_version="1",
            metrics={"r2": 0.9},
        )
        assert completed is not None
        await repository.commit()


@pytest.mark.anyio
async def test_structured_machine_risk_alert_and_cross_company_isolation(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_ai_monitored_prediction_service] = (
            _PredictionDouble
        )
        admin_headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="pilot-admin@example.com",
        )
        admin_detail = await client.get("/users/me", headers=admin_headers)
        admin_id = UUID(admin_detail.json()["id"])
        await _create_succeeded_model_job(session_factory, admin_id)
        await _second_tenant_admin(session_factory)
        tenant_b_tokens = await _login(client, "tenant-b-admin@example.com")
        tenant_b_headers = {
            "Authorization": f"Bearer {tenant_b_tokens['access_token']}"
        }

        company = (await client.get("/companies", headers=admin_headers)).json()[
            "items"
        ][0]
        factory = await client.post(
            "/factories",
            headers=admin_headers,
            json={
                "company_id": company["id"],
                "name": "Pilot Factory",
                "location": "Alexandria",
            },
        )
        machine = await client.post(
            "/machines",
            headers=admin_headers,
            json={
                "factory_id": factory.json()["id"],
                "name": "Pilot CNC",
                "serial_number": "PILOT-CNC-1",
            },
        )
        machine_id = machine.json()["id"]

        schema_body = {
            "features": [
                {
                    "name": "temperature_c",
                    "data_type": "float",
                    "unit": "celsius",
                    "minimum": 0,
                    "maximum": 120,
                },
                {
                    "name": "vibration_mm_s",
                    "data_type": "float",
                    "unit": "mm/s",
                    "minimum": 0,
                    "maximum": 30,
                },
            ],
            "algorithm": "random_forest_regression",
            "task_type": "regression",
            "target_name": "risk_score",
        }
        schema = await client.put(
            f"/ai/models/{MODEL_NAME}/versions/1/feature-schema",
            headers=admin_headers,
            json=schema_body,
        )
        assert schema.status_code == 200, schema.text
        cross_model = await client.get(
            f"/ai/models/{MODEL_NAME}/versions/1/feature-schema",
            headers=tenant_b_headers,
        )
        assert cross_model.status_code == 404
        cross_machine = await client.get(
            f"/machines/{machine_id}", headers=tenant_b_headers
        )
        assert cross_machine.status_code == 404

        invalid = await client.post(
            f"/ai/models/{MODEL_NAME}/versions/1/structured-prediction",
            headers=admin_headers,
            json={"machine_id": machine_id, "values": {"temperature_c": 82.0}},
        )
        assert invalid.status_code == 422
        wrong_names = await client.post(
            f"/ai/models/{MODEL_NAME}/versions/1/structured-prediction",
            headers=admin_headers,
            json={
                "machine_id": machine_id,
                "values": {"temperature_c": 82.0, "unknown_feature": 7.4},
            },
        )
        assert wrong_names.status_code == 422
        assert wrong_names.json()["detail"]["unknown"] == ["unknown_feature"]
        wrong_type = await client.post(
            f"/ai/models/{MODEL_NAME}/versions/1/structured-prediction",
            headers=admin_headers,
            json={
                "machine_id": machine_id,
                "values": {
                    "temperature_c": "not-a-number",
                    "vibration_mm_s": 7.4,
                },
            },
        )
        assert wrong_type.status_code == 422
        predicted = await client.post(
            f"/ai/models/{MODEL_NAME}/versions/1/structured-prediction",
            headers={**admin_headers, "X-Correlation-ID": "pilot-risk-test"},
            json={
                "machine_id": machine_id,
                "values": {"temperature_c": 84.0, "vibration_mm_s": 7.4},
            },
        )
        assert predicted.status_code == 200, predicted.text
        assert predicted.json()["risk_state"] == "critical"

        risk = await client.get(
            f"/pilot/machines/{machine_id}/risk", headers=admin_headers
        )
        assert risk.status_code == 200, risk.text
        assert risk.json()["alert_id"] is not None
        cross_risk = await client.get(
            f"/pilot/machines/{machine_id}/risk", headers=tenant_b_headers
        )
        assert cross_risk.status_code == 404

        alert_id = risk.json()["alert_id"]
        acknowledged = await client.post(
            f"/pilot/machine-risk/{risk.json()['id']}/acknowledge",
            headers=admin_headers,
            json={"operator_note": "Bearing inspection requested."},
        )
        assert acknowledged.status_code == 204, acknowledged.text
        acknowledged_risk = await client.get(
            f"/pilot/machines/{machine_id}/risk", headers=admin_headers
        )
        assert acknowledged_risk.json()["acknowledged_at"] is not None
        alert = await client.get(
            f"/ai/monitoring/alerts/{alert_id}", headers=admin_headers
        )
        assert alert.json()["status"] == "acknowledged"
        assert alert.json()["operator_note"] == "Bearing inspection requested."
        resolved = await client.post(
            f"/ai/monitoring/alerts/{alert_id}/resolve",
            headers=admin_headers,
            json={"engineer_note": "Inspection completed in pilot fixture."},
        )
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["status"] == "resolved"
        assert (
            resolved.json()["engineer_note"] == "Inspection completed in pilot fixture."
        )

        audit = await client.get("/audit-events?limit=100", headers=admin_headers)
        actions = {item["action"] for item in audit.json()["items"]}
        assert {
            "model.feature_schema_saved",
            "prediction.structured_executed",
            "alert.acknowledged",
            "alert.resolved",
        } <= actions
