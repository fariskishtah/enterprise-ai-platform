"""Automated release readiness gate and migration upgrade/downgrade validation."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_full_migration_chain_and_release_readiness_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "release-readiness.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "release-readiness-secret-key-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()

    config = Config("alembic.ini")

    # 1. Upgrade full schema to head
    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    # Verify expected production platform tables exist
    expected_tables = {
        "users",
        "refresh_tokens",
        "experiments",
        "training_runs",
        "model_artifacts",
        "training_jobs",
        "datasets",
        "dataset_versions",
        "automl_studies",
        "automl_trials",
        "rag_knowledge_bases",
        "rag_knowledge_base_dataset_versions",
        "rag_index_builds",
        "rag_indexed_chunks",
        "rag_chunk_embeddings",
        "rag_conversations",
        "rag_messages",
        "rag_message_citations",
    }
    assert expected_tables <= tables, f"Missing tables: {expected_tables - tables}"

    # 2. Downgrade to pre-dataset/RAG milestone (0011)
    command.downgrade(config, "0011")

    with sqlite3.connect(db_path) as connection:
        downgraded_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    assert "datasets" not in downgraded_tables
    assert "rag_knowledge_bases" not in downgraded_tables
    assert "users" in downgraded_tables
    assert "experiments" in downgraded_tables
    assert "training_jobs" in downgraded_tables

    # 3. Re-upgrade back to head
    command.upgrade(config, "head")

    with sqlite3.connect(db_path) as connection:
        reupgraded_tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    assert expected_tables <= reupgraded_tables
    get_settings.cache_clear()
