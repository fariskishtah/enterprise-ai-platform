# Platform Observability

This phase adds local and production-oriented metrics and logs without changing
API, training, prediction, monitoring, retraining, MLflow, or worker business
behavior. Tempo, OpenTelemetry tracing, Alertmanager, and external alert
delivery are not included. Logging details are in
[Structured logging and Loki](structured-logging-and-loki.md).

## Architecture

```text
FastAPI /metrics ───────────────┐
Dramatiq worker :9191/metrics ──┤
PostgreSQL exporter ────────────┤
Redis exporter ────────────────►│ Prometheus ──► Grafana
cAdvisor ───────────────────────┤
Prometheus self-metrics ────────┘

Backend / worker stdout ──► Alloy ──► Loki ──► Grafana
```

The FastAPI process exposes the required unauthenticated metrics route. The
current Compose worker uses one Dramatiq process and exposes a second metrics
listener only on the internal Compose network. This makes worker-side training
completion and background-failure counters visible without publishing another
host port.

Prometheus scrapes every target at 15-second intervals and stores 15 days of
local data in `prometheus-data`. Grafana stores local state in `grafana-data`,
but its datasource, folder, and dashboards remain source-controlled provisioning
files.

## Local startup and URLs

Copy the example environment if needed, then start the stack:

```bash
cp .env.example .env
docker compose up --build -d
docker compose ps
```

Do not overwrite an existing `.env`; merge only the observability variables you
need. The local endpoints are:

| Service | URL |
| --- | --- |
| Backend metrics | <http://localhost:8000/metrics> |
| Prometheus | <http://localhost:9090> |
| Prometheus targets | <http://localhost:9090/targets> |
| Loki readiness | <http://localhost:3100/ready> |
| Alloy readiness | <http://localhost:12345/-/ready> |
| Grafana | <http://localhost:3000> |

Grafana uses `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD`. The example
password is a placeholder and must be changed anywhere beyond disposable local
development.

Useful health checks:

```bash
curl --fail http://localhost:8000/metrics
curl --fail http://localhost:9090/-/healthy
curl --fail http://localhost:3100/ready
curl --fail http://localhost:12345/-/ready
curl --fail http://localhost:3000/api/health
curl --fail http://localhost:9090/api/v1/targets
```

## Metrics

The HTTP middleware publishes:

- `http_requests_total`
- `http_request_duration_seconds`
- `http_requests_in_progress`

Routes use FastAPI/Starlette templates such as `/companies/{company_id}`. Raw
paths and path parameter values are never labels. `/metrics`, `/health`, `/docs`,
and `/openapi.json` are excluded from request instrumentation.

Bounded application metrics are:

- `training_jobs_submitted_total`
- `training_jobs_completed_total`
- `training_jobs_failed_total`
- `training_job_duration_seconds`
- `prediction_requests_total`
- `prediction_rows_total`
- `prediction_failures_total`
- `monitoring_evaluations_total`
- `monitoring_evaluation_duration_seconds`
- `monitoring_alerts_created_total`
- `monitoring_alerts_resolved_total`
- `retraining_requests_total`
- `retraining_requests_blocked_total`
- `background_job_failures_total`

Metric updates are failure-isolated. A client-library failure is logged with a
fixed metric name and cannot fail the business operation.

## Label-cardinality policy

Allowed labels are limited to service, environment, HTTP method, normalized
route, response status, task type, algorithm, terminal status, alert type,
severity, retraining trigger, and a fixed background-job name.

The instrumentation must never add model names, registered model names, UUIDs,
prediction-event IDs, job IDs, tenant IDs, user IDs, emails, tokens, arbitrary
paths, exception messages, request bodies, feature values, or prediction values
as labels.

## Grafana dashboards

The automatically provisioned `Platform Observability` folder contains:

- **Platform Overview**: backend traffic, 5xx rate, P50/P95/P99 latency,
  in-progress requests, AI job/activity rates, monitoring duration and alerts,
  container CPU/memory, and PostgreSQL/Redis availability.
- **Backend API**: normalized-route request rates, response status breakdown,
  latency percentiles, slowest route templates, and in-progress requests.
