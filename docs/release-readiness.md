# Release readiness operations

This runbook complements the detailed production deployment, observability, backup,
and HTTPS guides. It does not replace environment-specific change control.

## Environment boundaries

- **Local:** use `docker compose up`; HTTP and API documentation may be enabled.
- **Staging:** mirror production topology and secret injection, use isolated data and
  test-only accounts, and run browser and production smoke checks before promotion.
- **Production:** use the production Compose overlay, HTTPS reverse proxy, externally
  injected secrets, explicit CORS origins, disabled API documentation, managed backups,
  and the read-only smoke defaults described below.

Never commit environment files. Set a unique `SECRET_KEY`, PostgreSQL and Grafana
credentials, JWT issuer/audience, `REDIS_URL`, public domain/HTTPS values,
`VITE_API_BASE_URL`, and an exact JSON `CORS_ALLOWED_ORIGINS` list through the deployment
secret mechanism. Do not use a localhost frontend API fallback in a production build.

## Startup and dependency checks

1. Validate both Compose layers with `docker compose -f docker-compose.yml -f
docker-compose.prod.yml config -q`.
2. Take and verify a database backup.
3. Run Alembic upgrade before accepting traffic. A migration failure must stop the
   release; do not start the API against a partially migrated schema.
4. Start PostgreSQL, Redis, the API, training worker, frontend, and reverse proxy.
5. Treat `/health` as process liveness and `/ready` as synchronous database readiness.
   `/operational-status` reports sanitized database, Redis, queue, and expiring real
   training-worker heartbeat states. The API can serve database-backed reads during an
   asynchronous dependency outage, but new queued work is rejected safely.
6. Run `scripts/verify-production.sh` and then the external smoke test.

The worker records a category-only Redis heartbeat every
`WORKER_HEARTBEAT_INTERVAL_SECONDS`; it expires after `WORKER_HEARTBEAT_TTL_SECONDS`.
No hostname, process identifier, container identifier, or connection detail is stored.
Confirm both the heartbeat and queue metrics before accepting asynchronous mutations.

## Browser E2E

From `frontend/`:

```bash
npm ci
npx playwright install chromium
npm run test:e2e
```

`E2E_BASE_URL` selects the frontend URL. Set `E2E_EXTERNAL_SERVER=1` and
`E2E_REAL_BACKEND=true` for the isolated staging runtime. `scripts/staging-local.sh`
starts production images, runs migrations, and can idempotently seed environment-provided
admin, engineer, and operator credentials plus the bounded demo workflow. Fixture tests
remain for refresh races and deterministic client edge cases.

## Read-only production smoke

```bash
BASE_URL=https://staging.example \
SMOKE_EMAIL='staging-smoke@example.invalid' \
SMOKE_PASSWORD='injected-by-secret-store' \
scripts/smoke-production.sh
```

The script checks health, readiness, the expected docs status, login, current user, one
bounded hierarchy read, and logout. It never prints tokens or credentials. Set
`SMOKE_DOCS_EXPECTED_STATUS` only when the environment intentionally exposes docs.
Prediction is disabled by default because it writes a prediction event. Enable it only
for an approved test model with `SMOKE_ENABLE_PREDICTION=true`, `SMOKE_MODEL_NAME`,
`SMOKE_MODEL_VERSION`, and `SMOKE_FEATURE_MATRIX_JSON`.

## Backup, restore, migrations, and rollback

Use `scripts/backup-postgres.sh`; it writes a timestamped custom-format archive and
SHA-256 sidecar without overwriting an existing archive. Verify an archive in a
disposable PostgreSQL container with `scripts/verify-postgres-backup.sh BACKUP_FILE`.
See [backups and disaster recovery](backups-and-disaster-recovery.md) for restore steps.

Application rollback and database rollback are separate decisions. Prefer rolling the
application back to a version compatible with the migrated schema. Never assume Alembic
downgrades are lossless: inspect the release migrations first. If a migration is
irreversible or has transformed data, restore a verified pre-release backup into a new
database and switch only after validation. See the [release checklist](release-checklist.md)
and the production deployment guide for the controlled sequence.

## Security and incident checks

- Keep `script-src 'self'`, `object-src 'none'`, and `frame-ancestors 'none'` in CSP.
  `style-src 'unsafe-inline'` remains narrowly required by current React runtime style
  attributes; removing it without replacing those attributes breaks theme behavior.
- HTML must not be cached as immutable. Hashed assets may use long-lived immutable cache
  headers. Production source maps and debug banners must remain absent.
- Authentication endpoints have distributed Redis-backed limits. Sensitive prediction,
  upload, training, promotion, evaluation, alert, and retraining mutations use a
  per-user/per-endpoint Redis limit controlled by `MUTATION_RATE_LIMIT_*`. Authentication
  retains its availability-oriented failure behavior; authenticated sensitive mutations
  fail closed with a sanitized 503 if Redis is unavailable.
- Partial audit coverage must remain labelled as partial. Domain promotion and retraining
  records are persisted; security events are available in structured server logs.
- During an incident, inspect API, reverse-proxy, Redis, worker, PostgreSQL, queue-depth,
  and observability logs without copying tokens or request bodies into tickets.

For restart, drain traffic, stop accepting asynchronous mutations, stop application
services, retain volumes, apply the documented startup order, wait for readiness, and
rerun smoke checks. Never delete volumes as part of routine shutdown or rollback.
