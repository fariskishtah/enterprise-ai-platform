"""Safe bounded prediction-event retention command."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import timedelta

from app.config.settings import Settings, get_settings
from app.db.session import build_session_factory
from app.repositories.ai_monitoring import PredictionMonitoringRepository
from app.utils.security import utc_now


@dataclass(frozen=True, slots=True)
class PredictionEventRetentionResult:
    """One bounded cleanup result."""

    eligible_count: int
    deleted_count: int
    dry_run: bool


async def retain_prediction_events(
    settings: Settings,
    *,
    dry_run: bool,
) -> PredictionEventRetentionResult:
    """Count or delete one bounded batch older than configured retention."""
    cutoff = utc_now() - timedelta(days=settings.prediction_event_retention_days)
    session_factory = build_session_factory(settings.database_url)
    async with session_factory() as session:
        repository = PredictionMonitoringRepository(session)
        eligible = await repository.count_events_before(cutoff)
        deleted = 0
        if not dry_run:
            deleted = await repository.delete_events_before(
                cutoff=cutoff,
                limit=settings.prediction_event_retention_batch_size,
            )
            await repository.commit()
    return PredictionEventRetentionResult(
        eligible_count=eligible,
        deleted_count=deleted,
        dry_run=dry_run,
    )


def _parse_dry_run() -> bool:
    parser = argparse.ArgumentParser(
        description="Delete one bounded batch of expired prediction events.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Count eligible events without deleting them (the default).",
    )
    mode.add_argument(
        "--execute",
        action="store_true",
        help="Delete at most the configured retention batch size.",
    )
    arguments = parser.parse_args()
    return not arguments.execute


def main() -> None:
    """Run a dry-run by default or one explicitly authorized deletion batch."""
    result = asyncio.run(
        retain_prediction_events(get_settings(), dry_run=_parse_dry_run()),
    )
    print(
        f"dry_run={str(result.dry_run).lower()} eligible={result.eligible_count} "
        f"deleted={result.deleted_count}",
    )


if __name__ == "__main__":
    main()
