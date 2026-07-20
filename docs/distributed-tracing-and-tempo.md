# Distributed Tracing and Tempo

The local platform exports privacy-preserving OpenTelemetry traces from the
FastAPI backend and Dramatiq worker to a pinned, single-binary Grafana Tempo
service. Grafana provisions Tempo with fixed UID `tempo` and connects traces to
the existing Loki UID `loki` and Prometheus UID `prometheus`.

## Architecture

```text
HTTP client
  -> FastAPI SERVER span
     -> training/prediction/monitoring/promotion/retraining span
        -> SQLAlchemy CLIENT spans
        -> Dramatiq PRODUCER span
           -> Redis CLIENT span
           -> message.options["otel_trace_context"]
              -> Dramatiq CONSUMER span
                 -> worker business span
                    -> SQLAlchemy CLIENT spans
  -> OTLP/gRPC :4317 -> Tempo -> Grafana

JSON stdout -> Alloy -> Loki <- trace_id links -> Tempo
Prometheus metrics <-------------------------- trace-to-metrics links
```

`app/observability/tracing.py` owns process-local provider construction, resource
attributes, sampling, OTLP export, controlled ASGI server spans, safe domain
spans, and client-library instrumentation. The backend initializes tracing after
logging and before accepting requests. Dramatiq initializes its provider in each
worker process after fork so the batch exporter does not inherit a dead worker
thread.

Tempo stores blocks, its WAL, and local TraceQL-metrics data in the persistent
`tempo-data` volume. It accepts OTLP gRPC on the internal Compose port `4317` and
OTLP HTTP on `4318`; only its query/readiness port `3200` is bound to localhost.

## Identity and propagation

The three identifiers have separate purposes:

- `request_id` identifies one HTTP exchange and is returned in
  `X-Request-ID`. It is not tracing context.
- `correlation_id` is a business/log correlation value that may continue into a
  background job. It is returned in `X-Correlation-ID` and kept in the existing
  Dramatiq option.
- `trace_id` is the 32-character lowercase OpenTelemetry trace identity. It is
  read only from the active span and is never synthesized from either other ID.

The producer creates a `PRODUCER` span, injects only W3C `traceparent` and
optional `tracestate`, and stores those strings in the bounded reserved
`otel_trace_context` message option. The consumer validates and extracts that
carrier, starts a `CONSUMER` span with the extracted remote parent, activates it
for the actor, and always detaches and ends it. Retry enqueue preserves an
already-valid carrier, so a retry remains linked to the original producer rather
than acquiring an unrelated ambient parent. Invalid carriers safely produce a
new root consumer span.

All existing actors receive consumer and business spans: training, scheduled
monitoring, both retention jobs, reference-profile reconciliation, retraining
reconciliation, and stale-alert reconciliation.

## Instrumentation and privacy

HTTP span names use method plus FastAPI route template, for example
`POST /ai/training-jobs/random-forest/regression`. The middleware never places a
raw path, query string, request/response body, or arbitrary header in a span.
`/health`, `/metrics`, `/docs`, `/openapi.json`, and `/redoc` are excluded.

SQLAlchemy instruments async engines without SQL comments or parameter values.
The underlying driver continues to use bind parameters. Redis command arguments
are replaced by `?`; Redis Search query/index enrichments are disabled. Resource
attributes are limited to service name, service namespace, service version, and
deployment environment.

Manual span attributes use a fixed vocabulary of bounded categories such as
algorithm, task type, lifecycle status, trigger, alert type, severity, and
outcome. The implementation never adds user IDs, emails, UUIDs, model names,
request payloads, database payloads, feature/prediction values, credentials,
authorization/cookie headers, Redis values, SQL parameters, or exception values.
Error spans record only a bounded exception type and error status.

Loki labels remain exactly the existing bounded Docker label set: `service`,
`container`, `environment`, and `stream`. `trace_id`, `span_id`, `request_id`,
`correlation_id`, routes, model names, and job IDs are JSON fields, never Loki
labels.

## Configuration

Defaults are suitable for the local Compose network:

