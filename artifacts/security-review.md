# Security review

Reviewed: 2026-07-29. Status: **not approved for unrestricted production**.

## Verified controls

- Argon2 passwords, short-lived access tokens, rotating/reuse-detecting refresh
  families in Secure HttpOnly cookies with CSRF validation, session revocation,
  generic recovery responses, and enforced email ownership.
- Six-role centralized permissions, owner-only boundaries, last-owner protection,
  tenant-scoped queries, and cross-company regression tests.
- Digest-only expiring single-use verification/invitation/reset credentials and
  encrypted token-bearing asynchronous email bodies.
- Backend-owned plan, amount, EGP currency, company, entitlement, and payment
  truth. Browser redirect parameters cannot activate a subscription.
- Paymob hosted collection (no raw card endpoint), SHA-512 callback HMAC,
  normalized card-free payload retention, transaction/event uniqueness, durable
  queueing, row locking, idempotent processing, and terminal event precedence.
- Central backend entitlement checks, atomic bounded metering, production-required
  enforcement, structured quota errors, and audited expiring overrides.
- Owner/Admin billing UI permission gates backed by server authorization,
  duplicate-checkout prevention, allowlisted HTTP(S) redirect schemes, accessible
  confirmations, and authenticated payment-status polling.

## Open findings

| Severity | Finding | Required remediation |
| --- | --- | --- |
| Critical release gate | No credential-backed Paymob sandbox/live transaction has been executed. | Complete merchant sandbox acceptance, signed callback, refund/reversal, and production-key ceremony using deployment-owned credentials. |
| High | Login rate limiting exists without account-specific progressive lockout. | Add bounded lockout/backoff without enabling account enumeration or abusive lockout. |
| High | Single-host deployment lacks HA and operator-proven off-host restore. | Use managed/redundant data services and complete a signed recovery exercise. |
| Medium | CSV/plain-text ingestion lacks malware quarantine/scanning. | Add quarantine and an asynchronous scanner gate. |
| Medium | Dependency/container/security workflows require current release review. | Run and review Bandit, pip-audit, npm audit, gitleaks, Semgrep, Trivy, SBOM, and licence results. |

No credentials, raw payment data, or real customer data are stored in source or
screenshots. Provider secrets must remain in the deployment secret manager.
