"""Persistence adapter for sensors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.models.manufacturing import Factory, Machine
from app.models.sensor import Sensor
from app.schemas.common import SortOrder
from app.schemas.sensors import SensorSortField
from app.utils.security import utc_now


@dataclass(frozen=True)
class SensorPage:
    """Paginated sensor result."""

    items: list[Sensor]
    total: int


def normalize_sensor_name(name: str) -> str:
    """Normalize sensor names for per-machine uniqueness."""
    return " ".join(name.strip().casefold().split())


class SensorRepository:
    """Repository for sensor persistence."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_machine_by_id(
        self, machine_id: UUID, *, company_id: UUID | None = None
    ) -> Machine | None:
        """Return an active machine by ID."""
        statement = select(Machine).where(
            Machine.id == machine_id,
            Machine.deleted_at.is_(None),
        )
        if company_id is not None:
            statement = statement.join(Factory).where(Factory.company_id == company_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_sensor_by_id(
        self,
        sensor_id: UUID,
        *,
        include_deleted: bool = False,
        company_id: UUID | None = None,
    ) -> Sensor | None:
        """Return a sensor by ID."""
        statement = select(Sensor).where(Sensor.id == sensor_id)
        if company_id is not None:
            statement = (
                statement.join(Machine, Machine.id == Sensor.machine_id)
                .join(Factory, Factory.id == Machine.factory_id)
                .where(Factory.company_id == company_id)
            )
        if not include_deleted:
            statement = statement.where(Sensor.deleted_at.is_(None))
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_sensor_by_machine_and_name(
        self,
        *,
        machine_id: UUID,
        normalized_name: str,
        exclude_sensor_id: UUID | None = None,
    ) -> Sensor | None:
        """Return a sensor by machine and normalized name."""
        statement = select(Sensor).where(
            Sensor.machine_id == machine_id,
            Sensor.normalized_name == normalized_name,
        )
        if exclude_sensor_id is not None:
            statement = statement.where(Sensor.id != exclude_sensor_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list_sensors(
        self,
        *,
        limit: int,
        offset: int,
        search: str | None,
        machine_id: UUID | None,
        sort_by: SensorSortField,
        sort_order: SortOrder,
        company_id: UUID | None = None,
    ) -> SensorPage:
        """Return paginated active sensors."""
        statement = select(Sensor).where(Sensor.deleted_at.is_(None))
        if company_id is not None:
            statement = (
                statement.join(Machine, Machine.id == Sensor.machine_id)
                .join(Factory, Factory.id == Machine.factory_id)
                .where(Factory.company_id == company_id)
            )
        if machine_id is not None:
            statement = statement.where(Sensor.machine_id == machine_id)
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(
                or_(
                    Sensor.name.ilike(pattern),
                    Sensor.sensor_type.ilike(pattern),
                    Sensor.unit.ilike(pattern),
                    Sensor.description.ilike(pattern),
                ),
            )
        return await self._paginate(
            statement=statement,
            sort_column=self._sort_column(sort_by),
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    async def create_sensor(
        self,
        *,
        machine_id: UUID,
        name: str,
        normalized_name: str,
        sensor_type: str | None,
        unit: str | None,
        sampling_rate: float,
        min_value: float,
        max_value: float,
        description: str | None,
    ) -> Sensor:
        """Create a sensor."""
        sensor = Sensor(
            machine_id=machine_id,
            name=name,
            normalized_name=normalized_name,
            sensor_type=sensor_type,
            unit=unit,
            sampling_rate=sampling_rate,
            min_value=min_value,
            max_value=max_value,
            description=description,
        )
        self._session.add(sensor)
        await self._session.flush()
        await self._session.refresh(sensor)
        return sensor

    async def soft_delete_sensor(self, sensor: Sensor) -> None:
        """Soft delete a sensor."""
        sensor.deleted_at = utc_now()
        await self._session.flush()

    async def commit(self) -> None:
        """Commit the active transaction."""
        await self._session.commit()

    async def rollback(self) -> None:
        """Roll back the active transaction."""
        await self._session.rollback()

    async def refresh(self, sensor: Sensor) -> None:
        """Refresh a sensor from the database."""
        await self._session.refresh(sensor)

    async def _paginate(
        self,
        *,
        statement: Select[tuple[Sensor]],
        sort_column: ColumnElement[object],
        sort_order: SortOrder,
        limit: int,
        offset: int,
    ) -> SensorPage:
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
                Sensor.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(paginated_statement)
        return SensorPage(items=list(result.scalars().all()), total=total or 0)

    def _sort_column(self, sort_by: SensorSortField) -> ColumnElement[object]:
        return cast(
            ColumnElement[object],
            {
                SensorSortField.NAME: Sensor.name,
                SensorSortField.SENSOR_TYPE: Sensor.sensor_type,
                SensorSortField.CREATED_AT: Sensor.created_at,
                SensorSortField.UPDATED_AT: Sensor.updated_at,
            }[sort_by],
        )
