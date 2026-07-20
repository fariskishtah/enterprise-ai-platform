# Monitoring and retraining failures

Owner: AI Platform

## Impact

Drift evaluations or governed retraining reconciliation can fail, delaying detection and corrective model workflows.

## Symptoms

- `MonitoringRetrainingFailures` or monitoring success burn alerts fire.
- Monitoring evaluations end `failed` or reconciliation actors fail repeatedly.

## Dashboard and queries

AI Operations (`http://localhost:3000/d/ai-operations`)

```promql
sum(increase(monitoring_evaluations_total{final_status="failed"}[30m]))
```

## Immediate checks

1. Separate evaluation failures from `retraining_reconciliation` actor failures.
2. Check registry/artifact access, database health, eligible model aliases, and evaluation window inputs.
3. Inspect governance decisions: `blocked_*` is an expected policy result, not an operational failure.

## Diagnosis

- Evaluation failures affect the exact monitoring SLI; reconciliation failures are captured by the background actor SLI.
- Current retraining counters observe created and blocked decisions, not every execution failure; use worker outcomes and persisted audits.

## Mitigation

- Restore the failed integration or correct invalid evaluation inputs, then use documented reconciliation commands or APIs.
- Never weaken governance thresholds or reinterpret blocked decisions as successes to clear an alert.

## Escalation

Escalate if drift coverage is blind, audits cannot persist, retraining state diverges, or manual reconciliation is required.

## Verification

1. Monitoring evaluations complete with healthy/warning/critical business statuses rather than `failed`.
2. Reconciliation actors complete and audits/requests match persisted state.
3. Monitoring and background SLO alerts resolve.

