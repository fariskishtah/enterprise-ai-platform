# FactoryMind production runbook

Last reviewed: 2026-08-12

Scope: single-host AWS production at <https://factorymind.ddnsgeek.com>

Expected migration: `0033_billing_phase2_contracts`

Approved initial envelope: 1–20 users; one actively executing training job
Payment invariant: `PAYMENT_PROVIDER=disabled`

This runbook is for authorized operators. Use `ssh factorymind-aws`, work from the production repository root, and use the existing untracked `.env.production` without displaying it. Never paste secrets into commands, logs, tickets, or chat. Never run `docker compose down`, remove production volumes, downgrade migrations, or restore over the live database.

## Command convention

Where this document says `compose`, use the production stack explicitly:

```bash
docker compose --project-name ai-manufacturing-platform \
  --env-file .env.production \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.https.yml
```

Do not rely on whichever Compose files happen to be in a shell variable or history. Before any change, record UTC time, incident/change ID, current Git revision, current migration, service state, and rollback revision without printing environment values.

## 1. Routine health check

Read-only checks:

```bash
curl --fail --silent --show-error https://factorymind.ddnsgeek.com/healthz >/dev/null
curl --fail --silent --show-error https://factorymind.ddnsgeek.com/api/health >/dev/null
git rev-parse HEAD
compose ps
compose exec -T backend alembic current
compose exec -T backend sh -c 'test "$PAYMENT_PROVIDER" = disabled'
docker inspect --format '{{.Name}} {{.State.Status}} {{.State.Health.Status}} {{.RestartCount}}' $(compose ps -q)
df -h /
free -m
```

PASS means public health succeeds, required containers are running/healthy, migration is `0033_billing_phase2_contracts`, payment is disabled, restart counts are understood, and disk/memory have headroom. Do not print the full environment.

## 2. Restart or recreate one service

Use only after diagnosis and only for the affected stateless service. Preserve logs first:

```bash
compose logs --since 30m --timestamps SERVICE > /tmp/factorymind-SERVICE-incident.log
compose restart SERVICE
compose ps SERVICE
```

If a configuration/image refresh specifically requires recreation:

```bash
compose up -d --no-deps --force-recreate SERVICE
```

Then run the routine health check and inspect new logs. Do not casually restart PostgreSQL or Redis. Never restart multiple services to hide an unknown cause.

## 3. Safe deployment

Prerequisites: approved clean commit, green final checklist, immutable image references/digests, unexpired security decisions, current encrypted backup and isolated restore evidence, explicit migration approval, rollback revision, two-person approval, and a monitored window.

```bash
git status --short
git rev-parse HEAD
docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.prod.yml \
  -f docker-compose.https.yml config --quiet
./scripts/deploy-production.sh --env-file .env.production --https
```

The script applies migrations. Do not run it merely to restart a service. Afterward verify public health, revision, migration, disabled payment provider, queue/worker health, logs, and the critical customer path. Stop and roll back the application if health or tenant/auth checks fail.

## 4. Application image rollback

Rollback is an application rollback that preserves current volumes and migration:

```bash
./scripts/rollback-production.sh APPROVED_REVISION --env-file .env.production
```

The script checks PostgreSQL image compatibility and verifies service health. Do not use it for a schema downgrade. If the old application cannot run safely against the current schema, choose a reviewed roll-forward fix or declare a recovery incident.

## 5. Migrations

Read-only status:

```bash
compose exec -T backend alembic current
compose run --rm --no-deps backend alembic heads
```

Before a migration: review upgrade and downgrade code, test an empty upgrade and a restored production-like copy, check locks/runtime, take and verify an encrypted backup, and approve rollback/roll-forward behavior. Apply migrations only through an approved deployment. Never run an ad hoc production downgrade. Afterward confirm one head, application readiness, representative reads/writes, and audit evidence.

## 6. Encrypted backup

The passphrase must be injected at runtime by the approved secret mechanism and tested only for presence. The EC2 instance profile supplies temporary AWS credentials. Do not use static access keys.

