# Backup and Recovery

## Pilot service objective

The initial controlled-pilot targets are an RPO of 24 hours and an RTO of
4–8 hours. They are objectives, not demonstrated guarantees. The deployment
owner must schedule one daily backup and run a disposable restore test at least
monthly and before a pilot upgrade.

## Backup scope

`scripts/backup-production.sh` creates one application-consistent recovery
package containing:

- a PostgreSQL custom-format dump without ownership or privilege statements;
- dataset storage;
- model artifact storage;
- AI/RAG artifact storage;
- MLflow metadata/artifacts;
- application version, Git commit, migration revision, creation time, backup
  ID, contents, and retention metadata.

Each item is covered by a SHA-256 manifest. The payload is encrypted with
AES-256-CBC and PBKDF2 (200,000 iterations) and authenticated with a separate
HMAC-SHA256 before publication. Local publication is available for development.
Production/pilot publication supports an S3-compatible HTTPS endpoint with
AES256 or KMS server-side encryption.

The encryption passphrase and S3 credentials must come from the deployment
secret manager. They must not be committed, printed, or stored with the backup.
Key loss makes a backup unrecoverable; key compromise requires rotation and a
new full backup.

## Commands

Local encrypted backup against the active Compose project:

```bash
BACKUP_TARGET=local \
BACKUP_DIR="$PWD/backups/application" \
BACKUP_ENCRYPTION_PASSPHRASE='<from-secret-manager>' \
./scripts/backup-production.sh
```

S3-compatible destination:

```bash
BACKUP_TARGET=s3 \
BACKUP_S3_URI='s3://pilot-backups/customer-a' \
BACKUP_S3_ENDPOINT_URL='https://objects.example.com' \
BACKUP_S3_SSE='aws:kms' \
BACKUP_S3_KMS_KEY_ID='<kms-key-id>' \
BACKUP_ENCRYPTION_PASSPHRASE='<from-secret-manager>' \
./scripts/backup-production.sh
```

Disposable validation:

```bash
BACKUP_ENCRYPTION_PASSPHRASE='<from-secret-manager>' \
./scripts/restore-validation.sh \
  backups/application/pilot-YYYYMMDDTHHMMSSZ-xxxxxxxx.tar.gz.enc
```

For a non-default Compose project, provide
`BACKUP_COMPOSE_PROJECT_NAME`, `BACKUP_COMPOSE_ENV_FILE`, and a colon-separated
`BACKUP_COMPOSE_FILES` list.

## Restore safety and evidence

Restore validation verifies the HMAC before decryption, rejects unsafe archive
paths, checks every payload checksum, restores PostgreSQL into a disposable
isolated container, verifies the migration revision and core table counts,
extracts artifact archives into disposable volumes, starts the recovered
backend, checks readiness, and completes an authenticated login/identity smoke
request. It writes a redacted evidence file under `artifacts/`.

The workflow never targets a live database and exposes no live-overwrite flag.
A production restore is therefore a deliberate operator runbook: provision a
new environment, validate it, freeze writes, reconcile the RPO gap, switch
traffic, and retain the old environment until acceptance.

Backup and restore outcomes are added to the company audit trail on a
best-effort basis through the running backend. A backup failure must still be
alerted externally because database unavailability may also prevent that audit
record.

## Ownership, retention, and escalation

- **Owner:** designated pilot operations engineer.
- **Frequency:** daily encrypted full application backup.
- **Retention:** 14 days by default; customer policy may require longer.
- **Restore test:** monthly and before upgrades.
- **Access:** least-privilege backup writer; separate restore-reader role.
- **Failure:** page the deployment owner, preserve logs, do not delete the last
  known-good backup, and retry only after diagnosing storage/database health.
- **Evidence:** retain the restore report and backup object metadata according
  to the customer security policy.

S3 lifecycle/versioning, object lock, cross-account replication, legal hold,
automated alert delivery, and provider-specific disaster recovery are not
configured by this repository.

