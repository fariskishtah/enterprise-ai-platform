# Restore Validation Report

## Status

**Passed locally against a disposable restore target on 2026-07-24.**

## Observed candidate evidence

- Backup ID: `pilot-20260724T023843Z-a28d8563`
- Restore validation ID: `restore-20260724T023905Z-64b3325b`
- Migration revision: `0015_add_pilot_identity_audit`
- Restored companies: 1
- Restored users: 3
- Restored factories: 1
- Restored datasets: 2
- Restored training jobs: 1
- Artifact archive checksums and safe paths: passed
- Backend readiness: passed
- Authenticated smoke: passed

The timestamped local evidence was written to:

```text
artifacts/release/restore-20260724T023905Z-64b3325b.txt
```

## Command exercised

The successful restore ran inside the final unified command:

```bash
eval "$(fnm env --shell bash)"
fnm use 22
./scripts/validate-release.sh --full --allow-dirty
```

That command created an encrypted local backup with the staging Compose
project configuration and passed the resulting archive to
`scripts/restore-validation.sh` with the same passphrase.

## Safety behavior observed

- The backup includes PostgreSQL plus dataset, model-artifact, AI-artifact, and
  MLflow archives with a manifest and checksums.
- Restore validation creates separately named disposable database, Redis,
  artifact volumes, and backend containers.
- Archive paths and checksums are checked before extraction.
- The restore script does not target the running source database or source
  volumes and performs no live overwrite.
- Cleanup removed the disposable restore resources after validation.
- Shell syntax validation passed for both backup and restore scripts.

## Target coverage and limitations

- The local filesystem backup target was exercised end to end.
- S3-compatible configuration validation was exercised without network access:
  an insecure HTTP endpoint was rejected with exit code 2.
- No S3-compatible upload/download was performed because no pilot object-store
  endpoint or credentials were supplied.
- Backup scheduling, retention, object lock, off-host custody, alerting, and
  recurring restore drills remain deployment responsibilities.
- This result supports controlled-pilot recovery validation only; it is not
  production disaster-recovery certification.
