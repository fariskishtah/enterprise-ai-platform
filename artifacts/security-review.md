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

## Open findings

| Severity | Finding | Required remediation |
| --- | --- | --- |
| Critical | Email ownership is not verified before login. | Add hashed, expiring verification tokens, delivery, resend throttling, and login policy. |
| Critical | Paymob checkout/webhook handling is not implemented. | Add hosted checkout, HMAC verification over exact raw payload, transactional idempotency, state transitions, and concurrency tests before enabling billing. |
| High | Refresh tokens remain accessible to JavaScript in session storage. | Prefer same-site Secure HttpOnly refresh cookies with CSRF protection; retain short access tokens in memory. |
| High | Login rate limiting exists, but there is no account-specific progressive lockout. | Add bounded failed-attempt state without enabling account enumeration or denial-of-service abuse. |
| High | Support email delivery runs in the request path and only supports disabled/Resend. | Persist outbound messages and queue bounded retries with sanitized failure data and a capture provider. |
| High | Only three roles are implemented. | Introduce Owner/Admin/Engineer/Operator/Analyst/Viewer through a compatibility migration and centralized permissions. |
| Medium | CSV/plain-text ingestion lacks a production malware scanner. | Add quarantine and an asynchronous scanner hook before marking uploads ready. |
| Medium | Current dependency/container scans were not rerun in this change. | Run CI security workflow and review Bandit, pip-audit, npm audit, gitleaks, Semgrep, Trivy, SBOM, and licences. |

No secrets were added. Real provider credentials must be supplied through the
deployment secret manager and must never use `.env.example` placeholder values.
