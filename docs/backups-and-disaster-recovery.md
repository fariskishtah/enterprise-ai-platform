# Backups and disaster recovery

This runbook covers the repository's local Docker Compose deployment. PostgreSQL
is the source of truth for business records, users, training-job state, model
governance, and monitoring metadata. Redis is a persistent queue/cache boundary;
MLflow, model artifacts, and observability stores are local supporting data.

## Data classification and recovery priority

| Priority | Data | Local persistence | Recovery expectation |
| --- | --- | --- | --- |
| 1 | PostgreSQL business and control-plane data | `postgres-data` named volume plus backups | Restore the latest verified backup first. |
| 2 | MLflow and model artifacts | `mlflow-data`, `model-artifact-data`, and `ai-artifact-data` | Preserve volumes; reconcile artifacts with PostgreSQL after database recovery. |
| 3 | Redis queues and cache | AOF on `redis-data` with `appendfsync everysec` | Recover AOF where possible, then reconcile jobs against PostgreSQL. |
| 4 | Prometheus, logs, traces, dashboards, and alert state | Local named volumes and source-controlled configuration | Best effort; telemetry history is not required to recover business state. |

Local named volumes are not backups: host or Docker storage loss can remove them
together. The scripts below create and test portable PostgreSQL archives without
reading credentials on the host or mounting the live database volume.

## Create a PostgreSQL backup

Start PostgreSQL, then run the backup from anywhere inside the repository:

```bash
docker compose up -d postgres
./scripts/backup-postgres.sh
```

The script executes `pg_dump` inside the existing PostgreSQL 16 service, writes
a custom-format archive to a temporary file, calculates SHA-256, and atomically
renames the completed archive and checksum. The default destination is
`backups/postgres/`, which Git ignores. It does not stop PostgreSQL or touch a
Docker volume.

The default retention is seven days. Override the destination or retention for
one invocation with shell environment variables:

```bash
BACKUP_DIR=/safe/local/path RETENTION_DAYS=14 ./scripts/backup-postgres.sh
```

Only files named `postgres-*.dump` or `postgres-*.dump.sha256` that are older
than the configured period are removed, and only from the configured backup
directory. Unrelated files and nested directories are left unchanged.

## Verify a backup restore

Verify every backup intended for recovery:

```bash
./scripts/verify-postgres-backup.sh backups/postgres/postgres-YYYYmmddTHHMMSSZ.dump
```

The verifier checks the adjacent `.sha256` file when present, validates the
archive catalog, and restores into a new disposable container using the exact
PostgreSQL image resolved from Compose. It inspects restored schemas and tables,
never restores into the live database, never attaches `postgres-data`, and
automatically removes the temporary container. A missing checksum is reported;
production recovery policy should reject unchecksummed archives.

## Scheduling

No scheduler is installed by this repository. A daily local cron entry can run
the script at 02:15 and append operational output to a user-owned log:

```cron
15 2 * * * cd /absolute/path/to/ai-manufacturing-platform && BACKUP_DIR=/absolute/path/to/backups/postgres RETENTION_DAYS=7 ./scripts/backup-postgres.sh >>/absolute/path/to/logs/postgres-backup.log 2>&1
```

Use absolute paths, protect the backup directory and log permissions, monitor
cron failures, and regularly run restore verification. A backup that has not
been restored successfully is not sufficient recovery evidence.

## Local RPO and RTO targets

These are engineering targets for a single-host development deployment, not a
production SLA:

- PostgreSQL RPO: 24 hours, assuming the documented daily backup completes.
- PostgreSQL RTO: 60 minutes to select, verify, restore, migrate, and validate a
  modest local database.
- Redis RPO: up to approximately one second with AOF `appendfsync everysec`.
  Queued or in-flight work can still be duplicated or lost and must be
  reconciled against PostgreSQL.
- Observability RPO/RTO: best effort. Source-controlled configuration can be
  recreated, but local metrics, logs, traces, and alert history may be lost.

The PostgreSQL targets assume the latest archive and checksum remain accessible,
Docker and the repository are available, and the archive has passed a recent
restore verification.

