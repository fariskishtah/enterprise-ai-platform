# API high error rate

Owner: Platform

## Impact

Clients receive 5xx responses and API availability consumes its error budget.

## Symptoms

- `APIHighErrorRate` or API availability burn alerts fire.
- Backend API panels show a rising 5xx ratio while the backend target may remain healthy.

## Dashboard and queries

Backend API (`http://localhost:3000/d/backend-api`)

```promql
slo:http_availability:error_ratio_rate5m
```

## Immediate checks

1. Confirm `up{job="backend"}` is 1 and compare 5xx rates by normalized route.
2. Inspect recent backend logs for fixed error kinds and correlate representative failures to Tempo traces.
3. Check PostgreSQL and Redis target health before attributing the issue to application code.

## Diagnosis

- A broad route distribution usually indicates a shared dependency or deployment problem.
- One normalized route dominating the failures points to that handler or its downstream operation.
- A scrape outage is handled by `BackendDown`; do not treat missing traffic as a healthy business signal.

## Mitigation

- Restore an unhealthy dependency, or roll back/disable the in-scope failing change using the normal deployment process.
- Reduce optional workload only when it preserves API correctness; do not hide failures by changing the SLI query.

## Escalation

Escalate immediately if the critical burn alert fires, authentication or data-integrity paths fail, or mitigation requires data repair.

## Verification

1. The 5m error ratio remains below 0.001 for at least 15 minutes.
2. Critical and warning burn alerts resolve in Prometheus and Alertmanager.
3. Representative client requests succeed and correlated logs/traces show no continuing failures.

