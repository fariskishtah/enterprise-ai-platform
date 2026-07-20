# Container resource pressure

Owner: Platform

## Impact

A quota-bound observability container can throttle or be OOM-killed, reducing telemetry availability.

## Symptoms

- `ContainerCPUQuotaPressure` or `ContainerMemoryLimitPressure` fires.
- Platform Overview shows sustained use close to the configured Compose limit.

## Dashboard and queries

Platform Overview (`http://localhost:3000/d/platform-overview`)

```promql
max by (container_label_com_docker_compose_service) (container_memory_working_set_bytes)
```

## Immediate checks

1. Identify the bounded Compose service label from the alert.
2. Inspect service logs for compaction, ingestion, or allocation pressure.
3. Compare workload rate and retention behavior before changing resource limits.

## Diagnosis

- These alerts only evaluate for containers with explicit non-zero limits/quotas.
- A brief spike is filtered by the 15-minute `for`; sustained pressure needs workload or capacity analysis.

## Mitigation

- Reduce confirmed optional load or apply a reviewed Compose resource adjustment appropriate to the service.
- Do not delete telemetry volumes to lower usage.

## Escalation

Escalate before OOM risk affects incident visibility, or when storage/ingestion behavior is unexpected.

## Verification

1. CPU or memory remains below 90% of its configured limit for at least 15 minutes.
2. The affected service remains ready and its Prometheus target is up.
3. No data-integrity or ingestion errors continue.

