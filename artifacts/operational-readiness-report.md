# Operational readiness validation report

Validated locally on 2026-07-29 against the release-candidate source and staging
Compose topology. This report is evidence of configuration and runtime checks,
not evidence of an external on-call path.

| Capability | Result | Evidence / limitation |
| --- | --- | --- |
| Dashboards | PASS | Provisioned API, platform, SLO, alerting, AI, data/RAG, logs, traces, and correlation dashboards have static contract coverage. |
| Prometheus rules | PASS | Rule files have bounded labels, valid dashboard/runbook links, unique names, and SLO burn-rate tests. |
| Log aggregation | PASS (local) | Alloy to Loki is configured; sensitive structured-field contracts are tested. External retention/access policy remains deployment-owned. |
| Trace propagation | PASS (contract) | W3C request/worker propagation and fixed job-name contracts are tested. Production OTLP destination is deployment-owned. |
| Worker/training/RAG metrics | PASS | Worker terminal outcomes, training, monitoring, dataset, RAG, chatbot, timeout, and reconciliation metrics are exported. |
| Email metrics/alert | PASS (contract) | Delivery outcomes exclude recipient/content labels; repeated retry/failure alert added. Real provider alert firing remains blocked with email acceptance. |
| Billing webhook metrics/alert | PASS (contract) | Billing actor now maps to bounded worker metrics; any processing failure has a critical alert. Real Paymob firing remains blocked. |
| Database/Redis | PASS (contract) | Exporter loss, dependency unavailability, connection saturation, and Redis memory saturation rules exist. |
| Disk usage | PASS (container scope) | cAdvisor filesystem-pressure alert added. Host/off-host backup capacity requires deployment monitoring. |
| High latency/error rate | PASS | Explicit 5-minute error and latency alerts plus multi-window SLO burn alerts exist. |
| Alert delivery | BLOCKED | Alertmanager intentionally has local null receivers; no deployment-owned pager/webhook credentials were available. |
| Queue depth/oldest age | BLOCKED | Durable state and Redis queues are inspectable, but no bounded exported depth/age metric or alert exists. |
| Backup failure/freshness | BLOCKED | Backup/restore scripts and audit records exist, but no Prometheus success/failure/freshness exporter or external alert exists. |

The platform is operationally documented but cannot be approved for unrestricted
production until the three blocked alerting items are implemented and deliberately
fired into the real on-call path. The procedures are in `runbook.md`, escalation
in `incident-response.md`, gates in `release-checklist.md`, and recovery decisions
in `rollback-plan.md`.

## Controlled initial-launch risk decision — 2026-08-12

The Security Owner temporarily accepts the unproven external alert receiver for
the initial 1–20-user launch only. This is not evidence that external alert
delivery works. Compensating controls are manual production health verification
immediately after deployment and after canary, preserved application/container
logs, disabled payments, and a maximum of one active training job. External
alert delivery remains required post-launch.
