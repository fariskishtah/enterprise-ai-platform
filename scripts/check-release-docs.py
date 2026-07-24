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
TRIVY_ROUTER_ADVISORY = "GHSA-qwww-vcr4-c8h2"
TRIVY_ROUTER_PATH = "frontend/package-lock.json"


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
    if 'path: "/users"' not in navigation:
        fail("supported tenant user administration is missing from navigation")

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
    expiry_values = re.findall(
        r"\| Expires \| (\d{4}-\d{2}-\d{2}) \|", exception_register
    )
    for expiry_value in expiry_values:
        if date.fromisoformat(expiry_value) < date.today():
            fail(f"security exception expired on {expiry_value}")

    trivy_ignore = (ROOT / ".trivyignore.yaml").read_text(encoding="utf-8")
    trivy_entry = re.search(
        rf"(?ms)^  - id: {re.escape(TRIVY_ROUTER_ADVISORY)}\s*$"
        r"(?P<body>.*?)(?=^  - id:|\Z)",
        trivy_ignore,
    )
    if trivy_entry is None:
        fail(f".trivyignore.yaml lacks {TRIVY_ROUTER_ADVISORY}")

    trivy_body = trivy_entry.group("body")
    trivy_paths = re.findall(r'(?m)^      - ["\']?([^"\']+)["\']?\s*$', trivy_body)
    if trivy_paths != [TRIVY_ROUTER_PATH]:
        fail(f"{TRIVY_ROUTER_ADVISORY} must apply only to {TRIVY_ROUTER_PATH}")

    statement_match = re.search(
        r"(?m)^    statement:\s*[\"']?(.*?)[\"']?\s*$", trivy_body
    )
    expiry_match = re.search(
        r"(?m)^    expired_at:\s*[\"']?(\d{4}-\d{2}-\d{2})[\"']?\s*$",
        trivy_body,
    )
    if statement_match is None or expiry_match is None:
        fail(f"{TRIVY_ROUTER_ADVISORY} lacks a statement or expiry")

    exception_id_match = re.search(r"SEC-\d{4}-\d{3}", statement_match.group(1))
    if exception_id_match is None:
        fail(f"{TRIVY_ROUTER_ADVISORY} statement lacks a security exception ID")

    exception_id = exception_id_match.group(0)
    exception_section = re.search(
        rf"(?ms)^### {re.escape(exception_id)}\b.*?(?=^### |\Z)",
        exception_register,
    )
    if exception_section is None:
        fail(f"{exception_id} referenced by Trivy is not registered")

    registered_expiry = re.search(
        r"\| Expires \| (\d{4}-\d{2}-\d{2}) \|", exception_section.group(0)
    )
    if (
        f"`{TRIVY_ROUTER_ADVISORY}`" not in exception_section.group(0)
        or registered_expiry is None
        or registered_expiry.group(1) != expiry_match.group(1)
    ):
        fail(f"{TRIVY_ROUTER_ADVISORY} and {exception_id} advisory/expiry do not match")

    print(
        f"Release documentation is consistent for version {version}; "
        f"{len(expiry_values)} open exception expiry date(s) checked; "
        f"Trivy {TRIVY_ROUTER_ADVISORY} matches {exception_id}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