## Redis recovery expectations

Redis is not the source of truth. Its AOF and existing `redis-data` volume reduce
loss during a container restart, but they do not provide a cross-system
transaction with PostgreSQL. After Redis loss or replay:

1. Restore Redis connectivity without flushing or deleting the volume.
2. Treat PostgreSQL training-job and monitoring records as authoritative.
3. Use the documented bounded reconciliation paths for queued, orphaned, stale,
   or in-flight jobs; expect repeated delivery and rely on idempotency controls.
4. Confirm workers drain valid jobs and that terminal PostgreSQL states are not
   re-enqueued.

Transient cache and rate-limit state can be rebuilt. Dedicated Redis backups are
not implemented because irreplaceable business state belongs in PostgreSQL.

## Disaster scenarios

- **PostgreSQL container loss, volume intact:** recreate the service with
  `docker compose up -d postgres`; do not restore unless data validation shows
  the volume is unusable or incomplete.
- **PostgreSQL volume or host storage loss:** provision clean replacement
  storage, verify the selected off-volume archive, and perform the controlled
  manual restore below.
- **Corruption or operator error:** stop application writers, preserve evidence,
  select the newest backup from before the event, verify it ephemerally, and
  restore to clean storage.
- **Redis loss:** restart with the existing AOF volume if available, then
  reconcile PostgreSQL job state. Do not flush queues as a recovery shortcut.
- **Whole-host loss:** rebuild from source control, restore PostgreSQL from an
  off-host backup, restore required model artifacts, then recreate Redis and
  observability services.

## Recovery order

1. Declare the incident, stop backend and worker writes, record the failure
   window, and preserve affected volumes and logs. Never run `docker compose
   down -v`.
2. Inventory available PostgreSQL archives and checksums. Select the newest
   archive consistent with the incident time and required RPO.
3. Run `./scripts/verify-postgres-backup.sh BACKUP_FILE`. Do not continue if the
   checksum, catalog, restore, or inspection fails.
4. Provision a clean PostgreSQL 16 instance and empty target database. Keep the
   failed live volume detached so rollback and investigation remain possible.
5. Perform the authorized manual restore from inside that clean instance:

   ```bash
   pg_restore --exit-on-error --no-owner --no-privileges --dbname TARGET_DATABASE BACKUP_FILE
   ```

   This command is intentionally not automated. Confirm the target connection
   and obtain explicit approval because selecting a live target can be
   destructive. Never restore over the existing development database.
6. Apply any required Alembic migrations once, then validate PostgreSQL before
   reconnecting other services.
7. Restore or validate MLflow and model-artifact volumes, checking exact model
   versions and aliases against PostgreSQL records.
8. Start Redis and workers. Reconcile queued, stale, and in-flight work from
   authoritative PostgreSQL state before enabling producers.
9. Start the backend, then frontend, then the observability stack. Keep external
   writes disabled until the checks below pass.

## Verification after recovery

- Confirm PostgreSQL readiness, the expected Alembic revision, schema/table
  counts, representative business-record counts, and a read-only API request.
- Confirm authentication, a representative authorized write/read cycle, and
  model registry aliases point to available artifacts.
- Confirm Redis reports `appendonly=yes` and `appendfsync=everysec`, workers are
  healthy, queue depth is plausible, and reconciliation has no unexplained jobs.
- Confirm backend/worker metrics scrape, alerts evaluate, and logs and traces are
  accepted. Telemetry history gaps are expected after full local storage loss.
- Record the backup filename, checksum result, timestamps, observed data loss,
  validation evidence, and the decision to reopen writes.

## Production limitations

This local workflow has no off-host copy, encryption, access policy, immutable
retention, point-in-time recovery, scheduler monitoring, geographic redundancy,
or automated recovery orchestration. A production design should use encrypted,
access-controlled off-host backups, PostgreSQL WAL archiving or managed PITR,
separate failure domains, retention locks, alerting on backup age/failure,
automated restore drills, documented key recovery, and audited recovery access.
Set production RPO/RTO only after measured restore exercises at production scale.
