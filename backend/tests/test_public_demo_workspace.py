"""Public registration workspace isolation and deterministic seed coverage."""

from uuid import UUID

import pytest
from app.dependencies.services import get_training_job_queue
from app.models.manufacturing import Company, Factory, Machine
from app.models.sensor import Sensor
from app.models.sensor_data import ReadingSource, SensorReading
from app.models.user import User, UserRole
from app.repositories.users import UserRepository
from app.services.users import UserService
from app.utils.passwords import PasswordHasher
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.ai_api_support import ai_api_client, regression_training_payload
from tests.test_auth_api import VALID_PASSWORD


async def _register_and_login(
    client: AsyncClient, *, email: str
) -> tuple[dict[str, str], dict[str, object]]:
    registered = await client.post(
        "/auth/register",
        json={
            "email": email,
            "name": "Public Demo User",
            "password": VALID_PASSWORD,
            "role": "engineer",
        },
    )
    assert registered.status_code == 201, registered.text
    login = await client.post(
        "/auth/login",
        json={"email": email, "password": VALID_PASSWORD},
    )
    assert login.status_code == 200, login.text
    return (
        {"Authorization": f"Bearer {login.json()['access_token']}"},
        registered.json(),
    )


class _CapturingTrainingQueue:
    def __init__(self) -> None:
        self.job_ids: list[UUID] = []

    def enqueue(self, job_id: UUID) -> str:
        self.job_ids.append(job_id)
        return f"public-demo-{job_id}"


@pytest.mark.anyio
async def test_public_demo_workspace_is_bounded_idempotent_and_isolated(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Each signup gets one tenant and repeat preparation creates no duplicates."""
    owner_headers, owner = await _register_and_login(
        api_client, email="workspace-owner@example.com"
    )
    other_headers, other = await _register_and_login(
        api_client, email="workspace-other@example.com"
    )

    first = await api_client.post(
        "/product/public-demo-workspace/prepare", headers=owner_headers
    )
    repeated = await api_client.post(
        "/product/public-demo-workspace/prepare", headers=owner_headers
    )
    other_prepared = await api_client.post(
        "/product/public-demo-workspace/prepare", headers=other_headers
    )

    assert (
        first.status_code == repeated.status_code == other_prepared.status_code == 200
    )
    assert (
        first.json()
        == repeated.json()
        == {
            "status": "ready",
            "factory_count": 1,
            "machine_count": 3,
            "sensor_count": 21,
            "reading_count": 126,
        }
    )
    assert owner["company_id"] != other["company_id"]

    owner_factories = await api_client.get("/factories", headers=owner_headers)
    other_factories = await api_client.get("/factories", headers=other_headers)
    assert owner_factories.status_code == other_factories.status_code == 200
    assert [item["name"] for item in owner_factories.json()["items"]] == [
        "Cairo Smart Plant"
    ]
    assert [item["name"] for item in other_factories.json()["items"]] == [
        "Cairo Smart Plant"
    ]
    assert (
        owner_factories.json()["items"][0]["id"]
        != (other_factories.json()["items"][0]["id"])
    )

    owner_company_id = UUID(str(owner["company_id"]))
    async with session_factory() as session:
        company = await session.get(Company, owner_company_id)
        assert company is not None and company.is_public_demo is True
        counts = {
            "factories": await session.scalar(
                select(func.count(Factory.id)).where(
                    Factory.company_id == owner_company_id
                )
            ),
            "machines": await session.scalar(
                select(func.count(Machine.id))
                .join(Factory)
                .where(Factory.company_id == owner_company_id)
            ),
            "sensors": await session.scalar(
                select(func.count(Sensor.id))
                .join(Machine)
                .join(Factory)
                .where(Factory.company_id == owner_company_id)
            ),
            "readings": await session.scalar(
                select(func.count(SensorReading.id))
                .join(Sensor)
                .join(Machine)
                .join(Factory)
                .where(
                    Factory.company_id == owner_company_id,
                    SensorReading.source == ReadingSource.SIMULATION,
                )
            ),
        }
        users = (
            await session.scalars(
                select(User).where(User.company_id == owner_company_id)
            )
        ).all()

    assert counts == {
        "factories": 1,
        "machines": 3,
        "sensors": 21,
        "readings": 126,
    }
    assert [user.email for user in users] == ["workspace-owner@example.com"]


@pytest.mark.anyio
async def test_public_demo_compute_uses_quota_path_and_company_model_namespace(
    settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path,
) -> None:
    """Demo accounts cannot use legacy compute or a shared MLflow model name."""
    queue = _CapturingTrainingQueue()
    async with ai_api_client(settings, session_factory, tmp_path=tmp_path) as (
        client,
        application,
    ):
        application.dependency_overrides[get_training_job_queue] = lambda: queue
        headers, user = await _register_and_login(
            client, email="demo-model-scope@example.com"
        )
        payload = regression_training_payload()
        bounded = await client.post(
            "/ai/training-jobs/random-forest/regression",
            headers=headers,
            json=payload,
        )
        bounded_detail = await client.get(
            bounded.json()["status_url"],
            headers=headers,
        )
        custom_name = await client.post(
            "/ai/training-jobs/random-forest/regression",
            headers=headers,
            json={**payload, "registered_model_name": "shared_model"},
        )
        synchronous = await client.post(
            "/ai/training/random-forest/regression",
            headers=headers,
            json=payload,
        )
        foreign_prediction = await client.post(
            "/ai/predictions/random-forest/regression",
            headers=headers,
            json={
                "registered_model_name": "ai_core_random_forest_regression",
                "version_or_alias": "1",
                "features": [[1.0]],
            },
        )
        foreign_model = await client.get(
            "/ai/models/ai_core_random_forest_regression/versions/1",
            headers=headers,
        )

    assert bounded.status_code == 202, bounded.text
    assert bounded_detail.status_code == 200, bounded_detail.text
    expected_prefix = f"public_demo_{UUID(str(user['company_id'])).hex}_"
    assert bounded_detail.json()["registered_model_name"].startswith(expected_prefix)
    assert len(queue.job_ids) == 1
    assert custom_name.status_code == 422
    assert synchronous.status_code == 403
    assert foreign_prediction.status_code == foreign_model.status_code == 404


@pytest.mark.anyio
async def test_existing_non_demo_company_cannot_use_public_workspace_preparation(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The preparation endpoint trusts only the persisted company marker."""
    async with session_factory() as session:
        company = Company(
            name="Private Existing Company",
            normalized_name="private existing company",
            is_public_demo=False,
        )
        session.add(company)
        await session.flush()
        await UserService(
            repository=UserRepository(session),
            password_hasher=PasswordHasher(),
        ).create_user(
            email="non-demo-engineer@example.com",
            password=VALID_PASSWORD,
            role=UserRole.ENGINEER,
            company_id=company.id,
        )
    login = await api_client.post(
        "/auth/login",
        json={
            "email": "non-demo-engineer@example.com",
            "password": VALID_PASSWORD,
        },
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    response = await api_client.post(
        "/product/public-demo-workspace/prepare", headers=headers
    )
    assert response.status_code == 403
