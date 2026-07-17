"""Feature engineering pipeline tests."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import polars as pl
import pytest
from app.models.sensor_data import ReadingQuality, ReadingSource
from app.repositories.feature_engineering import FeatureEngineeringRepository
from app.repositories.manufacturing import ManufacturingRepository
from app.repositories.sensor_data import SensorDataRepository
from app.repositories.sensors import SensorRepository
from app.services.exceptions import InvalidFeatureDatasetError
from app.services.feature_engineering import FeatureEngineeringService
from app.services.manufacturing import ManufacturingService
from app.services.sensors import SensorService
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def create_sensor_id(session: AsyncSession) -> UUID:
    """Create a sensor for feature engineering tests."""
    manufacturing_service = ManufacturingService(
        repository=ManufacturingRepository(session),
    )
    company = await manufacturing_service.create_company(
        name=f"Feature Company {uuid4()}",
        description=None,
    )
    factory = await manufacturing_service.create_factory(
        company_id=company.id,
        name="Feature Factory",
        location=None,
        description=None,
    )
    machine = await manufacturing_service.create_machine(
        factory_id=factory.id,
        name="Feature Machine",
        serial_number=None,
        manufacturer=None,
        model=None,
    )
    sensor = await SensorService(repository=SensorRepository(session)).create_sensor(
        machine_id=machine.id,
        name="Temperature Sensor",
        sensor_type="temperature",
        unit="celsius",
        sampling_rate=1.0,
        min_value=-50.0,
        max_value=250.0,
        description=None,
    )
    return sensor.id


async def insert_readings(
    session: AsyncSession,
    *,
    sensor_id: UUID,
    values: list[float],
    start_at: datetime,
    quality: ReadingQuality = ReadingQuality.GOOD,
) -> None:
    """Bulk insert source readings for feature tests."""
    repository = SensorDataRepository(session)
    records = [
        {
            "sensor_id": sensor_id,
            "timestamp": start_at + timedelta(minutes=index),
            "value": value,
            "quality": quality,
            "source": ReadingSource.API,
            "batch_id": None,
        }
        for index, value in enumerate(values)
    ]
    await repository.bulk_create_sensor_readings(records)
    await repository.commit()


def feature_service(
    session: AsyncSession,
    *,
    dataset_dir: Path,
    rolling_window_size: int = 3,
) -> FeatureEngineeringService:
    """Build a feature engineering service for tests."""
    return FeatureEngineeringService(
        repository=FeatureEngineeringRepository(session),
        dataset_dir=dataset_dir,
        rolling_window_size=rolling_window_size,
    )


@pytest.mark.anyio
async def test_feature_pipeline_generates_expected_features(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Feature export generates time, rolling, lag, statistics, and delta features."""
    async with session_factory() as session:
        sensor_id = await create_sensor_id(session)
        start_at = datetime(2026, 7, 13, 6, 0, tzinfo=UTC)
        await insert_readings(
            session,
            sensor_id=sensor_id,
            values=[10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0, 30.0],
            start_at=start_at,
        )

        result = await feature_service(
            session,
            dataset_dir=tmp_path,
            rolling_window_size=3,
        ).export_feature_dataset(
            sensor_id=sensor_id,
            timestamp_from=None,
            timestamp_to=None,
        )
        frame = pl.read_parquet(result.file_path).sort("timestamp")
        third_row = frame.row(2, named=True)
        last_row = frame.row(-1, named=True)

        assert result.dataset_name == "dataset_v1.parquet"
        assert result.version == 1
        assert result.rows == 11
        assert result.file_path.exists()
        assert third_row["hour"] == 6
        assert third_row["day_of_month"] == 13
        assert third_row["month"] == 7
        assert third_row["weekend"] is False
        assert third_row["shift"] == "day"
        assert third_row["rolling_mean"] == 12.0
        assert third_row["rolling_min"] == 10.0
        assert third_row["rolling_max"] == 14.0
        assert third_row["lag_1"] == 12.0
        assert last_row["lag_10"] == 10.0
        assert last_row["mean"] == 20.0
        assert last_row["median"] == 20.0
        assert last_row["min"] == 10.0
        assert last_row["max"] == 30.0
        assert last_row["range"] == 20.0
        assert last_row["delta"] == 2.0
        assert last_row["percent_change"] == pytest.approx(2.0 / 28.0)
        assert last_row["rate_of_change"] == pytest.approx(2.0 / 60.0)


