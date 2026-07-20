# Performance and Load Testing

This runbook covers the bounded local k6 scenarios in `performance/k6/`. They
exercise API latency, throughput, and error rate without running an
unbounded workload. Run them only against a local or otherwise explicitly
authorized environment. The defaults are deliberately small and are not a
production capacity target.

The suite uses `GET /health` and `GET /metrics`, optionally authenticates with
`POST /auth/login`, and exercises the protected `GET /factories` read when test
credentials are supplied. Authentication load covers a successful login when
credentials are supplied and always checks an expected invalid-credentials
response.
The separate training scenario creates a small deterministic Random Forest
regression job and polls its status only when explicitly enabled.

## Prerequisites

- Docker with Compose v2; no host k6 installation is required.
- The stack running locally and responding at `http://localhost:8000/health`.
- A dedicated, non-production test account for protected or training requests.
  Put `TEST_EMAIL` and `TEST_PASSWORD` in the current
  shell or a local secret manager; never add them to commands, scripts, result
  files, or source control.
- Run every command below from the repository root.

Start the dependencies and backend, then create the gitignored result directory:

```bash
docker compose up -d postgres redis backend training-worker
curl --fail http://localhost:8000/health
mkdir -p performance/results
```

The commands use `host.docker.internal` so a k6 container can reach the backend
port published by Compose. `--add-host=host.docker.internal:host-gateway` also
provides that name on current Linux Docker Engine installations.

## Smoke test

The smoke test runs one virtual user for 10 seconds by default and can never run
for more than 30 seconds or two VUs. It checks health and the public Prometheus
metrics endpoint. If both credential variables are present, it logs in once
during setup and also checks `/factories` without printing the password or token.

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --add-host=host.docker.internal:host-gateway \
  --env BASE_URL=http://host.docker.internal:8000 \
  --env TEST_EMAIL \
  --env TEST_PASSWORD \
  --volume "$PWD/performance/k6:/scripts:ro" \
  --volume "$PWD/performance/results:/results" \
  grafana/k6:2.1.0 \
  run --summary-export=/results/smoke-summary.json /scripts/smoke.js
```

Credentials are optional for this command. An absent pair skips the protected
check; supplying only one value is a configuration error.

## Representative API load

The API scenario uses 3 virtual users by default: a 5-second warm-up, 20-second
steady interval, and 5-second cool-down. Each iteration sleeps for 0.5 seconds.
It measures health for every run and includes `/factories` when both test
credentials are available.

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --add-host=host.docker.internal:host-gateway \
  --env BASE_URL=http://host.docker.internal:8000 \
  --env TEST_EMAIL \
  --env TEST_PASSWORD \
  --volume "$PWD/performance/k6:/scripts:ro" \
  --volume "$PWD/performance/results:/results" \
  grafana/k6:2.1.0 \
  run --summary-export=/results/api-load-summary.json /scripts/api-load.js
```

## Authentication load

Authentication testing uses one virtual user for two iterations by default and
cannot exceed three iterations. Each iteration sends a deliberately invalid
login and sleeps for 10 seconds; when credentials are supplied, it also logs in
and logs out. A `401` from the invalid login is expected and checked, so it is
not an application failure. Without credentials, the scenario safely exercises
only the failure path.

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --add-host=host.docker.internal:host-gateway \
  --env BASE_URL=http://host.docker.internal:8000 \
  --env TEST_EMAIL \
  --env TEST_PASSWORD \
  --volume "$PWD/performance/k6:/scripts:ro" \
  --volume "$PWD/performance/results:/results" \
  grafana/k6:2.1.0 \
  run --summary-export=/results/auth-load-summary.json /scripts/auth-load.js
```

Do not use this default scenario as a rate-limit or credential-attack test.
Testing the limiter requires separate authorization, an isolated account and
source, and an agreed request budget; it is intentionally not automated here.
Token refresh is not included because rotating refresh tokens under load would
add mutable credential state without improving the representative login signal.

## Opt-in training-job check

This scenario is disabled unless `ENABLE_TRAINING_LOAD=true`. It requires the
test credentials, runs exactly one virtual user, creates one small deterministic
job by default, and polls each job at most six times with a two-second interval.
The executor has a five-minute hard timeout. With the default six polls at a
two-second interval, one job normally spends at most about 12 seconds polling.
There is no safe job-deletion endpoint,
so job metadata and any completed local artifacts remain in the target local
environment; use a disposable development environment when that matters.

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --add-host=host.docker.internal:host-gateway \
  --env BASE_URL=http://host.docker.internal:8000 \
  --env TEST_EMAIL \
  --env TEST_PASSWORD \
  --env ENABLE_TRAINING_LOAD=true \
  --volume "$PWD/performance/k6:/scripts:ro" \
  --volume "$PWD/performance/results:/results" \
  grafana/k6:2.1.0 \
  run --summary-export=/results/training-job-summary.json \
  /scripts/training-job-load.js
```

The deterministic payload is intentionally tiny and requests no large dataset.
The default idempotency key prefix makes repeat runs replay the same local job
instead of creating duplicates. Set `TRAINING_IDEMPOTENCY_KEY` to a new value
only for a deliberate new job. This scenario validates bounded submission/status
behavior, not model-training capacity, and job submission does not use the
lightweight API latency threshold.

