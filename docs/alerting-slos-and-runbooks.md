# Alerting, SLOs, and Runbooks

This guide defines the local production-oriented alerting pipeline, service-level
indicators, 30-day objectives, multi-window burn alerts, and operator response.
Prometheus owns recording/alerting rules; Alertmanager owns grouping, inhibition,
and routing. Grafana-managed alerts are intentionally not provisioned, avoiding
two alert sources for the same condition.

## Architecture

```text
backend / worker / exporters / platform services
                        │
                        ▼
Prometheus ── recording rules ── SLI + burn-rate series
     │
     ├── alerting rules ──► Alertmanager ──► local null receivers
     │                            │
     └────────────────────────────┴──► Grafana dashboards
```

Alertmanager 0.32.1 binds to `127.0.0.1:9093`, stores local state in the
`alertmanager-data` volume for 120 hours, and has no email, chat, incident, or
webhook integration. Its empty severity-specific receivers make alerts visible
and testable without sending external notifications. Prometheus retains 30 days
of local samples in `prometheus-data` so the objective window can be evaluated.

## SLI and SLO definitions

All ratios aggregate only over bounded `service` and `environment` labels.
Counter resets are handled by `rate`. An observed zero-traffic interval has zero
bad-event ratio; scrape availability alerts separately detect missing targets.

| SLO | Good events | Eligible / total events | 30-day objective | Error budget |
| --- | --- | --- | ---: | ---: |
| API availability | Completed HTTP responses that are not 5xx | Instrumented HTTP responses | 99.9% | 0.1% |
| API latency | Instrumented requests in the histogram bucket `le="0.5"` | Instrumented request-duration observations | 99% | 1% |
| Background job success | Known Dramatiq actor attempts ending `completed` | Attempts ending `completed` or `failed` | 99% | 1% |
| Training success | Terminally completed training jobs | Completed plus terminally failed training jobs | 95% | 5% |
| Monitoring success | Evaluations ending in a business status other than `failed` | All completed/failed monitoring evaluation attempts | 99% | 1% |

API instrumentation excludes `/metrics`, `/health`, `/docs`, `/openapi.json`,
and `/redoc`. It labels normalized route templates, never raw request paths.
Client 4xx responses are eligible availability events and count as available;
they can still be investigated from status panels when unexpected.

The background denominator uses `background_jobs_processed_total`, whose
cardinality is bounded to the seven existing actor names and terminal statuses
`completed`, `failed`, and `skipped`. Skipped messages are excluded because no
business execution occurred. The older `background_job_failures_total` remains
unchanged for compatibility.

Monitoring statuses such as `healthy`, `warning`, `critical`, and `unavailable`
are successful workflow executions; only `failed` is an operational failure.
Retraining `blocked_*` decisions are valid governance outcomes, not failures.
The current retraining counters observe created and blocked decisions but not
every execution exception, so retraining operational health uses the bounded
`retraining_reconciliation` actor outcome as a proxy. This limitation must be
addressed before claiming an independent retraining-execution SLO.

## Recording rules

`infrastructure/observability/prometheus/rules/sli-recording-rules.yml` creates
stable series for 5m, 30m, 1h, 2h, 6h, 1d, 3d, and 30d windows:

```promql
slo:http_availability:error_ratio_rate5m
slo:http_availability:burn_rate1h
slo:http_availability:good_ratio30d
slo:http_availability:error_budget_remaining_ratio30d
```

The same suffixes exist for `http_latency`, `background_job_success`,
`training_success`, and `monitoring_success`. Burn rate is the observed bad-event
ratio divided by the SLO's error-budget fraction. A burn rate of `1` is exactly
sustainable over 30 days; `14.4` consumes budget 14.4 times faster.

A new installation needs traffic and elapsed time before a 30-day value truly
represents 30 days. Prometheus evaluates over the samples available within the
range. Treat the first 30 days as warm-up and retain the volume across container
replacement.

## Multi-window burn strategy

An alert fires only when both its short and long window exceed the same
multiplier. This reduces noise from isolated spikes while catching rapid budget
loss.

| Tier | Paired windows | Multiplier | Severity | Purpose |
| --- | --- | ---: | --- | --- |
| Fast | 5m and 1h | 14.4x | critical | Immediate response |
| Medium | 30m and 6h | 6x | warning | Sustained incident |
| Slow | 2h and 1d | 3x | warning | Long degradation |
| Ticket | 6h and 3d | 1x | info | Budget-consuming follow-up |

Every primary SLO has all four tiers. Critical alerts inhibit warning/info
notifications for the same `service` and `slo`; warning alerts inhibit info.
Alerts remain queryable even when their receiver notification is inhibited.

## Alert catalog

Rule files under `infrastructure/observability/prometheus/rules/` contain:

- API error and latency degradation, background actor failure bursts, terminal
  training failures, and monitoring/retraining orchestration failures.
- Backend, worker, exporter, and cAdvisor target availability.
- Alertmanager, Loki, Tempo, and Grafana target/config health, plus Prometheus
  rule-evaluation and alert-delivery failures.
- PostgreSQL connection utilization and Redis memory utilization when Redis has
  an explicit non-zero `maxmemory`.
