"""Bounded guided CSV onboarding built on the existing object store."""

from __future__ import annotations

import csv
import io
import math
import statistics
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from typing import BinaryIO, cast
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.datasets.storage import DatasetStorageError, LocalDatasetObjectStorage
from app.models.demo_experience import DataImport, DataImportStatus
from app.models.manufacturing import Factory, Machine
from app.models.sensor import Sensor
from app.models.sensor_data import ReadingQuality, ReadingSource, SensorReading
from app.schemas.demo_experience import ImportMapping, ImportShape
from app.utils.security import utc_now

MAX_PREVIEW_ROWS = 20
MAX_ERROR_SAMPLES = 20
ALLOWED_MEDIA_TYPES = {"text/csv", "application/csv", "application/vnd.ms-excel"}
FORMULA_PREFIXES = ("=", "+", "-", "@")


class GuidedDataError(ValueError):
    """Safe client-visible guided onboarding error."""


def safe_csv_filename(filename: str | None) -> str:
    value = (filename or "").strip()
    if not value or PurePath(value).name != value or not value.lower().endswith(".csv"):
        raise GuidedDataError("A safe CSV filename is required.")
    if any(ord(character) < 32 for character in value):
        raise GuidedDataError("The CSV filename contains unsupported characters.")
    return value[:255]


def _decode_csv(payload: bytes) -> str:
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise GuidedDataError("CSV files must use UTF-8 encoding.") from exc


def _detect_delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text[:8192], delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _rows(
    text: str, *, delimiter: str, maximum_rows: int
) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter, strict=True)
    try:
        headers = next(reader)
    except (StopIteration, csv.Error) as exc:
        raise GuidedDataError(
            "The CSV does not contain a readable header row."
        ) from exc
    normalized = [item.strip().casefold() for item in headers]
    if not headers or any(not item for item in normalized):
        raise GuidedDataError("CSV headers cannot be empty.")
    if len(normalized) != len(set(normalized)):
        raise GuidedDataError("CSV headers must be unique.")
    if len(headers) > 256:
        raise GuidedDataError("The CSV contains too many columns.")
    values: list[dict[str, str]] = []
    try:
        for number, raw in enumerate(reader, start=1):
            if number > maximum_rows:
                raise GuidedDataError("The CSV exceeds the configured row limit.")
            if len(raw) != len(headers):
                raw = [*raw[: len(headers)], *([""] * max(0, len(headers) - len(raw)))]
            values.append(dict(zip(headers, raw, strict=True)))
    except csv.Error as exc:
        raise GuidedDataError("The CSV structure is invalid.") from exc
    if not values:
        raise GuidedDataError("The CSV does not contain any data rows.")
    return headers, values


def _suggestions(headers: list[str]) -> dict[str, object]:
    lowered = {header.casefold(): header for header in headers}

    def find(*names: str) -> str | None:
        for name in names:
            if name in lowered:
                return lowered[name]
        return None

    timestamp = find("timestamp", "time", "datetime", "date")
    machine = find("machine", "machine_id", "asset", "asset_id")
    sensor = find("sensor", "sensor_name", "feature", "feature_name")
    value = find("value", "reading", "feature_value")
    confidence = (
        sum(item is not None for item in (timestamp, machine, sensor, value)) / 4
    )
    return {
        "timestamp": timestamp,
        "machine": machine,
        "sensor": sensor,
        "value": value,
        "confidence": round(confidence, 2),
        "confirmed": False,
    }


