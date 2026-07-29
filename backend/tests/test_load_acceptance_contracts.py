"""Safety contracts for the release-candidate load harness."""

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_LOAD_SCRIPT = _ROOT / "tests/load/acceptance.js"
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
        "/operations/maintenance-feedback",
        "/ai/datasets?",
        "/documents?",
        "/knowledge-bases/",
        "/billing/plans",
        "/billing/subscription",
        "/billing/usage",
        "/billing/history/payments",
    ):
        assert path in script


def test_staging_load_fixture_disables_external_providers_and_verifies_users() -> None:
    staging = _text(_STAGING_SCRIPT)
    seed = _text(_SEED_SCRIPT)

    assert '"EMAIL_PROVIDER=disabled"' in staging
    assert '"PAYMENT_PROVIDER=disabled"' in staging
    assert '"PAYMENT_SANDBOX_MODE=false"' in staging
    assert '"BILLING_ENTITLEMENTS_ENFORCED=false"' in staging
    assert '"is_email_verified": True' in seed
    assert '"email_verified_at": datetime.now(UTC)' in seed
