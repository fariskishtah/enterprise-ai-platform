# Background job failures

Owner: AI Platform

## Impact

Dramatiq actors fail, delaying training, monitoring, retention, or reconciliation outcomes.

## Symptoms

- `BackgroundJobFailureBurst` or background success burn alerts fire.
- Worker lifecycle logs show bounded `job_name` values ending in `failed`.

## Dashboard and queries

AI Operations (`http://localhost:3000/d/ai-operations`)

```promql
sum by (job_name) (increase(background_jobs_processed_total{final_status="failed"}[30m]))
```

## Immediate checks

1. Identify the bounded actor name with the largest failure increase.
2. Correlate a representative lifecycle log to its trace and dependency spans.
3. Check job-specific scheduling flags and PostgreSQL/Redis health without changing them during diagnosis.

## Diagnosis

- One actor failing suggests its application path; many actors failing suggests worker, database, or broker infrastructure.
- Skipped messages are excluded from the success SLI and should be reviewed separately when unexpected.

## Mitigation

- Restore the failing dependency or correct the actor-specific defect; allow configured bounded retries to operate.
- Pause an optional scheduler only through the documented configuration process if repeated work worsens the incident.

## Escalation

Escalate when failures exhaust retries, affect multiple actors, risk stale governance state, or require manual record reconciliation.

## Verification

1. Failed terminal outcomes stop increasing and completed outcomes resume.
2. The 5m and 1h success burn rates fall below alert thresholds.
3. Persisted job states agree with worker lifecycle outcomes.

