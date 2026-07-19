"""Bounded retention and stale-alert reconciliation used by worker actors."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import timedelta

from app.config.settings import Settings, get_settings
from app.db.session import build_session_factory
from app.observability.metrics import record_monitoring_alert_resolved
from app.repositories.monitoring_alerts import MonitoringAlertRepository
from app.repositories.monitoring_evaluations import MonitoringEvaluationRepository
from app.utils.security import utc_now


@dataclass(frozen=True, slots=True)
class MonitoringEvaluationRetentionResult:
    eligible_count: int
    deleted_count: int
    dry_run: bool


@dataclass(frozen=True, slots=True)
class StaleAlertReconciliationResult:
    resolved_count: int


async def retain_monitoring_evaluations(
    settings: Settings, *, dry_run: bool
) -> MonitoringEvaluationRetentionResult:
    cutoff = utc_now() - timedelta(days=settings.monitoring_evaluation_retention_days)
    session_factory = build_session_factory(settings.database_url)
    async with session_factory() as session:
        repository = MonitoringEvaluationRepository(session)
        eligible = await repository.count_before(cutoff)
        deleted = 0
        if not dry_run:
            deleted = await repository.delete_before(
                cutoff=cutoff,
                limit=settings.monitoring_evaluation_retention_batch_size,
            )
            await repository.commit()
    return MonitoringEvaluationRetentionResult(eligible, deleted, dry_run)


async def reconcile_stale_alerts(
    settings: Settings,
) -> StaleAlertReconciliationResult:
    cutoff = utc_now() - timedelta(hours=settings.monitoring_stale_alert_hours)
    session_factory = build_session_factory(settings.database_url)
    async with session_factory() as session:
        repository = MonitoringAlertRepository(session)
        resolved = await repository.resolve_stale(
            last_detected_before=cutoff,
            limit=settings.monitoring_evaluation_retention_batch_size,
        )
        await repository.commit()
        for alert in resolved:
            record_monitoring_alert_resolved(
                alert_type=alert.alert_type.value,
                severity=alert.severity.value,
            )
    return StaleAlertReconciliationResult(len(resolved))


def main() -> None:
    """Expose dry-run evaluation retention and explicit alert reconciliation."""
    parser = argparse.ArgumentParser(description="Run bounded monitoring maintenance.")
    subcommands = parser.add_subparsers(dest="command", required=True)
    retention = subcommands.add_parser("evaluation-retention")
    retention.add_argument("--execute", action="store_true")
    subcommands.add_parser("stale-alerts")
    arguments = parser.parse_args()
    settings = get_settings()
    if arguments.command == "evaluation-retention":
        result = asyncio.run(
            retain_monitoring_evaluations(settings, dry_run=not arguments.execute)
        )
        print(
            f"dry_run={str(result.dry_run).lower()} "
            f"eligible={result.eligible_count} deleted={result.deleted_count}"
        )
        return
    alert_result = asyncio.run(reconcile_stale_alerts(settings))
    print(f"resolved={alert_result.resolved_count}")


if __name__ == "__main__":
    main()
