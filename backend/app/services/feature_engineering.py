"""Feature engineering pipeline for validated sensor readings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

import polars as pl

from app.repositories.feature_engineering import (
    FeatureEngineeringRepository,
    FeatureSourceReading,
)
from app.services.exceptions import InvalidFeatureDatasetError
from app.utils.security import as_utc, utc_now


@dataclass(frozen=True)
class FeatureDatasetExport:
    """Metadata for an exported feature dataset."""

    dataset_name: str
    version: int
    file_path: Path
    rows: int
    columns: int
    created_at: datetime


class FeatureEngineeringService:
    """Generate ML-ready feature datasets from validated sensor readings."""

    def __init__(
        self,
        *,
        repository: FeatureEngineeringRepository,
        dataset_dir: Path | str,
        rolling_window_size: int,
    ) -> None:
        self._repository = repository
        self._dataset_dir = Path(dataset_dir)
        self._rolling_window_size = rolling_window_size

    async def export_feature_dataset(
        self,
        *,
        sensor_id: UUID | None,
        timestamp_from: datetime | None,
        timestamp_to: datetime | None,
    ) -> FeatureDatasetExport:
        """Generate and export a versioned Parquet feature dataset."""
        if (
            timestamp_from is not None
            and timestamp_to is not None
            and as_utc(timestamp_from) > as_utc(timestamp_to)
        ):
            raise InvalidFeatureDatasetError(
                "timestamp_from must be before timestamp_to.",
            )

        readings = await self._repository.list_validated_readings(
            sensor_id=sensor_id,
            timestamp_from=as_utc(timestamp_from) if timestamp_from else None,
            timestamp_to=as_utc(timestamp_to) if timestamp_to else None,
        )
        if not readings:
            raise InvalidFeatureDatasetError(
                "No validated sensor readings are available for feature export.",
            )

        dataset = self.build_feature_frame(readings)
        version = self._next_dataset_version()
        dataset_name = f"dataset_v{version}.parquet"
        file_path = self._dataset_dir / dataset_name
        self._dataset_dir.mkdir(parents=True, exist_ok=True)
        dataset.write_parquet(file_path)
        return FeatureDatasetExport(
            dataset_name=dataset_name,
            version=version,
            file_path=file_path,
            rows=dataset.height,
            columns=dataset.width,
            created_at=utc_now(),
        )

    def build_feature_frame(self, readings: list[FeatureSourceReading]) -> pl.DataFrame:
        """Run the modular feature extraction pipeline."""
        frame = self._source_frame(readings)
        frame = self._add_time_features(frame)
        frame = self._add_rolling_features(frame)
        frame = self._add_lag_features(frame)
        frame = self._add_statistical_features(frame)
        frame = self._add_delta_features(frame)
        return self._finalize_features(frame)

    def _source_frame(self, readings: list[FeatureSourceReading]) -> pl.DataFrame:
        return pl.DataFrame(
            {
                "sensor_id": [str(reading.sensor_id) for reading in readings],
                "timestamp": [as_utc(reading.timestamp) for reading in readings],
                "value": [reading.value for reading in readings],
                "quality": [reading.quality.value for reading in readings],
            },
        ).sort(["sensor_id", "timestamp"])

    def _add_time_features(self, frame: pl.DataFrame) -> pl.DataFrame:
        hour = pl.col("timestamp").dt.hour()
        return frame.with_columns(
            hour.alias("hour"),
            pl.col("timestamp").dt.weekday().alias("day_of_week"),
            pl.col("timestamp").dt.day().alias("day_of_month"),
            pl.col("timestamp").dt.month().alias("month"),
            pl.col("timestamp").dt.weekday().is_in([6, 7]).alias("weekend"),
            pl.when((hour >= 6) & (hour < 14))
            .then(pl.lit("day"))
            .when((hour >= 14) & (hour < 22))
            .then(pl.lit("swing"))
            .otherwise(pl.lit("night"))
            .alias("shift"),
        )

    def _add_rolling_features(self, frame: pl.DataFrame) -> pl.DataFrame:
        return frame.with_columns(
            pl.col("value")
            .rolling_mean(window_size=self._rolling_window_size, min_samples=1)
            .over("sensor_id")
            .alias("rolling_mean"),
            pl.col("value")
            .rolling_std(window_size=self._rolling_window_size, min_samples=2)
            .over("sensor_id")
            .fill_null(0.0)
            .alias("rolling_std"),
            pl.col("value")
            .rolling_min(window_size=self._rolling_window_size, min_samples=1)
            .over("sensor_id")
            .alias("rolling_min"),
            pl.col("value")
            .rolling_max(window_size=self._rolling_window_size, min_samples=1)
            .over("sensor_id")
            .alias("rolling_max"),
        )

    def _add_lag_features(self, frame: pl.DataFrame) -> pl.DataFrame:
        return frame.with_columns(
            pl.col("value").shift(1).over("sensor_id").fill_null(0.0).alias("lag_1"),
            pl.col("value").shift(5).over("sensor_id").fill_null(0.0).alias("lag_5"),
            pl.col("value").shift(10).over("sensor_id").fill_null(0.0).alias("lag_10"),
        )

    def _add_statistical_features(self, frame: pl.DataFrame) -> pl.DataFrame:
        return frame.with_columns(
            pl.col("value").mean().over("sensor_id").alias("mean"),
            pl.col("value").median().over("sensor_id").alias("median"),
            pl.col("value").std().over("sensor_id").fill_null(0.0).alias("std"),
            pl.col("value").var().over("sensor_id").fill_null(0.0).alias("variance"),
            pl.col("value").min().over("sensor_id").alias("min"),
            pl.col("value").max().over("sensor_id").alias("max"),
        ).with_columns((pl.col("max") - pl.col("min")).alias("range"))

    def _add_delta_features(self, frame: pl.DataFrame) -> pl.DataFrame:
        previous_value = pl.col("value").shift(1).over("sensor_id")
        previous_timestamp = pl.col("timestamp").shift(1).over("sensor_id")
        delta = (
            pl.when(previous_value.is_null())
            .then(0.0)
            .otherwise(
                pl.col("value") - previous_value,
            )
        )
        elapsed_seconds = (pl.col("timestamp") - previous_timestamp).dt.total_seconds()
        return frame.with_columns(
            delta.alias("delta"),
            pl.when(previous_value.is_null() | (previous_value == 0.0))
            .then(0.0)
            .otherwise(delta / previous_value)
            .alias("percent_change"),
            pl.when(previous_timestamp.is_null() | (elapsed_seconds <= 0))
            .then(0.0)
            .otherwise(delta / elapsed_seconds)
            .alias("rate_of_change"),
        )

    def _finalize_features(self, frame: pl.DataFrame) -> pl.DataFrame:
        return frame.fill_nan(0.0).fill_null(0.0)

    def _next_dataset_version(self) -> int:
        if not self._dataset_dir.exists():
            return 1
        versions: list[int] = []
        for path in self._dataset_dir.glob("dataset_v*.parquet"):
            version_text = path.stem.removeprefix("dataset_v")
            if version_text.isdigit():
                versions.append(int(version_text))
        return max(versions, default=0) + 1
