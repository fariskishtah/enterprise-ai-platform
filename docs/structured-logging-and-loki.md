# Structured Logging and Loki

The backend and Dramatiq worker emit privacy-preserving structured logs to
standard output. Grafana Alloy discovers only containers in this Compose
project, attaches a small bounded label set, and pushes the original log lines to
Loki. Grafana provisions Loki alongside Prometheus and loads two log dashboards.

## Architecture

```text
HTTP request
  └─ validated request/correlation context
       └─ FastAPI JSON stdout ─┐
                              ├─► Alloy ─► Loki filesystem/TSDB ─► Grafana
Dramatiq message options      │
  └─ correlation_id only      │
       └─ worker JSON stdout ─┘
```

The API returns the configured request and correlation headers on normal
responses. Valid incoming values are accepted; invalid or oversized values are
replaced with UUIDs. If no valid correlation ID is supplied, it uses the request
ID. Context variables are always reset after the request, including exceptions.

The worker copies only a validated `correlation_id` into Dramatiq message
options. Retries retain that value. Job arguments, UUIDs, user data, and request
data are not added to message metadata or structured fields. Each of the seven
actors emits fixed-vocabulary started and completed/failed/skipped lifecycle
records with duration and bounded attempt number.

## Configuration

```text
STRUCTURED_LOGGING_ENABLED=true
LOG_FORMAT=json
LOG_LEVEL=INFO
HTTP_ACCESS_LOGGING_ENABLED=true
REQUEST_ID_HEADER=X-Request-ID
CORRELATION_ID_HEADER=X-Correlation-ID
LOG_SERVICE_NAME=ai-manufacturing-backend
LOG_ENVIRONMENT=local
LOKI_PORT=3100
ALLOY_PORT=12345
```

`LOG_FORMAT` accepts `json` or `text`; `LOG_LEVEL` accepts `DEBUG`, `INFO`,
`WARNING`, `ERROR`, or `CRITICAL`. Header names, service names, and environment
values are validated at startup. Container defaults use JSON. Setting
`STRUCTURED_LOGGING_ENABLED=false` selects the safe text formatter.

The application emits one `http_request_completed` record after each request,
using the matched route template rather than the raw path. `/metrics`, `/health`,
`/docs`, and `/openapi.json` are excluded. Uvicorn's raw access logger is always
disabled, preventing duplicate or unnormalized request lines; disabling
`HTTP_ACCESS_LOGGING_ENABLED` therefore disables HTTP access logs entirely.

## Log schema and privacy contract

Every JSON line includes:

```text
timestamp level logger message service environment
request_id correlation_id trace_id
```

`trace_id` is populated when an active OpenTelemetry span has a valid trace context and
is otherwise `null`. Records add only relevant allowlisted fields:

```text
method normalized_route status_code duration_ms
job_name task_type algorithm trigger alert_type severity
lifecycle_status attempt_number error_kind
```

The formatter ignores arbitrary record extras. It redacts credentials, bearer
tokens, cookies, common secret assignments, URL credentials, emails, UUIDs, and
named feature/prediction/body/artifact payloads from messages. Exception output
contains the exception type and a bounded list of filename/function/line frames;
it does not include the exception value, local variables, or source code.

Application logging must never add authorization headers, cookies, request
bodies, raw feature values, raw predictions, model artifacts, emails, user or
tenant identifiers, registered model identities, or arbitrary exception text.
Logging failures are swallowed so they cannot change an HTTP or background-job
business result.

## Loki and Alloy

Loki runs as a single local binary with TSDB schema v13, filesystem object
storage, in-memory ring state, and seven-day retention in the `loki-data` volume.
The compactor enforces retention. This topology is for local development, not
high availability.

Alloy stores Docker tail positions in `alloy-data`. Its discovery filter accepts
only containers bearing this Compose project label. After relabeling,
`stage.label_keep` enforces exactly four Loki stream labels:

- `service`: bounded Compose service name.
- `container`: bounded Compose container name.
- `environment`: configured deployment environment.
- `stream`: the constant `docker`.

