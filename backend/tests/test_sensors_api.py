"""Sensor API tests."""

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
    company_name: str = "Acme Manufacturing",
    factory_name: str = "Detroit Assembly",
    machine_name: str = "CNC Mill 01",
) -> dict[str, object]:
    """Create company, factory, and machine records through the API."""
    company_response = await api_client.post(
        "/companies",
        headers=headers,
        json={"name": company_name},
    )
    assert company_response.status_code == 201
    factory_response = await api_client.post(
        "/factories",
        headers=headers,
        json={
            "company_id": company_response.json()["id"],
            "name": factory_name,
        },
    )
    assert factory_response.status_code == 201
    machine_response = await api_client.post(
        "/machines",
        headers=headers,
        json={
            "factory_id": factory_response.json()["id"],
            "name": machine_name,
        },
    )
    assert machine_response.status_code == 201
    return machine_response.json()


async def create_sensor(
    api_client: AsyncClient,
    headers: dict[str, str],
    *,
    machine_id: str,
    name: str = "Temperature Sensor",
) -> dict[str, object]:
    """Create a sensor through the API."""
    response = await api_client.post(
        "/sensors",
        headers=headers,
        json={
            "machine_id": machine_id,
            "name": name,
            "sensor_type": "temperature",
            "unit": "celsius",
            "sampling_rate": 2.5,
            "min_value": -20.0,
            "max_value": 120.0,
            "description": "Spindle temperature sensor",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.anyio
async def test_admin_can_crud_sensor(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Admin users have full sensor CRUD access."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )
    machine = await create_machine_hierarchy(api_client, headers)
    sensor = await create_sensor(api_client, headers, machine_id=str(machine["id"]))

    get_response = await api_client.get(f"/sensors/{sensor['id']}", headers=headers)
    update_response = await api_client.patch(
        f"/sensors/{sensor['id']}",
        headers=headers,
        json={"sampling_rate": 5.0, "max_value": 150.0},
    )
    delete_response = await api_client.delete(
        f"/sensors/{sensor['id']}",
        headers=headers,
    )
    deleted_response = await api_client.get(f"/sensors/{sensor['id']}", headers=headers)

    assert get_response.status_code == 200
    assert update_response.status_code == 200
    assert update_response.json()["sampling_rate"] == 5.0
    assert delete_response.status_code == 204
    assert deleted_response.status_code == 404


@pytest.mark.anyio
async def test_engineer_can_create_update_read_but_not_delete_sensor(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Engineer users can create, update, and read sensors, but cannot delete."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ENGINEER,
        email="engineer@example.com",
    )
    machine = await create_machine_hierarchy(api_client, headers)
    sensor = await create_sensor(api_client, headers, machine_id=str(machine["id"]))

    update_response = await api_client.patch(
        f"/sensors/{sensor['id']}",
        headers=headers,
        json={"name": "Updated Temperature Sensor"},
    )
    delete_response = await api_client.delete(
        f"/sensors/{sensor['id']}",
        headers=headers,
    )

    assert update_response.status_code == 200
    assert delete_response.status_code == 403


@pytest.mark.anyio
async def test_operator_has_read_only_sensor_access(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Operator users can read sensors but cannot create them."""
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
    machine = await create_machine_hierarchy(api_client, admin_headers)
    sensor = await create_sensor(
        api_client,
        admin_headers,
        machine_id=str(machine["id"]),
    )

    list_response = await api_client.get("/sensors", headers=operator_headers)
    get_response = await api_client.get(
        f"/sensors/{sensor['id']}",
        headers=operator_headers,
    )
    create_response = await api_client.post(
        "/sensors",
        headers=operator_headers,
        json={
            "machine_id": machine["id"],
            "name": "Operator Sensor",
            "sampling_rate": 1.0,
            "min_value": 0.0,
            "max_value": 10.0,
        },
    )

    assert list_response.status_code == 200
    assert get_response.status_code == 200
    assert create_response.status_code == 403


@pytest.mark.anyio
async def test_sensor_machine_must_exist(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sensor creation validates that the owning machine exists."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )

    response = await api_client.post(
        "/sensors",
        headers=headers,
        json={
            "machine_id": str(uuid4()),
            "name": "Temperature Sensor",
            "sampling_rate": 1.0,
            "min_value": 0.0,
            "max_value": 10.0,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Machine does not exist."


@pytest.mark.anyio
async def test_sensor_name_unique_inside_machine(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sensor names are unique inside a machine."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )
    first_machine = await create_machine_hierarchy(api_client, headers)
    second_machine = await create_machine_hierarchy(
        api_client,
        headers,
        company_name="Beta Manufacturing",
        factory_name="Beta Factory",
        machine_name="CNC Mill 02",
    )
    await create_sensor(
        api_client,
        headers,
        machine_id=str(first_machine["id"]),
        name="Temperature Sensor",
    )

    duplicate_response = await api_client.post(
        "/sensors",
        headers=headers,
        json={
            "machine_id": first_machine["id"],
            "name": "  TEMPERATURE   SENSOR  ",
            "sampling_rate": 1.0,
            "min_value": 0.0,
            "max_value": 10.0,
        },
    )
    same_name_other_machine_response = await api_client.post(
        "/sensors",
        headers=headers,
        json={
            "machine_id": second_machine["id"],
            "name": "Temperature Sensor",
            "sampling_rate": 1.0,
            "min_value": 0.0,
            "max_value": 10.0,
        },
    )

    assert duplicate_response.status_code == 409
    assert same_name_other_machine_response.status_code == 201


@pytest.mark.anyio
async def test_sensor_validation_rejects_invalid_rate_and_range(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sensor request validation rejects invalid sampling rate and value range."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )
    machine = await create_machine_hierarchy(api_client, headers)

    invalid_rate_response = await api_client.post(
        "/sensors",
        headers=headers,
        json={
            "machine_id": machine["id"],
            "name": "Temperature Sensor",
            "sampling_rate": 0.0,
            "min_value": 0.0,
            "max_value": 10.0,
        },
    )
    invalid_range_response = await api_client.post(
        "/sensors",
        headers=headers,
        json={
            "machine_id": machine["id"],
            "name": "Pressure Sensor",
            "sampling_rate": 1.0,
            "min_value": 10.0,
            "max_value": 10.0,
        },
    )

    assert invalid_rate_response.status_code == 422
    assert invalid_range_response.status_code == 422


@pytest.mark.anyio
async def test_sensor_update_rejects_resulting_invalid_range(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sensor updates validate the resulting min/max range."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )
    machine = await create_machine_hierarchy(api_client, headers)
    sensor = await create_sensor(api_client, headers, machine_id=str(machine["id"]))

    response = await api_client.patch(
        f"/sensors/{sensor['id']}",
        headers=headers,
        json={"min_value": 200.0},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Minimum value must be less than maximum value."


@pytest.mark.anyio
async def test_list_machine_sensors_and_search_sort(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sensors can be listed globally and from the owning machine."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )
    machine = await create_machine_hierarchy(api_client, headers)
    await create_sensor(
        api_client,
        headers,
        machine_id=str(machine["id"]),
        name="Temperature Sensor",
    )
    await create_sensor(
        api_client,
        headers,
        machine_id=str(machine["id"]),
        name="Pressure Sensor",
    )

    machine_sensors_response = await api_client.get(
        f"/machines/{machine['id']}/sensors?sort_by=name&sort_order=asc",
        headers=headers,
    )
    search_response = await api_client.get(
        "/sensors?search=pressure",
        headers=headers,
    )

    assert machine_sensors_response.status_code == 200
    assert [item["name"] for item in machine_sensors_response.json()["items"]] == [
        "Pressure Sensor",
        "Temperature Sensor",
    ]
    assert search_response.json()["total"] == 1
    assert search_response.json()["items"][0]["name"] == "Pressure Sensor"


@pytest.mark.anyio
async def test_machine_sensor_list_requires_existing_machine(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The nested machine sensor endpoint validates machine existence."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )

    response = await api_client.get(f"/machines/{uuid4()}/sensors", headers=headers)

    assert response.status_code == 404


@pytest.mark.anyio
async def test_sensor_endpoints_require_authentication(api_client: AsyncClient) -> None:
    """Sensor routes require bearer authentication."""
    response = await api_client.get("/sensors")

    assert response.status_code == 401
