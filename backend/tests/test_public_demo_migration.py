"""Public-demo company marker migration coverage."""

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_public_demo_marker_migration_preserves_existing_companies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "public-demo-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "public-demo-migration-key-with-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()
    config = Config("alembic.ini")

    command.upgrade(config, "0021_add_support_requests")
    company_id = uuid4().hex
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO companies (id, name, normalized_name) VALUES (?, ?, ?)",
            (company_id, "Existing Company", "existing company"),
        )
        connection.commit()

    command.upgrade(config, "0022_add_public_demo_workspaces")
    with sqlite3.connect(database_path) as connection:
        columns = {
            row[1]: row for row in connection.execute("PRAGMA table_info(companies)")
        }
        indexes = {row[1] for row in connection.execute("PRAGMA index_list(companies)")}
        marker = connection.execute(
            "SELECT is_public_demo FROM companies WHERE id = ?", (company_id,)
        ).fetchone()

        assert columns["is_public_demo"][3] == 1
        assert "ix_companies_public_demo" in indexes
        assert marker == (0,)
        connection.execute(
            "UPDATE companies SET is_public_demo = 1 WHERE id = ?", (company_id,)
        )
        connection.commit()

    command.downgrade(config, "0021_add_support_requests")
    with sqlite3.connect(database_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(companies)")}
        assert "is_public_demo" not in columns

    command.upgrade(config, "head")
    command.check(config)
    get_settings.cache_clear()
