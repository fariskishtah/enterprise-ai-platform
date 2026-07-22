"""Bounded parsers for the initial registered dataset formats."""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass

from app.datasets.domain import TabularColumn, TabularSchema
from app.utils.safe_text import ensure_safe_multiline, ensure_safe_single_line


class DatasetIngestionError(ValueError):
    """A terminal, safe validation failure for uploaded data."""


@dataclass(frozen=True, slots=True)
class DatasetIngestionResult:
    schema_snapshot: dict[str, object]
    row_count: int | None = None
    column_count: int | None = None
    document_text: str | None = None


def ingest_csv(
    payload: bytes,
    *,
    maximum_rows: int,
    maximum_columns: int,
    maximum_cell_characters: int,
    target_column: str | None,
    split_column: str | None,
) -> DatasetIngestionResult:
    """Validate strict UTF-8 CSV and infer a bounded JSON-safe schema."""
    text = _decode_text(payload)
    try:
        rows = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(rows)
    except (StopIteration, csv.Error) as exc:
        raise DatasetIngestionError("CSV could not be parsed.") from exc
    normalized = [value.strip() for value in header]
    if not normalized or any(not value for value in normalized):
        raise DatasetIngestionError("CSV column names cannot be empty.")
    if len(normalized) > maximum_columns:
        raise DatasetIngestionError("CSV contains too many columns.")
    if len(set(value.casefold() for value in normalized)) != len(normalized):
        raise DatasetIngestionError("CSV column names must be unique.")
    if any(len(value) > 128 for value in normalized):
        raise DatasetIngestionError("CSV column names are too long.")
    try:
        normalized = [ensure_safe_single_line(value) for value in normalized]
    except ValueError as exc:
        raise DatasetIngestionError(
            "CSV column names contain unsupported characters."
        ) from exc

    columns: list[list[str]] = [[] for _ in normalized]
    row_count = 0
    try:
        for row in rows:
            row_count += 1
            if row_count > maximum_rows:
                raise DatasetIngestionError("CSV contains too many rows.")
            if len(row) != len(normalized):
                raise DatasetIngestionError("CSV rows must match the header width.")
            for index, raw_value in enumerate(row):
                value = raw_value.strip()
                if len(value) > maximum_cell_characters:
                    raise DatasetIngestionError("CSV contains an oversized value.")
                try:
                    ensure_safe_multiline(value)
                except ValueError as exc:
                    raise DatasetIngestionError(
                        "CSV contains unsupported characters."
                    ) from exc
                if _looks_executable(value):
                    raise DatasetIngestionError("CSV formulas are not supported.")
                columns[index].append(value)
    except (csv.Error, UnicodeError) as exc:
        raise DatasetIngestionError("CSV could not be parsed.") from exc
    if row_count < 4:
        raise DatasetIngestionError("CSV must contain at least four data rows.")
    if any(all(value == "" for value in values) for values in columns):
        raise DatasetIngestionError("CSV columns cannot be entirely empty.")

    inferred = tuple(
        TabularColumn(
            name=name,
            data_type=_infer_type(values),
            nullable=any(value == "" for value in values),
        )
        for name, values in zip(normalized, columns, strict=True)
    )
    try:
        schema = TabularSchema(
            columns=inferred,
            target_column=target_column,
            split_column=split_column,
        )
    except ValueError as exc:
        raise DatasetIngestionError("Dataset column configuration is invalid.") from exc
    if split_column is not None:
        split_values = columns[normalized.index(split_column)]
        training_count = 0
        evaluation_count = 0
        for value in split_values:
            normalized_split = value.strip().casefold()
            if normalized_split in {"train", "training"}:
                training_count += 1
            elif normalized_split in {"eval", "evaluation", "test", "validation"}:
                evaluation_count += 1
            else:
                raise DatasetIngestionError("Split values must be train or evaluation.")
        if training_count < 2 or evaluation_count < 2:
            raise DatasetIngestionError(
                "Explicit splits require at least two training and evaluation rows."
            )
    return DatasetIngestionResult(
        schema_snapshot=schema.model_dump(mode="json"),
        row_count=row_count,
        column_count=len(normalized),
    )


