"""Persistence adapter for feature engineering source data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sensor_data import ReadingQuality, SensorReading


@dataclass(frozen=True)
class FeatureSourceReading:
    """Sensor reading fields required for feature generation."""

    sensor_id: UUID
    timestamp: datetime
    value: float
    quality: ReadingQuality


class FeatureEngineeringRepository:
    """Repository for feature engineering source readings."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_validated_readings(
        self,
        *,
        sensor_id: UUID | None,
        timestamp_from: datetime | None,
        timestamp_to: datetime | None,
    ) -> list[FeatureSourceReading]:
        """Return validated readings for feature engineering."""
        statement = select(
            SensorReading.sensor_id,
            SensorReading.timestamp,
            SensorReading.value,
            SensorReading.quality,
        ).where(
            SensorReading.quality.in_(
                [ReadingQuality.GOOD, ReadingQuality.OUTLIER],
            ),
        )
        if sensor_id is not None:
            statement = statement.where(SensorReading.sensor_id == sensor_id)
        if timestamp_from is not None:
            statement = statement.where(SensorReading.timestamp >= timestamp_from)
        if timestamp_to is not None:
            statement = statement.where(SensorReading.timestamp <= timestamp_to)

        result = await self._session.execute(
            statement.order_by(
                SensorReading.sensor_id.asc(),
                SensorReading.timestamp.asc(),
            ),
        )
        return [
            FeatureSourceReading(
                sensor_id=row.sensor_id,
                timestamp=row.timestamp,
                value=row.value,
                quality=row.quality,
            )
            for row in result.all()
        ]
