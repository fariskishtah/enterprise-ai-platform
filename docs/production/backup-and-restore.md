# Production backup and restore

## Service objective and ownership

The initial release-candidate objective is a 24-hour RPO and a 4–8 hour RTO.
These are planning targets, not demonstrated guarantees. The operations owner
must run an encrypted full backup daily, monitor completion, and complete a
disposable restore monthly and before each production upgrade.

## Protected data

`scripts/backup-production.sh` captures PostgreSQL plus uploaded datasets and
documents, model artifacts, AI/RAG artifacts, and MLflow state. Its manifest
records the application commit, version, migration revision, content list, and
retention. Grafana dashboards and alert rules are source-controlled; runtime
Grafana preferences are not a recovery dependency and should be exported
separately if operators customize them.

Every payload item has a SHA-256 checksum. The package uses AES-256-CBC with
PBKDF2 (200,000 iterations) plus HMAC-SHA256. Store the passphrase in a secret
manager separate from the backup. Losing it makes the backup unrecoverable.

## Run and validate

```bash
BACKUP_TARGET=local \
BACKUP_DIR='<protected-local-staging-directory>' \
BACKUP_ENCRYPTION_PASSPHRASE='<secret-manager-value>' \
./scripts/backup-production.sh

BACKUP_ENCRYPTION_PASSPHRASE='<same-secret-manager-value>' \
./scripts/restore-validation.sh '<encrypted-archive>.tar.gz.enc'
```

The restore validates the HMAC before decryption, archive paths, all checksums,
migration head, tenant and application counts, billing tables, authentication
records, and document metadata. It restores managed volumes, starts an isolated
backend, and completes readiness plus authenticated identity checks. Disposable
containers, network, volumes, and plaintext staging are removed on exit.

## Off-host storage and retention

Production must set `BACKUP_TARGET=s3`, an HTTPS `BACKUP_S3_URI`, and preferably
`BACKUP_S3_SSE=aws:kms` with a deployment-owned KMS key. Use a write-only
application role, separate restore-reader role, bucket versioning, lifecycle
retention, object lock where policy requires it, cross-account or cross-region
replication, access logging, and alerts for missed/failed jobs. Default local
retention is 14 days; the deployment owner must reconcile provider lifecycle,
legal hold, and customer deletion policy.

## Recovery cutover

Never restore over the active database. Provision a new environment, restore
and validate it, freeze writes, reconcile changes since the backup, run the
release verification suite, switch traffic, and retain the old environment for
the rollback window. Record archive object version, backup/restore IDs,
migration revision, row-count evidence, timestamps, approvers, actual RPO/RTO,
and any reconciliation performed. See `docs/production/rollback-plan.md` after
that file is established by the operational-readiness phase.
