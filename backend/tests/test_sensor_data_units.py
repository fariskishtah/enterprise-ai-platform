"""Sensor data repository and service tests."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.models.sensor_data import ReadingQuality, ReadingSource
from app.models.user import UserRole
from app.repositories.manufacturing import ManufacturingRepository
from app.repositories.sensor_data import SensorDataRepository
from app.repositories.sensors import SensorRepository
from app.repositories.users import UserRepository
from app.schemas.common import SortOrder
from app.schemas.sensor_data import SensorReadingSortField, UploadJobSortField
from app.services.exceptions import (
    InvalidSensorReadingError,
    RelatedResourceNotFoundError,
)
from app.services.manufacturing import ManufacturingService
from app.services.sensor_data import SensorDataService
from app.services.sensors import SensorService
from app.services.users import UserService
from app.utils.passwords import PasswordHasher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

VALID_PASSWORD = "ValidPassword1!"


async def create_user_id(
    session: AsyncSession,
    *,
    email: str = "admin@example.com",
) -> UUID:
    """Create a user and return its ID for FK-backed unit tests."""
    service = UserService(
        repository=UserRepository(session),
        password_hasher=PasswordHasher(),
    )
    user = await service.create_user(
        email=email,
        password=VALID_PASSWORD,
        role=UserRole.ADMIN,
    )
    return user.id


async def create_sensor_id(
    session: AsyncSession,
    *,
    name: str = "Temperature Sensor",
    sensor_type: str = "temperature",
    unit: str = "celsius",
    min_value: float = -50.0,
    max_value: float = 150.0,
) -> UUID:
    """Create a machine and sensor for sensor data tests."""
    manufacturing_service = ManufacturingService(
        repository=ManufacturingRepository(session),
    )
    company = await manufacturing_service.create_company(
        name=f"{name} Company",
        description=None,
    )
    factory = await manufacturing_service.create_factory(
        company_id=company.id,
        name=f"{name} Factory",
        location=None,
        description=None,
    )
    machine = await manufacturing_service.create_machine(
        factory_id=factory.id,
        name=f"{name} Machine",
        serial_number=None,
        manufacturer=None,
        model=None,
    )
    sensor_service = SensorService(repository=SensorRepository(session))
    sensor = await sensor_service.create_sensor(
        machine_id=machine.id,
        name=name,
        sensor_type=sensor_type,
        unit=unit,
        sampling_rate=1.0,
        min_value=min_value,
        max_value=max_value,
        description=None,
    )
    return sensor.id


@pytest.mark.anyio
async def test_repository_creates_upload_job_and_sensor_reading(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Repository operations persist upload jobs and sensor readings."""
    async with session_factory() as session:
        sensor_id = await create_sensor_id(session)
        user_id = await create_user_id(session)
        repository = SensorDataRepository(session)
        upload_job = await repository.create_upload_job(
            filename="readings.csv",
            source=ReadingSource.API,
            created_by=user_id,
        )
        reading = await repository.create_sensor_reading(
            sensor_id=sensor_id,
            timestamp=datetime.now(UTC) - timedelta(minutes=1),
            value=42.0,
            quality=ReadingQuality.GOOD,
            source=ReadingSource.API,
            batch_id=upload_job.id,
        )
        await repository.increment_upload_job_valid_rows(upload_job)
        await repository.commit()

        readings_page = await repository.list_sensor_readings(
            limit=20,
            offset=0,
            sensor_id=sensor_id,
            batch_id=upload_job.id,
            quality=ReadingQuality.GOOD,
            source=ReadingSource.API,
            timestamp_from=None,
            timestamp_to=None,
            sort_by=SensorReadingSortField.TIMESTAMP,
            sort_order=SortOrder.DESC,
        )
        jobs_page = await repository.list_upload_jobs(
            limit=20,
            offset=0,
            status=None,
            source=ReadingSource.API,
            created_by=None,
            sort_by=UploadJobSortField.CREATED_AT,
            sort_order=SortOrder.DESC,
        )

        assert readings_page.total == 1
        assert readings_page.items[0].id == reading.id
        assert jobs_page.total == 1
        assert jobs_page.items[0].total_rows == 1
        assert jobs_page.items[0].valid_rows == 1


