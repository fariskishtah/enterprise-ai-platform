"""Manufacturing domain application service."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.models.manufacturing import Company, Factory, Machine
from app.repositories.manufacturing import (
    ManufacturingRepository,
    Page,
    normalize_name,
)
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


@dataclass(frozen=True)
class CompanyUpdateFields:
    """Company fields requested for update."""

    provided: frozenset[str]
    name: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class FactoryUpdateFields:
    """Factory fields requested for update."""

    provided: frozenset[str]
    company_id: UUID | None = None
    name: str | None = None
    location: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class MachineUpdateFields:
    """Machine fields requested for update."""

    provided: frozenset[str]
    factory_id: UUID | None = None
    name: str | None = None
    serial_number: str | None = None
    manufacturer: str | None = None
    model: str | None = None


class ManufacturingService:
    """Application use cases for companies, factories, and machines."""

    def __init__(self, *, repository: ManufacturingRepository) -> None:
        self._repository = repository

    async def list_companies(
        self,
        *,
        limit: int,
        offset: int,
        search: str | None,
        sort_by: CompanySortField,
        sort_order: SortOrder,
    ) -> Page[Company]:
        """Return paginated companies."""
        return await self._repository.list_companies(
            limit=limit,
            offset=offset,
            search=search,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def get_company(self, company_id: UUID) -> Company:
        """Return a company by ID."""
        company = await self._repository.get_company_by_id(company_id)
        if company is None:
            raise ResourceNotFoundError("Company not found.")
        return company

    async def create_company(
        self,
        *,
        name: str,
        description: str | None,
    ) -> Company:
        """Create a company with a unique name."""
        normalized_name = normalize_name(name)
        existing_company = await self._repository.get_company_by_normalized_name(
            normalized_name,
        )
        if existing_company is not None:
            raise DuplicateCompanyNameError("Company name is already in use.")

        try:
            company = await self._repository.create_company(
                name=name,
                normalized_name=normalized_name,
                description=description,
            )
            await self._repository.commit()
        except IntegrityError as exc:
            await self._repository.rollback()
            raise DuplicateCompanyNameError(
                "Company name is already in use.",
            ) from exc
        return company

    async def update_company(
        self,
        company_id: UUID,
        fields: CompanyUpdateFields,
    ) -> Company:
        """Update a company."""
        company = await self.get_company(company_id)
        if "name" in fields.provided and fields.name is not None:
            normalized_name = normalize_name(fields.name)
            existing_company = await self._repository.get_company_by_normalized_name(
                normalized_name,
                exclude_company_id=company.id,
            )
            if existing_company is not None:
                raise DuplicateCompanyNameError("Company name is already in use.")
            company.name = fields.name
            company.normalized_name = normalized_name
        if "description" in fields.provided:
            company.description = fields.description

        try:
            await self._repository.commit()
        except IntegrityError as exc:
            await self._repository.rollback()
            raise DuplicateCompanyNameError(
                "Company name is already in use.",
            ) from exc
        await self._repository.refresh(company)
        return company

    async def delete_company(self, company_id: UUID) -> None:
        """Soft delete a company and its descendants."""
        company = await self.get_company(company_id)
        await self._repository.soft_delete_company(company)
        await self._repository.commit()

    async def list_factories(
        self,
        *,
        limit: int,
        offset: int,
        search: str | None,
        company_id: UUID | None,
        sort_by: FactorySortField,
        sort_order: SortOrder,
    ) -> Page[Factory]:
        """Return paginated factories."""
        return await self._repository.list_factories(
            limit=limit,
            offset=offset,
            search=search,
            company_id=company_id,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def get_factory(self, factory_id: UUID) -> Factory:
        """Return a factory by ID."""
        factory = await self._repository.get_factory_by_id(factory_id)
        if factory is None:
            raise ResourceNotFoundError("Factory not found.")
        return factory

    async def create_factory(
        self,
        *,
        company_id: UUID,
        name: str,
        location: str | None,
        description: str | None,
    ) -> Factory:
        """Create a factory that belongs to an existing company."""
        await self._require_company(company_id)
        factory = await self._repository.create_factory(
            company_id=company_id,
            name=name,
            location=location,
            description=description,
        )
        await self._repository.commit()
        return factory

    async def update_factory(
        self,
        factory_id: UUID,
        fields: FactoryUpdateFields,
    ) -> Factory:
        """Update a factory."""
        factory = await self.get_factory(factory_id)
        if "company_id" in fields.provided and fields.company_id is not None:
            await self._require_company(fields.company_id)
            factory.company_id = fields.company_id
        if "name" in fields.provided and fields.name is not None:
            factory.name = fields.name
        if "location" in fields.provided:
            factory.location = fields.location
        if "description" in fields.provided:
            factory.description = fields.description

        await self._repository.commit()
        await self._repository.refresh(factory)
        return factory

    async def delete_factory(self, factory_id: UUID) -> None:
        """Soft delete a factory and its machines."""
        factory = await self.get_factory(factory_id)
        await self._repository.soft_delete_factory(factory)
        await self._repository.commit()

    async def list_machines(
        self,
        *,
        limit: int,
        offset: int,
        search: str | None,
        factory_id: UUID | None,
        company_id: UUID | None,
        sort_by: MachineSortField,
        sort_order: SortOrder,
    ) -> Page[Machine]:
        """Return paginated machines."""
        return await self._repository.list_machines(
            limit=limit,
            offset=offset,
            search=search,
            factory_id=factory_id,
            company_id=company_id,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def get_machine(self, machine_id: UUID) -> Machine:
        """Return a machine by ID."""
        machine = await self._repository.get_machine_by_id(machine_id)
        if machine is None:
            raise ResourceNotFoundError("Machine not found.")
        return machine

    async def create_machine(
        self,
        *,
        factory_id: UUID,
        name: str,
        serial_number: str | None,
        manufacturer: str | None,
        model: str | None,
    ) -> Machine:
        """Create a machine that belongs to an existing factory."""
        await self._require_factory(factory_id)
        machine = await self._repository.create_machine(
            factory_id=factory_id,
            name=name,
            serial_number=serial_number,
            manufacturer=manufacturer,
            model=model,
        )
        await self._repository.commit()
        return machine

    async def update_machine(
        self,
        machine_id: UUID,
        fields: MachineUpdateFields,
    ) -> Machine:
        """Update a machine."""
        machine = await self.get_machine(machine_id)
        if "factory_id" in fields.provided and fields.factory_id is not None:
            await self._require_factory(fields.factory_id)
            machine.factory_id = fields.factory_id
        if "name" in fields.provided and fields.name is not None:
            machine.name = fields.name
        if "serial_number" in fields.provided:
            machine.serial_number = fields.serial_number
        if "manufacturer" in fields.provided:
            machine.manufacturer = fields.manufacturer
        if "model" in fields.provided:
            machine.model = fields.model

        await self._repository.commit()
        await self._repository.refresh(machine)
        return machine

    async def delete_machine(self, machine_id: UUID) -> None:
        """Soft delete a machine."""
        machine = await self.get_machine(machine_id)
        await self._repository.soft_delete_machine(machine)
        await self._repository.commit()

    async def _require_company(self, company_id: UUID) -> Company:
        company = await self._repository.get_company_by_id(company_id)
        if company is None:
            raise RelatedResourceNotFoundError("Company does not exist.")
        return company

    async def _require_factory(self, factory_id: UUID) -> Factory:
        factory = await self._repository.get_factory_by_id(factory_id)
        if factory is None:
            raise RelatedResourceNotFoundError("Factory does not exist.")
        return factory
