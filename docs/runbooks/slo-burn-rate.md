# SLO multi-window burn rate

Owner: Platform

## Impact

A user-facing or workflow SLO is consuming error budget faster than its sustainable 30-day rate.

## Symptoms

- A `*SLOBurnFast`, `Medium`, `Slow`, or `Ticket` alert fires.
- SLO Overview shows paired short/long windows above the same multiplier.

## Dashboard and queries

SLO Overview (`http://localhost:3000/d/slo-overview`)

```promql
slo:http_availability:burn_rate1h
```

## Immediate checks

1. Identify the `slo`, `service`, severity, and paired windows on the alert.
2. Open the SLO-specific dashboard, then use the linked API/job/monitoring runbook for root cause.
3. Confirm Prometheus rule health and denominator traffic before interpreting a sparse new installation.

## Diagnosis

- 14.4x (5m/1h) is urgent; 6x (30m/6h) and 3x (2h/1d) indicate sustained loss; 1x (6h/3d) is ticket-level.
- Critical alerts inhibit warning/info notifications for the same service/SLO while all alerts remain inspectable.

## Mitigation

- Mitigate the underlying bad events; never silence by editing the SLI denominator, labels, or target during an incident.
- Use a reviewed silence only for known maintenance, with scope and expiry.

## Escalation

Escalate fast-burn critical alerts immediately; escalate slower burns when budget remaining is low or no safe mitigation exists.

## Verification

1. Both paired windows fall below their multiplier and alerts resolve.
2. The 30-day good ratio and budget-remaining panels stabilize after expected window lag.
3. The underlying application/infrastructure verification steps pass.