- **AI Operations**: training submissions and terminal states, training duration,
  prediction requests/rows/failures, monitoring results and alerts, governed
  retraining requests/blocked decisions, and background actor failures.
- **Logs Overview**: per-service log volume, warnings, errors, normalized HTTP
  completions, worker lifecycles, and monitoring/retraining failures.
- **Request Correlation**: request-ID and correlation-ID text filters across API
  and worker logs without making either identifier a Loki label.

Provisioned dashboards are read-only in the UI. Change the JSON files and
restart Grafana to make durable updates.

## Configuration

```text
OBSERVABILITY_METRICS_ENABLED=true
OBSERVABILITY_METRICS_PATH=/metrics
OBSERVABILITY_SERVICE_NAME=ai-manufacturing-backend
OBSERVABILITY_ENVIRONMENT=local
OBSERVABILITY_WORKER_METRICS_PORT=9191
PROMETHEUS_PORT=9090
LOKI_PORT=3100
ALLOY_PORT=12345
GRAFANA_PORT=3000
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=replace-with-a-local-password
```

Disabling `OBSERVABILITY_METRICS_ENABLED` removes the FastAPI metrics endpoint
and disables custom metric updates and the worker listener. If
`OBSERVABILITY_METRICS_PATH` changes, update the backend `metrics_path` in
`infrastructure/observability/prometheus/prometheus.yml` to match.

## Privacy and security

The metrics endpoint deliberately has no JWT dependency so Prometheus can scrape
it. It exposes process aggregates and fixed labels only; it never reads or emits
request bodies, authorization headers, credentials, raw features, raw
predictions, emails, user IDs, model identities, or stored monitoring reports.

Prometheus, Loki, Alloy, and Grafana host ports bind to `127.0.0.1`. Exporters,
cAdvisor, and worker metrics have internal Compose ports only. PostgreSQL
exporter credentials reuse local database environment variables and are not
written to Prometheus or Grafana provisioning files. Alloy receives a read-only
Docker socket mount to discover this Compose project's logs; do not expose its
HTTP endpoint or reuse that access in an untrusted environment.

## Troubleshooting

Validate configuration and inspect services:

```bash
docker compose config -q
docker compose ps
docker compose logs prometheus loki alloy grafana postgres-exporter redis-exporter cadvisor
docker compose exec prometheus promtool check config /etc/prometheus/prometheus.yml
```

If a Prometheus target is down, inspect `/targets`, verify the target container
is healthy, and curl its internal endpoint from the Prometheus container. If a
dashboard is absent, inspect Grafana logs for datasource or dashboard
provisioning errors. Empty AI panels are expected until the corresponding
operation occurs.

## Current limitations

- The worker listener assumes the current Compose configuration of one Dramatiq
  process. Multiple processes in one container require one port per process or a
  different aggregation design.
- Python counters reset when a process restarts; Prometheus rate functions handle
  normal counter resets.
- cAdvisor visibility depends on the container runtime. Docker Desktop may expose
  fewer host/container details than native Linux.
- The PostgreSQL exporter uses the application database account for local
  convenience.
- There are no alert rules, Alertmanager, traces, SLOs, or external alert
  destinations in this phase.

## Production recommendations

- Keep `/metrics` reachable only from the Prometheus network or an authenticated
  internal ingress even though application JWT is intentionally not required.
- Terminate TLS and use secret-managed Grafana credentials; disable public
  registration and restrict administrative access.
- Give PostgreSQL exporter a dedicated least-privilege monitoring role and use
  its password-file support rather than a plaintext environment value.
- Pin and routinely update exporter, Prometheus, Grafana, and cAdvisor images;
  scan them in CI before promotion.
- Use durable monitored storage, retention sized for capacity, backup Grafana
  state where UI-managed content is allowed, and deploy Prometheus/Grafana
  outside the application failure domain.
- Add recording/alerting rules and SLOs only after baseline traffic and latency
  distributions are understood.

The implementation uses the official Prometheus Python client and Grafana file
provisioning conventions:

- <https://prometheus.github.io/client_python/>
- <https://grafana.com/docs/grafana/latest/administration/provisioning/>
