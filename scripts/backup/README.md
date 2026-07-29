# Production backup entry point

Run [`../backup-production.sh`](../backup-production.sh) for the supported,
encrypted application backup workflow. The script intentionally lives at the
top level to preserve existing automation and release-script integrations.

The operator procedure, secret requirements, retention policy, and restore
test are documented in `docs/production/backup-and-restore.md`.
