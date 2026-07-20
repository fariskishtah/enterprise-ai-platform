# Grafana down

Owner: Platform

## Impact

Provisioned dashboards and datasource exploration are unavailable; Prometheus, Alertmanager, Loki, and Tempo continue independently.

## Symptoms

- `GrafanaDown` fires or `/api/health` fails.
- Dashboard URLs referenced by alerts cannot be opened.

## Dashboard and queries

Alerting Overview (`http://localhost:3000/d/alerting-overview`)

```promql
up{job="grafana"}
```

## Immediate checks

1. Run `curl --fail http://localhost:3000/api/health` and inspect Grafana logs.
2. Check provisioning parse errors and the `grafana-data` mount.
3. Query Prometheus/Alertmanager directly to preserve incident visibility.

## Diagnosis

- A running container with failed health often indicates startup migration, database, or provisioning failure.
- Datasource-specific errors with healthy Grafana should be handled by the relevant Loki/Tempo/Prometheus runbook.

## Mitigation

- Fix the confirmed provisioning/configuration issue and recreate only Grafana.
- Preserve `grafana-data`; durable dashboards must be fixed in source JSON, not only in the UI.

## Escalation

Escalate if Grafana state migration fails, persistent state appears corrupt, or dashboards are required for a critical incident.

## Verification

1. Grafana health and Prometheus scrape are healthy.
2. All provisioned dashboards load through the API and datasource health checks succeed.
3. No provisioning errors remain in logs.

