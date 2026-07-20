# PostgreSQL issues

Owner: Platform

## Impact

API and worker persistence may fail or stall, affecting nearly every platform workflow.

## Symptoms

- `PostgresExporterDown` or `PostgresConnectionSaturation` fires.
- API/worker logs report safe database error kinds or elevated latency.

## Dashboard and queries

Platform Overview (`http://localhost:3000/d/platform-overview`)

```promql
sum(pg_stat_activity_count) / scalar(max(pg_settings_max_connections))
```

## Immediate checks

1. Run `docker compose ps postgres postgres-exporter`.
2. Use `pg_isready` through the Compose service and inspect PostgreSQL logs.
3. Break down `pg_stat_activity_count` by state and database; look for sustained idle-in-transaction use.

## Diagnosis

- Exporter-down alone is telemetry loss; confirm database readiness separately.
- High connections with low work suggests pool/leak behavior; active saturation suggests load or slow queries.

## Mitigation

- Stop the confirmed connection leak or slow workload and let application pools recover.
- Do not terminate sessions, change `max_connections`, or modify data without explicit incident authority.

## Escalation

Escalate immediately for corruption, failed migrations, lock chains, rejected connections, or any required destructive database action.

## Verification

1. Readiness and exporter scrape are healthy.
2. Connection utilization stays below 80% and application error/latency signals recover.
3. A representative API write/read and worker persistence operation succeeds.