@pytest.mark.anyio
async def test_service_rejects_missing_sensor(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sensor readings require an existing active sensor."""
    async with session_factory() as session:
        service = SensorDataService(repository=SensorDataRepository(session))

        with pytest.raises(RelatedResourceNotFoundError):
            await service.create_sensor_reading(
                sensor_id=uuid4(),
                timestamp=datetime.now(UTC) - timedelta(minutes=1),
                value=1.0,
                quality=ReadingQuality.GOOD,
                source=ReadingSource.API,
                batch_id=None,
            )


@pytest.mark.anyio
async def test_service_rejects_future_timestamp(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sensor readings cannot be timestamped in the future."""
    async with session_factory() as session:
        sensor_id = await create_sensor_id(session)
        service = SensorDataService(repository=SensorDataRepository(session))

        with pytest.raises(InvalidSensorReadingError):
            await service.create_sensor_reading(
                sensor_id=sensor_id,
                timestamp=datetime.now(UTC) + timedelta(minutes=1),
                value=42.0,
                quality=ReadingQuality.GOOD,
                source=ReadingSource.API,
                batch_id=None,
            )


@pytest.mark.anyio
async def test_service_rejects_values_outside_configured_sensor_range(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Sensor readings must fit the configured sensor range."""
    async with session_factory() as session:
        sensor_id = await create_sensor_id(session, min_value=-10.0, max_value=80.0)
        service = SensorDataService(repository=SensorDataRepository(session))

        with pytest.raises(InvalidSensorReadingError):
            await service.create_sensor_reading(
                sensor_id=sensor_id,
                timestamp=datetime.now(UTC) - timedelta(minutes=1),
                value=500.0,
                quality=ReadingQuality.OUTLIER,
                source=ReadingSource.API,
                batch_id=None,
            )


@pytest.mark.anyio
async def test_service_rejects_negative_rpm_reading(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """RPM readings cannot be negative even if the configured range is permissive."""
    async with session_factory() as session:
        sensor_id = await create_sensor_id(
            session,
            name="Spindle RPM Sensor",
            sensor_type="rpm",
            unit="RPM",
            min_value=-100.0,
            max_value=10000.0,
        )
        service = SensorDataService(repository=SensorDataRepository(session))

        with pytest.raises(InvalidSensorReadingError):
            await service.create_sensor_reading(
                sensor_id=sensor_id,
                timestamp=datetime.now(UTC) - timedelta(minutes=1),
                value=-1.0,
                quality=ReadingQuality.BAD,
                source=ReadingSource.API,
                batch_id=None,
            )


@pytest.mark.anyio
async def test_service_increments_upload_job_counts_for_batched_reading(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Batched readings update upload job row counters."""
    async with session_factory() as session:
        sensor_id = await create_sensor_id(session)
        service = SensorDataService(repository=SensorDataRepository(session))
        created_by = await create_user_id(session)
        upload_job = await service.create_upload_job(
            filename="readings.csv",
            source=ReadingSource.API,
            created_by=created_by,
        )

        await service.create_sensor_reading(
            sensor_id=sensor_id,
            timestamp=datetime.now(UTC) - timedelta(minutes=1),
            value=10.0,
            quality=ReadingQuality.GOOD,
            source=ReadingSource.API,
            batch_id=upload_job.id,
        )
        refreshed_upload_job = await service.get_upload_job(upload_job.id)

        assert refreshed_upload_job.total_rows == 1
        assert refreshed_upload_job.valid_rows == 1
        assert refreshed_upload_job.invalid_rows == 0


@pytest.mark.anyio
async def test_service_rejects_upload_job_source_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Readings linked to an upload job must use the same source."""
    async with session_factory() as session:
        sensor_id = await create_sensor_id(session)
        service = SensorDataService(repository=SensorDataRepository(session))
        created_by = await create_user_id(session)
        upload_job = await service.create_upload_job(
            filename="readings.csv",
            source=ReadingSource.CSV,
            created_by=created_by,
        )

        with pytest.raises(InvalidSensorReadingError):
            await service.create_sensor_reading(
                sensor_id=sensor_id,
                timestamp=datetime.now(UTC) - timedelta(minutes=1),
                value=10.0,
                quality=ReadingQuality.GOOD,
                source=ReadingSource.API,
                batch_id=upload_job.id,
            )
