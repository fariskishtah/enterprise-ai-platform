#!/usr/bin/env python3
"""Generate deterministic manufacturing validation CSVs outside Git."""

from __future__ import annotations

import argparse
import csv
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROFILE_ROWS = {"small": 1_000, "medium": 50_000, "large": 250_000}
MAX_ROWS = PROFILE_ROWS["large"]


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--output", type=Path, required=True)
    result.add_argument("--profile", choices=PROFILE_ROWS, default="small")
    result.add_argument("--rows", type=int)
    result.add_argument(
        "--format", choices=("onboarding", "training"), default="onboarding"
    )
    result.add_argument("--scenario", choices=("normal", "faults"), default="normal")
    return result


def bounded_rows(profile: str, requested: int | None) -> int:
    rows = PROFILE_ROWS[profile] if requested is None else requested
    if rows < 100 or rows > MAX_ROWS:
        raise ValueError(f"rows must be between 100 and {MAX_ROWS}")
    return rows


def generated_values(index: int) -> tuple[float, float, float, float]:
    cycle = math.sin(index / 48)
    temperature = 68.0 + 6.2 * cycle + (index % 17) * 0.03
    vibration = 2.1 + 0.7 * math.sin(index / 31) + (index % 13) * 0.01
    energy = 41.0 + 5.5 * math.cos(index / 67) + temperature * 0.08
    risk = min(
        1.0,
        max(
            0.0,
            (temperature - 64.0) / 28.0
            + (vibration - 1.5) / 12.0
            + (0.08 if index % 97 == 0 else 0.0),
        ),
    )
    return temperature, vibration, energy, risk


def write_onboarding(writer: csv.writer, rows: int, *, faults: bool) -> dict[str, int]:
    writer.writerow(("timestamp", "machine", "sensor", "value"))
    start = datetime(2026, 7, 1, 8, tzinfo=UTC)
    invalid = missing = gaps = stale = 0
    for index in range(rows):
        temperature, vibration, _energy, _risk = generated_values(index)
        sensor = (
            "Spindle Temperature DEMO-01"
            if index % 2 == 0
            else "Spindle Vibration DEMO-01"
        )
        value: object = temperature if index % 2 == 0 else vibration
        timestamp = start + timedelta(
            minutes=index + (1 if faults and index > 700 else 0)
        )
        if faults and index % 503 == 0:
            value = "not-a-number"
            invalid += 1
        elif faults and index % 347 == 0:
            value = ""
            missing += 1
        if faults and index == 701:
            gaps += 1
        if faults and index % 997 == 0:
            timestamp = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(minutes=index)
            stale += 1
        writer.writerow(
            (
                timestamp.isoformat().replace("+00:00", "Z"),
                "CNC Mill DEMO-01",
                sensor,
                value if isinstance(value, str) else f"{value:.4f}",
            )
        )
    return {"invalid": invalid, "missing": missing, "gaps": gaps, "stale": stale}


def write_training(writer: csv.writer, rows: int, *, faults: bool) -> dict[str, int]:
    writer.writerow(
        (
            "temperature_c",
            "vibration_mm_s",
            "energy_kwh",
            "risk_score",
            "fault_target",
            "split",
        )
    )
    invalid = missing = imbalanced = 0
    for index in range(rows):
        temperature, vibration, energy, risk = generated_values(index)
        target: object = 1 if index % 97 == 0 else 0
        if target == 0:
            imbalanced += 1
        if faults and index % 503 == 0:
            target = "invalid"
            invalid += 1
        row: list[object] = [
            f"{temperature:.4f}",
            f"{vibration:.4f}",
            f"{energy:.4f}",
            f"{risk:.6f}",
            target,
            "evaluation" if index % 5 == 0 else "train",
        ]
        if faults and index % 347 == 0:
            row[1] = ""
            missing += 1
        writer.writerow(row)
    return {
        "invalid": invalid,
        "missing": missing,
        "majority_target_rows": imbalanced,
    }


def main() -> int:
    args = parser().parse_args()
    try:
        rows = bounded_rows(args.profile, args.rows)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        if args.format == "onboarding":
            findings = write_onboarding(writer, rows, faults=args.scenario == "faults")
        else:
            findings = write_training(writer, rows, faults=args.scenario == "faults")
    print(
        f"Generated {rows} deterministic {args.format} rows "
        f"({args.scenario}) at {args.output}."
    )
    print(f"Size: {args.output.stat().st_size} bytes. Injected findings: {findings}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
