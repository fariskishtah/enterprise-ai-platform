"""Sensor data Alembic migration tests."""

import sqlite3

from alembic import command
from alembic.config import Config
from app.config.settings import get_settings


def test_alembic_head_creates_sensor_data_tables_and_indexes(
    tmp_path,
    monkeypatch,
) -> None:
    """Alembic head creates the Sprint 5 tables and time-series indexes."""
    database_path = tmp_path / "sensor-data-migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-with-sufficient-entropy")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()

    config = Config("alembic.ini")
    command.upgrade(config, "head")

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'",
            )
        }
        reading_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list('sensor_readings')")
        }
        upload_job_indexes = {
            row[1] for row in connection.execute("PRAGMA index_list('upload_jobs')")
        }
    finally:
        connection.close()
        get_settings.cache_clear()

    assert "sensor_readings" in tables
    assert "upload_jobs" in tables
    assert "ix_sensor_readings_sensor_timestamp" in reading_indexes
    assert "ix_sensor_readings_batch_timestamp" in reading_indexes
    assert "ix_upload_jobs_status_created" in upload_job_indexes
