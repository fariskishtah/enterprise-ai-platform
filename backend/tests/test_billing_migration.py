"""Billing foundation migration coverage."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_billing_migration_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "billing-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "billing-migration-test-key-with-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    command.check(config)
    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        payment_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(payments)")
        }
        webhook_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(billing_webhook_events)")
        }
        subscription_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(subscriptions)")
        }
        user_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(users)")
        }
    assert {
        "billing_plans",
        "plan_entitlements",
        "subscriptions",
        "payments",
        "invoice_references",
        "payment_provider_customers",
        "billing_webhook_events",
        "usage_counters",
        "billing_audit_events",
        "billing_reconciliation_runs",
        "billing_reconciliation_results",
    } <= tables
    assert {
        "provider_checkout_id",
        "idempotency_key",
        "plan_code",
        "checkout_url",
        "provider_occurred_at",
        "updated_at",
        "purpose",
        "checkout_intent_status",
        "checkout_expires_at",
        "superseded_by_payment_id",
        "return_reference_hash",
        "return_reference_expires_at",
        "environment",
        "commercial_model",
        "provider_decision",
        "provider_integration_id",
        "provider_merchant_id",
    } <= payment_columns
    assert {
        "raw_provider_event_id",
        "safe_payload",
        "company_id",
        "queued_at",
        "processing_started_at",
        "next_retry_at",
        "last_error_category",
        "dead_lettered_at",
        "replay_count",
        "validation_outcome",
    } <= webhook_columns
    assert "is_platform_operator" in user_columns
    assert {
        "pending_plan_id",
        "latest_payment_id",
        "status_changed_at",
        "suspended_at",
        "ended_at",
        "version",
    } <= subscription_columns

    command.downgrade(config, "0022_add_public_demo_workspaces")
    with sqlite3.connect(database_path) as connection:
        remaining = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert "billing_plans" not in remaining
    assert "companies" in remaining
    get_settings.cache_clear()


def test_phase2_downgrade_refuses_to_discard_webhook_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "billing-phase2-downgrade-guard.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "billing-migration-test-key-with-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "head")
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO billing_webhook_events "
            "(id, provider, provider_event_id, event_type, payload_hash, status, "
            "attempts, replay_count, validation_outcome) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "0198d6df-16c8-7e0d-8080-000000000001",
                "paymob",
                "phase2-downgrade-evidence",
                "transaction",
                "0" * 64,
                "quarantined",
                0,
                0,
                "quarantined_unknown_payment",
            ),
        )

    with pytest.raises(RuntimeError, match="retain 0033"):
        command.downgrade(config, "0032_billing_phase1_remediation")
    get_settings.cache_clear()
