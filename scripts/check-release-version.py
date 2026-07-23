#!/usr/bin/env python3
"""Verify projections of the canonical release version."""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-(?:0|[1-9A-Za-z-][0-9A-Za-z-]*)(?:\.[0-9A-Za-z-]+)*)?$"
)


def main() -> int:
    canonical = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if SEMVER.fullmatch(canonical) is None:
        print(f"VERSION is not a supported SemVer value: {canonical!r}", file=sys.stderr)
        return 1

    with (ROOT / "backend/pyproject.toml").open("rb") as stream:
        backend = str(tomllib.load(stream)["project"]["version"])
    with (ROOT / "frontend/package.json").open(encoding="utf-8") as stream:
        frontend = str(json.load(stream)["version"])
    with (ROOT / "frontend/package-lock.json").open(encoding="utf-8") as stream:
        lock = json.load(stream)
        frontend_lock = str(lock["version"])
        frontend_root_lock = str(lock["packages"][""]["version"])

    declarations = {
        "backend/pyproject.toml": backend,
        "frontend/package.json": frontend,
        "frontend/package-lock.json": frontend_lock,
        "frontend/package-lock.json root package": frontend_root_lock,
    }
    mismatches = {
        location: value
        for location, value in declarations.items()
        if value != canonical
    }
    if mismatches:
        print(f"Canonical release version is {canonical}.", file=sys.stderr)
        for location, value in mismatches.items():
            print(f"{location} declares {value}.", file=sys.stderr)
        return 1
    print(f"Release version {canonical} is consistent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