def ingest_plain_text(
    payload: bytes, *, maximum_characters: int
) -> DatasetIngestionResult:
    text = _decode_text(payload)
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        raise DatasetIngestionError("The document contains no text.")
    if len(normalized) > maximum_characters:
        raise DatasetIngestionError("The extracted document text is too large.")
    if "\x00" in normalized:
        raise DatasetIngestionError("The document contains unsupported characters.")
    try:
        normalized = ensure_safe_multiline(normalized)
    except ValueError as exc:
        raise DatasetIngestionError(
            "The document contains unsupported characters."
        ) from exc
    return DatasetIngestionResult(
        schema_snapshot={"format": "plain_text", "character_count": len(normalized)},
        document_text=normalized,
    )


def tabular_training_snapshot(
    payload: bytes,
    *,
    schema_snapshot: dict[str, object],
    evaluation_fraction: float,
) -> tuple[list[list[float]], list[float | int], list[list[float]], list[float | int]]:
    """Resolve one immutable numeric CSV version into a deterministic held-out split."""
    columns_value = schema_snapshot.get("columns")
    target_value = schema_snapshot.get("target_column")
    split_value = schema_snapshot.get("split_column")
    if not isinstance(columns_value, list) or not isinstance(target_value, str):
        raise DatasetIngestionError("The dataset has no configured target column.")
    names = [item.get("name") for item in columns_value if isinstance(item, dict)]
    if len(names) != len(columns_value) or target_value not in names:
        raise DatasetIngestionError("The dataset schema is invalid.")
    text = _decode_text(payload)
    reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
    feature_names = [
        name
        for name in names
        if isinstance(name, str) and name not in {target_value, split_value}
    ]
    if not feature_names:
        raise DatasetIngestionError("The dataset requires numeric feature columns.")
    training_x: list[list[float]] = []
    training_y: list[float | int] = []
    evaluation_x: list[list[float]] = []
    evaluation_y: list[float | int] = []
    parsed: list[tuple[list[float], float | int, str | None]] = []
    try:
        for row in reader:
            features = [_finite_number(row.get(name)) for name in feature_names]
            target = _finite_number(row.get(target_value))
            parsed.append(
                (features, target, row.get(split_value) if split_value else None)
            )
    except (TypeError, ValueError, csv.Error) as exc:
        raise DatasetIngestionError(
            "Training datasets require finite numeric features and targets."
        ) from exc
    if split_value is not None:
        for features, target, split in parsed:
            normalized_split = (split or "").strip().casefold()
            if normalized_split in {"train", "training"}:
                training_x.append(features)
                training_y.append(target)
            elif normalized_split in {"eval", "evaluation", "test", "validation"}:
                evaluation_x.append(features)
                evaluation_y.append(target)
            else:
                raise DatasetIngestionError("Split values must be train or evaluation.")
        if len(training_x) < 2 or len(evaluation_x) < 2:
            raise DatasetIngestionError(
                "Explicit splits require at least two training and evaluation rows."
            )
    else:
        evaluation_rows = max(2, round(len(parsed) * evaluation_fraction))
        if len(parsed) - evaluation_rows < 2:
            raise DatasetIngestionError("Dataset is too small for a held-out split.")
        boundary = len(parsed) - evaluation_rows
        for features, target, _split in parsed[:boundary]:
            training_x.append(features)
            training_y.append(target)
        for features, target, _split in parsed[boundary:]:
            evaluation_x.append(features)
            evaluation_y.append(target)
    return training_x, training_y, evaluation_x, evaluation_y


def _decode_text(payload: bytes) -> str:
    try:
        return payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise DatasetIngestionError("Uploads must use valid UTF-8 encoding.") from exc


def _looks_executable(value: str) -> bool:
    if not value:
        return False
    if value[0] in {"=", "+", "@"}:
        return True
    if value[0] == "-":
        try:
            return not math.isfinite(float(value))
        except ValueError:
            return True
    return False


def _infer_type(values: list[str]) -> str:
    present = [value for value in values if value != ""]
    if present and all(value.casefold() in {"true", "false"} for value in present):
        return "boolean"
    try:
        if present and all(
            str(int(value)) == value or value.startswith("+") for value in present
        ):
            return "integer"
    except ValueError:
        pass
    try:
        numbers = [float(value) for value in present]
        if present and all(math.isfinite(value) for value in numbers):
            return "float"
    except ValueError:
        pass
    return "string"


def _finite_number(value: str | None) -> float | int:
    if value is None or value.strip() == "":
        raise ValueError("Missing numeric value.")
    stripped = value.strip()
    number = float(stripped)
    if not math.isfinite(number):
        raise ValueError("Non-finite numeric value.")
    return int(number) if number.is_integer() else number
