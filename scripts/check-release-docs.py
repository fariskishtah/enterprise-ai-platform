#!/usr/bin/env python3
"""Check release documentation and governance invariants."""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DOCUMENTS = (
    "docs/release/repository-audit.md",
    "docs/release/supported-scope.md",
    "docs/release/versioning-policy.md",
    "docs/release/legal-readiness-checklist.md",
    "docs/release/performance-budget.md",
    "docs/release/release-validation-report.md",
    "docs/security/security-exception-register.md",
)
ACTIVE_DOCUMENTS = (
    "README.md",
    "docs/api.md",
    "docs/architecture.md",
    "docs/commercial-handoff.md",
    "docs/data-rag-operations.md",
    "docs/database.md",
    "docs/development.md",
    "docs/release-readiness.md",
)
STALE_CLAIMS = (
    re.compile(r"RAG (?:is )?not implemented", re.IGNORECASE),
    re.compile(r"frontend (?:is|being) (?:only )?a lightweight landing", re.IGNORECASE),
    re.compile(r"JSON[- ](?:stored )?vector scan", re.IGNORECASE),
)


def fail(message: str) -> None:
    print(f"release documentation error: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    missing = [path for path in REQUIRED_DOCUMENTS if not (ROOT / path).is_file()]
    if missing:
        fail(f"missing required files: {', '.join(missing)}")

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    for relative_path in ACTIVE_DOCUMENTS:
        content = (ROOT / relative_path).read_text(encoding="utf-8")
        for pattern in STALE_CLAIMS:
            if pattern.search(content):
                fail(f"{relative_path} contains stale claim {pattern.pattern!r}")

    supported_scope = (ROOT / "docs/release/supported-scope.md").read_text(
        encoding="utf-8"
    )
    if "Explicitly Out of Scope for This Release" not in supported_scope:
        fail("supported scope lacks the required out-of-scope section")
    if version not in supported_scope:
        fail("supported scope does not identify the canonical version")

    navigation = (ROOT / "frontend/src/navigation.ts").read_text(encoding="utf-8")
    if 'path: "/users"' in navigation:
        fail("unsupported user administration is still exposed in navigation")

    for lock_path in (
        ROOT / "backend/requirements/base.lock",
        ROOT / "backend/requirements/dev.lock",
    ):
        lock_content = lock_path.read_text(encoding="utf-8")
        if "--hash=sha256:" not in lock_content:
            fail(f"{lock_path.relative_to(ROOT)} is not hash locked")

    exception_register = (
        ROOT / "docs/security/security-exception-register.md"
    ).read_text(encoding="utf-8")
    expiry_values = re.findall(r"\| Expires \| (\d{4}-\d{2}-\d{2}) \|", exception_register)
    for expiry_value in expiry_values:
        if date.fromisoformat(expiry_value) < date.today():
            fail(f"security exception expired on {expiry_value}")

    print(
        f"Release documentation is consistent for version {version}; "
        f"{len(expiry_values)} open exception expiry date(s) checked."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
