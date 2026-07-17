"""CSV ETL pipeline for sensor readings."""

from __future__ import annotations

import math
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

import pandera.errors as pandera_errors
import pandera.polars as pa
import polars as pl

from app.models.sensor import Sensor
from app.models.sensor_data import (
    ReadingQuality,
    ReadingSource,
    UploadJob,
    UploadJobStatus,
)
from app.repositories.sensor_data import SensorDataRepository, SensorReadingInsert
from app.services.exceptions import (
    InvalidSensorDataUploadError,
    ResourceNotFoundError,
)
from app.utils.security import as_utc, utc_now


@dataclass(frozen=True)
class SensorReadingCandidate:
    """Validated row candidate before outlier classification."""

    sensor_id: UUID
    timestamp: datetime
    value: float
    quality: ReadingQuality


@dataclass(frozen=True)
class ChunkProcessingResult:
    """ETL processing totals for a CSV chunk."""

    total_rows: int
    valid_rows: int
    invalid_rows: int


@dataclass
class UploadProcessingCounters:
    """Mutable counters for one upload."""

    total_rows: int = 0
    valid_rows: int = 0
    invalid_rows: int = 0


class SensorDataEtlService:
    """CSV upload ETL pipeline for sensor readings."""

    def __init__(
        self,
        *,
        repository: SensorDataRepository,
        chunk_size: int,
        float_precision: int,
        outlier_z_score_threshold: float,
    ) -> None:
        self._repository = repository
        self._chunk_size = chunk_size
        self._float_precision = float_precision
        self._outlier_z_score_threshold = outlier_z_score_threshold
        self._schema = pa.DataFrameSchema(
            {
                "sensor_id": pa.Column(str, nullable=False),
                "timestamp": pa.Column(str, nullable=False),
                "value": pa.Column(str, nullable=False),
            },
            strict=False,
        )

    async def process_csv_upload(
        self,
        *,
        upload_job_id: UUID,
        file: BinaryIO,
    ) -> UploadJob:
        """Process a CSV upload through the ETL pipeline."""
        upload_job = await self._repository.get_upload_job_by_id(upload_job_id)
        if upload_job is None:
            raise ResourceNotFoundError("Upload job not found.")
        if upload_job.source != ReadingSource.CSV:
            raise InvalidSensorDataUploadError("CSV uploads require a CSV upload job.")
        if upload_job.status != UploadJobStatus.PENDING:
            raise InvalidSensorDataUploadError("Upload job is not pending.")

        started_at = utc_now()
        await self._repository.start_upload_job(upload_job, started_at=started_at)
        await self._repository.commit()

        counters = UploadProcessingCounters()
        seen_keys: set[tuple[UUID, datetime]] = set()
        try:
            for raw_chunk in self._read_csv_batches(file):
                result = await self._process_chunk(
                    raw_chunk=raw_chunk,
                    row_offset=counters.total_rows,
                    upload_job_id=upload_job.id,
                    seen_keys=seen_keys,
                )
                counters.total_rows += result.total_rows
                counters.valid_rows += result.valid_rows
                counters.invalid_rows += result.invalid_rows
        except Exception:
            await self._repository.rollback()
            upload_job = await self._repository.get_upload_job_by_id(upload_job_id)
            if upload_job is not None:
                await self._repository.finalize_upload_job(
                    upload_job,
                    status=UploadJobStatus.FAILED,
                    total_rows=counters.total_rows,
                    valid_rows=counters.valid_rows,
                    invalid_rows=max(counters.invalid_rows, 1),
                    finished_at=utc_now(),
                )
                await self._repository.commit()
            raise

        final_status = (
            UploadJobStatus.COMPLETED
            if counters.invalid_rows == 0
            else UploadJobStatus.FAILED
        )
        upload_job = await self._repository.get_upload_job_by_id(upload_job_id)
        if upload_job is None:
            raise ResourceNotFoundError("Upload job not found.")
        await self._repository.finalize_upload_job(
            upload_job,
            status=final_status,
            total_rows=counters.total_rows,
            valid_rows=counters.valid_rows,
            invalid_rows=counters.invalid_rows,
            finished_at=utc_now(),
        )
        await self._repository.commit()
        await self._repository.refresh(upload_job)
        return upload_job

    def _read_csv_batches(self, file: BinaryIO) -> Iterator[pl.DataFrame]:
        """Read uploaded CSV content in Polars batches."""
        temp_path = self._write_upload_to_temp_file(file)
        try:
            try:
                reader = pl.read_csv_batched(
                    str(temp_path),
                    batch_size=self._chunk_size,
                    infer_schema_length=0,
                    try_parse_dates=False,
                )
            except Exception as exc:
                raise InvalidSensorDataUploadError(
                    "CSV file could not be parsed.",
                ) from exc

            while True:
                try:
                    batches = reader.next_batches(1)
                except Exception as exc:
                    raise InvalidSensorDataUploadError(
                        "CSV file could not be parsed.",
                    ) from exc
                if not batches:
                    break
                yield from batches
        finally:
            temp_path.unlink(missing_ok=True)

    def _write_upload_to_temp_file(self, file: BinaryIO) -> Path:
        file.seek(0)
        with tempfile.NamedTemporaryFile(
            prefix="sensor-readings-",
            suffix=".csv",
            delete=False,
        ) as temp_file:
            while True:
                chunk = file.read(1024 * 1024)
                if not chunk:
                    break
                temp_file.write(chunk)
            return Path(temp_file.name)

    async def _process_chunk(
        self,
        *,
        raw_chunk: pl.DataFrame,
        row_offset: int,
        upload_job_id: UUID,
        seen_keys: set[tuple[UUID, datetime]],
    ) -> ChunkProcessingResult:
        normalized_chunk = self._normalize_column_names(raw_chunk)
        self._validate_schema(normalized_chunk)
        cleaned_chunk = self._clean_chunk(normalized_chunk, row_offset=row_offset)
        total_rows = cleaned_chunk.height
        if total_rows == 0:
            return ChunkProcessingResult(total_rows=0, valid_rows=0, invalid_rows=0)

        candidate_sensor_ids = self._extract_candidate_sensor_ids(cleaned_chunk)
        sensors = await self._repository.get_sensors_by_ids(candidate_sensor_ids)
        candidates, invalid_rows = self._build_candidates(cleaned_chunk, sensors)
        existing_keys = await self._repository.get_existing_reading_keys(
            {(candidate.sensor_id, candidate.timestamp) for candidate in candidates},
        )
        deduplicated_candidates: list[SensorReadingCandidate] = []
        for candidate in candidates:
            key = (candidate.sensor_id, candidate.timestamp)
            if key in seen_keys or key in existing_keys:
                invalid_rows += 1
                continue
            seen_keys.add(key)
            deduplicated_candidates.append(candidate)

        classified_candidates = self._detect_outliers(deduplicated_candidates)
        records = [
            self._candidate_to_record(candidate, upload_job_id)
            for candidate in classified_candidates
        ]
        inserted_rows = await self._repository.bulk_create_sensor_readings(records)
        return ChunkProcessingResult(
            total_rows=total_rows,
            valid_rows=inserted_rows,
            invalid_rows=invalid_rows,
        )

    def _normalize_column_names(self, frame: pl.DataFrame) -> pl.DataFrame:
        normalized_names: dict[str, str] = {}
        seen_names: set[str] = set()
        for column_name in frame.columns:
            normalized_name = column_name.strip().casefold()
            if normalized_name in seen_names:
                raise InvalidSensorDataUploadError(
                    "CSV column names are duplicated after normalization.",
                )
            seen_names.add(normalized_name)
            normalized_names[column_name] = normalized_name
        return frame.rename(normalized_names)

    def _validate_schema(self, frame: pl.DataFrame) -> None:
        try:
            self._schema.validate(frame, lazy=True)
        except (pandera_errors.SchemaError, pandera_errors.SchemaErrors) as exc:
            raise InvalidSensorDataUploadError(
                "CSV schema validation failed.",
            ) from exc

    def _clean_chunk(self, frame: pl.DataFrame, *, row_offset: int) -> pl.DataFrame:
        if "quality" not in frame.columns:
            frame = frame.with_columns(
                pl.lit(ReadingQuality.GOOD.value).alias("quality"),
            )
        return (
            frame.with_row_index("_row_number", offset=row_offset + 1)
            .select("_row_number", "sensor_id", "timestamp", "value", "quality")
            .with_columns(
                pl.col("sensor_id")
                .cast(pl.String, strict=False)
                .str.strip_chars()
                .alias("_sensor_id"),
                pl.col("timestamp")
                .cast(pl.String, strict=False)
                .str.strip_chars()
                .alias("_timestamp"),
                pl.col("value")
                .cast(pl.String, strict=False)
                .str.strip_chars()
                .cast(pl.Float64, strict=False)
                .round(self._float_precision)
                .alias("_value"),
                pl.when(
                    pl.col("quality").is_null()
                    | (
                        pl.col("quality")
                        .cast(pl.String, strict=False)
                        .str.strip_chars()
                        == ""
                    ),
                )
                .then(pl.lit(ReadingQuality.GOOD.value))
                .otherwise(
                    pl.col("quality")
                    .cast(pl.String, strict=False)
                    .str.strip_chars()
                    .str.to_uppercase(),
                )
                .alias("_quality"),
            )
            .select("_row_number", "_sensor_id", "_timestamp", "_value", "_quality")
        )

    def _extract_candidate_sensor_ids(self, frame: pl.DataFrame) -> set[UUID]:
        sensor_ids: set[UUID] = set()
        for sensor_id_value in frame["_sensor_id"].drop_nulls().unique().to_list():
            sensor_id = self._parse_uuid(sensor_id_value)
            if sensor_id is not None:
                sensor_ids.add(sensor_id)
        return sensor_ids

    def _build_candidates(
        self,
        frame: pl.DataFrame,
        sensors: dict[UUID, Sensor],
    ) -> tuple[list[SensorReadingCandidate], int]:
        candidates: list[SensorReadingCandidate] = []
        invalid_rows = 0
        for row in frame.iter_rows(named=True):
            sensor_id = self._parse_uuid(row["_sensor_id"])
            timestamp = self._parse_timestamp(row["_timestamp"])
            value = row["_value"]
            quality = self._parse_quality(row["_quality"])
            if (
                sensor_id is None
                or timestamp is None
                or not isinstance(value, float)
                or not math.isfinite(value)
                or quality is None
            ):
                invalid_rows += 1
                continue

            sensor = sensors.get(sensor_id)
            if sensor is None or not self._is_engineering_value_valid(sensor, value):
                invalid_rows += 1
                continue
            if timestamp > utc_now():
                invalid_rows += 1
                continue

            candidates.append(
                SensorReadingCandidate(
                    sensor_id=sensor_id,
                    timestamp=timestamp,
                    value=value,
                    quality=quality,
                ),
            )
        return candidates, invalid_rows

    def _detect_outliers(
        self,
        candidates: list[SensorReadingCandidate],
    ) -> list[SensorReadingCandidate]:
        if len(candidates) < 3:
            return candidates
        frame = pl.DataFrame(
            {
                "index": list(range(len(candidates))),
                "sensor_id": [str(candidate.sensor_id) for candidate in candidates],
                "value": [candidate.value for candidate in candidates],
            },
        ).with_columns(
            pl.col("value").mean().over("sensor_id").alias("_mean"),
            pl.col("value").std().over("sensor_id").alias("_std"),
        )
        outlier_indexes = set(
            frame.filter(
                (pl.col("_std") > 0)
                & (
                    ((pl.col("value") - pl.col("_mean")).abs() / pl.col("_std"))
                    > self._outlier_z_score_threshold
                ),
            )["index"].to_list(),
        )
        if not outlier_indexes:
            return candidates
        classified_candidates: list[SensorReadingCandidate] = []
        for index, candidate in enumerate(candidates):
            if index in outlier_indexes and candidate.quality == ReadingQuality.GOOD:
                classified_candidates.append(
                    SensorReadingCandidate(
                        sensor_id=candidate.sensor_id,
                        timestamp=candidate.timestamp,
                        value=candidate.value,
                        quality=ReadingQuality.OUTLIER,
                    ),
                )
                continue
            classified_candidates.append(candidate)
        return classified_candidates

    def _candidate_to_record(
        self,
        candidate: SensorReadingCandidate,
        upload_job_id: UUID,
    ) -> SensorReadingInsert:
        return {
            "sensor_id": candidate.sensor_id,
            "timestamp": candidate.timestamp,
            "value": candidate.value,
            "quality": candidate.quality,
            "source": ReadingSource.CSV,
            "batch_id": upload_job_id,
        }

    def _parse_uuid(self, value: object) -> UUID | None:
        if not isinstance(value, str) or value == "":
            return None
        try:
            return UUID(value)
        except ValueError:
            return None

    def _parse_timestamp(self, value: object) -> datetime | None:
        if not isinstance(value, str) or value == "":
            return None
        normalized_value = value.strip()
        if normalized_value.endswith("Z"):
            normalized_value = f"{normalized_value[:-1]}+00:00"
        try:
            return as_utc(datetime.fromisoformat(normalized_value))
        except ValueError:
            return None

    def _parse_quality(self, value: object) -> ReadingQuality | None:
        if not isinstance(value, str) or value == "":
            return ReadingQuality.GOOD
        try:
            return ReadingQuality(value)
        except ValueError:
            return None

    def _is_engineering_value_valid(self, sensor: Sensor, value: float) -> bool:
        if self._is_rpm_sensor(sensor) and value < 0:
            return False
        return sensor.min_value <= value <= sensor.max_value

    def _is_rpm_sensor(self, sensor: Sensor) -> bool:
        labels = " ".join(
            item
            for item in (sensor.name, sensor.sensor_type, sensor.unit)
            if item is not None
        )
        return "rpm" in labels.casefold()