Request IDs, correlation IDs, levels, routes, statuses, job names, and all other
fields remain inside the JSON body and are extracted with `| json` at query time.
Never promote them to labels. Alloy needs only its config, persistent data, and
the read-only Docker socket; it does not mount Docker's storage directory and is
not privileged.

## Local startup and validation

```bash
docker compose config -q
docker compose up --build -d
docker compose ps
curl --fail http://localhost:3100/ready
curl --fail http://localhost:12345/-/ready
curl --fail http://localhost:3000/api/health
```

Validate source-controlled configs directly:

```bash
docker run --rm \
  -v "$PWD/infrastructure/observability/loki/loki-config.yml:/etc/loki/config.yml:ro" \
  grafana/loki:3.7.3 \
  -config.file=/etc/loki/config.yml -verify-config=true

docker run --rm \
  -e COMPOSE_PROJECT_NAME=ai-manufacturing-platform \
  -e LOG_ENVIRONMENT=local \
  -v "$PWD/infrastructure/observability/alloy/config.alloy:/etc/alloy/config.alloy:ro" \
  -v /var/run/docker.sock:/var/run/docker.sock:ro \
  grafana/alloy:v1.17.1 validate /etc/alloy/config.alloy
```

## Query examples

All queries start with bounded stream labels and parse fields from the body:

```logql
{service="backend",environment="local"} | json | __error__=""
```

Find a request without labeling by ID:

```logql
{service="backend",environment="local"}
  | json | __error__=""
  | request_id="example-request-id"
```

Follow one correlation across API and worker containers:

```logql
{service=~"backend|training-worker",environment="local"}
  | json | __error__=""
  | correlation_id="example-correlation-id"
```

Count errors by bounded service label:

```logql
sum by (service) (
  count_over_time(
    {service=~"backend|training-worker",environment="local"}
      | json | __error__="" | level=~"ERROR|CRITICAL" [5m]
  )
)
```

Grafana's **Logs Overview** dashboard provides service volume, warning/error
counts, HTTP completions, worker lifecycle, and monitoring/retraining failure
views. **Request Correlation** accepts request-ID and correlation-ID regular
expressions as body-field filters.

Dashboard selectors always include `stream="docker"` as a non-empty equality
matcher. Loki rejects selectors made only from All-compatible regular
expressions such as `{service=~".*",environment=~".*"}`. Service and environment
dashboard variables therefore use explicit regex interpolation while the
constant stream matcher keeps the All selection valid.

## Troubleshooting

```bash
docker compose ps
docker compose logs loki alloy grafana
curl --fail http://localhost:3100/ready
curl --fail http://localhost:3100/loki/api/v1/labels
curl --fail http://localhost:12345/-/ready
```

If Loki is ready but no logs arrive, inspect Alloy logs, verify the Compose
project label matches `COMPOSE_PROJECT_NAME`, confirm the Docker socket mount is
readable, and check that Alloy's Loki write endpoint reports no errors. If a
dashboard is missing, inspect Grafana provisioning logs and confirm the Loki
datasource health through `/api/datasources/uid/loki/health` while authenticated.

If JSON parsing reports errors, inspect the raw stream. Application containers
should emit JSON; infrastructure containers may emit text and are intentionally
still collected. Dashboard queries use `__error__=""` when they require parsed
fields.

## Security and production hardening

Loki and Alloy bind only to `127.0.0.1` locally. The Docker socket grants broad
read visibility into container metadata and logs even when mounted read-only;
keep Alloy isolated and never expose its API publicly. Logs must be treated as
sensitive operational data, access-controlled, encrypted in transit and at
rest, and governed by retention and deletion policy.

For production, replace the single-binary filesystem topology with a supported
durable object store and an appropriately scaled Loki deployment. Use tenant
isolation where required, authenticated gateways, TLS, secret-managed Grafana
credentials, monitored ingestion limits, backups where appropriate, and alerts
for dropped logs, write failures, and storage pressure. Review retention against
legal requirements before deployment. Keep the four-label policy and perform
privacy sampling as part of release verification.
