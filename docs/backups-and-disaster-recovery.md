# Backups and disaster recovery

This runbook covers the repository's local Docker Compose deployment. PostgreSQL
is the source of truth for business records, users, training-job state, dataset
lineage, RAG metadata, model governance, and monitoring metadata. Uploaded
dataset source objects live on the managed `dataset-data` volume and must be
recovered with their PostgreSQL metadata. Redis is a persistent queue/cache
boundary; MLflow, model artifacts, and observability stores are local supporting
data.

## Data classification and recovery priority

| Priority | Data | Local persistence | Recovery expectation |
| --- | --- | --- | --- |
| 1 | PostgreSQL business/control-plane data and uploaded dataset objects | `postgres-data` and `dataset-data` named volumes plus paired backups | Restore and validate one matching database/object recovery point first. |
| 2 | MLflow and model artifacts | `mlflow-data`, `model-artifact-data`, and `ai-artifact-data` | Preserve volumes; reconcile artifacts with PostgreSQL after database recovery. |
| 3 | Redis queues and cache | AOF on `redis-data` with `appendfsync everysec` | Recover AOF where possible, then reconcile jobs against PostgreSQL. |
| 4 | Prometheus, logs, traces, dashboards, and alert state | Local named volumes and source-controlled configuration | Best effort; telemetry history is not required to recover business state. |

Local named volumes are not backups: host or Docker storage loss can remove them
together. The scripts below create and test a portable PostgreSQL archive plus a
read-only archive of the managed dataset volume without reading database
credentials on the host or mounting the live database volume.

## Create a paired application backup

Start PostgreSQL and the backend, then run the backup from anywhere inside the
repository:

```bash
docker compose up -d postgres backend
./scripts/backup-postgres.sh
```

The script first executes `pg_dump` inside the existing pgvector-enabled
PostgreSQL 16 service. It then resolves the backend's managed `dataset-data`
mount and reads it through a locked-down, networkless, read-only ephemeral
container. Dataset objects are immutable and durably written before their
metadata transaction commits, so this database-first snapshot can include a
harmless newer unreferenced object but cannot omit an object referenced by the
database snapshot under the current lifecycle.

The completed set contains matching timestamped files and SHA-256 sidecars:

```text
postgres-YYYYmmddTHHMMSSZ.dump
postgres-YYYYmmddTHHMMSSZ.dump.sha256
dataset-YYYYmmddTHHMMSSZ.tar.gz
dataset-YYYYmmddTHHMMSSZ.tar.gz.sha256
```

All four files are built under temporary names. Dataset artifacts are published
first and the PostgreSQL checksum is published last as the usable-set completion
marker. The default destination is `backups/postgres/`, which Git ignores. The
script does not stop a service, write to a managed volume, or delete a volume.

The default retention is seven days. Override the destination or retention for
one invocation with shell environment variables:

```bash
BACKUP_DIR=/safe/local/path RETENTION_DAYS=14 ./scripts/backup-postgres.sh
```

Only matching PostgreSQL and dataset archive/checksum names older than the
configured period are removed, and only from the configured backup directory.
Unrelated files and nested directories are left unchanged.

## Verify a backup restore

Verify every backup intended for recovery:

```bash
./scripts/verify-postgres-backup.sh backups/postgres/postgres-YYYYmmddTHHMMSSZ.dump
```

The verifier infers the paired dataset archive from the timestamp, or accepts it
explicitly as a second argument. For a pair, both `.sha256` files are required.
It validates archive paths and entry types, restores PostgreSQL into a new
disposable container using the exact pgvector-enabled image resolved from
Compose, and confirms the `vector` extension plus restored schemas and tables.
It never restores into the live database, never attaches `postgres-data` or
`dataset-data`, and automatically removes the temporary database container.
Legacy PostgreSQL-only archives remain inspectable, but they are not sufficient
to recover dataset/RAG source objects.

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

- PostgreSQL and dataset-object RPO: 24 hours, assuming the documented paired
  daily backup completes and both archives remain together.
- PostgreSQL and dataset-object RTO: 60 minutes to select, verify, restore,
  migrate, reconcile, and validate a modest local installation.
- Redis RPO: up to approximately one second with AOF `appendfsync everysec`.
  Queued or in-flight work can still be duplicated or lost and must be
  reconciled against PostgreSQL.
