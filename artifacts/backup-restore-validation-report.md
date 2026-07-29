# Backup and restore validation report

Date: 2026-07-29  
Current status: **local encrypted backup and isolated restore PASS; off-host BLOCKED**

The acceptance run created a 73,312-byte encrypted application archive and
authenticated sidecar. Restore validation passed at migration
`0031_entitlement_overrides` after verifying the HMAC, every payload checksum,
safe extraction, PostgreSQL restore, and all four managed artifact archives.

Redacted restored counts were: 1 company, 4 users, 1 factory, 1 dataset, 3
training jobs, 0 subscriptions, 0 payments, 0 invoice references, 21 refresh
tokens, 0 password-reset tokens, 0 email-verification tokens, 0 team
invitations, 1 document record, and 0 document chunks. Zero is a valid restored
count; table existence and queryability were still proved. The disposable
backend passed readiness and authenticated identity smoke checks.

One reproducible defect was fixed during acceptance: optional Compose arguments
used an empty-array expansion incompatible with macOS Bash 3.2 plus `set -u`.
Both backup and restore entry points now use a nounset-safe expansion and have a
regression contract.

No archive, database export, encryption passphrase, access credential, or
sensitive restored value was retained or committed; disposable containers,
network, volumes, plaintext staging, and encrypted temporary archives were
removed. Off-host publication remains blocked until deployment-owned
S3-compatible credentials and lifecycle policy are available.