## Environment variables and enforced limits

| Variable | Default | Enforced range or behavior |
| --- | --- | --- |
| `BASE_URL` | `http://host.docker.internal:8000` | Target API base URL; use only an authorized environment |
| `ALLOW_REMOTE_TARGET` | unset/false | Non-local targets are refused unless this is explicitly `true` |
| `TEST_EMAIL`, `TEST_PASSWORD` | unset | Optional pair for smoke/API/auth; both required for training |
| `INVALID_TEST_EMAIL`, `INVALID_TEST_PASSWORD` | safe invalid values | Optional auth failure-path inputs; never use a real account |
| `SMOKE_DURATION_SECONDS` | `10` | 1–30 seconds |
| `SMOKE_VUS` | `1` | 1–2 VUs |
| `API_VUS` | `3` | 1–20 VUs |
| `API_WARMUP_SECONDS` | `5` | 1–60 seconds |
| `API_STEADY_SECONDS` | `20` | 1–180 seconds |
| `API_COOLDOWN_SECONDS` | `5` | 1–60 seconds; API total is capped at 300 seconds |
| `API_PAUSE_SECONDS` | `0.5` | 0.1–5 seconds between iterations |
| `AUTH_ITERATIONS` | `2` | 1–3 shared iterations; always 1 VU and a 2-minute executor timeout |
| `AUTH_PAUSE_SECONDS` | `10` | 5–30 seconds after each iteration |
| `ENABLE_TRAINING_LOAD` | unset/false | Must equal `true` before any training job is submitted |
| `TRAINING_JOBS` | `1` | 1–3 shared iterations/jobs; always 1 VU |
| `TRAINING_MAX_POLLS` | `6` | 1–20 bounded status requests per job |
| `TRAINING_POLL_SECONDS` | `2` | 1–5 seconds between polls |
| `TRAINING_IDEMPOTENCY_KEY` | `k6-local-small-regression-v1` | Prefix, at most 120 characters; executor timeout is 5 minutes |

Invalid or out-of-range values fail during script initialization instead of
silently increasing load. The scenarios do not delete volumes, mutate existing
manufacturing records, log secrets, or launch uncontrolled polling.

## Thresholds and interpreting results

All scenarios enforce an HTTP failure rate below 1% and a check pass rate above
99%. Smoke requires p95 below 500 ms for health and factories and below 1 second
for metrics. API load requires global and factories p95 below 500 ms. Auth
success and expected-failure p95 must stay below 1.5 seconds. Training status
p95 must stay below 500 ms; job submission and model execution have no invented
lightweight latency target. The 500 ms boundary aligns with the API latency SLO,
although a short local run is not a 30-day SLO measurement.

The end-of-test summary and `*-summary.json` contain the useful signals:

- `http_reqs` count and rate show achieved throughput, not merely configured
  virtual users.
- `http_req_duration` p50 is the typical response, p95 is the slowest 5% boundary,
  and p99 exposes rarer tail latency. A healthy median can coexist with a poor
  p99, usually indicating contention, cold paths, or local scheduling pauses.
- `http_req_failed` is k6's transport/unexpected-response failure rate. Expected
  invalid-login `401` responses are classified and checked separately.
- `checks` is the application assertion pass rate. Inspect named failed checks
  even when the aggregate HTTP failure threshold passes.

Correlate anomalies with Grafana's backend API dashboard and container resource
panels. A threshold failure can reflect script configuration, laptop CPU/memory
pressure, Docker resource limits, or a real application bottleneck. Reproduce a
failure under controlled conditions before changing application code.

`performance/results/` is gitignored. Summary exports do not intentionally
contain request bodies, passwords, or tokens, but treat them as local operational
data and review them before sharing. Reusing a filename overwrites that result;
choose a timestamped name when retaining multiple runs.

## Longer bounded manual run

For a longer representative check, keep concurrency modest and extend only the
bounded API stages. This example uses 5 VUs for 4 minutes total, below the
script's 5-minute hard ceiling:

```bash
docker run --rm \
  --user "$(id -u):$(id -g)" \
  --add-host=host.docker.internal:host-gateway \
  --env BASE_URL=http://host.docker.internal:8000 \
  --env TEST_EMAIL \
  --env TEST_PASSWORD \
  --env API_VUS=5 \
  --env API_WARMUP_SECONDS=30 \
  --env API_STEADY_SECONDS=180 \
  --env API_COOLDOWN_SECONDS=30 \
  --volume "$PWD/performance/k6:/scripts:ro" \
  --volume "$PWD/performance/results:/results" \
  grafana/k6:2.1.0 \
  run --summary-export=/results/api-load-long-summary.json \
  /scripts/api-load.js
```

Watch backend, PostgreSQL, Redis, the training worker, and Docker resource usage
throughout a longer run and stop on unexpected error growth or resource
exhaustion. Do not turn this into an unattended soak test. Laptop results
include Docker Desktop virtualization, power management, competing processes,
filesystem behavior, and small local datasets; they are useful for regression
comparisons on the same machine, but are not production capacity or scaling
guarantees.

## CI validation

CI uses the same pinned `grafana/k6:2.1.0` image to run `k6 inspect` against the
four entry scripts. Inspection evaluates script structure and options without
starting the application, sending requests, or running load on pull requests.
