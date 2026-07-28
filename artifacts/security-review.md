# Security review

Reviewed: 2026-07-28. Status: **not approved for unrestricted production**.

## Controls verified in source and tests

- Argon2 password hashing, password strength validation, generic login/reset
  responses, short-lived JWT access tokens, hashed rotating refresh tokens, and
  session revocation.
- Server-side role checks and company scoping across the existing manufacturing,
  AI, operations, RAG, support, audit, and new billing persistence domains.
- Request/correlation IDs, structured logging, sensitive-field redaction,
  configurable exact CORS/host policy, request-size limits, security headers,
  production API-docs denial, and production rejection of demo/seed controls.
- Bounded upload/import paths, owner-scoped document/RAG records, safe report
  spreadsheet cells, and non-root/read-only production application containers.
- Billing prices/currency are backend-owned. No raw card endpoint or fake payment
  success path was added. Provider/event uniqueness constraints establish an
  idempotency foundation.
- New accounts use digest-only, expiring, single-use email-verification tokens.
  Production requires server-side enforcement while preserving login and resend;
  token-bearing queued bodies are encrypted, provider delivery stays async, and
  capture/disabled providers are rejected in production.
- Six roles use one server-side permission matrix. Existing Admins migrate to
  Owner; Admin cannot manage Owner, read-only roles cannot mutate through legacy
  dependencies, and the final active Owner is protected transactionally.
- Invitation tokens are digest-only, encrypted in queued mail, expiring,
  single-use, cooldown-rotated, company-bound, and cannot move an existing user
  across tenant ownership boundaries.

## Open findings

| Severity | Finding | Required remediation |
| --- | --- | --- |
| Critical | Paymob checkout/webhook handling is not implemented. | Add hosted checkout, HMAC verification over exact raw payload, transactional idempotency, state transitions, and concurrency tests before enabling billing. |
| High | Refresh tokens remain accessible to JavaScript in session storage. | Prefer same-site Secure HttpOnly refresh cookies with CSRF protection; retain short access tokens in memory. |
| High | Login rate limiting exists, but there is no account-specific progressive lockout. | Add bounded failed-attempt state without enabling account enumeration or denial-of-service abuse. |
| Medium | CSV/plain-text ingestion lacks a production malware scanner. | Add quarantine and an asynchronous scanner hook before marking uploads ready. |
| Medium | Current dependency/container scans were not rerun in this change. | Run CI security workflow and review Bandit, pip-audit, npm audit, gitleaks, Semgrep, Trivy, SBOM, and licences. |

No secrets were added. Real provider credentials must be supplied through the
deployment secret manager and must never use `.env.example` placeholder values.
