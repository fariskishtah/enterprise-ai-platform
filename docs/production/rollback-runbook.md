# Production rollback runbook

Use rollback only after preserving evidence and creating an encrypted backup.

1. Declare the incident, stop new writes at the reverse proxy if integrity is in
   doubt, and record current image digests and Alembic revision.
2. Capture service status, bounded logs, queue depth, database connections, disk
   use, and worker heartbeat without printing secrets.
3. Create and checksum an encrypted backup with
   `scripts/backup-production.sh`.
4. Prefer an application-image rollback when the schema remains compatible.
   Recreate only backend, worker, frontend, and proxy from the last reviewed
   image set.
5. If schema rollback is required, first validate the exact Alembic downgrade
   against a disposable restored database. Never downgrade the live database
   merely because an application rollback failed.
6. Run health, readiness, authentication, tenant isolation, one read, one bounded
   write, worker completion, and report download smoke checks.
7. Reopen traffic only after terminal job state and audit history are consistent.

If restore is required, use `scripts/restore-validation.sh` first. Live overwrite
requires the script's explicit destructive flag, an approved maintenance window,
two-person review, and a verified rollback artifact. Retain failed images and
logs until the post-incident review is complete.
