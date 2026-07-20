# Alertmanager down or alert delivery failure

Owner: Platform

## Impact

Prometheus alerts may not be grouped, inhibited, or exposed through Alertmanager; configured receivers are intentionally local null receivers.

## Symptoms

- `AlertmanagerDown`, config reload, rule evaluation, or delivery alerts fire.
- Prometheus reports an unhealthy Alertmanager target or notification errors.

## Dashboard and queries

Alerting Overview (`http://localhost:3000/d/alerting-overview`)

```promql
up{job="alertmanager"}
```

## Immediate checks

1. Run `curl --fail http://localhost:9093/-/healthy` and inspect Alertmanager logs.
2. Validate config with `docker compose exec alertmanager amtool check-config /etc/alertmanager/alertmanager.yml`.
3. Inspect Prometheus `/api/v1/alertmanagers`, rule health, and notification error metrics.

## Diagnosis

- Config reload failure keeps the last valid route; service down prevents all delivery.
- Rule evaluation failure is upstream of delivery and must be fixed in the named rule group.

## Mitigation

- Restore the last valid source-controlled configuration and recreate only Alertmanager/Prometheus as required.
- Do not add external notification credentials during incident response; local receivers remain intentionally empty.

## Escalation

Escalate immediately when critical alerts cannot be observed, rule evaluations fail broadly, or routing state cannot be restored.

## Verification

1. Alertmanager health, config status, and Prometheus discovery are healthy.
2. A controlled temporary Prometheus alert appears grouped in Alertmanager, then resolves after cleanup.
3. No notification or rule-evaluation errors continue increasing.

