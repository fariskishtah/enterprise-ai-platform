# Loki down

Owner: Platform

## Impact

Centralized log search and log-to-trace correlation are unavailable; application execution continues.

## Symptoms

- `LokiDown` fires or Grafana Loki datasource health fails.
- Logs Overview panels return datasource errors rather than empty results.

## Dashboard and queries

Logs Overview (`http://localhost:3000/d/logs-overview`)

```promql
up{job="loki"}
```

## Immediate checks

1. Run `curl --fail http://localhost:3100/ready` and inspect `docker compose ps loki`.
2. Inspect recent Loki logs and confirm its config/volume mounts.
3. Check Alloy separately; ingestion can fail even when Loki is ready.

## Diagnosis

- A failed Prometheus scrape plus failed readiness indicates Loki; a healthy Loki with missing logs points to Alloy or selectors.
- Review storage and retention errors without deleting data.

## Mitigation

- Correct the confirmed config/storage issue and recreate only Loki if necessary.
- Preserve `loki-data`; do not clear chunks or indexes to force readiness.

## Escalation

Escalate when storage appears corrupt, logs are required for an active incident, or recovery risks retained data.

## Verification

1. Readiness, Prometheus scrape, and Grafana datasource health succeed.
2. A fresh bounded application log appears in Logs Overview.
3. Log-derived trace links still resolve.

