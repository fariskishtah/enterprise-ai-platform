"""Safety contracts for the release-candidate load harness."""

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_LOAD_SCRIPT = _ROOT / "tests/load/acceptance.js"
_CAPACITY_SCRIPT = _ROOT / "tests/load/capacity.js"
_STAGING_SCRIPT = _ROOT / "scripts/staging-local.sh"
_SEED_SCRIPT = _ROOT / "scripts/seed_staging_users.py"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_acceptance_load_is_local_only_and_covers_release_endpoints() -> None:
    script = _text(_LOAD_SCRIPT)

    assert "Acceptance load tests refuse non-local targets." in script
    for path in (
        "/health",
        "/auth/login",
        "/reporting/executive-dashboard",
        "/machines?",
        "/operations/alerts?",
        "/ai/datasets?",
        "/documents?",
        "/knowledge-bases/",
        "/billing/plans",
        "/billing/subscription",
        "/billing/usage",
        "/billing/history/payments",
    ):
        assert path in script
    assert "/operations/maintenance-feedback" not in script


def test_capacity_load_is_read_only_local_bounded_and_stops_on_degradation() -> None:
    script = _text(_CAPACITY_SCRIPT)

    assert "Capacity load tests refuse non-local targets." in script
    assert "[10, 25, 50, 100, 250, 500]" in script
    assert "rate<0.02" in script
    assert "abortOnFail: true" in script
    assert '"http_req_duration{phase:steady}"' in script
    assert "capacity_setup_latency" in script
    assert "capacity_steady_latency" in script
    assert "capacity_setup_errors" in script
    assert "capacity_steady_errors" in script
    assert 'WORKLOAD === "auth"' in script
    assert 'WORKLOAD === "auth" ? "p(95)<1500" : "p(95)<1000"' in script
    assert 'executor: "per-vu-iterations"' in script
    assert "p(95)<1000" in script
    assert "p(99)<2500" in script
    assert '"CAPACITY_DURATION_SECONDS"' in script
    assert '"CAPACITY_PAUSE_SECONDS", 2' in script
    assert "30," in script and "120," in script
    assert 'new Set(["api", "auth", "db", "rag", "mixed"])' in script
    for path in (
        "/reporting/executive-dashboard",
        "/factories?",
        "/users/me",
        "/machines?",
        "/operations/alerts?",
        "/ai/datasets?",
        "/auth/refresh",
        "/knowledge-bases/",
    ):
        assert path in script
    for mutation in (
        "/operations/maintenance-feedback",
        "/ai/training-jobs/random-forest",
        "/billing/checkout",
        "PAYMOB",
    ):
        assert mutation not in script
    assert "/health" not in script
    assert "RAG_LOAD_USER_COUNT" in script
    assert "knowledgeBaseId: items[0].knowledge_base_id" in script


def test_staging_load_fixture_disables_external_providers_and_verifies_users() -> None:
    staging = _text(_STAGING_SCRIPT)
    seed = _text(_SEED_SCRIPT)

    assert '"EMAIL_PROVIDER=disabled"' in staging
    assert '"PAYMENT_PROVIDER=disabled"' in staging
    assert '"PAYMENT_SANDBOX_MODE=false"' in staging
    assert '"BILLING_ENTITLEMENTS_ENFORCED=false"' in staging
    assert "E2E_EXTERNAL_EMAIL" in staging
    assert "RAG_LOAD_USER_COUNT" in staging
    assert "RAG_LOAD_EMAIL_PREFIX" in staging
    assert "RAG_LOAD_EMAIL_DOMAIN" in staging
    assert '"is_email_verified": True' in seed
    assert '"email_verified_at": datetime.now(UTC)' in seed
    assert '"role": UserRole.ENGINEER' in seed
