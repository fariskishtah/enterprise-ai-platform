"""Feature engineering API tests."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.config.settings import Settings
from app.core.application import create_app
from app.dependencies.database import get_db_session
from app.models.sensor_data import ReadingQuality, ReadingSource
from app.models.user import UserRole
from app.repositories.manufacturing import ManufacturingRepository
from app.repositories.sensor_data import SensorDataRepository
from app.repositories.sensors import SensorRepository
from app.repositories.users import UserRepository
from app.services.manufacturing import ManufacturingService
from app.services.sensors import SensorService
from app.services.users import UserService
from app.utils.passwords import PasswordHasher
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

VALID_PASSWORD = "ValidPassword1!"


async def create_role_user(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    email: str,
    role: UserRole,
) -> None:
    """Create a user for RBAC tests."""
    async with session_factory() as session:
        service = UserService(
            repository=UserRepository(session),
            password_hasher=PasswordHasher(),
        )
        await service.create_user(email=email, password=VALID_PASSWORD, role=role)


async def auth_headers(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    role: UserRole,
    email: str,
) -> dict[str, str]:
    """Return Authorization headers for a user role."""
    await create_role_user(session_factory, email=email, role=role)
    response = await client.post(
        "/auth/login",
        json={"email": email, "password": VALID_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def create_sensor_with_readings(
    session_factory: async_sessionmaker[AsyncSession],
) -> UUID:
    """Create a sensor with feature source readings."""
    async with session_factory() as session:
        manufacturing_service = ManufacturingService(
            repository=ManufacturingRepository(session),
        )
        company = await manufacturing_service.create_company(
            name=f"Feature API Company {uuid4()}",
            description=None,
        )
        factory = await manufacturing_service.create_factory(
            company_id=company.id,
            name="Feature API Factory",
            location=None,
            description=None,
        )
        machine = await manufacturing_service.create_machine(
            factory_id=factory.id,
            name="Feature API Machine",
            serial_number=None,
            manufacturer=None,
            model=None,
        )
        sensor = await SensorService(
            repository=SensorRepository(session),
        ).create_sensor(
            machine_id=machine.id,
            name="Temperature Sensor",
            sensor_type="temperature",
            unit="celsius",
            sampling_rate=1.0,
            min_value=-50.0,
            max_value=200.0,
            description=None,
        )
        await SensorDataRepository(session).bulk_create_sensor_readings(
            [
                {
                    "sensor_id": sensor.id,
                    "timestamp": datetime.now(UTC) - timedelta(minutes=3 - index),
                    "value": float(index),
                    "quality": ReadingQuality.GOOD,
                    "source": ReadingSource.API,
                    "batch_id": None,
                }
                for index in range(3)
            ],
        )
        await session.commit()
        return sensor.id


@asynccontextmanager
async def feature_api_client(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    dataset_dir: Path,
) -> AsyncIterator[AsyncClient]:
    """Return an API client configured with an isolated feature dataset path."""
    application = create_app(
        settings.model_copy(update={"feature_dataset_dir": str(dataset_dir)}),
    )

    async def override_get_db_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    application.dependency_overrides[get_db_session] = override_get_db_session
    transport = ASGITransport(app=application)

    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    application.dependency_overrides.clear()


@pytest.mark.anyio
async def test_admin_can_export_feature_dataset(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Admin users can export feature datasets through the API."""
    async with feature_api_client(
        settings,
        session_factory,
        dataset_dir=tmp_path,
    ) as client:
        headers = await auth_headers(
            client,
            session_factory,
            role=UserRole.ADMIN,
            email="admin@example.com",
        )
        sensor_id = await create_sensor_with_readings(session_factory)
        response = await client.post(
            "/feature-datasets",
            headers=headers,
            json={"sensor_id": str(sensor_id)},
        )

    assert response.status_code == 201
    assert response.json()["dataset_name"] == "dataset_v1.parquet"
    assert response.json()["rows"] == 3


@pytest.mark.anyio
async def test_operator_cannot_export_feature_dataset(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Operators cannot create feature dataset exports."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.OPERATOR,
        email="operator@example.com",
    )

    response = await api_client.post(
        "/feature-datasets",
        headers=headers,
        json={"sensor_id": str(uuid4())},
    )

    assert response.status_code == 403
