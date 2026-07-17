"""Sensor data API tests."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from app.models.user import UserRole
from app.repositories.users import UserRepository
from app.services.users import UserService
from app.utils.passwords import PasswordHasher
from httpx import AsyncClient
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
        repository = UserRepository(session)
        service = UserService(
            repository=repository,
            password_hasher=PasswordHasher(),
        )
        await service.create_user(email=email, password=VALID_PASSWORD, role=role)


async def auth_headers(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    role: UserRole,
    email: str,
) -> dict[str, str]:
    """Return Authorization headers for a user role."""
    await create_role_user(session_factory, email=email, role=role)
    response = await api_client.post(
        "/auth/login",
        json={"email": email, "password": VALID_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def create_machine_hierarchy(
    api_client: AsyncClient,
    headers: dict[str, str],
    *,
    name_suffix: str = "A",
) -> dict[str, object]:
    """Create company, factory, and machine records through the API."""
    company_response = await api_client.post(
        "/companies",
        headers=headers,
        json={"name": f"Acme Manufacturing {name_suffix}"},
    )
    assert company_response.status_code == 201
    factory_response = await api_client.post(
        "/factories",
        headers=headers,
        json={
            "company_id": company_response.json()["id"],
            "name": f"Detroit Assembly {name_suffix}",
        },
    )
    assert factory_response.status_code == 201
    machine_response = await api_client.post(
        "/machines",
        headers=headers,
        json={
            "factory_id": factory_response.json()["id"],
            "name": f"CNC Mill {name_suffix}",
        },
    )
    assert machine_response.status_code == 201
    return machine_response.json()


async def create_sensor(
    api_client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str = "Temperature Sensor",
    sensor_type: str = "temperature",
    unit: str = "celsius",
    min_value: float = -50.0,
    max_value: float = 150.0,
    suffix: str = "A",
) -> dict[str, object]:
    """Create a sensor through the API."""
    machine = await create_machine_hierarchy(api_client, headers, name_suffix=suffix)
    response = await api_client.post(
        "/sensors",
        headers=headers,
        json={
            "machine_id": machine["id"],
            "name": name,
            "sensor_type": sensor_type,
            "unit": unit,
            "sampling_rate": 2.5,
            "min_value": min_value,
            "max_value": max_value,
        },
    )
    assert response.status_code == 201
    return response.json()


def reading_payload(
    sensor_id: str,
    *,
    value: float = 42.0,
    source: str = "API",
    quality: str = "GOOD",
    batch_id: str | None = None,
) -> dict[str, object]:
    """Return a valid sensor reading payload."""
    payload: dict[str, object] = {
        "sensor_id": sensor_id,
        "timestamp": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        "value": value,
        "quality": quality,
        "source": source,
    }
    if batch_id is not None:
        payload["batch_id"] = batch_id
    return payload


@pytest.mark.anyio
async def test_admin_can_create_upload_job_and_sensor_reading(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Admin users have full sensor data access."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )
    sensor = await create_sensor(api_client, headers)
    upload_job_response = await api_client.post(
        "/upload-jobs",
        headers=headers,
        json={"filename": "readings.csv", "source": "API"},
    )
    assert upload_job_response.status_code == 201

    upload_job = upload_job_response.json()
    create_reading_response = await api_client.post(
        "/sensor-readings",
        headers=headers,
        json=reading_payload(
            str(sensor["id"]),
            batch_id=upload_job["id"],
        ),
    )
    assert create_reading_response.status_code == 201

    reading = create_reading_response.json()
    get_reading_response = await api_client.get(
        f"/sensor-readings/{reading['id']}",
        headers=headers,
    )
    nested_response = await api_client.get(
        f"/sensors/{sensor['id']}/readings",
        headers=headers,
    )
    refreshed_upload_job_response = await api_client.get(
        f"/upload-jobs/{upload_job['id']}",
        headers=headers,
    )

    assert get_reading_response.status_code == 200
    assert nested_response.status_code == 200
    assert nested_response.json()["total"] == 1
    assert refreshed_upload_job_response.json()["total_rows"] == 1
    assert refreshed_upload_job_response.json()["valid_rows"] == 1


@pytest.mark.anyio
async def test_engineer_can_create_and_operator_is_read_only(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Engineers can create/read sensor data and operators are read-only."""
    engineer_headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ENGINEER,
        email="engineer@example.com",
    )
    operator_headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.OPERATOR,
        email="operator@example.com",
    )
    sensor = await create_sensor(api_client, engineer_headers)
    create_response = await api_client.post(
        "/sensor-readings",
        headers=engineer_headers,
        json=reading_payload(str(sensor["id"])),
    )
    operator_list_response = await api_client.get(
        "/sensor-readings",
        headers=operator_headers,
    )
    operator_create_reading_response = await api_client.post(
        "/sensor-readings",
        headers=operator_headers,
        json=reading_payload(str(sensor["id"])),
    )
    operator_create_job_response = await api_client.post(
        "/upload-jobs",
        headers=operator_headers,
        json={"filename": "operator.csv", "source": "CSV"},
    )

    assert create_response.status_code == 201
    assert operator_list_response.status_code == 200
    assert operator_create_reading_response.status_code == 403
    assert operator_create_job_response.status_code == 403


