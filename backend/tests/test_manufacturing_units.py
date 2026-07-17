"""Manufacturing repository and service tests."""

from uuid import uuid4

import pytest
from app.repositories.manufacturing import ManufacturingRepository, normalize_name
from app.schemas.common import SortOrder
from app.schemas.manufacturing import (
    CompanySortField,
    FactorySortField,
    MachineSortField,
)
from app.services.exceptions import (
    DuplicateCompanyNameError,
    RelatedResourceNotFoundError,
    ResourceNotFoundError,
)
from app.services.manufacturing import ManufacturingService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.mark.anyio
async def test_repository_creates_lists_and_soft_deletes_company(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Repository operations persist, list, and soft delete companies."""
    async with session_factory() as session:
        repository = ManufacturingRepository(session)
        company = await repository.create_company(
            name="Acme Manufacturing",
            normalized_name=normalize_name("Acme Manufacturing"),
            description=None,
        )
        await repository.commit()

        page = await repository.list_companies(
            limit=20,
            offset=0,
            search="acme",
            sort_by=CompanySortField.NAME,
            sort_order=SortOrder.ASC,
        )
        await repository.soft_delete_company(company)
        await repository.commit()

        assert page.total == 1
        assert page.items[0].id == company.id
        assert await repository.get_company_by_id(company.id) is None


@pytest.mark.anyio
async def test_service_rejects_duplicate_company_name(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Service rejects duplicate normalized company names."""
    async with session_factory() as session:
        service = ManufacturingService(repository=ManufacturingRepository(session))
        await service.create_company(name="Acme Manufacturing", description=None)

        with pytest.raises(DuplicateCompanyNameError):
            await service.create_company(name="ACME   MANUFACTURING", description=None)


@pytest.mark.anyio
async def test_service_validates_factory_parent_company(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Factory creation requires an existing company."""
    async with session_factory() as session:
        service = ManufacturingService(repository=ManufacturingRepository(session))

        with pytest.raises(RelatedResourceNotFoundError):
            await service.create_factory(
                company_id=uuid4(),
                name="Detroit Assembly",
                location=None,
                description=None,
            )


@pytest.mark.anyio
async def test_service_validates_machine_parent_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Machine creation requires an existing factory."""
    async with session_factory() as session:
        service = ManufacturingService(repository=ManufacturingRepository(session))

        with pytest.raises(RelatedResourceNotFoundError):
            await service.create_machine(
                factory_id=uuid4(),
                name="CNC Mill",
                serial_number=None,
                manufacturer=None,
                model=None,
            )


@pytest.mark.anyio
async def test_service_soft_delete_company_hides_descendants(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Soft deleting a company hides its factories and machines."""
    async with session_factory() as session:
        service = ManufacturingService(repository=ManufacturingRepository(session))
        company = await service.create_company(
            name="Acme Manufacturing",
            description=None,
        )
        factory = await service.create_factory(
            company_id=company.id,
            name="Detroit Assembly",
            location=None,
            description=None,
        )
        machine = await service.create_machine(
            factory_id=factory.id,
            name="CNC Mill",
            serial_number=None,
            manufacturer=None,
            model=None,
        )

        await service.delete_company(company.id)

        with pytest.raises(ResourceNotFoundError):
            await service.get_company(company.id)
        with pytest.raises(ResourceNotFoundError):
            await service.get_factory(factory.id)
        with pytest.raises(ResourceNotFoundError):
            await service.get_machine(machine.id)


@pytest.mark.anyio
async def test_repository_filters_factories_and_machines(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Repository list filters constrain factories and machines by parent IDs."""
    async with session_factory() as session:
        service = ManufacturingService(repository=ManufacturingRepository(session))
        company = await service.create_company(
            name="Acme Manufacturing",
            description=None,
        )
        factory = await service.create_factory(
            company_id=company.id,
            name="Detroit Assembly",
            location="Detroit",
            description=None,
        )
        machine = await service.create_machine(
            factory_id=factory.id,
            name="CNC Mill",
            serial_number="CNC-001",
            manufacturer="Okuma",
            model=None,
        )

        factories = await service.list_factories(
            limit=20,
            offset=0,
            search="detroit",
            company_id=company.id,
            sort_by=FactorySortField.NAME,
            sort_order=SortOrder.ASC,
        )
        machines = await service.list_machines(
            limit=20,
            offset=0,
            search="okuma",
            factory_id=factory.id,
            company_id=company.id,
            sort_by=MachineSortField.NAME,
            sort_order=SortOrder.ASC,
        )

        assert factories.items[0].id == factory.id
        assert machines.items[0].id == machine.id
