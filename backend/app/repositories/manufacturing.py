"""Persistence adapter for manufacturing domain entities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar, cast
from uuid import UUID

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.models.manufacturing import Company, Factory, Machine
from app.schemas.common import SortOrder
from app.schemas.manufacturing import (
    CompanySortField,
    FactorySortField,
    MachineSortField,
)
from app.utils.security import utc_now

T = TypeVar("T", Company, Factory, Machine)


@dataclass(frozen=True)
class Page[T: Company | Factory | Machine]:
    """Paginated repository result."""

    items: list[T]
    total: int


def normalize_name(name: str) -> str:
    """Normalize entity names for uniqueness and search."""
    return " ".join(name.strip().casefold().split())


class ManufacturingRepository:
    """Repository for manufacturing domain persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_company_by_id(
        self,
        company_id: UUID,
        *,
        include_deleted: bool = False,
        tenant_company_id: UUID | None = None,
    ) -> Company | None:
        """Return a company by ID."""
        statement = select(Company).where(Company.id == company_id)
        if tenant_company_id is not None:
            statement = statement.where(Company.id == tenant_company_id)
        if not include_deleted:
            statement = statement.where(Company.deleted_at.is_(None))
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_company_by_normalized_name(
        self,
        normalized_name: str,
        *,
        exclude_company_id: UUID | None = None,
    ) -> Company | None:
        """Return a company by normalized name."""
        statement = select(Company).where(Company.normalized_name == normalized_name)
        if exclude_company_id is not None:
            statement = statement.where(Company.id != exclude_company_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list_companies(
        self,
        *,
        limit: int,
        offset: int,
        search: str | None,
        sort_by: CompanySortField,
        sort_order: SortOrder,
        company_id: UUID | None = None,
    ) -> Page[Company]:
        """Return paginated active companies."""
        statement = select(Company).where(Company.deleted_at.is_(None))
        if company_id is not None:
            statement = statement.where(Company.id == company_id)
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    Company.name.ilike(pattern),
                    Company.description.ilike(pattern),
                ),
            )
        return await self._paginate(
            statement=statement,
            model=Company,
            sort_column=self._company_sort_column(sort_by),
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    async def create_company(
        self,
        *,
        name: str,
        normalized_name: str,
        description: str | None,
    ) -> Company:
        """Create a company."""
        company = Company(
            name=name,
            normalized_name=normalized_name,
            description=description,
        )
        self._session.add(company)
        await self._session.flush()
        await self._session.refresh(company)
        return company

    async def get_factory_by_id(
        self,
        factory_id: UUID,
        *,
        include_deleted: bool = False,
        company_id: UUID | None = None,
    ) -> Factory | None:
        """Return a factory by ID."""
        statement = select(Factory).where(Factory.id == factory_id)
        if company_id is not None:
            statement = statement.where(Factory.company_id == company_id)
        if not include_deleted:
            statement = statement.where(Factory.deleted_at.is_(None))
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

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
        """Return paginated active factories."""
        statement = select(Factory).where(Factory.deleted_at.is_(None))
        if company_id is not None:
            statement = statement.where(Factory.company_id == company_id)
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    Factory.name.ilike(pattern),
                    Factory.location.ilike(pattern),
                    Factory.description.ilike(pattern),
                ),
            )
        return await self._paginate(
            statement=statement,
            model=Factory,
            sort_column=self._factory_sort_column(sort_by),
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    async def create_factory(
        self,
        *,
        company_id: UUID,
        name: str,
        location: str | None,
        description: str | None,
    ) -> Factory:
        """Create a factory."""
        factory = Factory(
            company_id=company_id,
            name=name,
            location=location,
            description=description,
        )
        self._session.add(factory)
        await self._session.flush()
        await self._session.refresh(factory)
        return factory

    async def get_machine_by_id(
        self,
        machine_id: UUID,
        *,
        include_deleted: bool = False,
        company_id: UUID | None = None,
    ) -> Machine | None:
        """Return a machine by ID."""
        statement = select(Machine).where(Machine.id == machine_id)
        if company_id is not None:
            statement = statement.join(Factory).where(Factory.company_id == company_id)
        if not include_deleted:
            statement = statement.where(Machine.deleted_at.is_(None))
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

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
        """Return paginated active machines."""
        statement = select(Machine).where(Machine.deleted_at.is_(None))
        if factory_id is not None:
            statement = statement.where(Machine.factory_id == factory_id)
        if company_id is not None:
            statement = statement.join(Factory).where(Factory.company_id == company_id)
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    Machine.name.ilike(pattern),
                    Machine.serial_number.ilike(pattern),
                    Machine.manufacturer.ilike(pattern),
                    Machine.model.ilike(pattern),
                ),
            )
        return await self._paginate(
            statement=statement,
            model=Machine,
            sort_column=self._machine_sort_column(sort_by),
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    async def create_machine(
        self,
        *,
        factory_id: UUID,
        name: str,
        serial_number: str | None,
        manufacturer: str | None,
        model: str | None,
    ) -> Machine:
        """Create a machine."""
        machine = Machine(
            factory_id=factory_id,
            name=name,
            serial_number=serial_number,
            manufacturer=manufacturer,
            model=model,
        )
        self._session.add(machine)
        await self._session.flush()
        await self._session.refresh(machine)
        return machine

    async def soft_delete_company(self, company: Company) -> None:
        """Soft delete a company and its child factories and machines."""
        deleted_at = utc_now()
        company.deleted_at = deleted_at
        await self._session.execute(
            update(Factory)
            .where(Factory.company_id == company.id, Factory.deleted_at.is_(None))
            .values(deleted_at=deleted_at),
        )
        await self._session.execute(
            update(Machine)
            .where(
                Machine.factory_id.in_(
                    select(Factory.id).where(Factory.company_id == company.id),
                ),
                Machine.deleted_at.is_(None),
            )
            .values(deleted_at=deleted_at),
        )
        await self._session.flush()

    async def soft_delete_factory(self, factory: Factory) -> None:
        """Soft delete a factory and its child machines."""
        deleted_at = utc_now()
        factory.deleted_at = deleted_at
        await self._session.execute(
            update(Machine)
            .where(Machine.factory_id == factory.id, Machine.deleted_at.is_(None))
            .values(deleted_at=deleted_at),
        )
        await self._session.flush()

    async def soft_delete_machine(self, machine: Machine) -> None:
        """Soft delete a machine."""
        machine.deleted_at = utc_now()
        await self._session.flush()

    async def commit(self) -> None:
        """Commit the active transaction."""
        await self._session.commit()

    async def rollback(self) -> None:
        """Roll back the active transaction."""
        await self._session.rollback()

    async def refresh(self, entity: Company | Factory | Machine) -> None:
        """Refresh an entity from the database."""
        await self._session.refresh(entity)

    async def _paginate(
        self,
        *,
        statement: Select[tuple[T]],
        model: type[T],
        sort_column: ColumnElement[object],
        sort_order: SortOrder,
        limit: int,
        offset: int,
    ) -> Page[T]:
        count_statement = select(func.count()).select_from(
            statement.order_by(None).subquery(),
        )
        total = await self._session.scalar(count_statement)

        ordered_column = (
            sort_column.desc() if sort_order == SortOrder.DESC else sort_column.asc()
        )
        paginated_statement = (
            statement.order_by(
                ordered_column,
                model.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(paginated_statement)
        return Page(items=list(result.scalars().all()), total=total or 0)

    def _company_sort_column(
        self,
        sort_by: CompanySortField,
    ) -> ColumnElement[object]:
        return cast(
            ColumnElement[object],
            {
                CompanySortField.NAME: Company.name,
                CompanySortField.CREATED_AT: Company.created_at,
                CompanySortField.UPDATED_AT: Company.updated_at,
            }[sort_by],
        )

    def _factory_sort_column(
        self,
        sort_by: FactorySortField,
    ) -> ColumnElement[object]:
        return cast(
            ColumnElement[object],
            {
                FactorySortField.NAME: Factory.name,
                FactorySortField.LOCATION: Factory.location,
                FactorySortField.CREATED_AT: Factory.created_at,
                FactorySortField.UPDATED_AT: Factory.updated_at,
            }[sort_by],
        )

    def _machine_sort_column(
        self,
        sort_by: MachineSortField,
    ) -> ColumnElement[object]:
        return cast(
            ColumnElement[object],
            {
                MachineSortField.NAME: Machine.name,
                MachineSortField.SERIAL_NUMBER: Machine.serial_number,
                MachineSortField.CREATED_AT: Machine.created_at,
                MachineSortField.UPDATED_AT: Machine.updated_at,
            }[sort_by],
        )