@pytest.mark.anyio
async def test_sensor_reading_validation_rejects_invalid_data(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sensor reading API rejects invalid rows without discarding them."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )
    sensor = await create_sensor(api_client, headers, min_value=-10.0, max_value=80.0)
    rpm_sensor = await create_sensor(
        api_client,
        headers,
        name="Spindle RPM Sensor",
        sensor_type="rpm",
        unit="RPM",
        min_value=-100.0,
        max_value=10000.0,
        suffix="B",
    )

    missing_sensor_response = await api_client.post(
        "/sensor-readings",
        headers=headers,
        json=reading_payload(str(uuid4())),
    )
    future_payload = reading_payload(str(sensor["id"]))
    future_payload["timestamp"] = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    future_response = await api_client.post(
        "/sensor-readings",
        headers=headers,
        json=future_payload,
    )
    range_response = await api_client.post(
        "/sensor-readings",
        headers=headers,
        json=reading_payload(str(sensor["id"]), value=500.0, quality="OUTLIER"),
    )
    rpm_response = await api_client.post(
        "/sensor-readings",
        headers=headers,
        json=reading_payload(str(rpm_sensor["id"]), value=-1.0, quality="BAD"),
    )

    assert missing_sensor_response.status_code == 422
    assert missing_sensor_response.json()["detail"] == "Sensor does not exist."
    assert future_response.status_code == 422
    assert future_response.json()["detail"] == (
        "Reading timestamp cannot be in the future."
    )
    assert range_response.status_code == 422
    assert range_response.json()["detail"] == (
        "Reading value is outside the sensor configured range."
    )
    assert rpm_response.status_code == 422
    assert rpm_response.json()["detail"] == "RPM sensor readings cannot be negative."


@pytest.mark.anyio
async def test_sensor_reading_and_upload_job_filters(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sensor data list endpoints support production filters."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )
    sensor = await create_sensor(api_client, headers)
    await api_client.post(
        "/upload-jobs",
        headers=headers,
        json={"filename": "simulation.csv", "source": "SIMULATION"},
    )
    await api_client.post(
        "/sensor-readings",
        headers=headers,
        json=reading_payload(str(sensor["id"]), value=10.0),
    )
    await api_client.post(
        "/sensor-readings",
        headers=headers,
        json=reading_payload(
            str(sensor["id"]),
            value=11.0,
            source="SIMULATION",
            quality="OUTLIER",
        ),
    )

    readings_response = await api_client.get(
        "/sensor-readings?quality=OUTLIER&source=SIMULATION",
        headers=headers,
    )
    upload_jobs_response = await api_client.get(
        "/upload-jobs?source=SIMULATION&status=PENDING",
        headers=headers,
    )

    assert readings_response.status_code == 200
    assert readings_response.json()["total"] == 1
    assert readings_response.json()["items"][0]["source"] == "SIMULATION"
    assert upload_jobs_response.status_code == 200
    assert upload_jobs_response.json()["total"] == 1


@pytest.mark.anyio
async def test_upload_job_source_must_match_batched_reading(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Batched readings cannot be linked to an upload job with another source."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )
    sensor = await create_sensor(api_client, headers)
    upload_job_response = await api_client.post(
        "/upload-jobs",
        headers=headers,
        json={"filename": "readings.csv", "source": "CSV"},
    )

    response = await api_client.post(
        "/sensor-readings",
        headers=headers,
        json=reading_payload(
            str(sensor["id"]),
            source="API",
            batch_id=upload_job_response.json()["id"],
        ),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Reading source must match the upload job source."
    )


@pytest.mark.anyio
async def test_nested_sensor_readings_requires_existing_sensor(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The nested sensor readings endpoint validates sensor existence."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )

    response = await api_client.get(f"/sensors/{uuid4()}/readings", headers=headers)

    assert response.status_code == 404


@pytest.mark.anyio
async def test_sensor_data_endpoints_require_authentication(
    api_client: AsyncClient,
) -> None:
    """Sensor data routes require bearer authentication."""
    readings_response = await api_client.get("/sensor-readings")
    upload_jobs_response = await api_client.get("/upload-jobs")

    assert readings_response.status_code == 401
    assert upload_jobs_response.status_code == 401


@pytest.mark.anyio
async def test_csv_upload_endpoint_processes_file_and_finalizes_job(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """CSV uploads run the ETL pipeline and finalize upload job counters."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )
    sensor = await create_sensor(api_client, headers)
    upload_job_response = await api_client.post(
        "/upload-jobs",
        headers=headers,
        json={"filename": "readings.csv", "source": "CSV"},
    )
    upload_job = upload_job_response.json()
    csv_content = (
        "sensor_id,timestamp,value\n"
        f"{sensor['id']},{(datetime.now(UTC) - timedelta(minutes=5)).isoformat()},10\n"
        f"{sensor['id']},{(datetime.now(UTC) - timedelta(minutes=4)).isoformat()},11\n"
        f"{sensor['id']},{(datetime.now(UTC) + timedelta(minutes=1)).isoformat()},12\n"
    )

    response = await api_client.post(
        f"/upload-jobs/{upload_job['id']}/csv",
        headers=headers,
        files={
            "file": (
                "readings.csv",
                BytesIO(csv_content.encode("utf-8")),
                "text/csv",
            ),
        },
    )
    readings_response = await api_client.get(
        f"/sensors/{sensor['id']}/readings",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "FAILED"
    assert response.json()["total_rows"] == 3
    assert response.json()["valid_rows"] == 2
    assert response.json()["invalid_rows"] == 1
    assert readings_response.json()["total"] == 2


@pytest.mark.anyio
async def test_operator_cannot_upload_csv(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Operators can read sensor data but cannot run CSV uploads."""
    admin_headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )
    operator_headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.OPERATOR,
        email="operator@example.com",
    )
    upload_job_response = await api_client.post(
        "/upload-jobs",
        headers=admin_headers,
        json={"filename": "readings.csv", "source": "CSV"},
    )

    response = await api_client.post(
        f"/upload-jobs/{upload_job_response.json()['id']}/csv",
        headers=operator_headers,
        files={
            "file": (
                "readings.csv",
                BytesIO(b"sensor_id,timestamp,value\n"),
                "text/csv",
            ),
        },
    )

    assert response.status_code == 403
