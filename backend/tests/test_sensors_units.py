"""Sensor repository and service tests."""

from uuid import uuid4

import pytest
from app.repositories.manufacturing import ManufacturingRepository
from app.repositories.sensors import SensorRepository, normalize_sensor_name
from app.schemas.common import SortOrder
from app.schemas.sensors import SensorSortField
from app.services.exceptions import (
    DuplicateSensorNameError,
    InvalidSensorRangeError,
    RelatedResourceNotFoundError,
    ResourceNotFoundError,
)
from app.services.manufacturing import ManufacturingService
from app.services.sensors import SensorService, SensorUpdateFields
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def create_machine_id(
    session: AsyncSession,
) -> object:
    """Create a company, factory, and machine for sensor tests."""
    manufacturing_service = ManufacturingService(
        repository=ManufacturingRepository(session),
    )
    company = await manufacturing_service.create_company(
        name="Acme Manufacturing",
        description=None,
    )
    factory = await manufacturing_service.create_factory(
        company_id=company.id,
        name="Detroit Assembly",
        location=None,
        description=None,
    )
    machine = await manufacturing_service.create_machine(
        factory_id=factory.id,
        name="CNC Mill",
        serial_number=None,
        manufacturer=None,
        model=None,
    )
    return machine.id


@pytest.mark.anyio
async def test_repository_creates_lists_and_soft_deletes_sensor(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Repository operations persist, list, and soft delete sensors."""
    async with session_factory() as session:
        machine_id = await create_machine_id(session)
        repository = SensorRepository(session)
        sensor = await repository.create_sensor(
            machine_id=machine_id,
            name="Temperature Sensor",
            normalized_name=normalize_sensor_name("Temperature Sensor"),
            sensor_type="temperature",
            unit="celsius",
            sampling_rate=2.5,
            min_value=-20.0,
            max_value=120.0,
            description=None,
        )
        await repository.commit()

        page = await repository.list_sensors(
            limit=20,
            offset=0,
            search="temperature",
            machine_id=machine_id,
            sort_by=SensorSortField.NAME,
            sort_order=SortOrder.ASC,
        )
        await repository.soft_delete_sensor(sensor)
        await repository.commit()

        assert page.total == 1
        assert page.items[0].id == sensor.id
        assert await repository.get_sensor_by_id(sensor.id) is None


@pytest.mark.anyio
async def test_service_rejects_missing_machine(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sensor creation requires an existing machine."""
    async with session_factory() as session:
        service = SensorService(repository=SensorRepository(session))

        with pytest.raises(RelatedResourceNotFoundError):
            await service.create_sensor(
                machine_id=uuid4(),
                name="Temperature Sensor",
                sensor_type=None,
                unit=None,
                sampling_rate=1.0,
                min_value=0.0,
                max_value=10.0,
                description=None,
            )


@pytest.mark.anyio
async def test_service_rejects_duplicate_name_inside_machine(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sensor names are unique inside a machine."""
    async with session_factory() as session:
        machine_id = await create_machine_id(session)
        service = SensorService(repository=SensorRepository(session))
        await service.create_sensor(
            machine_id=machine_id,
            name="Temperature Sensor",
            sensor_type=None,
            unit=None,
            sampling_rate=1.0,
            min_value=0.0,
            max_value=10.0,
            description=None,
        )

        with pytest.raises(DuplicateSensorNameError):
            await service.create_sensor(
                machine_id=machine_id,
                name="TEMPERATURE   SENSOR",
                sensor_type=None,
                unit=None,
                sampling_rate=1.0,
                min_value=0.0,
                max_value=10.0,
                description=None,
            )


@pytest.mark.anyio
async def test_service_rejects_invalid_range(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sensor service rejects invalid value ranges."""
    async with session_factory() as session:
        machine_id = await create_machine_id(session)
        service = SensorService(repository=SensorRepository(session))

        with pytest.raises(InvalidSensorRangeError):
            await service.create_sensor(
                machine_id=machine_id,
                name="Temperature Sensor",
                sensor_type=None,
                unit=None,
                sampling_rate=1.0,
                min_value=10.0,
                max_value=10.0,
                description=None,
            )


@pytest.mark.anyio
async def test_service_update_validates_resulting_range(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sensor update validates the final value range."""
    async with session_factory() as session:
        machine_id = await create_machine_id(session)
        service = SensorService(repository=SensorRepository(session))
        sensor = await service.create_sensor(
            machine_id=machine_id,
            name="Temperature Sensor",
            sensor_type=None,
            unit=None,
            sampling_rate=1.0,
            min_value=0.0,
            max_value=10.0,
            description=None,
        )

        with pytest.raises(InvalidSensorRangeError):
            await service.update_sensor(
                sensor.id,
                SensorUpdateFields(
                    provided=frozenset({"min_value"}),
                    min_value=20.0,
                ),
            )


@pytest.mark.anyio
async def test_service_soft_delete_hides_sensor(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Soft deleted sensors are not returned by service reads."""
    async with session_factory() as session:
        machine_id = await create_machine_id(session)
        service = SensorService(repository=SensorRepository(session))
        sensor = await service.create_sensor(
            machine_id=machine_id,
            name="Temperature Sensor",
            sensor_type=None,
            unit=None,
            sampling_rate=1.0,
            min_value=0.0,
            max_value=10.0,
            description=None,
        )

        await service.delete_sensor(sensor.id)

        with pytest.raises(ResourceNotFoundError):
            await service.get_sensor(sensor.id)
