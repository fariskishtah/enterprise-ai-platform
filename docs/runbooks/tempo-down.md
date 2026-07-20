# Tempo down

Owner: Platform

## Impact

Distributed trace ingestion/search and trace correlation are unavailable; application requests should remain failure-isolated.

## Symptoms

- `TempoDown` fires or the Grafana Tempo datasource is unhealthy.
- Trace dashboards return datasource errors or recent traces stop appearing.

## Dashboard and queries

Distributed Tracing Overview (`http://localhost:3000/d/distributed-tracing-overview`)

```promql
up{job="tempo"}
```

## Immediate checks

1. Run `curl --fail http://localhost:3200/ready` and inspect Tempo logs.
2. Verify config validation and OTLP receiver ports inside Compose.
3. Check backend/worker logs for bounded exporter warnings; trace export must not fail business operations.

## Diagnosis

- Failed readiness points to Tempo/config/storage; healthy Tempo with missing traces points to OTLP connectivity or sampling.
- Keep trace absence distinct from application failure.

## Mitigation

- Correct the confirmed configuration/storage issue and recreate only Tempo if necessary.
- Preserve `tempo-data`; do not disable API/worker failure isolation.

## Escalation

Escalate for storage corruption, prolonged incident-debugging blindness, or repeated exporter backpressure.

## Verification

1. Tempo readiness, scrape, and datasource health succeed.
2. A new API request produces a searchable trace and log correlation remains bidirectional.
3. Backend and worker health remain unaffected.

