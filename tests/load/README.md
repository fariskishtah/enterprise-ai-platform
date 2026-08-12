# Release-candidate load acceptance

These profiles are bounded to loopback targets in `acceptance.js`. Use the
disposable seeded staging stack, whose email and payment providers are disabled
and whose RAG implementation is deterministic/local.

```bash
export E2E_ADMIN_EMAIL='admin@load-validation.invalid'
export E2E_ENGINEER_EMAIL='engineer@load-validation.invalid'
export E2E_OPERATOR_EMAIL='operator@load-validation.invalid'
export E2E_SMOKE_EMAIL='smoke@load-validation.invalid'
export E2E_PASSWORD='<generated-disposable-password>'
./scripts/staging-local.sh start
./scripts/staging-local.sh seed

export BASE_URL='http://127.0.0.1:18080/api'
export TEST_EMAIL="$E2E_ADMIN_EMAIL"
export TEST_PASSWORD="$E2E_PASSWORD"
export RAG_LOAD_USER_COUNT=50
export RAG_LOAD_EMAIL_PREFIX=phase5-rag
export RAG_LOAD_EMAIL_DOMAIN=example.com
for profile in smoke normal stress spike soak; do
  ACCEPTANCE_PROFILE="$profile" ./scripts/run-load-tests.sh acceptance
done
```

Raw summaries are written to the ignored `artifacts/load-runs/` directory.
Before and after the profiles, record Docker stats/restarts, PostgreSQL
connections and slow activity, Redis memory/clients, Dramatiq queue depth, and
Prometheus target/alert state. Publish only aggregated, non-sensitive evidence.

## Phase 5 capacity profiles

`capacity.js` is read-only and excludes health/readiness traffic from capacity
claims. It supports only the progressive concurrency steps `10`, `25`, `50`,
`100`, `250`, and `500`, with API, authentication, database-heavy, RAG, and
mixed workloads. Each step defaults to 30 seconds and aborts after a sustained
error/check rate above 2%, p95 above 1 second, or p99 above 2.5 seconds.

Run one workload and one level at a time. Proceed only after reviewing the k6
summary and infrastructure measurements from the previous level:

```bash
export BASE_URL='http://127.0.0.1:18080/api'
export TEST_EMAIL="$E2E_ADMIN_EMAIL"
export TEST_PASSWORD="$E2E_PASSWORD"
export RAG_TEST_EMAIL="$E2E_ENGINEER_EMAIL"
export RAG_TEST_PASSWORD="$E2E_PASSWORD"

for users in 10 25 50 100 250 500; do
  CAPACITY_WORKLOAD=mixed CAPACITY_VUS="$users" \
    ./scripts/run-load-tests.sh capacity
  # Stop here unless errors, latency, health, DB, Redis, queue, CPU, memory,
  # and disk headroom remain within the documented thresholds.
done
```

Do not run all levels unattended. The seed command creates an idempotent,
owner-isolated RAG identity/knowledge-base fixture for each configured load
user; the capacity harness never disables the real rate limiter. Setup and
teardown traffic are tagged separately and excluded from steady-state capacity
thresholds. Authentication profiles perform one login/refresh/logout cycle per
virtual user so a local benchmark does not become a synthetic brute-force loop.

Document ingestion is a separate, explicitly enabled single-job scenario. It
creates one synthetic document dataset and knowledge base in the disposable
staging project, waits for parsing and indexing, and never calls an external AI
or payment provider:

```bash
ENABLE_DOCUMENT_INGESTION_LOAD=true \
DOCUMENT_LOAD_RUN_ID=phase5-local-001 \
./scripts/run-load-tests.sh document-ingest
```

The existing `training` scenario remains the bounded background-worker check.
It submits at most three three-tree local jobs and must not be expanded into an
expensive model-training load.

## Local disk safety

Keep 40 GiB free as the warning threshold and do not start the isolated stack
below 30 GiB free. Low-risk recurring cleanup is limited to tool caches:

```bash
python3 -m pip cache purge
npm cache clean --force
uv cache clean
go clean -cache
```

Review Homebrew downloads, Hugging Face caches, Playwright browsers, Docker
build cache, images, stopped containers, and any project-local artifacts before
removal. Never automate removal of Docker volumes, database/Redis storage,
repository files, credentials, protected screenshots, or `BILLING_AUDIT.md`.
List exact Docker objects before any object cleanup; do not use an unscoped
`docker system prune -a`.
