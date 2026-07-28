# Production readiness plan

Audit date: 2026-07-28  
Branch: `feature/production-saas-upgrade`  
Starting revision: `f0b3817`  
Starting worktree: clean  
Release currently declared by the repository: controlled pilot `0.9.0`

## Executive assessment

The repository is a substantial, tested controlled-pilot platform rather than a
prototype. It already has a coherent FastAPI/SQLAlchemy service layer, 22 ordered
Alembic migrations, tenant-scoped manufacturing and AI workflows, a typed React
application, Dramatiq workers, Docker deployments, security checks, and a broad
Grafana/Prometheus/Loki/Tempo stack. Existing documentation correctly avoids a
production-readiness claim.

The requested enterprise SaaS scope is not complete. The most consequential
gaps are billing and entitlements, verified account ownership, durable
transactional-email delivery, the six-role permission model, and removal of
demo-oriented behavior from normal customer journeys. The frontend has good
foundations and extensive route coverage, but lacks the requested password and
verification pages, billing pages, notification preferences, dedicated 403 and
500 routes, and production screenshot gallery. RAG is deliberately limited to
deterministic local embeddings and extractive answers over CSV/plain text.

Production readiness must remain **not approved** until all Critical items and
their runtime acceptance tests pass with deployment-owned credentials.

## Baseline evidence

- Runtime host: macOS ARM64, 8 logical CPUs, 8 GiB RAM, approximately 54 GiB free.
- Local Compose services observed running: API, frontend, PostgreSQL/pgvector,
  Redis, worker, Prometheus, Grafana, Loki, Tempo, Alloy, Alertmanager,
  PostgreSQL exporter, Redis exporter, and cAdvisor.
- Runtime probes: API `/health` returned 200; frontend returned 200; local API
  documentation returned 200 as configured.
- Frontend baseline: ESLint, Prettier, TypeScript, Vite production build, and
  performance-budget check passed on 2026-07-28.
- Backend baseline: full pytest run started before changes; its final result is
  recorded in `artifacts/final-test-report.md`.
- Repository size: 751 tracked files and approximately 124,000 source lines in
  `backend/app` plus `frontend/src`.
- Existing release evidence was inspected but is historical evidence for an
  earlier commit and is not treated as proof for this change.

## Architecture audit

| Area | Current implementation | Finding | Priority |
| --- | --- | --- | --- |
| Backend | FastAPI routers, dependency injection, application services, repositories, typed schemas | Mature structure; several very large route/service modules increase change risk | Medium |
| Frontend | React 18, TypeScript, Vite, lazy routes, typed API modules, reusable shells/states | Strong foundation; several pages exceed 500 lines and one demo page exceeds 1,200 lines | Medium |
| Database | PostgreSQL/pgvector and linear migrations `0001`–`0022` | No billing, invitation, verification, email-delivery, notification, or usage schema | Critical |
| Authentication | Argon2, short JWT access token, hashed rotating refresh tokens, logout/revocation, password reset backend | Registration immediately logs in; no email verification, login lockout, invitation flow, or six-role model | Critical |
| Token storage | Access and refresh tokens returned to JavaScript and stored in `sessionStorage` | Bounded persistence but vulnerable to token theft through XSS; cookie settings exist without an HttpOnly session flow | High |
| Authorization | Server-side role dependencies and company filters across major resources | Only admin/engineer/operator; systematic BOLA regression tests exist for many but not all future domains | Critical |
| Multi-tenancy | `company_id` scoping in repositories/routes plus ownership constraints | Good foundation; every new billing/email/admin query must preserve company scope and opaque 404 behavior | Critical |
| Manufacturing | Companies, factories, machines, sensors, readings, imports, operations | Functional; destructive actions need consistent confirmation and plan-limit enforcement | High |
| RAG | Immutable document datasets, worker indexing, pgvector, citation persistence, tenant scoping | Deterministic lexical hashing/extractive provider; CSV/plain UTF-8 only; no PDF/DOCX/OCR or production LLM provider | High |
| AI/models | Allowlisted sklearn plugins, MLflow, evaluation, promotion, rollback aliases, prediction monitoring | Broad tests; resource-bounded smoke validation and a current compatibility matrix are still required | High |
| Training | Dramatiq queues, retries, cancellation/reconciliation, metrics | Good pilot behavior; local CPU/ARM constraints must be reflected in current evidence | High |
| Feedback/support | Durable support request and audit models, Resend abstraction | Delivery occurs inside the API request; provider support is only disabled/Resend; disabled mode reports failure instead of capturing mail locally | Critical |
| Reporting | Executive summaries and CSV/XLSX/PDF generation | Existing routes are grouped in demo-named modules and need product-language separation | High |
| Billing | None | Plans, subscriptions, payments, webhooks, usage, entitlements, UI, and tests are absent | Critical |
| Demo behavior | Feature flags reject demo tools in production; explicit seed script | Customer home/settings still contain demo onboarding; public-demo tables/routes/services remain; naming is mixed with real import/report features | Critical |
| Observability | Full local stack, dashboards, alert rules, tracing, request IDs | Strong baseline; billing/email/auth metrics and dashboards do not exist | High |
| Docker/deploy | Local, staging, production and HTTPS Compose; non-root/read-only production containers | Single-host only; deployment credentials/TLS/off-host storage remain operator responsibilities | High |
| CI/CD | Backend quality/tests/audits, frontend lint/build/E2E, staging runtime, security and release workflows | Comprehensive baseline; new billing/email/E2E/load suites must be added to gates | High |
| Automated tests | Large pytest and Playwright suites plus k6 scripts | Broad pilot coverage; new requested journeys and empty/failed billing/email states absent | Critical |
| Accessibility | Semantic labels, focus styles, axe coverage in E2E | Must rerun all key routes at desktop/tablet/mobile; native `window.confirm` is inconsistent | Medium |
| Performance | Bounded pagination in many APIs, chunked frontend, k6 scenarios, prior reports | Some list endpoints return arrays; new queries need indexes and concurrency tests | High |
| Documentation | Extensive controlled-pilot docs and runbooks | Accurate for pilot but explicitly contradicts new scope; missing requested topic documents and current screenshots | High |

