"""Static safety contracts for the bounded local k6 suite."""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_K6_DIR = _ROOT / "performance/k6"
_ENTRY_SCRIPTS = (
    _K6_DIR / "smoke.js",
    _K6_DIR / "api-load.js",
    _K6_DIR / "auth-load.js",
    _K6_DIR / "training-job-load.js",
    _K6_DIR / "data-rag-load.js",
    _K6_DIR / "stress.js",
    _K6_DIR / "soak.js",
)
_COMMON = _K6_DIR / "common.js"
_CI = _ROOT / ".github/workflows/ci.yml"
_RUNBOOK = _ROOT / "docs/performance-and-load-testing.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_k6_entry_scripts_exist_and_share_safe_helpers() -> None:
    assert _COMMON.is_file()
    for script in _ENTRY_SCRIPTS:
        assert script.is_file()
        text = _text(script)
        assert "from './common.js'" in text
        assert "http_req_failed" in text
        assert "checks" in text
        assert "summaryTrendStats" in text


def test_credentials_are_environment_driven_and_never_logged() -> None:
    suite = "\n".join(_text(path) for path in (_COMMON, *_ENTRY_SCRIPTS))

    assert "__ENV.TEST_EMAIL" in suite
    assert "__ENV.TEST_PASSWORD" in suite
    assert re.search(r"password\s*:\s*['\"]", suite) is None
    assert "console.log" not in suite
    assert "console.error" not in suite


def test_default_load_profiles_are_bounded() -> None:
    smoke = _text(_K6_DIR / "smoke.js")
    api = _text(_K6_DIR / "api-load.js")
    auth = _text(_K6_DIR / "auth-load.js")

    assert "boundedInteger('SMOKE_DURATION_SECONDS', 10, 1, 30)" in smoke
    assert "boundedInteger('SMOKE_VUS', 1, 1, 2)" in smoke
    assert "boundedInteger('API_VUS', 3, 1, 20)" in api
    assert "> 300" in api
    assert "boundedInteger('AUTH_ITERATIONS', 2, 1, 3)" in auth
    assert "vus: 1" in auth
    assert "maxDuration: '2m'" in auth


def test_training_is_opt_in_small_idempotent_and_bounded() -> None:
    training = _text(_K6_DIR / "training-job-load.js")

    assert "enabled('ENABLE_TRAINING_LOAD')" in training
    assert "boundedInteger('TRAINING_JOBS', 1, 1, 3)" in training
    assert "vus: 1" in training
    assert "maxDuration: '5m'" in training
    assert "'Idempotency-Key'" in training
    assert "n_estimators: 3" in training
    assert "for (let poll = 0; poll < maxPolls; poll += 1)" in training


def test_ci_uses_one_pinned_k6_version_for_inspection_only() -> None:
    ci = _text(_CI)

    assert ci.count("grafana/k6:2.1.0") == len(_ENTRY_SCRIPTS)
    for script in _ENTRY_SCRIPTS:
        assert f"inspect /scripts/{script.name}" in ci
    assert "grafana/k6:latest" not in ci


def test_runbook_explains_metrics_safety_and_capacity_limits() -> None:
    runbook = _text(_RUNBOOK).lower()

    for term in ("p95", "p99", "error rate", "throughput", "laptop"):
        assert term in runbook
    assert "not production capacity" in runbook
    assert "enable_training_load=true" in runbook