- Observability RPO/RTO: best effort. Source-controlled configuration can be
  recreated, but local metrics, logs, traces, and alert history may be lost.

These targets assume the latest matching archives and both checksums remain
accessible, Docker and the repository are available, and the pair has passed a
recent restore verification.

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
- **PostgreSQL or dataset volume loss:** provision clean replacement storage,
  verify one matching off-volume pair, and perform the controlled manual restore
  below. Do not combine timestamps.
- **Corruption or operator error:** stop application writers, preserve evidence,
  select the newest backup from before the event, verify it ephemerally, and
  restore to clean storage.
- **Redis loss:** restart with the existing AOF volume if available, then
  reconcile PostgreSQL job state. Do not flush queues as a recovery shortcut.
- **Whole-host loss:** rebuild from source control, restore PostgreSQL and
  dataset objects from one off-host backup pair, restore required model
  artifacts, then recreate Redis and observability services.

## Recovery order

1. Declare the incident, stop backend and worker writes, record the failure
   window, and preserve affected volumes and logs. Never run `docker compose
   down -v`.
2. Inventory PostgreSQL/dataset archive pairs and checksums. Select the newest
   complete matching timestamp consistent with the incident time and required
   RPO.
3. Run `./scripts/verify-postgres-backup.sh BACKUP_FILE`. Do not continue if the
   checksum, catalog, restore, or inspection fails.
4. Provision a clean pgvector-enabled PostgreSQL 16 instance, empty target
   database, and empty dataset-object destination. Keep failed live volumes
   detached so rollback and investigation remain possible. The migration role
   must be able to run `CREATE EXTENSION vector`, or a database administrator
   must pre-provision that extension on the target database with `public` on the
   migration `search_path`.
5. Perform the authorized manual restore from inside that clean instance:

   ```bash
   pg_restore --exit-on-error --no-owner --no-privileges --dbname TARGET_DATABASE BACKUP_FILE
   ```

   This command is intentionally not automated. Confirm the target connection
   and obtain explicit approval because selecting a live target can be
   destructive. Never restore over the existing development database.
6. Restore the matching dataset archive only into the clean managed dataset
   volume. This is intentionally an authorized manual operation: verify the
   archive checksum and destination twice, reject symbolic links or traversal,
   and never extract over the failed live volume. Then verify stored object
   digests against ready dataset-version metadata.
7. Apply any required Alembic migrations once, then validate PostgreSQL,
   including the `vector` extension and `vector(256)` embedding column, before
   reconnecting other services.
8. Restore or validate MLflow and model-artifact volumes, checking exact model
   versions and aliases against PostgreSQL records.
9. Start Redis and workers. Reconcile queued, stale, and in-flight work from
   authoritative PostgreSQL state before enabling producers.
10. Start the backend, then frontend, then the observability stack. Keep external
   writes disabled until the checks below pass.

## Verification after recovery

- Confirm PostgreSQL readiness, the expected Alembic revision, schema/table
  counts, the `vector` extension, representative business-record counts, and a
  read-only API request.
- Confirm every ready dataset version's managed object is present and its stored
  SHA-256 digest matches; then run one bounded RAG retrieval against a known
  ready knowledge base.
- Confirm authentication, a representative authorized write/read cycle, and
  model registry aliases point to available artifacts.
- Confirm Redis reports `appendonly=yes` and `appendfsync=everysec`, workers are
  healthy, queue depth is plausible, and reconciliation has no unexplained jobs.
- Confirm backend/worker metrics scrape, alerts evaluate, and logs and traces are
  accepted. Telemetry history gaps are expected after full local storage loss.
- Record the backup filename, checksum result, timestamps, observed data loss,
  validation evidence, and the decision to reopen writes.

## Production limitations

This local workflow has no built-in off-host copy, encryption, access policy, immutable
retention, point-in-time recovery, scheduler monitoring, geographic redundancy,
or automated recovery orchestration. A production design should use encrypted,
access-controlled off-host backups, PostgreSQL WAL archiving or managed PITR,
separate failure domains, retention locks, alerting on backup age/failure,
automated restore drills, documented key recovery, and audited recovery access.
Set production RPO/RTO only after measured restore exercises at production scale.
