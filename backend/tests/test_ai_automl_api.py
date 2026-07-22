"""AutoML management API idempotency, ownership, and lifecycle tests."""

from pathlib import Path
from uuid import UUID

import pytest
from app.config.settings import Settings
from app.ml.automl.models import AutoMLTrialStatus
from app.models.user import User, UserRole
from app.repositories.automl import AutoMLRepository
from app.utils.security import utc_now
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import ai_api_client, auth_headers


def automl_payload() -> dict[str, object]:
    return {
        "task_type": "regression",
        "primary_metric": "rmse",
        "metric_direction": "minimize",
        "random_seed": 19,
        "plugin_ids": ["ridge_regression"],
        "plugin_search_spaces": [
            {
                "plugin_id": "ridge_regression",
                "task_type": "regression",
                "parameters": [
                    {
                        "name": "alpha",
                        "kind": "float",
                        "low": 0.001,
                        "high": 100.0,
                        "default": 1.0,
                        "log_scale": True,
                    },
                    {
                        "name": "fit_intercept",
                        "kind": "categorical",
                        "choices": [True, False],
                        "default": True,
                    },
                ],
                "probability_support": False,
            }
        ],
        "data": {
            "training_data_fingerprint": "a" * 64,
            "evaluation_data_fingerprint": "b" * 64,
            "training_row_count": 20,
            "evaluation_row_count": 5,
            "feature_count": 2,
        },
        "budget": {
            "trial_budget": 4,
            "time_budget_seconds": 120,
            "per_trial_timeout_seconds": 30,
            "max_concurrent_trials": 1,
            "cross_validation_folds": 3,
        },
    }


@pytest.mark.anyio
async def test_automl_metadata_submission_idempotency_listing_and_cancellation(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        _,
    ):
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="automl-owner@example.com",
        )
        request_headers = {**headers, "Idempotency-Key": "stable-study"}
        metadata = await client.get("/ai/automl/algorithms", headers=headers)
        created = await client.post(
            "/ai/automl/studies", headers=request_headers, json=automl_payload()
        )
        replay = await client.post(
            "/ai/automl/studies", headers=request_headers, json=automl_payload()
        )
        study_id = created.json()["study_id"]
        async with session_factory() as session:
            owner_id = await session.scalar(
                select(User.id).where(User.email == "automl-owner@example.com")
            )
            assert owner_id is not None
            trial = await AutoMLRepository(session).create_trial(
                study_id=UUID(study_id),
                trial_number=0,
                plugin_id="ridge_regression",
                status=AutoMLTrialStatus.QUEUED,
                parameters={"alpha": 1.0, "fit_intercept": True},
                parameter_fingerprint="c" * 64,
                random_seed=21,
                queued_at=utc_now(),
            )
            await session.commit()
        listed = await client.get(
            "/ai/automl/studies?status=queued&task_type=regression", headers=headers
        )
        detail = await client.get(f"/ai/automl/studies/{study_id}", headers=headers)
        trials = await client.get(
            f"/ai/automl/studies/{study_id}/trials", headers=headers
        )
        trial_detail = await client.get(
            f"/ai/automl/studies/{study_id}/trials/{trial.id}", headers=headers
        )
        cancelled = await client.post(
            f"/ai/automl/studies/{study_id}/cancel", headers=headers
        )
        repeated_cancel = await client.post(
            f"/ai/automl/studies/{study_id}/cancel", headers=headers
        )

    assert metadata.status_code == 200
    assert metadata.json() and all(
        item["id"] != "knn_regression" for item in metadata.json()
    )
    assert "import_path" not in metadata.text
    assert created.status_code == 202 and created.json()["created"] is True
    assert replay.status_code == 202 and replay.json()["created"] is False
    assert replay.json()["study_id"] == study_id
    assert listed.json()["total"] == 1
    assert "request_fingerprint" not in detail.json()
    assert trials.json()["items"][0]["trial_number"] == 0
    assert trial_detail.status_code == 200
    assert trial_detail.json()["parameters"]["alpha"] == 1.0
    assert cancelled.json()["status"] == "cancelled"
    assert repeated_cancel.json()["cancellation"] == "unchanged"


@pytest.mark.anyio
async def test_automl_conflict_owner_hiding_admin_access_and_operator_denial(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        _,
    ):
        owner = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="automl-a@example.com",
        )
        other = await auth_headers(
            client,
            session_factory,
            role=UserRole.ENGINEER,
            email="automl-b@example.com",
        )
        admin = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="automl-admin@example.com",
        )
        operator = await auth_headers(
            client,
            session_factory,
            role=UserRole.OPERATOR,
            email="automl-operator@example.com",
        )
        keyed = {**owner, "Idempotency-Key": "conflicting-study"}
        created = await client.post(
            "/ai/automl/studies", headers=keyed, json=automl_payload()
        )
        changed = automl_payload()
        changed["random_seed"] = 20
        conflict = await client.post("/ai/automl/studies", headers=keyed, json=changed)
        study_id = created.json()["study_id"]
        hidden = await client.get(f"/ai/automl/studies/{study_id}", headers=other)
        admin_read = await client.get(f"/ai/automl/studies/{study_id}", headers=admin)
        forbidden = await client.get("/ai/automl/studies", headers=operator)

    assert conflict.status_code == 409
    assert hidden.status_code == 404
    assert admin_read.status_code == 200
    assert forbidden.status_code == 403
