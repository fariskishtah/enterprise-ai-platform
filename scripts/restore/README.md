# Production restore validation entry point

Run [`../restore-validation.sh`](../restore-validation.sh) to restore an
encrypted backup into disposable PostgreSQL, Redis, backend, and managed-volume
resources. It never accepts a live target database.

The cutover procedure remains an operator-controlled blue/green recovery and
is documented in `docs/production/backup-and-restore.md`.
