# Backend down

Owner: Platform

## Impact

API service and its metrics endpoint are unreachable; client traffic may be completely unavailable.

## Symptoms

- `BackendDown` fires and `up{job="backend"}` is 0.
- Prometheus target details show a scrape connection or HTTP error.

## Dashboard and queries

Platform Overview (`http://localhost:3000/d/platform-overview`)

```promql
up{job="backend"}
```

## Immediate checks

1. Run `docker compose ps backend` and inspect health/state.
2. Run `docker compose logs --tail=200 backend` and look for startup, dependency, or bind failures.
3. Check `docker compose ps postgres redis tempo` without restarting healthy dependencies.

## Diagnosis

- A stopped container points to process exit or Compose configuration; a running target with scrape errors points to listener/network/path mismatch.
- Correlate startup errors with the last local configuration change.

## Mitigation

- Correct the confirmed configuration or dependency issue and recreate only `backend` when necessary.
- Preserve volumes and never bypass migrations or health dependencies to force startup.

## Escalation

Escalate immediately for data corruption, repeated crash loops, failed migrations, or inability to restore the service safely.

## Verification

1. `curl --fail http://localhost:8000/health` and `/metrics` succeed.
2. `up{job="backend"}` remains 1 for at least ten minutes.
3. API availability alerts resolve and a representative authenticated workflow succeeds.

