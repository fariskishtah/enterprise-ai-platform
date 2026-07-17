"""Persistence adapter for sensor data platform entities."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TypeVar, cast
from uuid import UUID

from sqlalchemy import Select, func, insert, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.models.sensor import Sensor
from app.models.sensor_data import (
    ReadingQuality,
    ReadingSource,
    SensorReading,
    UploadJob,
    UploadJobStatus,
)
from app.schemas.common import SortOrder
from app.schemas.sensor_data import SensorReadingSortField, UploadJobSortField

T = TypeVar("T", SensorReading, UploadJob)
type SensorReadingInsert = dict[str, object]


@dataclass(frozen=True)
class Page[T: SensorReading | UploadJob]:
    """Paginated repository result."""

    items: list[T]
    total: int


class SensorDataRepository:
    """Repository for sensor readings and upload jobs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_sensor_by_id(self, sensor_id: UUID) -> Sensor | None:
        """Return an active sensor by ID."""
        statement = select(Sensor).where(
            Sensor.id == sensor_id,
            Sensor.deleted_at.is_(None),
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_sensors_by_ids(self, sensor_ids: set[UUID]) -> dict[UUID, Sensor]:
        """Return active sensors keyed by ID."""
        if not sensor_ids:
            return {}
        statement = select(Sensor).where(
            Sensor.id.in_(sensor_ids),
            Sensor.deleted_at.is_(None),
        )
        result = await self._session.execute(statement)
        sensors = result.scalars().all()
        return {sensor.id: sensor for sensor in sensors}

    async def create_upload_job(
        self,
        *,
        filename: str,
        source: ReadingSource,
        created_by: UUID,
    ) -> UploadJob:
        """Create an upload job."""
        upload_job = UploadJob(
            filename=filename,
            source=source,
            created_by=created_by,
        )
        self._session.add(upload_job)
        await self._session.flush()
        await self._session.refresh(upload_job)
        return upload_job

    async def get_upload_job_by_id(self, upload_job_id: UUID) -> UploadJob | None:
        """Return an upload job by ID."""
        statement = select(UploadJob).where(UploadJob.id == upload_job_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def list_upload_jobs(
        self,
        *,
        limit: int,
        offset: int,
        status: UploadJobStatus | None,
        source: ReadingSource | None,
        created_by: UUID | None,
        sort_by: UploadJobSortField,
        sort_order: SortOrder,
    ) -> Page[UploadJob]:
        """Return paginated upload jobs."""
        statement = select(UploadJob)
        if status is not None:
            statement = statement.where(UploadJob.status == status)
        if source is not None:
            statement = statement.where(UploadJob.source == source)
        if created_by is not None:
            statement = statement.where(UploadJob.created_by == created_by)
        return await self._paginate(
            statement=statement,
            model=UploadJob,
            sort_column=self._upload_job_sort_column(sort_by),
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    async def create_sensor_reading(
        self,
        *,
        sensor_id: UUID,
        timestamp: datetime,
        value: float,
        quality: ReadingQuality,
        source: ReadingSource,
        batch_id: UUID | None,
    ) -> SensorReading:
        """Create a sensor reading."""
        reading = SensorReading(
            sensor_id=sensor_id,
            timestamp=timestamp,
            value=value,
            quality=quality,
            source=source,
            batch_id=batch_id,
        )
        self._session.add(reading)
        await self._session.flush()
        await self._session.refresh(reading)
        return reading

    async def bulk_create_sensor_readings(
        self,
        records: Sequence[SensorReadingInsert],
    ) -> int:
        """Bulk insert sensor readings."""
        if not records:
            return 0
        await self._session.execute(insert(SensorReading), list(records))
        await self._session.flush()
        return len(records)

    async def get_sensor_reading_by_id(
        self,
        reading_id: UUID,
    ) -> SensorReading | None:
        """Return a sensor reading by ID."""
        statement = select(SensorReading).where(SensorReading.id == reading_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_existing_reading_keys(
        self,
        keys: set[tuple[UUID, datetime]],
    ) -> set[tuple[UUID, datetime]]:
        """Return reading keys already persisted in the database."""
        if not keys:
            return set()
        statement = select(
            SensorReading.sensor_id,
            SensorReading.timestamp,
        ).where(tuple_(SensorReading.sensor_id, SensorReading.timestamp).in_(keys))
        result = await self._session.execute(statement)
        return {(row.sensor_id, row.timestamp) for row in result.all()}

    async def list_sensor_readings(
        self,
        *,
        limit: int,
        offset: int,
        sensor_id: UUID | None,
        batch_id: UUID | None,
        quality: ReadingQuality | None,
        source: ReadingSource | None,
        timestamp_from: datetime | None,
        timestamp_to: datetime | None,
        sort_by: SensorReadingSortField,
        sort_order: SortOrder,
    ) -> Page[SensorReading]:
        """Return paginated sensor readings."""
        statement = select(SensorReading)
        if sensor_id is not None:
            statement = statement.where(SensorReading.sensor_id == sensor_id)
        if batch_id is not None:
            statement = statement.where(SensorReading.batch_id == batch_id)
        if quality is not None:
            statement = statement.where(SensorReading.quality == quality)
        if source is not None:
            statement = statement.where(SensorReading.source == source)
        if timestamp_from is not None:
            statement = statement.where(SensorReading.timestamp >= timestamp_from)
        if timestamp_to is not None:
            statement = statement.where(SensorReading.timestamp <= timestamp_to)
        return await self._paginate(
            statement=statement,
            model=SensorReading,
            sort_column=self._sensor_reading_sort_column(sort_by),
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    async def increment_upload_job_valid_rows(self, upload_job: UploadJob) -> None:
        """Record one valid reading against an upload job."""
        upload_job.total_rows += 1
        upload_job.valid_rows += 1
        await self._session.flush()

    async def start_upload_job(
        self,
        upload_job: UploadJob,
        *,
        started_at: datetime,
    ) -> None:
        """Mark an upload job as processing."""
        upload_job.status = UploadJobStatus.PROCESSING
        upload_job.started_at = started_at
        upload_job.finished_at = None
        upload_job.total_rows = 0
        upload_job.valid_rows = 0
        upload_job.invalid_rows = 0
        await self._session.flush()

    async def finalize_upload_job(
        self,
        upload_job: UploadJob,
        *,
        status: UploadJobStatus,
        total_rows: int,
        valid_rows: int,
        invalid_rows: int,
        finished_at: datetime,
    ) -> None:
        """Finalize an upload job with ETL processing totals."""
        upload_job.status = status
        upload_job.total_rows = total_rows
        upload_job.valid_rows = valid_rows
        upload_job.invalid_rows = invalid_rows
        upload_job.finished_at = finished_at
        await self._session.flush()

    async def commit(self) -> None:
        """Commit the active transaction."""
        await self._session.commit()

    async def rollback(self) -> None:
        """Roll back the active transaction."""
        await self._session.rollback()

    async def refresh(self, entity: SensorReading | UploadJob) -> None:
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

    def _sensor_reading_sort_column(
        self,
        sort_by: SensorReadingSortField,
    ) -> ColumnElement[object]:
        return cast(
            ColumnElement[object],
            {
                SensorReadingSortField.TIMESTAMP: SensorReading.timestamp,
                SensorReadingSortField.CREATED_AT: SensorReading.created_at,
                SensorReadingSortField.VALUE: SensorReading.value,
            }[sort_by],
        )

    def _upload_job_sort_column(
        self,
        sort_by: UploadJobSortField,
    ) -> ColumnElement[object]:
        return cast(
            ColumnElement[object],
            {
                UploadJobSortField.CREATED_AT: UploadJob.created_at,
                UploadJobSortField.STARTED_AT: UploadJob.started_at,
                UploadJobSortField.FINISHED_AT: UploadJob.finished_at,
                UploadJobSortField.FILENAME: UploadJob.filename,
                UploadJobSortField.STATUS: UploadJob.status,
            }[sort_by],
        )
