"""Sensor data ETL pipeline tests."""

from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import UUID, uuid4

import pytest
from app.models.sensor_data import ReadingQuality, ReadingSource, UploadJobStatus
from app.models.user import UserRole
from app.repositories.manufacturing import ManufacturingRepository
from app.repositories.sensor_data import SensorDataRepository
from app.repositories.sensors import SensorRepository
from app.repositories.users import UserRepository
from app.schemas.common import SortOrder
from app.schemas.sensor_data import SensorReadingSortField
from app.services.exceptions import InvalidSensorDataUploadError
from app.services.manufacturing import ManufacturingService
from app.services.sensor_data import SensorDataService
from app.services.sensor_data_etl import SensorDataEtlService
from app.services.sensors import SensorService
from app.services.users import UserService
from app.utils.passwords import PasswordHasher
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

VALID_PASSWORD = "ValidPassword1!"


async def create_user_id(session: AsyncSession) -> UUID:
    """Create a user for upload job ownership."""
    service = UserService(
        repository=UserRepository(session),
        password_hasher=PasswordHasher(),
    )
    user = await service.create_user(
        email=f"user-{uuid4()}@example.com",
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
    max_value: float = 200.0,
) -> UUID:
    """Create a sensor for ETL tests."""
    manufacturing_service = ManufacturingService(
        repository=ManufacturingRepository(session),
    )
    company = await manufacturing_service.create_company(
        name=f"Company {uuid4()}",
        description=None,
    )
    factory = await manufacturing_service.create_factory(
        company_id=company.id,
        name="Factory",
        location=None,
        description=None,
    )
    machine = await manufacturing_service.create_machine(
        factory_id=factory.id,
        name="Machine",
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


async def create_csv_upload_job(session: AsyncSession, user_id: UUID):
    """Create a CSV upload job."""
    service = SensorDataService(repository=SensorDataRepository(session))
    return await service.create_upload_job(
        filename="readings.csv",
        source=ReadingSource.CSV,
        created_by=user_id,
    )


def csv_file(content: str) -> BytesIO:
    """Return CSV content as a binary file object."""
    return BytesIO(content.encode("utf-8"))


def timestamp(minutes_ago: int) -> str:
    """Return an ISO UTC timestamp in the past."""
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()


@pytest.mark.anyio
async def test_etl_pipeline_completes_all_valid_csv_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A valid CSV upload is cleaned, normalized, bulk inserted, and completed."""
    async with session_factory() as session:
        user_id = await create_user_id(session)
        sensor_id = await create_sensor_id(session)
        upload_job = await create_csv_upload_job(session, user_id)
        etl_service = SensorDataEtlService(
            repository=SensorDataRepository(session),
            chunk_size=2,
            float_precision=2,
            outlier_z_score_threshold=3.0,
        )

        result = await etl_service.process_csv_upload(
            upload_job_id=upload_job.id,
            file=csv_file(
                " sensor_id , timestamp , value , quality \n"
                f" {sensor_id} , {timestamp(5)} , 10.126 , good \n"
                f" {sensor_id} , {timestamp(4)} , 11.124 , \n"
            ),
        )
        page = await SensorDataService(
            repository=SensorDataRepository(session),
        ).list_sensor_readings(
            limit=20,
            offset=0,
            sensor_id=sensor_id,
            batch_id=upload_job.id,
            quality=None,
            source=ReadingSource.CSV,
            timestamp_from=None,
            timestamp_to=None,
            sort_by=SensorReadingSortField.VALUE,
            sort_order=SortOrder.ASC,
        )

        assert result.status == UploadJobStatus.COMPLETED
        assert result.total_rows == 2
        assert result.valid_rows == 2
        assert result.invalid_rows == 0
        assert [reading.value for reading in page.items] == [10.13, 11.12]
        assert all(reading.source == ReadingSource.CSV for reading in page.items)


@pytest.mark.anyio
async def test_etl_pipeline_counts_invalid_rows_and_marks_outliers(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Invalid rows are counted, valid rows are inserted, and outliers are flagged."""
    async with session_factory() as session:
        user_id = await create_user_id(session)
        sensor_id = await create_sensor_id(session, max_value=200.0)
        upload_job = await create_csv_upload_job(session, user_id)
        first_timestamp = timestamp(10)
        etl_service = SensorDataEtlService(
            repository=SensorDataRepository(session),
            chunk_size=16,
            float_precision=2,
            outlier_z_score_threshold=1.0,
        )

        result = await etl_service.process_csv_upload(
            upload_job_id=upload_job.id,
            file=csv_file(
                "sensor_id,timestamp,value,quality\n"
                f"{sensor_id},{first_timestamp},10,GOOD\n"
                f"{sensor_id},{timestamp(9)},11,GOOD\n"
                f"{sensor_id},{timestamp(8)},12,GOOD\n"
                f"{sensor_id},{timestamp(7)},100,GOOD\n"
                f"{uuid4()},{timestamp(6)},10,GOOD\n"
                f"{sensor_id},{datetime.now(UTC) + timedelta(minutes=1)},10,GOOD\n"
                f"{sensor_id},{timestamp(5)},abc,GOOD\n"
                f"{sensor_id},{first_timestamp},13,GOOD\n"
                f"{sensor_id},{timestamp(4)},9999,GOOD\n"
            ),
        )
        page = await SensorDataService(
            repository=SensorDataRepository(session),
        ).list_sensor_readings(
            limit=20,
            offset=0,
            sensor_id=sensor_id,
            batch_id=upload_job.id,
            quality=None,
            source=ReadingSource.CSV,
            timestamp_from=None,
            timestamp_to=None,
            sort_by=SensorReadingSortField.VALUE,
            sort_order=SortOrder.ASC,
        )

        assert result.status == UploadJobStatus.FAILED
        assert result.total_rows == 9
        assert result.valid_rows == 4
        assert result.invalid_rows == 5
        assert page.total == 4
        assert any(reading.quality == ReadingQuality.OUTLIER for reading in page.items)


@pytest.mark.anyio
async def test_etl_pipeline_fails_schema_invalid_csv_and_finalizes_job(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Schema-invalid CSV files fail the upload job instead of hanging it."""
    async with session_factory() as session:
        user_id = await create_user_id(session)
        sensor_id = await create_sensor_id(session)
        upload_job = await create_csv_upload_job(session, user_id)
        etl_service = SensorDataEtlService(
            repository=SensorDataRepository(session),
            chunk_size=2,
            float_precision=2,
            outlier_z_score_threshold=3.0,
        )

        with pytest.raises(InvalidSensorDataUploadError):
            await etl_service.process_csv_upload(
                upload_job_id=upload_job.id,
                file=csv_file(
                    "sensor_id,timestamp\n" f"{sensor_id},{timestamp(5)}\n",
                ),
            )
        refreshed_job = await SensorDataService(
            repository=SensorDataRepository(session),
        ).get_upload_job(upload_job.id)

        assert refreshed_job.status == UploadJobStatus.FAILED
        assert refreshed_job.invalid_rows == 1


@pytest.mark.anyio
async def test_etl_pipeline_rejects_non_pending_upload_job(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """CSV uploads only run for pending upload jobs."""
    async with session_factory() as session:
        user_id = await create_user_id(session)
        sensor_id = await create_sensor_id(session)
        upload_job = await create_csv_upload_job(session, user_id)
        etl_service = SensorDataEtlService(
            repository=SensorDataRepository(session),
            chunk_size=2,
            float_precision=2,
            outlier_z_score_threshold=3.0,
        )
        await etl_service.process_csv_upload(
            upload_job_id=upload_job.id,
            file=csv_file(
                "sensor_id,timestamp,value\n" f"{sensor_id},{timestamp(5)},10\n",
            ),
        )

        with pytest.raises(InvalidSensorDataUploadError):
            await etl_service.process_csv_upload(
                upload_job_id=upload_job.id,
                file=csv_file(
                    "sensor_id,timestamp,value\n" f"{sensor_id},{timestamp(4)},11\n",
                ),
            )


@pytest.mark.anyio
async def test_etl_pipeline_performance_smoke_processes_chunked_bulk_insert(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A larger CSV is processed in chunks and inserted in bulk."""
    async with session_factory() as session:
        user_id = await create_user_id(session)
        sensor_id = await create_sensor_id(session, min_value=0.0, max_value=2000.0)
        upload_job = await create_csv_upload_job(session, user_id)
        etl_service = SensorDataEtlService(
            repository=SensorDataRepository(session),
            chunk_size=128,
            float_precision=3,
            outlier_z_score_threshold=3.0,
        )
        base_timestamp = datetime.now(UTC) - timedelta(days=1)
        rows = [
            "sensor_id,timestamp,value",
            *[
                (
                    f"{sensor_id},"
                    f"{(base_timestamp + timedelta(seconds=index)).isoformat()},"
                    f"{float(index)}"
                )
                for index in range(1000)
            ],
        ]

        result = await etl_service.process_csv_upload(
            upload_job_id=upload_job.id,
            file=csv_file("\n".join(rows)),
        )

        assert result.status == UploadJobStatus.COMPLETED
        assert result.total_rows == 1000
        assert result.valid_rows == 1000
        assert result.invalid_rows == 0
