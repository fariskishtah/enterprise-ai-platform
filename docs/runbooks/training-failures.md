# Training failures

Owner: AI Platform

## Impact

Model training jobs terminate unsuccessfully, consuming the 95% workflow error budget.

## Symptoms

- `TrainingFailures` or training success burn alerts fire.
- `training_jobs_failed_total` increases for bounded task/algorithm labels.

## Dashboard and queries

AI Operations (`http://localhost:3000/d/ai-operations`)

```promql
sum by (task_type, algorithm) (increase(training_jobs_failed_total[30m]))
```

## Immediate checks

1. Identify affected task type and algorithm without inspecting customer payloads.
2. Inspect the matching persisted training job error code and safe worker logs.
3. Check artifacts, MLflow path, database, Redis, and local resource pressure.

## Diagnosis

- Validation failures indicate request/specification defects; retryable integration failures indicate dependencies; broad algorithms failing suggest shared infrastructure.
- Distinguish terminal job counters from transient actor retry attempts.

## Mitigation

- Fix the confirmed input, artifact, or integration issue and resubmit through the normal API only when idempotency permits.
- Do not mark failed jobs successful or edit artifacts manually.

## Escalation

Escalate for repeated terminal failures, artifact integrity concerns, promotion impact, or unknown failures across algorithms.

## Verification

1. New safe training work succeeds and records completion/duration metrics.
2. Training burn rates recover across paired windows.
3. Persisted training, artifact, tracking, and registry state remains consistent.

