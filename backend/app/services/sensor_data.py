"""Sensor data platform application service."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.models.sensor import Sensor
from app.models.sensor_data import (
    ReadingQuality,
    ReadingSource,
    SensorReading,
    UploadJob,
    UploadJobStatus,
)
from app.repositories.sensor_data import Page, SensorDataRepository
from app.schemas.common import SortOrder
from app.schemas.sensor_data import SensorReadingSortField, UploadJobSortField
from app.services.exceptions import (
    InvalidSensorReadingError,
    RelatedResourceNotFoundError,
    ResourceNotFoundError,
)
from app.utils.security import as_utc, utc_now


class SensorDataService:
    """Application use cases for sensor readings and upload jobs."""

    def __init__(self, *, repository: SensorDataRepository) -> None:
        self._repository = repository

    async def create_upload_job(
        self,
        *,
        filename: str,
        source: ReadingSource,
        created_by: UUID,
    ) -> UploadJob:
        """Create an upload job owned by the current user."""
        upload_job = await self._repository.create_upload_job(
            filename=filename,
            source=source,
            created_by=created_by,
        )
        await self._repository.commit()
        return upload_job

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
        return await self._repository.list_upload_jobs(
            limit=limit,
            offset=offset,
            status=status,
            source=source,
            created_by=created_by,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def get_upload_job(self, upload_job_id: UUID) -> UploadJob:
        """Return an upload job by ID."""
        upload_job = await self._repository.get_upload_job_by_id(upload_job_id)
        if upload_job is None:
            raise ResourceNotFoundError("Upload job not found.")
        return upload_job

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
        """Create a validated sensor reading."""
        sensor = await self._require_sensor(sensor_id)
        upload_job = None
        if batch_id is not None:
            upload_job = await self._require_upload_job(batch_id)
            if upload_job.source != source:
                raise InvalidSensorReadingError(
                    "Reading source must match the upload job source.",
                )

        normalized_timestamp = as_utc(timestamp)
        self._validate_reading(
            sensor=sensor,
            timestamp=normalized_timestamp,
            value=value,
        )
        try:
            reading = await self._repository.create_sensor_reading(
                sensor_id=sensor_id,
                timestamp=normalized_timestamp,
                value=value,
                quality=quality,
                source=source,
                batch_id=batch_id,
            )
            if upload_job is not None:
                await self._repository.increment_upload_job_valid_rows(upload_job)
            await self._repository.commit()
        except Exception:
            await self._repository.rollback()
            raise
        return reading

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
        return await self._repository.list_sensor_readings(
            limit=limit,
            offset=offset,
            sensor_id=sensor_id,
            batch_id=batch_id,
            quality=quality,
            source=source,
            timestamp_from=as_utc(timestamp_from) if timestamp_from else None,
            timestamp_to=as_utc(timestamp_to) if timestamp_to else None,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def list_readings_for_sensor(
        self,
        *,
        sensor_id: UUID,
        limit: int,
        offset: int,
        quality: ReadingQuality | None,
        source: ReadingSource | None,
        timestamp_from: datetime | None,
        timestamp_to: datetime | None,
        sort_by: SensorReadingSortField,
        sort_order: SortOrder,
    ) -> Page[SensorReading]:
        """Return readings for an existing active sensor."""
        sensor = await self._repository.get_sensor_by_id(sensor_id)
        if sensor is None:
            raise ResourceNotFoundError("Sensor not found.")
        return await self.list_sensor_readings(
            limit=limit,
            offset=offset,
            sensor_id=sensor_id,
            batch_id=None,
            quality=quality,
            source=source,
            timestamp_from=timestamp_from,
            timestamp_to=timestamp_to,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    async def get_sensor_reading(self, reading_id: UUID) -> SensorReading:
        """Return a sensor reading by ID."""
        reading = await self._repository.get_sensor_reading_by_id(reading_id)
        if reading is None:
            raise ResourceNotFoundError("Sensor reading not found.")
        return reading

    async def _require_sensor(self, sensor_id: UUID) -> Sensor:
        sensor = await self._repository.get_sensor_by_id(sensor_id)
        if sensor is None:
            raise RelatedResourceNotFoundError("Sensor does not exist.")
        return sensor

    async def _require_upload_job(self, upload_job_id: UUID) -> UploadJob:
        upload_job = await self._repository.get_upload_job_by_id(upload_job_id)
        if upload_job is None:
            raise RelatedResourceNotFoundError("Upload job does not exist.")
        return upload_job

    def _validate_reading(
        self,
        *,
        sensor: Sensor,
        timestamp: datetime,
        value: float,
    ) -> None:
        if timestamp > utc_now():
            raise InvalidSensorReadingError(
                "Reading timestamp cannot be in the future.",
            )
        if self._is_rpm_sensor(sensor) and value < 0:
            raise InvalidSensorReadingError("RPM sensor readings cannot be negative.")
        if value < sensor.min_value or value > sensor.max_value:
            raise InvalidSensorReadingError(
                "Reading value is outside the sensor configured range.",
            )

    def _is_rpm_sensor(self, sensor: Sensor) -> bool:
        labels = " ".join(
            item
            for item in (sensor.name, sensor.sensor_type, sensor.unit)
            if item is not None
        )
        return "rpm" in labels.casefold()
