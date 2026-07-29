# Security review

Reviewed: 2026-07-29. Status: **release candidate only**.

## Current automated evidence

- `pip-audit`: 93 production-lock dependencies, 0 known vulnerabilities.
- Bandit: 57,516 lines, 0 medium/high findings (30 low-severity observations
  excluded by the `-ll` release threshold).
- Semgrep: 225 Python/TypeScript rules over 449 targets, 0 findings.
- Gitleaks: 153 commits and approximately 6.57 MB scanned, 0 leaks.
- Trivy filesystem: one HIGH React Router advisory covered by the bounded
  `SEC-2026-003` exception; 0 Dockerfile misconfigurations.
- Candidate-image Trivy: frontend and reverse proxy have 0 HIGH/CRITICAL
  findings. Backend has 23 occurrences across 12 HIGH/CRITICAL CVEs, all
  currently unfixed by the Debian repositories; the actionable scan has 0.
  This is the existing short-lived `SEC-2026-002` risk, not a hidden pass.
- Frontend production build passed its performance budget. Built JS/CSS/HTML
  contained no production secret-name/value markers; only
  `VITE_API_BASE_URL` is consumed by application source.

Raw machine reports are retained under the ignored `artifacts/release/`
working directory and are not committed because they are large, ephemeral
scanner output. The reviewed summaries below are committed.

## Application control review

- Authentication uses Argon2, short access tokens, rotating/reuse-detecting
  refresh families, Secure/HttpOnly/SameSite refresh cookies, CSRF validation
  for cookie mutation, generic recovery responses, and durable revocation.
- Six-role centralized permissions, tenant-scoped repositories, owner-only
  boundaries, last-owner protection, and cross-tenant regression tests protect
  administrative and billing routes.
- CORS and trusted hosts are explicit production requirements. Proxy trust is
  allowlisted. Production API docs and debug behavior are disabled.
- Upload size/type/content limits, safe storage names, CSV/document bounds, and
  archive-path checks exist. Malware quarantine/scanning remains absent.
- Outbound provider URLs are configuration-validated; hosted payment redirects
  are scheme-allowlisted. No browser-controlled amount, plan, company, or
  payment status is authoritative.
- Paymob callbacks require SHA-512 HMAC and durable idempotent processing. Raw
  card data is not accepted or retained. Provider secrets are redacted.
- SQLAlchemy parameterization and repository scoping prevent dynamic SQL in
  normal request paths. RAG context is treated as untrusted content and does
  not grant tools or authorization; paid model calls remain deployment-gated.
- Rate limits cover authentication, expensive AI/RAG paths, support, and
  feedback. Structured error handling avoids tracebacks or secrets in client
  responses and log-redaction tests cover sensitive fields.

## Findings and disposition

| Severity | Finding | Disposition |
| --- | --- | --- |
| Critical release gate | No credential-backed Paymob sandbox transaction or real email delivery has been accepted. | Block production; complete both deployment-owned acceptance procedures. |
| High accepted risk (time-bounded) | Backend base contains 23 unfixed HIGH/CRITICAL occurrences across 12 CVEs. | `SEC-2026-002`, expires 2026-08-06; refresh/rescan immediately when a fixed compatible base exists. |
| High accepted risk (time-bounded) | React Router RSC-only advisory affects the lock, while this product deploys a static SPA with no RSC/actions. | `SEC-2026-003`, expires 2026-08-15; complete coordinated React 19/Router 8 migration. |
| High | Login throttling has no account-specific progressive lockout. | Add bounded backoff/lockout without enumeration or attacker-controlled denial of service. |
| High | Single-host architecture lacks HA; off-host backup publication is unproved. | Configure deployment-owned immutable off-host storage and prove restore from that object. |
| Medium | CSV/plain-text ingestion has no malware quarantine/scanner. | Add quarantine and asynchronous scanner before accepting untrusted public uploads. |
| Low | Bandit recorded 30 low-severity observations below the release threshold. | Retain raw report and reassess when touched; no medium/high Bandit findings. |

No unsafe automatic upgrades were performed. Exceptions remain visible in
`docs/security/security-exception-register.md` and expire closed: an expired
entry fails repository release checks.
