# Backup and restore validation report

Date: 2026-07-29  
Current status: **local encrypted backup and isolated restore PASS; off-host BLOCKED**

The final acceptance run created a 66,496-byte encrypted application archive and
authenticated sidecar. Restore validation passed at migration
`0031_entitlement_overrides` after verifying the HMAC, every payload checksum,
safe extraction, PostgreSQL restore, and all four managed artifact archives.

Redacted restored counts were: 2 companies, 5 users, 1 factory, 2 datasets, 1
training job, 0 subscriptions, 0 payments, 0 invoice references, 6 refresh
tokens, 0 password-reset tokens, 0 email-verification tokens, 0 team
invitations, 1 document record, and 0 document chunks. Zero is a valid restored
count; table existence and queryability were still proved. The disposable
backend passed readiness and authenticated identity smoke checks.

One reproducible defect was fixed during acceptance: optional Compose arguments
used an empty-array expansion incompatible with macOS Bash 3.2 plus `set -u`.
Both backup and restore entry points now use a nounset-safe expansion and have a
regression contract.

No archive, database export, encryption passphrase, access credential, or
sensitive restored value is committed; disposable containers, network, volumes,
and plaintext staging were removed. Generated local encrypted archives are
ephemeral release evidence and are removed after report consolidation. Off-host
publication remains blocked until deployment-owned
S3-compatible credentials and lifecycle policy are available.
