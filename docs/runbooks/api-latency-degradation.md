# API latency degradation

Owner: Platform

## Impact

Eligible API requests exceed 500 ms, degrading client workflows and consuming the latency error budget.

## Symptoms

- `APILatencyDegradation` or API latency burn alerts fire.
- P95/P99 latency rises, potentially without a matching 5xx increase.

## Dashboard and queries

Backend API (`http://localhost:3000/d/backend-api`)

```promql
slo:http_latency:error_ratio_rate5m
```

## Immediate checks

1. Compare latency by normalized route and method.
2. Inspect backend container CPU/memory, PostgreSQL connections, and Redis exporter health.
3. Use a slow representative request to pivot from logs to its Tempo trace without capturing request bodies.

## Diagnosis

- One slow route suggests handler, query, or model-loading work; broad latency suggests shared saturation.
- A healthy median with high P99 indicates tail amplification rather than uniform slowdown.
- Confirm traffic volume before interpreting a sparse histogram.

## Mitigation

- Relieve the confirmed bottleneck, bound optional concurrency, or revert the responsible change.
- Do not raise the 500 ms threshold during an incident; SLO changes require review.

## Escalation

Escalate if the fast burn alert is critical, latency affects safety-relevant workflows, or database/cache saturation persists.

## Verification

1. The fraction over 500 ms returns below 1% over both 5m and 1h windows.
2. P95/P99 panels stabilize and representative traces no longer show the diagnosed bottleneck.
3. Alertmanager no longer exposes the latency alerts.