class GuidedDataService:
    """Execute company-scoped guided import state transitions."""

    def __init__(
        self,
        *,
        session: AsyncSession,
        storage: LocalDatasetObjectStorage,
        maximum_bytes: int,
        maximum_rows: int,
    ) -> None:
        self._session = session
        self._storage = storage
        self._maximum_bytes = maximum_bytes
        self._maximum_rows = maximum_rows

    async def create(
        self,
        *,
        company_id: UUID,
        user_id: UUID,
        filename: str | None,
        media_type: str | None,
        idempotency_key: str,
        source: BinaryIO,
    ) -> DataImport:
        existing = await self._session.scalar(
            select(DataImport).where(
                DataImport.company_id == company_id,
                DataImport.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing
        safe_name = safe_csv_filename(filename)
        normalized_media = (media_type or "text/csv").split(";")[0].strip().lower()
        if normalized_media not in ALLOWED_MEDIA_TYPES:
            raise GuidedDataError(
                "The uploaded file must use a supported CSV media type."
            )
        try:
            stored = self._storage.write(source, maximum_bytes=self._maximum_bytes)
            payload = self._storage.read(stored.key, maximum_bytes=self._maximum_bytes)
            text = _decode_csv(payload)
            delimiter = _detect_delimiter(text)
            headers, rows = _rows(
                text, delimiter=delimiter, maximum_rows=self._maximum_rows
            )
        except DatasetStorageError as exc:
            raise GuidedDataError(str(exc)) from exc
        item = DataImport(
            company_id=company_id,
            created_by=user_id,
            idempotency_key=idempotency_key,
            filename=safe_name,
            media_type=normalized_media,
            storage_key=stored.key,
            sha256_digest=stored.sha256_digest,
            size_bytes=stored.size_bytes,
            status=DataImportStatus.QUEUED.value,
            delimiter=delimiter,
            has_header=True,
            mapping={"suggestions": _suggestions(headers), "headers": headers},
            preview=rows[:MAX_PREVIEW_ROWS],
            total_rows=len(rows),
        )
        self._session.add(item)
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def get(self, *, company_id: UUID, import_id: UUID) -> DataImport:
        item = await self._session.scalar(
            select(DataImport).where(
                DataImport.id == import_id, DataImport.company_id == company_id
            )
        )
        if item is None:
            raise GuidedDataError("Data import not found.")
        return item

    async def list_imports(
        self, *, company_id: UUID, limit: int, offset: int
    ) -> tuple[list[DataImport], int]:
        filters = (DataImport.company_id == company_id,)
        total = int(
            await self._session.scalar(
                select(func.count()).select_from(DataImport).where(*filters)
            )
            or 0
        )
        items = list(
            (
                await self._session.scalars(
                    select(DataImport)
                    .where(*filters)
                    .order_by(DataImport.created_at.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        return items, total

    async def set_mapping(
        self,
        *,
        company_id: UUID,
        import_id: UUID,
        mapping: ImportMapping,
        delimiter: str,
    ) -> DataImport:
        item = await self.get(company_id=company_id, import_id=import_id)
        if item.status not in {
            DataImportStatus.QUEUED.value,
            DataImportStatus.FAILED.value,
        }:
            raise GuidedDataError(
                "Mapping cannot be changed in the current import state."
            )
        headers, rows = self._read(item, delimiter=delimiter)
        mapped = mapping.model_dump(mode="json")
        source_columns = [
            value
            for key, value in mapped.items()
            if key not in {"shape", "features"} and isinstance(value, str)
        ]
        source_columns.extend(mapped.get("features", []))
        unknown = sorted(set(source_columns).difference(headers))
        if unknown:
            raise GuidedDataError(
                f"Mapped columns are unavailable: {', '.join(unknown)}."
            )
        item.delimiter = delimiter
        item.mapping = {"headers": headers, "confirmed": mapped}
        item.preview = cast(list[dict[str, object]], rows[:MAX_PREVIEW_ROWS])
        item.quality_report = {}
        item.status = DataImportStatus.QUEUED.value
        await self._session.commit()
        await self._session.refresh(item)
        return item

    def _read(
        self, item: DataImport, *, delimiter: str | None = None
    ) -> tuple[list[str], list[dict[str, str]]]:
        payload = self._storage.read(
            item.storage_key, maximum_bytes=self._maximum_bytes
        )
        if not self._storage.verify(
            item.storage_key, item.sha256_digest, maximum_bytes=self._maximum_bytes
        ):
            raise GuidedDataError("The stored CSV integrity check failed.")
        return _rows(
            _decode_csv(payload),
            delimiter=delimiter or item.delimiter,
            maximum_rows=self._maximum_rows,
        )

    async def validate(self, *, company_id: UUID, import_id: UUID) -> DataImport:
        item = await self.get(company_id=company_id, import_id=import_id)
        if item.status in {
            DataImportStatus.COMPLETED.value,
            DataImportStatus.PARTIALLY_COMPLETED.value,
        }:
            return item
        confirmed = item.mapping.get("confirmed")
        if not isinstance(confirmed, dict):
            raise GuidedDataError("Confirm the column mapping before validation.")
        mapping = ImportMapping.model_validate(confirmed)
        item.status = DataImportStatus.VALIDATING.value
        item.started_at = utc_now()
        await self._session.flush()
        _, rows = self._read(item)
        quality, samples = await self._quality(company_id, rows, mapping)
        item.quality_report = quality
        item.error_samples = samples
        item.total_rows = len(rows)
        invalid_rows = quality["invalid_rows"]
        item.rejected_rows = invalid_rows if isinstance(invalid_rows, int) else 0
        item.progress_percent = 50
        item.status = DataImportStatus.QUEUED.value
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def confirm(
        self, *, company_id: UUID, import_id: UUID, accept_warnings: bool
    ) -> DataImport:
        item = await self.get(company_id=company_id, import_id=import_id)
        if item.status in {
            DataImportStatus.COMPLETED.value,
            DataImportStatus.PARTIALLY_COMPLETED.value,
        }:
            return item
        if not item.quality_report:
            raise GuidedDataError("Validate the import before confirmation.")
        blocking_count = item.quality_report.get("blocking_issue_count", 0)
        if isinstance(blocking_count, int) and blocking_count > 0:
            raise GuidedDataError(
                "Blocking data-quality issues must be corrected before import."
            )
        if (
            isinstance(item.quality_report.get("warning_issue_count"), int)
            and cast(int, item.quality_report["warning_issue_count"]) > 0
            and not accept_warnings
        ):
            raise GuidedDataError("Warnings must be accepted explicitly before import.")
        mapping = ImportMapping.model_validate(item.mapping["confirmed"])
        _, rows = self._read(item)
        sensors = await self._sensor_lookup(company_id)
        item.status = DataImportStatus.IMPORTING.value
        item.progress_percent = 75
        item.warnings_accepted = accept_warnings
        await self._session.flush()
        records, errors = self._records(rows, mapping, sensors)
        self._session.add_all(records)
        item.imported_rows = len(records)
        item.rejected_rows = len(errors)
        item.error_samples = errors[:MAX_ERROR_SAMPLES]
        item.progress_percent = 100
        item.completed_at = utc_now()
        item.status = (
            DataImportStatus.PARTIALLY_COMPLETED.value
            if errors
            else DataImportStatus.COMPLETED.value
        )
        await self._session.commit()
        await self._session.refresh(item)
        return item

    async def cancel(self, *, company_id: UUID, import_id: UUID) -> DataImport:
        item = await self.get(company_id=company_id, import_id=import_id)
        if item.status in {
            DataImportStatus.COMPLETED.value,
            DataImportStatus.PARTIALLY_COMPLETED.value,
        }:
            raise GuidedDataError("A completed import cannot be cancelled.")
        item.status = DataImportStatus.CANCELLED.value
        item.completed_at = utc_now()
        await self._session.commit()
        return item

    async def _sensor_lookup(self, company_id: UUID) -> dict[tuple[str, str], Sensor]:
        values = (
            await self._session.scalars(
                select(Sensor)
                .join(Machine, Sensor.machine_id == Machine.id)
                .join(Factory, Machine.factory_id == Factory.id)
                .where(
                    Factory.company_id == company_id,
                    Sensor.deleted_at.is_(None),
                    Machine.deleted_at.is_(None),
                    Factory.deleted_at.is_(None),
                )
            )
        ).all()
        machines = {
            machine.id: machine
            for machine in (
                await self._session.scalars(
                    select(Machine)
                    .join(Factory)
                    .where(
                        Factory.company_id == company_id, Machine.deleted_at.is_(None)
                    )
                )
            ).all()
        }
        return {
            (
                machines[sensor.machine_id].name.casefold(),
                sensor.name.casefold(),
            ): sensor
            for sensor in values
        }

    async def _quality(
        self,
        company_id: UUID,
        rows: list[dict[str, str]],
        mapping: ImportMapping,
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        sensors = await self._sensor_lookup(company_id)
        issues: dict[str, list[int]] = {}
        timestamps: list[datetime] = []
        values: list[float] = []
        seen: set[tuple[str, ...]] = set()
        label_counts: Counter[str] = Counter()
        samples: list[dict[str, object]] = []

        def mark(code: str, row_number: int, detail: str) -> None:
            issues.setdefault(code, []).append(row_number)
            if len(samples) < MAX_ERROR_SAMPLES:
                samples.append(
                    {"row": row_number, "code": code, "detail": detail[:160]}
                )

        for number, row in enumerate(rows, start=2):
            signature = tuple(row.values())
            if signature in seen:
                mark("duplicate_rows", number, "The row duplicates an earlier row.")
            seen.add(signature)
            raw_timestamp = row.get(mapping.timestamp, "").strip()
            if not raw_timestamp:
                mark("missing_timestamps", number, "Timestamp is empty.")
                parsed = None
            else:
                try:
                    parsed = datetime.fromisoformat(
                        raw_timestamp.replace("Z", "+00:00")
                    )
                    parsed = parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)
                    timestamps.append(parsed)
                except ValueError:
                    parsed = None
                    mark(
                        "invalid_timestamps", number, "Timestamp is not valid ISO 8601."
                    )
            machine_name = row.get(mapping.machine, "").strip()
            columns = (
                [(row.get(mapping.sensor or "", "").strip(), mapping.value or "")]
                if mapping.shape == ImportShape.LONG
                else [(feature, feature) for feature in mapping.features]
            )
            for sensor_name, value_column in columns:
                if (machine_name.casefold(), sensor_name.casefold()) not in sensors:
                    mark(
                        "unknown_sensors",
                        number,
                        f"Unknown machine/sensor: {machine_name}/{sensor_name}.",
                    )
                raw_value = row.get(value_column, "").strip()
                if not raw_value:
                    mark("missing_values", number, f"{value_column} is empty.")
                    continue
                if raw_value.startswith(FORMULA_PREFIXES):
                    mark(
                        "formula_like_values",
                        number,
                        "Formula-like cells are not accepted as numeric data.",
                    )
                    continue
                try:
                    value = float(raw_value)
                except ValueError:
                    mark(
                        "non_numeric_values", number, f"{value_column} is not numeric."
                    )
                    continue
                if not math.isfinite(value):
                    mark("infinite_values", number, f"{value_column} is not finite.")
                    continue
                values.append(value)
            if mapping.target:
                label_counts[row.get(mapping.target, "").strip()] += 1

        if len(values) >= 4:
            median = statistics.median(values)
            deviations = [abs(value - median) for value in values]
            mad = statistics.median(deviations)
            if mad > 0:
                outliers = sum(
                    abs(value - median) / (1.4826 * mad) > 3.5 for value in values
                )
                if outliers:
                    issues["outliers"] = list(range(1, outliers + 1))
        if len(timestamps) > 2:
            ordered = sorted(set(timestamps))
            intervals = [
                (right - left).total_seconds()
                for left, right in zip(ordered, ordered[1:], strict=False)
            ]
            if intervals and max(intervals) > max(60, statistics.median(intervals) * 3):
                issues["inconsistent_sampling"] = [0]
        if timestamps and max(timestamps) < utc_now() - timedelta(days=30):
            issues["stale_time_range"] = [0]
        if (
            label_counts
            and min(label_counts.values()) / sum(label_counts.values()) < 0.1
        ):
            issues["target_imbalance"] = [0]

        blocking_codes = {
            "missing_timestamps",
            "invalid_timestamps",
            "missing_values",
            "non_numeric_values",
            "infinite_values",
            "unknown_sensors",
            "formula_like_values",
        }
        descriptions = {
            "missing_timestamps": (
                "Rows cannot be ordered in time.",
                "Provide an ISO 8601 timestamp.",
            ),
            "invalid_timestamps": (
                "Timestamp text cannot be parsed.",
                "Use ISO 8601 with a timezone.",
            ),
            "duplicate_rows": (
                "Repeated rows may double-count observations.",
                "Remove intentional duplicates.",
            ),
            "missing_values": (
                "A mapped feature value is absent.",
                "Supply a finite numeric value.",
            ),
            "non_numeric_values": (
                "A mapped feature is not numeric.",
                "Correct the source value or mapping.",
            ),
            "infinite_values": (
                "Infinite values are unsupported.",
                "Replace with a finite measurement.",
            ),
            "formula_like_values": (
                "Spreadsheet formulas are unsafe input.",
                "Export evaluated numeric values.",
            ),
            "unknown_sensors": (
                "The machine or sensor is not registered.",
                "Correct names or register the resource.",
            ),
            "outliers": (
                "Values exceed the documented median/MAD rule.",
                "Review values; they may still be valid.",
            ),
            "inconsistent_sampling": (
                "Observed intervals vary materially.",
                "Check dropout or sampling configuration.",
            ),
            "stale_time_range": (
                "The newest reading is over 30 days old.",
                "Confirm this historical range is intended.",
            ),
            "target_imbalance": (
                "One target class is below 10%.",
                "Review class coverage before training.",
            ),
        }
        issue_rows = []
        for code, row_numbers in sorted(issues.items()):
            meaning, correction = descriptions[code]
            severity = "Blocking" if code in blocking_codes else "Warning"
            issue_rows.append(
                {
                    "code": code,
                    "severity": severity,
                    "count": len(row_numbers),
                    "meaning": meaning,
                    "correction": correction,
                    "samples": row_numbers[:MAX_ERROR_SAMPLES],
                }
            )
        invalid_rows = len(
            {
                row_number
                for code, row_numbers in issues.items()
                if code in blocking_codes
                for row_number in row_numbers
                if row_number > 0
            }
        )
        report: dict[str, object] = {
            "total_rows": len(rows),
            "valid_rows": max(0, len(rows) - invalid_rows),
            "invalid_rows": invalid_rows,
            "blocking_issue_count": sum(
                1 for item in issue_rows if item["severity"] == "Blocking"
            ),
            "warning_issue_count": sum(
                1 for item in issue_rows if item["severity"] == "Warning"
            ),
            "issues": issue_rows,
            "rule_note": (
                "Outliers use a median absolute deviation threshold of 3.5; "
                "this is a review signal, not statistical certainty."
            ),
        }
        return report, samples

    def _records(
        self,
        rows: list[dict[str, str]],
        mapping: ImportMapping,
        sensors: dict[tuple[str, str], Sensor],
    ) -> tuple[list[SensorReading], list[dict[str, object]]]:
        records: list[SensorReading] = []
        errors: list[dict[str, object]] = []
        for number, row in enumerate(rows, start=2):
            try:
                timestamp = datetime.fromisoformat(
                    row[mapping.timestamp].strip().replace("Z", "+00:00")
                )
                timestamp = timestamp.replace(
                    tzinfo=timestamp.tzinfo or UTC
                ).astimezone(UTC)
                machine_name = row[mapping.machine].strip().casefold()
                values = (
                    [(row[mapping.sensor or ""].strip(), row[mapping.value or ""])]
                    if mapping.shape == ImportShape.LONG
                    else [(feature, row[feature]) for feature in mapping.features]
                )
                for sensor_name, raw_value in values:
                    value = float(raw_value)
                    if not math.isfinite(value):
                        raise ValueError("non-finite value")
                    sensor = sensors[(machine_name, sensor_name.casefold())]
                    records.append(
                        SensorReading(
                            sensor_id=sensor.id,
                            timestamp=timestamp,
                            value=value,
                            quality=ReadingQuality.GOOD,
                            source=ReadingSource.CSV,
                        )
                    )
            except (KeyError, ValueError):
                errors.append(
                    {
                        "row": number,
                        "code": "row_rejected",
                        "detail": "Mapped data changed after validation.",
                    }
                )
        return records, errors
