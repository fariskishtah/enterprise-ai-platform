"""Sensor application service."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.models.sensor import Sensor
from app.repositories.sensors import SensorPage, SensorRepository, normalize_sensor_name
from app.schemas.common import SortOrder
from app.schemas.sensors import SensorSortField
from app.services.exceptions import (
    DuplicateSensorNameError,
    InvalidSensorRangeError,
    RelatedResourceNotFoundError,
    ResourceNotFoundError,
)


@dataclass(frozen=True)
class SensorUpdateFields:
    """Sensor fields requested for update."""

    provided: frozenset[str]
    machine_id: UUID | None = None
    name: str | None = None
    sensor_type: str | None = None
    unit: str | None = None
    sampling_rate: float | None = None
    min_value: float | None = None
    max_value: float | None = None
    description: str | None = None


class SensorService:
    """Application use cases for sensors."""

    def __init__(self, *, repository: SensorRepository) -> None:
        self._repository = repository

    async def list_sensors(
        self,
        *,
        limit: int,
        offset: int,
        search: str | None,
        machine_id: UUID | None,
        sort_by: SensorSortField,
        sort_order: SortOrder,
    ) -> SensorPage:
        """Return paginated sensors."""
        return await self._repository.list_sensors(
            limit=limit,
            offset=offset,
            search=search,
            machine_id=machine_id,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def list_machine_sensors(
        self,
        *,
        machine_id: UUID,
        limit: int,
        offset: int,
        search: str | None,
        sort_by: SensorSortField,
        sort_order: SortOrder,
    ) -> SensorPage:
        """Return paginated sensors for an active machine."""
        machine = await self._repository.get_machine_by_id(machine_id)
        if machine is None:
            raise ResourceNotFoundError("Machine not found.")
        return await self.list_sensors(
            limit=limit,
            offset=offset,
            search=search,
            machine_id=machine_id,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def get_sensor(self, sensor_id: UUID) -> Sensor:
        """Return a sensor by ID."""
        sensor = await self._repository.get_sensor_by_id(sensor_id)
        if sensor is None:
            raise ResourceNotFoundError("Sensor not found.")
        return sensor

    async def create_sensor(
        self,
        *,
        machine_id: UUID,
        name: str,
        sensor_type: str | None,
        unit: str | None,
        sampling_rate: float,
        min_value: float,
        max_value: float,
        description: str | None,
    ) -> Sensor:
        """Create a sensor for an existing machine."""
        await self._require_machine(machine_id)
        self._validate_range(min_value=min_value, max_value=max_value)
        normalized_name = normalize_sensor_name(name)
        existing_sensor = await self._repository.get_sensor_by_machine_and_name(
            machine_id=machine_id,
            normalized_name=normalized_name,
        )
        if existing_sensor is not None:
            raise DuplicateSensorNameError(
                "Sensor name is already in use for this machine.",
            )

        try:
            sensor = await self._repository.create_sensor(
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
            await self._repository.commit()
        except IntegrityError as exc:
            await self._repository.rollback()
            raise DuplicateSensorNameError(
                "Sensor name is already in use for this machine.",
            ) from exc
        return sensor

    async def update_sensor(
        self,
        sensor_id: UUID,
        fields: SensorUpdateFields,
    ) -> Sensor:
        """Update a sensor."""
        sensor = await self.get_sensor(sensor_id)
        target_machine_id = sensor.machine_id
        if "machine_id" in fields.provided and fields.machine_id is not None:
            await self._require_machine(fields.machine_id)
            target_machine_id = fields.machine_id

        target_name = sensor.name
        target_normalized_name = sensor.normalized_name
        if "name" in fields.provided and fields.name is not None:
            target_name = fields.name
            target_normalized_name = normalize_sensor_name(fields.name)

        if "machine_id" in fields.provided or "name" in fields.provided:
            existing_sensor = await self._repository.get_sensor_by_machine_and_name(
                machine_id=target_machine_id,
                normalized_name=target_normalized_name,
                exclude_sensor_id=sensor.id,
            )
            if existing_sensor is not None:
                raise DuplicateSensorNameError(
                    "Sensor name is already in use for this machine.",
                )

        target_min_value = sensor.min_value
        if "min_value" in fields.provided and fields.min_value is not None:
            target_min_value = fields.min_value
        target_max_value = sensor.max_value
        if "max_value" in fields.provided and fields.max_value is not None:
            target_max_value = fields.max_value
        self._validate_range(min_value=target_min_value, max_value=target_max_value)

        sensor.machine_id = target_machine_id
        sensor.name = target_name
        sensor.normalized_name = target_normalized_name
        if "sensor_type" in fields.provided:
            sensor.sensor_type = fields.sensor_type
        if "unit" in fields.provided:
            sensor.unit = fields.unit
        if "sampling_rate" in fields.provided and fields.sampling_rate is not None:
            sensor.sampling_rate = fields.sampling_rate
        if "min_value" in fields.provided and fields.min_value is not None:
            sensor.min_value = fields.min_value
        if "max_value" in fields.provided and fields.max_value is not None:
            sensor.max_value = fields.max_value
        if "description" in fields.provided:
            sensor.description = fields.description

        try:
            await self._repository.commit()
        except IntegrityError as exc:
            await self._repository.rollback()
            raise DuplicateSensorNameError(
                "Sensor name is already in use for this machine.",
            ) from exc
        await self._repository.refresh(sensor)
        return sensor

    async def delete_sensor(self, sensor_id: UUID) -> None:
        """Soft delete a sensor."""
        sensor = await self.get_sensor(sensor_id)
        await self._repository.soft_delete_sensor(sensor)
        await self._repository.commit()

    async def _require_machine(self, machine_id: UUID) -> None:
        machine = await self._repository.get_machine_by_id(machine_id)
        if machine is None:
            raise RelatedResourceNotFoundError("Machine does not exist.")

    def _validate_range(self, *, min_value: float, max_value: float) -> None:
        if min_value >= max_value:
            raise InvalidSensorRangeError(
                "Minimum value must be less than maximum value.",
            )