- CPU and memory pressure only for Compose containers with confirmed non-zero
  quotas/limits. Containers without limits do not produce those alerts.

No restart-loop alert is defined: cAdvisor in this topology exposes current
container lifecycle data but no reliable restart counter. No disk alert is
invented without an appropriate filesystem metric.

Every alert has bounded `severity`, `service`, `component`, `team`, and `slo`
labels plus summary, description, runbook, and dashboard annotations. Never add
tenant IDs, users, job/model IDs, raw paths, exception text, query values,
credentials, or payload data to alert labels or annotations.

## Routing and inhibition

Alertmanager groups by `alertname`, `service`, and `severity`. Critical,
warning, and info routes use separate empty local receivers; unmatched alerts
use `local-null`. `group_wait` is 30 seconds, `group_interval` is five minutes,
and `repeat_interval` is 12 hours. These settings exercise realistic grouping
while intentionally producing no external notification.

To add a real receiver later, use secret management, TLS, receiver ownership,
and a reviewed escalation policy. Do not put credentials directly in
`alertmanager.yml` or `.env.example`.

## Dashboards

- **SLO Overview** (`slo-overview`) shows each 30-day good ratio, budget
  remaining, and short/long burn series.
- **Alerting Overview** (`alerting-overview`) shows firing/pending alerts,
  Alertmanager target health, rule evaluation failures, delivery errors, and
  observability target health.

Every Prometheus panel and target explicitly uses datasource UID `prometheus`.
Existing dashboard and datasource UIDs remain unchanged.

## Local operation and validation

```bash
docker compose config -q
docker compose up -d --no-deps --force-recreate alertmanager prometheus grafana
curl --fail http://localhost:9093/-/healthy
curl --fail http://localhost:9090/-/ready
curl --fail http://localhost:3000/api/health
docker compose exec prometheus promtool check config /etc/prometheus/prometheus.yml
docker compose exec prometheus promtool check rules /etc/prometheus/rules/*.yml
docker compose exec alertmanager amtool check-config /etc/alertmanager/alertmanager.yml
```

Useful APIs:

```text
http://localhost:9090/api/v1/targets
http://localhost:9090/api/v1/rules
http://localhost:9090/api/v1/alertmanagers
http://localhost:9093/api/v2/status
http://localhost:9093/api/v2/alerts/groups
```

A pipeline test must use a temporary rule with a uniquely named `vector(1)`
alert, reload Prometheus, wait for the alert to fire and appear grouped in
Alertmanager, then remove the file, reload again, and confirm it disappears.
Never leave a permanently firing test rule in the source-controlled rules
directory.

## Adding a new SLO safely

1. Confirm a bounded, monotonic source metric exists and identify its exact
   labels in live exposition. Add instrumentation only when no truthful
   numerator/denominator can be formed, and test its failure isolation.
2. Write down the user outcome, good events, total eligible events, exclusions,
   objective, window, and known blind spots before writing PromQL.
3. Add error-ratio and burn-rate recordings for every standard window plus the
   30-day good ratio and clamped budget remaining. Define zero-traffic behavior.
4. Add all four paired-window alerts with bounded ownership labels, a valid
   dashboard UID, and an existing runbook. Avoid overlapping duplicate alerts.
5. Add dashboard panels with explicit datasource UID `prometheus`, update the
   runbook index, and extend uniqueness/cardinality/link contract tests.
6. Run promtool syntax and rule unit tests, amtool, Python quality gates,
   Compose validation, and live query evaluation. Use a temporary pipeline alert
   and remove it completely after Alertmanager exposure is confirmed.
7. Observe a baseline before changing an objective or multiplier. Treat such a
   change as a reviewed reliability-policy decision, not incident mitigation.

## Runbook index

- [API high error rate](runbooks/api-high-error-rate.md)
- [API latency degradation](runbooks/api-latency-degradation.md)
- [Backend down](runbooks/backend-down.md)
- [Worker down](runbooks/worker-down.md)
- [Background job failures](runbooks/background-job-failures.md)
- [Training failures](runbooks/training-failures.md)
- [Monitoring and retraining failures](runbooks/monitoring-retraining-failures.md)
- [PostgreSQL issues](runbooks/postgres-issues.md)
- [Redis issues](runbooks/redis-issues.md)
- [Loki down](runbooks/loki-down.md)
- [Tempo down](runbooks/tempo-down.md)
- [Grafana down](runbooks/grafana-down.md)
- [Alertmanager down](runbooks/alertmanager-down.md)
- [SLO burn rate](runbooks/slo-burn-rate.md)
- [Container resource pressure](runbooks/container-resource-pressure.md)

## Production limitations

This remains a single-node local topology: Prometheus and Alertmanager are not
HA, endpoints have no TLS/authentication, receivers are null, and storage uses
local named volumes. Production deployment needs redundant Prometheus and
Alertmanager instances, durable remote storage, authenticated service networks,
secret-managed receivers, tested on-call ownership, capacity planning, and
regular alert/runbook exercises. Preserve the privacy and bounded-cardinality
contracts during that transition.