```bash
test -n "${BACKUP_ENCRYPTION_PASSPHRASE+x}"
BACKUP_TARGET=s3 \
BACKUP_S3_URI='s3://factorymind-production-backups-442592659825/production-backups/' \
BACKUP_S3_SSE=aws:kms \
BACKUP_S3_KMS_KEY_ID='arn:aws:kms:us-east-1:442592659825:key/0bfd9191-4e51-4171-8756-23535baf55a5' \
BACKUP_RETENTION_DAYS=14 \
BACKUP_COMPOSE_PROJECT_NAME=ai-manufacturing-platform \
BACKUP_COMPOSE_ENV_FILE=.env.production \
BACKUP_COMPOSE_FILES='docker-compose.yml:docker-compose.prod.yml:docker-compose.https.yml' \
./scripts/backup-production.sh
```

Verify that only `.tar.gz.enc` and its authentication sidecar were published under the approved prefix with SSE-KMS. Record a cryptographic checksum, object version ID, creation time, and backup audit event in the restricted evidence system. Do not delete the local validated artifact until off-host verification completes.

## 7. Disposable restore

Assume the separate restore-reader role without printing temporary credentials. Download the encrypted object and authentication sidecar into a directory created with `mktemp -d`, verify SHA-256 against the recorded value, and run:

```bash
RESTORE_EVIDENCE_DIR=/tmp/factorymind-restore-evidence \
BACKUP_COMPOSE_PROJECT_NAME=ai-manufacturing-platform \
BACKUP_COMPOSE_ENV_FILE=.env.production \
BACKUP_COMPOSE_FILES='docker-compose.yml:docker-compose.prod.yml:docker-compose.https.yml' \
./scripts/restore-validation.sh /tmp/ISOLATED_DIRECTORY/BACKUP.tar.gz.enc
```

The script authenticates and decrypts into temporary storage, checks internal hashes, creates isolated Docker network/volumes/containers, restores PostgreSQL, checks the migration and representative counts, starts a disposable backend, verifies a disposable login/read, and cleans up. Confirm cleanup separately. Never set the target to the production database or application data directories. Keep the S3 object according to lifecycle policy.

## 8. Disk pressure

1. Check `df -h`, `df -i`, `docker system df`, named volume sizes, database growth, logs, and backup staging directories.
2. Identify the producer before removing anything. Preserve incident and audit evidence.
3. Rotate/compress only according to approved retention. Never delete database, Redis, model, dataset, MLflow, observability, or backup volumes.
4. At 70% sustained use, plan expansion/retention correction. At 85% or rapid growth, declare SEV-2 and pause nonessential training/onboarding through approved controls.
5. Reconfirm DB/worker/public health after mitigation.

## 9. CPU pressure

1. Inspect container CPU, request latency/error rate, active training, report/RAG activity, database queries, and restart counts.
2. If training is responsible, keep one worker and pause new submissions through an approved feature/control path; do not kill a fit without understanding artifact/job reconciliation.
3. If a new release caused pressure, use the application rollback procedure.
4. Scale only after sustained evidence and change approval; do not resize during diagnosis.

## 10. Memory pressure

1. Inspect host/container memory, OOM events, swap, database/Redis memory, and recent workload.
2. Preserve logs and determine whether the process leaks, a dataset/report is oversized, or limits are wrong.
3. Restart only the proven stateless offender if safe; do not restart PostgreSQL/Redis casually.
4. Reconcile interrupted queue jobs and verify customer-path health.

## 11. Training queue pressure

1. Check worker heartbeat, queue depth/oldest age, queued/running job rows, retries, stale/orphan thresholds, and current CPU/memory.
2. Production executes one training message at a time (`--processes 1 --threads 1`) and AutoML has one global slot. Do not increase either during an incident.
3. Let reconciliation handle stale/idempotent jobs; do not edit job rows manually.
4. Escalate for a stuck running job, repeated terminal failures, queue age above the runbook objective, or customer-facing entitlement mismatch.

## 12. Broken email

1. Confirm provider status, sender/domain verification, queue depth, retry/terminal states, reconciliation actor, and sanitized provider response codes.
2. Use generic customer messaging; never reveal whether an arbitrary account exists.
3. Do not expose verification/reset/invitation tokens or switch production to capture mode.
4. After correction, use a controlled mailbox to test signup verification, resend, password reset, invitation, and terminal/retry behavior.

## 13. Failed worker

