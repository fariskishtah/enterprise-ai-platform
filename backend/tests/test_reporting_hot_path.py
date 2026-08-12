"""Focused executive-dashboard aggregation regression coverage."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from app.api.routes.reporting import _metrics
from sqlalchemy.ext.asyncio import AsyncSession


class _Result:
    def one(self) -> SimpleNamespace:
        return SimpleNamespace(
            machine_count=4,
            open_alerts=3,
            critical_alerts=1,
            overdue_actions=2,
            completed_actions=5,
            acknowledgment_seconds=12.25,
            resolution_seconds=45.5,
            latest_reading=datetime(2026, 8, 11, tzinfo=UTC),
            feedback_count=6,
            shift_count=7,
        )


class _Session:
    def __init__(self) -> None:
        self.execute_count = 0

    async def execute(self, _statement: object) -> _Result:
        self.execute_count += 1
        return _Result()


@pytest.mark.anyio
async def test_dashboard_metrics_use_one_database_round_trip() -> None:
    session = _Session()
    end_at = datetime(2026, 8, 11, tzinfo=UTC)

    result = await _metrics(
        cast(AsyncSession, session),
        company_id=uuid4(),
        factory_id=None,
        start_at=end_at - timedelta(days=7),
        end_at=end_at,
    )

    assert session.execute_count == 1
    assert result["machine_count"] == 4
    assert result["open_alerts"] == 3
    assert result["data_freshness_at"] == "2026-08-11T00:00:00+00:00"
