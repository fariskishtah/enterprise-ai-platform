# Worker down

Owner: AI Platform

## Impact

Queued training, monitoring, retention, and reconciliation work cannot be processed.

## Symptoms

- `WorkerDown` fires and `up{job="training-worker"}` is 0.
- Background work stops progressing while API submissions may still succeed.

## Dashboard and queries

AI Operations (`http://localhost:3000/d/ai-operations`)

```promql
up{job="training-worker"}
```

## Immediate checks

1. Run `docker compose ps training-worker` and inspect recent worker logs.
2. Check Redis and PostgreSQL health because the worker depends on both.
3. Confirm port 9191 is listening inside the worker container, not on a host interface.

## Diagnosis

- A process exit usually appears in worker startup logs; a scrape-only failure can be a metrics-listener collision or worker process-count mismatch.
- Separate broker connectivity failures from training integration failures.

## Mitigation

- Fix the confirmed dependency/configuration issue and recreate only `training-worker`.
- Do not purge queues or Redis data; persisted jobs and bounded retry behavior must remain intact.

## Escalation

Escalate if queued work is time-critical, retries are exhausted, or recovery would require queue/data mutation.

## Verification

1. `up{job="training-worker"}` is 1 for ten minutes.
2. A safe queued operation reaches a terminal outcome and worker lifecycle logs complete.
3. Worker and background-job alerts resolve.