```text
TRACING_ENABLED=true
OTEL_SERVICE_NAME=ai-manufacturing-backend
OTEL_WORKER_SERVICE_NAME=ai-manufacturing-training-worker
OTEL_SERVICE_NAMESPACE=ai-manufacturing-platform
OTEL_ENVIRONMENT=local
OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317
OTEL_EXPORTER_OTLP_INSECURE=true
OTEL_TRACES_SAMPLER=parentbased_traceidratio
OTEL_TRACES_SAMPLER_ARG=1.0
TEMPO_PORT=3200
```

`OTEL_TRACES_SAMPLER_ARG` accepts a ratio from `0.0` through `1.0`. Parent-based
sampling means a valid incoming sampling decision is honored, including across
Dramatiq. A root span without a parent uses the configured ratio. Local
development uses `1.0` so short manual flows are observable. Production should
choose a capacity-tested ratio and keep the parent-based policy to avoid broken
distributed traces.

Disable tracing with `TRACING_ENABLED=false`. This bypasses server middleware,
does not construct the exporter, and leaves JSON `trace_id` as `null` outside
any independently active valid span. Exporter initialization failures are logged
safely and do not prevent application startup.

## Local operation

Start only the tracing-related services and their existing dependencies when the
base stack is already running:

```bash
docker compose up -d --build tempo backend training-worker grafana
```

Useful endpoints:

| Service | URL |
| --- | --- |
| Tempo readiness | <http://localhost:3200/ready> |
| Tempo status | <http://localhost:3200/status> |
| Grafana | <http://localhost:3000> |
| Loki readiness | <http://localhost:3100/ready> |
| Prometheus | <http://localhost:9090> |

Grafana's `Platform Observability` folder includes **Distributed Tracing
Overview** and **Trace Correlation**. The overview uses TraceQL metrics for rate,
errors, latency percentiles, and service grouping, plus recent/slow trace tables.
The correlation dashboard searches backend-to-worker structure, consumer and
producer spans, client spans, and errors.

From a trace, use the trace-to-logs action to run the provisioned Loki query on
the parsed JSON `trace_id`. From a Loki log detail, use the `TraceID` derived
field to open the exact trace in Tempo. Trace-to-metrics actions map
`service.name` to the existing Prometheus `service` label.

API-only verification without a browser:

```bash
curl --fail http://localhost:3200/ready
curl --fail -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" \
  http://localhost:3000/api/datasources/uid/tempo/health
curl --fail 'http://localhost:3200/api/search?q=%7B%7D&limit=20'
```

Do not paste credentials into shell history in a shared environment. Prefer a
protected credential file or secret manager beyond disposable local use.

## Troubleshooting

Validate configuration before startup:

```bash
docker compose config -q
docker run --rm \
  -v "$PWD/infrastructure/observability/tempo/tempo.yml:/etc/tempo/tempo.yml:ro" \
  grafana/tempo:2.10.5 \
  -config.file=/etc/tempo/tempo.yml -config.verify=true
```

If Tempo has no traces, check `/ready`, then inspect safe backend/worker logs for
export initialization or OTLP delivery errors. Confirm the endpoint is
`http://tempo:4317` inside Compose rather than `localhost`. The batch processor
can take several seconds to flush.

If an API trace has no worker spans, confirm the request actually enqueued a
Dramatiq job, inspect the worker lifecycle log with the same `correlation_id`,
and query the exact backend `trace_id`. A retry intentionally retains its
original `otel_trace_context`.

If TraceQL metric panels are empty while trace search works, allow an ingester
block to become queryable, widen the time range, and inspect Tempo logs. Local
blocks are enabled for TraceQL metrics; service-graph metrics are not remote
written to Prometheus, so a cross-service service-map view is intentionally not
provisioned.

## Production limitations

The Compose deployment is a local single-binary topology. It has no Tempo
multitenancy, authentication, TLS, object storage, replicas, autoscaling,
cross-zone durability, collector/gateway tier, tail sampling, or trace-specific
retention policies by tenant. The application sends OTLP directly to Tempo and
uses an insecure internal connection. For production, deploy an authenticated
TLS OpenTelemetry Collector tier, apply memory/batch/retry controls, use durable
object storage and HA Tempo components, enforce tenant boundaries and network
policy, monitor exporter drops and ingestion limits, and derive sampling and
retention from measured capacity and compliance requirements.

References:

- <https://opentelemetry.io/docs/languages/python/>
- <https://grafana.com/docs/tempo/latest/>
- <https://grafana.com/docs/grafana/latest/datasources/tempo/>