@pytest.mark.anyio
async def test_feature_export_versions_dataset_files(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Repeated exports create incrementing Parquet dataset versions."""
    async with session_factory() as session:
        sensor_id = await create_sensor_id(session)
        await insert_readings(
            session,
            sensor_id=sensor_id,
            values=[1.0, 2.0, 3.0],
            start_at=datetime.now(UTC) - timedelta(hours=1),
        )
        service = feature_service(session, dataset_dir=tmp_path)

        first = await service.export_feature_dataset(
            sensor_id=sensor_id,
            timestamp_from=None,
            timestamp_to=None,
        )
        second = await service.export_feature_dataset(
            sensor_id=sensor_id,
            timestamp_from=None,
            timestamp_to=None,
        )

        assert first.dataset_name == "dataset_v1.parquet"
        assert second.dataset_name == "dataset_v2.parquet"
        assert first.file_path.exists()
        assert second.file_path.exists()


@pytest.mark.anyio
async def test_feature_pipeline_excludes_bad_and_missing_readings(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Only validated readings are used for feature datasets."""
    async with session_factory() as session:
        sensor_id = await create_sensor_id(session)
        start_at = datetime.now(UTC) - timedelta(hours=1)
        await insert_readings(
            session,
            sensor_id=sensor_id,
            values=[1.0, 2.0],
            start_at=start_at,
            quality=ReadingQuality.GOOD,
        )
        await insert_readings(
            session,
            sensor_id=sensor_id,
            values=[3.0],
            start_at=start_at + timedelta(minutes=10),
            quality=ReadingQuality.BAD,
        )
        await insert_readings(
            session,
            sensor_id=sensor_id,
            values=[4.0],
            start_at=start_at + timedelta(minutes=20),
            quality=ReadingQuality.MISSING,
        )

        result = await feature_service(
            session,
            dataset_dir=tmp_path,
        ).export_feature_dataset(
            sensor_id=sensor_id,
            timestamp_from=None,
            timestamp_to=None,
        )
        frame = pl.read_parquet(result.file_path)

        assert result.rows == 2
        assert frame["quality"].to_list() == ["GOOD", "GOOD"]


@pytest.mark.anyio
async def test_feature_export_rejects_empty_dataset(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Feature export fails clearly when no validated readings exist."""
    async with session_factory() as session:
        service = feature_service(session, dataset_dir=tmp_path)

        with pytest.raises(InvalidFeatureDatasetError):
            await service.export_feature_dataset(
                sensor_id=uuid4(),
                timestamp_from=None,
                timestamp_to=None,
            )


@pytest.mark.anyio
async def test_feature_pipeline_performance_smoke(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """A larger reading set exports to Parquet with all expected rows."""
    async with session_factory() as session:
        sensor_id = await create_sensor_id(session)
        await insert_readings(
            session,
            sensor_id=sensor_id,
            values=[float(index) for index in range(1000)],
            start_at=datetime.now(UTC) - timedelta(days=1),
        )

        result = await feature_service(
            session,
            dataset_dir=tmp_path,
            rolling_window_size=10,
        ).export_feature_dataset(
            sensor_id=sensor_id,
            timestamp_from=None,
            timestamp_to=None,
        )
        frame = pl.read_parquet(result.file_path)

        assert result.rows == 1000
        assert frame.height == 1000
        assert "rolling_mean" in frame.columns
        assert "lag_10" in frame.columns
        assert "rate_of_change" in frame.columns
