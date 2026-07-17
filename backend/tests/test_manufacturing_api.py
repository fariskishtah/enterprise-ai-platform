"""Manufacturing domain API tests."""

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
    """Create a user directly through the service layer for RBAC tests."""
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


async def create_company(
    api_client: AsyncClient,
    headers: dict[str, str],
    *,
    name: str = "Acme Manufacturing",
) -> dict[str, object]:
    """Create a company through the API."""
    response = await api_client.post(
        "/companies",
        headers=headers,
        json={"name": name, "description": "Industrial operations group"},
    )
    assert response.status_code == 201
    return response.json()


async def create_factory(
    api_client: AsyncClient,
    headers: dict[str, str],
    *,
    company_id: str,
    name: str = "Detroit Assembly",
) -> dict[str, object]:
    """Create a factory through the API."""
    response = await api_client.post(
        "/factories",
        headers=headers,
        json={
            "company_id": company_id,
            "name": name,
            "location": "Detroit",
            "description": "Assembly operations",
        },
    )
    assert response.status_code == 201
    return response.json()


async def create_machine(
    api_client: AsyncClient,
    headers: dict[str, str],
    *,
    factory_id: str,
    name: str = "CNC Mill 01",
) -> dict[str, object]:
    """Create a machine through the API."""
    response = await api_client.post(
        "/machines",
        headers=headers,
        json={
            "factory_id": factory_id,
            "name": name,
            "serial_number": "CNC-001",
            "manufacturer": "Okuma",
            "model": "MB-5000H",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.anyio
async def test_admin_can_crud_and_soft_delete_company(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Admin users have full access to company CRUD."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )
    company = await create_company(api_client, headers)
    company_id = str(company["id"])

    get_response = await api_client.get(f"/companies/{company_id}", headers=headers)
    update_response = await api_client.patch(
        f"/companies/{company_id}",
        headers=headers,
        json={"name": "Acme Robotics"},
    )
    delete_response = await api_client.delete(
        f"/companies/{company_id}",
        headers=headers,
    )
    deleted_get_response = await api_client.get(
        f"/companies/{company_id}",
        headers=headers,
    )
    list_response = await api_client.get("/companies", headers=headers)

    assert get_response.status_code == 200
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Acme Robotics"
    assert delete_response.status_code == 204
    assert deleted_get_response.status_code == 404
    assert list_response.json()["total"] == 0


@pytest.mark.anyio
async def test_engineer_can_create_update_read_but_not_delete(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Engineer users can create, update, and read, but cannot delete."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ENGINEER,
        email="engineer@example.com",
    )
    company = await create_company(api_client, headers)
    company_id = str(company["id"])

    update_response = await api_client.patch(
        f"/companies/{company_id}",
        headers=headers,
        json={"description": "Updated description"},
    )
    delete_response = await api_client.delete(
        f"/companies/{company_id}",
        headers=headers,
    )

    assert update_response.status_code == 200
    assert delete_response.status_code == 403


@pytest.mark.anyio
async def test_operator_has_read_only_access(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Operator users can read domain data but cannot mutate it."""
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
    company = await create_company(api_client, admin_headers)

    list_response = await api_client.get("/companies", headers=operator_headers)
    get_response = await api_client.get(
        f"/companies/{company['id']}",
        headers=operator_headers,
    )
    create_response = await api_client.post(
        "/companies",
        headers=operator_headers,
        json={"name": "Operator Created Company"},
    )

    assert list_response.status_code == 200
    assert get_response.status_code == 200
    assert create_response.status_code == 403


@pytest.mark.anyio
async def test_company_name_must_be_unique(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Company names are unique after normalization."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )
    await create_company(api_client, headers, name="Acme Manufacturing")

    response = await api_client.post(
        "/companies",
        headers=headers,
        json={"name": "  ACME   MANUFACTURING  "},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Company name is already in use."


@pytest.mark.anyio
async def test_factory_and_machine_relationship_validation(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Factories and machines must reference existing active parents."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )
    company = await create_company(api_client, headers)

    missing_company_response = await api_client.post(
        "/factories",
        headers=headers,
        json={"company_id": str(uuid4()), "name": "Missing Parent Factory"},
    )
    factory = await create_factory(
        api_client,
        headers,
        company_id=str(company["id"]),
    )
    missing_factory_response = await api_client.post(
        "/machines",
        headers=headers,
        json={"factory_id": str(uuid4()), "name": "Missing Parent Machine"},
    )
    machine = await create_machine(
        api_client,
        headers,
        factory_id=str(factory["id"]),
    )

    assert missing_company_response.status_code == 422
    assert factory["company_id"] == company["id"]
    assert missing_factory_response.status_code == 422
    assert machine["factory_id"] == factory["id"]


@pytest.mark.anyio
async def test_pagination_search_sort_and_filtering(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """List endpoints support pagination, searching, sorting, and filtering."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )
    company_beta = await create_company(api_client, headers, name="Beta Manufacturing")
    company_alpha = await create_company(
        api_client,
        headers,
        name="Alpha Manufacturing",
    )
    company_gamma = await create_company(
        api_client,
        headers,
        name="Gamma Manufacturing",
    )
    factory = await create_factory(
        api_client,
        headers,
        company_id=str(company_alpha["id"]),
        name="Alpha Factory",
    )
    await create_machine(
        api_client,
        headers,
        factory_id=str(factory["id"]),
        name="Laser Cutter",
    )

    companies_response = await api_client.get(
        "/companies?limit=2&offset=0&sort_by=name&sort_order=asc",
        headers=headers,
    )
    search_response = await api_client.get(
        "/companies?search=gamma",
        headers=headers,
    )
    factory_filter_response = await api_client.get(
        f"/factories?company_id={company_alpha['id']}",
        headers=headers,
    )
    machine_filter_response = await api_client.get(
        f"/machines?company_id={company_alpha['id']}&search=laser",
        headers=headers,
    )

    assert companies_response.status_code == 200
    companies = companies_response.json()
    assert companies["total"] == 3
    assert [item["name"] for item in companies["items"]] == [
        "Alpha Manufacturing",
        "Beta Manufacturing",
    ]
    assert search_response.json()["items"][0]["id"] == company_gamma["id"]
    assert factory_filter_response.json()["items"][0]["id"] == factory["id"]
    assert machine_filter_response.json()["items"][0]["name"] == "Laser Cutter"
    assert company_beta["name"] == "Beta Manufacturing"


@pytest.mark.anyio
async def test_soft_delete_factory_hides_child_machines(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Soft deleting a factory also hides its machines."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )
    company = await create_company(api_client, headers)
    factory = await create_factory(api_client, headers, company_id=str(company["id"]))
    machine = await create_machine(api_client, headers, factory_id=str(factory["id"]))

    delete_response = await api_client.delete(
        f"/factories/{factory['id']}",
        headers=headers,
    )
    machine_response = await api_client.get(
        f"/machines/{machine['id']}",
        headers=headers,
    )

    assert delete_response.status_code == 204
    assert machine_response.status_code == 404


@pytest.mark.anyio
async def test_domain_endpoints_require_authentication(api_client: AsyncClient) -> None:
    """Manufacturing routes require bearer authentication."""
    response = await api_client.get("/companies")

    assert response.status_code == 401


@pytest.mark.anyio
async def test_validation_rejects_blank_name_and_empty_patch(
    api_client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Request validation rejects invalid domain payloads."""
    headers = await auth_headers(
        api_client,
        session_factory,
        role=UserRole.ADMIN,
        email="admin@example.com",
    )
    company = await create_company(api_client, headers)

    blank_name_response = await api_client.post(
        "/companies",
        headers=headers,
        json={"name": "   "},
    )
    empty_patch_response = await api_client.patch(
        f"/companies/{company['id']}",
        headers=headers,
        json={},
    )

    assert blank_name_response.status_code == 422
    assert empty_patch_response.status_code == 422


@pytest.mark.anyio
async def test_openapi_documents_manufacturing_routes(
    api_client: AsyncClient,
) -> None:
    """OpenAPI exposes Sprint 3 manufacturing routes."""
    response = await api_client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert "/companies" in schema["paths"]
    assert "/factories" in schema["paths"]
    assert "/machines" in schema["paths"]
