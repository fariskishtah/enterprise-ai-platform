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
    } <= tables
    assert {
        "provider_checkout_id",
        "idempotency_key",
        "plan_code",
        "checkout_url",
        "provider_occurred_at",
        "updated_at",
        "purpose",
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