1. Run `compose ps training-worker`; inspect sanitized logs, Redis, PostgreSQL, worker heartbeat, queue age, and resource pressure.
2. If dependencies are healthy and the worker alone is wedged, preserve logs and restart only `training-worker`.
3. Confirm one process/thread after restart and allow reconciliation to resolve in-flight jobs.
4. Verify no duplicate model/artifact was promoted and customer-visible statuses converge.

## 14. Failed reverse proxy

1. Check `compose ps reverse-proxy`, local backend/frontend health, certificate files/expiry, listener ownership, DNS, and proxy logs.
2. Confirm the proxy's declarative application/public/sandbox-edge networks before recreation.
3. Recreate only the proxy with `compose up -d --no-deps --force-recreate reverse-proxy`.
4. Verify HTTP→HTTPS redirect, certificate hostname/chain, HSTS, `/healthz`, `/api/health`, login, and no interruption to internal data services.

## 15. SSL issue

1. Inspect DNS and certificate dates/hostname/chain with `openssl s_client` without sending credentials.
2. Renew using the existing approved certificate process; do not replace keys ad hoc.
3. Run `scripts/reload-proxy-after-cert-renewal.sh` only after validating the renewed pair and configuration.
4. Verify redirect, HSTS, health, login, and expiry monitoring. Treat an expired/mismatched public certificate as SEV-1/2 based on reachability.

## 16. S3 backup issue

1. Confirm AWS CLI v2, `aws sts get-caller-identity`, expected writer role, system clock, bucket region, prefix, and KMS access without printing credentials.
2. Inspect only the intended prefix and bucket controls. Do not broaden policies automatically.
3. Distinguish S3 write denial, KMS encryption denial, assume-role denial, retrieval denial, checksum mismatch, and lifecycle/configuration failure.
4. Preserve the encrypted local artifact. If checksum mismatches, do not delete or overwrite either copy; quarantine the object version and escalate.
5. Use the restore-reader role for retrieval validation. Never grant the writer broad account-wide decrypt.

## 17. Expired security exception

`SEC-2026-002` expires 2026-08-26. Before expiry or any new image/revision approval, rescan the exact image/revision, remediate where possible, document compensating controls, and obtain an authorized close/renew decision. If it expires without approval, block new deployments and customer expansion; do not silently carry it forward. `SEC-2026-001` and `SEC-2026-003` were closed on 2026-08-12 and must not be reintroduced as audit suppressions.

## 18. External alert delivery

Current state is unproven: the configuration contains only local null receivers. By 2026-08-19, the production owner must choose one on-call destination, place its receiver URL/token only in the approved secret mechanism, configure a TLS-protected Alertmanager receiver and routing rule, then fire uniquely named temporary warning and critical alerts. Confirm receipt/grouping/inhibition, clear them, and confirm resolved notifications. Remove the temporary rule and retain timestamps/screenshots/message IDs without receiver secrets. Until then, run documented manual health checks for the controlled 1–20-user launch.

## 19. Incident triage

1. Declare severity and incident commander; open a UTC timeline.
2. Record confirmed customer/tenant scope, current revision/migration, service health, recent deployment, and known-good time.
3. Preserve sanitized logs, metrics, correlation IDs, image digests, queue state, and audit evidence. Never collect credentials, cookies, document contents, prompts, or model inputs unnecessarily.
4. Contain reversibly. Join security/privacy for suspected tenant breach, credential exposure, or data integrity risk.
5. Mitigate through one-service restart, application rollback, or approved roll-forward; never erase evidence or bypass migrations.
6. Verify from the customer path, reconcile queues/billing/audit records, monitor, and obtain explicit closure approval.
7. Complete a blameless review within five business days for SEV-1/2.

Escalate immediately for suspected cross-tenant access, data corruption, exposed secret, failed restore integrity, payment state corruption, total outage, or uncontrolled migration.

## 20. Post-action invariants

Every operational action ends by confirming:

- public production health passes;
- migration is the approved head;
- `PAYMENT_PROVIDER=disabled`;
- no unexpected restart loop;
- database, Redis, proxy, and worker are healthy;
- queue and audit state are consistent;
- customer data and production volumes were not modified outside the approved change;
- evidence and follow-up owner/date are recorded without secrets.