## Critical checklist

- [ ] Remove normal customer-flow demo onboarding and all automatic demo workspace
      preparation. Keep explicit development seeding disabled by default.
- [ ] Rename production import/report UI modules so real features do not depend on
      a demo namespace; gate or retire scenario-control routes without deleting
      existing persisted customer data.
- [ ] Add verified-email ownership, verification token lifecycle, resend flow,
      generic forgot-password delivery, login throttling/lockout, and security
      audit events.
- [ ] Expand roles to Owner, Admin, Engineer, Operator, Analyst, and Viewer with a
      centralized server-side permission matrix and backward-compatible role
      migration.
- [ ] Add invitation records and acceptance with company-bound, hashed,
      single-use, expiring tokens.
- [ ] Add a durable outbound-email model/queue with provider message ID, bounded
      attempts/backoff, timestamps, sanitized errors, local capture mode, Resend,
      SMTP, and provider-neutral templates.
- [ ] Move support/feedback delivery off the request path while preserving the
      submitted record if delivery fails.
- [ ] Add centralized plan catalogue and database-backed billing entities for
      plans, entitlements, customers, subscriptions, payments, invoices, webhook
      events, usage counters, and billing audit events.
- [ ] Implement backend-authoritative EGP prices (1,000 / 5,000 / 10,000), Paymob
      hosted-checkout abstraction, signature verification, idempotent/concurrent
      webhook processing, grace periods, and tenant-scoped management APIs.
- [ ] Enforce plan limits on write paths; never trust frontend price, currency,
      company, or entitlement values.
- [ ] Add tests for all requested auth, tenant, email, billing, idempotency, and
      concurrency cases; Critical status cannot close with failures.

## High-priority checklist

- [ ] Add forgot/reset/verify/invitation pages and accurate API-error messaging.
- [ ] Add pricing, billing status, payment history, usage, plan warning, and admin
      subscription pages with loading, empty, error, and success states.
- [ ] Add notification preferences and company settings backed by real APIs.
- [ ] Add explicit 403 and recoverable 500 pages; retain the 404 route.
- [ ] Replace JavaScript token persistence with secure HttpOnly refresh-cookie
      mode where same-site deployment supports it; document fallback risk.
- [ ] Add request idempotency to important creation endpoints and consistent
      error envelopes containing request/correlation IDs.
- [ ] Validate upload MIME/content agreement, quarantine/scan hook, request-size
      limits, and safe extraction for each supported document type.
- [ ] Produce the current model matrix and bounded training smoke report on this
      ARM64/CPU host; label deterministic local RAG accurately.
- [ ] Extend Prometheus metrics and Grafana dashboards for authentication,
      outbound email, billing/webhooks, RAG, and worker queue outcomes.
- [ ] Add requested health/login/dashboard/machines/alerts/documents/RAG/feedback/
      reports/billing load scenarios under `tests/load/` (or retain k6 with a
      compatibility wrapper) and capture current JSON results.
- [ ] Add full desktop/tablet/mobile Playwright route coverage, browser console
      and failed-request assertions, and safe screenshot fixtures.
- [ ] Update CI, Makefile/task commands, `.env.example`, README, deployment guide,
      and provider setup documents.

## Medium-priority checklist

- [ ] Split components above roughly 500 lines along domain boundaries.
- [ ] Consolidate dialogs, toast feedback, skeletons, filters, pagination, and
      confirmation patterns into reusable accessible components.
- [ ] Add accessible responsive-table alternatives and audit overflow at 390 px,
      768 px, and desktop widths.
- [ ] Add saved filters, notification center, onboarding checklist, import
      templates, retention controls, backup status, and status page only where
      they use real APIs.
- [ ] Add internationalization-ready message boundaries and consistent
      time-zone-aware timestamp rendering.
- [ ] Add soft delete/restore to high-value resources after defining retention
      and uniqueness semantics.
- [ ] Evaluate real semantic embedding and LLM providers behind existing RAG
      protocols with strict tenant, timeout, cost, and prompt-injection controls.

## Low-priority checklist

- [ ] Add dark mode only after every chart, email preview, and contrast state is
      validated.
- [ ] Add SSO/SCIM/MFA after core account verification and session controls are
      stable.
- [ ] Evaluate HA orchestration, managed object storage, managed PostgreSQL,
      multi-region recovery, and formal SLO capacity certification.
- [ ] Complete legal review for terms, privacy, data processing, asset provenance,
      and commercial licensing; placeholders must remain clearly marked.

## Planned implementation phases and exact systems

1. **Baseline and product separation** — `backend/app/config`, product/demo
   dependencies and routes, `scripts/seed_demo.py`, `frontend/src/pages`,
   navigation, router, tests, `.env.example`.
2. **Identity and email** — user/company models, repositories, services, auth and
   user routes/schemas, new Alembic migration, worker actors, email templates,
   account pages, audit and metrics tests.
3. **Billing and entitlements** — new billing model/repository/service/provider/
   route/schema modules, migration, worker follow-up actor, frontend API/pages,
   Paymob sandbox documentation, backend and browser tests.
4. **Frontend completion** — shared design-system components, error boundaries,
   settings/profile/team/admin/notification surfaces, accessibility and mobile
   coverage.
5. **AI/security/performance verification** — model smoke matrix, dependency and
   container scans, tenant/BOLA review, upload hardening, k6/Playwright execution,
   observability updates.
6. **Release evidence** — screenshots, README gallery, architecture/auth/email/
   billing/AI/testing/deployment/security/troubleshooting docs, clean migrations,
   full Compose rebuild, and final reports.

Each phase must leave lint, formatting, type checks, focused tests, and migration
validation green. Commits use conventional messages and do not include secrets,
runtime databases, generated caches, or real customer data.

## Exact acceptance gates

- Empty-database `alembic upgrade head` and downgrade/upgrade check succeed.
- Upgrade against the current local development database succeeds after backup.
- Backend lint, Black, mypy, pytest, dependency audit, and migration tests pass.
- Frontend ESLint, Prettier, TypeScript, production build, dependency audit, and
  Playwright tests pass.
- Compose configuration validates; every required service starts healthy without
  unexpected restart or error logs.
- Fresh registration requires verified ownership according to configuration;
  reset, invitation, session revocation, and all six roles behave as documented.
- Captured development email proves template/token flows without claiming real
  provider delivery.
- Paymob sandbox checkout and representative signed webhooks prove correct EGP
  pricing, idempotency, state transitions, grace policy, and entitlements.
- Document ingestion, grounded citation response, every available local model,
  and bounded worker training run have current evidence.
- Load smoke thresholds pass without paid external calls; normal/stress/spike/
  soak outcomes are reported honestly.
- Desktop/tablet/mobile page journeys have no unexpected console error, failed
  request, broken image, inaccessible form control, or horizontal overflow.
- Production screenshots contain only deterministic non-sensitive fixture data.
- `artifacts/final-implementation-report.md` explicitly lists unresolved
  credential, infrastructure, legal, semantic-model, and capacity limitations.

## External verification blockers expected

The implementation can provide adapters, mocks/capture providers, signature
tests, and sandbox procedures, but these checks require repository-owner or
deployment-operator input before production approval:

- Verified sender domain and real Resend/SendGrid/SES/SMTP credentials.
- Paymob production API key, integration ID, iframe/public key (as applicable),
  and HMAC secret; production merchant onboarding and webhook endpoint.
- Public DNS/TLS, secret manager, restricted database/Redis credentials, managed
  backup destination, and restore-owner sign-off.
- Any gated model credentials and approval to download models within disk/RAM
  limits.
- Legal terms, privacy/data-processing review, commercial license, asset rights,
  and customer acceptance testing.
