# FactoryMind final project handoff

Audit date: 2026-08-12

Production URL: <https://factorymind.ddnsgeek.com>

Frozen production revision: `af3f48f4247809bae45cb06957799bf883f6c68c`

Production migration: `0033_billing_phase2_contracts`
Decision: **OWNER ACTION REQUIRED — technical closure gates pass; two owner/external P1 findings remain**

## 1. Executive summary

FactoryMind's frozen production release is online, healthy, encrypted in transit, backed up off host, and suitable for its already approved controlled launch of 1–20 initial users. The core tenant-aware manufacturing, data, AI, knowledge, monitoring, reporting, team, audit, and entitlement workflows have broad automated and curated UI evidence. Production payment processing remains deliberately disabled.

The release-candidate source is technically closed: the public landing and SEO surface are implemented, the RAG capability-status regression is fixed, generated duplicates are isolated from the repository, formatting/build/security gates pass, and the full backend and three-engine Playwright suites are green. The candidate has not been deployed, so the frozen production revision remains unchanged.

Unrestricted customer handoff still requires qualified legal approval and an owned external alert destination with proven delivery. The nine public legal documents remain explicit unapproved placeholders and acceptance is intentionally not collected until counsel defines which documents require it. These are owner/external-service blockers, not unresolved implementation defects.

No production application, data, configuration, migration, infrastructure size, payment setting, or volume was changed during this audit.

## 2. Product purpose and honest scope

FactoryMind is a tenant-isolated manufacturing intelligence workspace for organizing factories, machines/assets, and sensors; onboarding structured data; training and evaluating governed models; running validated predictions; grounding answers in registered knowledge; monitoring model behavior; reporting; and administering users and entitlements.

The supported hierarchy is:

```text
Factory
└── Machine / Production Asset
    └── Sensor
```

There is no `ProductionLine` domain model. One synthetic seed label says “Demo production line”; it is descriptive fixture text, not a hierarchy entity.

Claims that must not be made: guaranteed failure prevention, zero hallucinations, zero downtime, direct PDF parsing, live physical IoT streaming, automatic model deployment, recurring billing, or live Paymob checkout. Knowledge ingestion verified for this release is UTF-8 plain text. RAG should be described as grounded answers with citations and explicit refusal when evidence is insufficient.

## 3. Architecture and production deployment

```text
Browser
  └── HTTPS reverse proxy
      ├── React/Vite frontend
      └── FastAPI backend
          ├── PostgreSQL + pgvector
          ├── Redis
          ├── single-process/single-thread Dramatiq training worker
          └── managed dataset, model, AI-artifact, and MLflow volumes

Operational telemetry
  └── Prometheus / Alertmanager / Grafana / Loki / Tempo / Alloy

Recovery
  └── application-encrypted archive → private SSE-KMS S3 object
      └── separate restore-reader role → disposable isolated restore
```

The host observed during the audit was an AWS EC2 `m7i-flex.large` with 2 vCPUs, about 7.6 GiB RAM, and a roughly 60 GB root filesystem at 32% use. Backend, frontend, PostgreSQL, Redis, reverse proxy, and training worker were healthy with zero observed restarts. The reverse proxy is declaratively attached to the application, public, and Paymob-sandbox-edge networks, so the previously manual network relationship survives recreation. Six named Compose volumes were present.

The topology remains a single-host pilot deployment. It is not highly available. Scaling must follow measured CPU, memory, disk, database pool, queue-age, error-rate, and latency evidence rather than a calendar or sales estimate.

## 4. Product modules and acceptance state

| Area                                           | Result | Evidence and limitation                                                                                                                                                                     |
| ---------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Signup and email verification                  | PASS   | Current operator-provided production acceptance plus auth tests and [screenshots](docs/final-acceptance/screenshots/README.md).                                                             |
| Login, logout, reset, expiry, session rotation | PASS   | Backend auth tests and desktop/mobile auth evidence. Cookies are secure in production; privacy-safe reset responses resist enumeration.                                                     |
| First-time customer experience                 | PASS   | Candidate provides a factual public landing with sign-in, account creation, and business inquiry actions. Legal approval remains an owner gate before unrestricted onboarding.              |
| Factory → machine/asset → sensor               | PASS   | Manufacturing API, invalid-ID, relationship, deletion, and tenant tests; curated hierarchy evidence.                                                                                        |
| Structured CSV onboarding                      | PASS   | Parsing, mapping, types, timestamps, unknown-sensor, replay, chunking, and error tests. This is not live IoT streaming.                                                                     |
| Data quality and dataset registry              | PASS   | Validation/remediation UI evidence and tenant-aware dataset lifecycle tests. No invented quality metrics are claimed.                                                                       |
| Guided AI, training, AutoML                    | PASS   | Submission, queue, retry, cancellation, completion/failure, study, and artifact tests. Execution is bounded to one worker process/thread and one global AutoML slot.                        |
| Model registry and evaluation                  | PASS   | Exact-version model, metadata, candidate/promotion, metrics, invalid-ID, and tenant tests. Only implemented metrics are shown.                                                              |
| Prediction                                     | PASS   | Validated features, exact model selection, safe errors, authorization, and privacy-preserving event tests.                                                                                  |
| Knowledge Base                                 | PASS   | UTF-8 text registration, indexing, READY/failure, reconciliation, and tenant tests. No PDF claim.                                                                                           |
| Grounded RAG                                   | PASS   | Citation, evidence relationship, refusal, empty/unavailable KB, idempotency, and cross-tenant tests.                                                                                        |
| Monitoring and retraining                      | PASS   | Prediction-event monitoring, evaluation, scheduling, drift, and governed retraining tests. Retraining is policy-controlled; it is not automatic production model deployment.                |
| Executive dashboard and reports                | PASS   | Real application-derived summaries, role checks, empty states, report creation/download, and tenant tests. Reports are not described as regulatory “audit-ready.”                           |
| Users, roles, and invitations                  | PASS   | Owner/admin/engineer/operator/analyst/viewer matrix, invitation lifecycle, role changes, removal, and last-owner protection.                                                                |
| Audit log                                      | PASS   | Actor/action/time/tenant records, access control, filters, and privacy-safe metadata tests.                                                                                                 |
| Billing and entitlements                       | PASS   | Starter EGP 1,000, Professional EGP 5,000, and Enterprise EGP 10,000 per prepaid access period; quota/gating/audit coverage. Renewal is manual, not recurring. `PAYMENT_PROVIDER=disabled`. |

Professional currently includes 25 users, 5 factories, 250 assets, 25 GB document storage, 5,000 monthly AI queries, training, and advanced reports. The plan catalog permits two queued/running training jobs for Professional, while the pilot host executes one job at a time. Operators must therefore distinguish entitlement capacity from physical execution concurrency.

## 5. Customer journey

The implemented journey is public login/signup → email verification → authenticated empty workspace → factory/machine/sensor → CSV onboarding/data quality/dataset → Guided AI/training/model/evaluation/prediction → Knowledge Base/RAG → monitoring/reports → team/settings/billing. Happy paths, invalid inputs, empty/loading/error states, refresh/session behavior, duplicate inputs, resend, reset, and authorization are represented across backend and frontend tests.

The in-app interactive browser runtime reported no available browser. The repository's explicitly required Playwright acceptance was nevertheless run on locally installed Chromium, Firefox, and WebKit engines: each engine passed 89 tests and skipped 23 tests that require an explicitly configured real staging backend. The automated routes cover the public entry, authentication, dashboard, hierarchy, data onboarding, Guided AI/AutoML, Knowledge Base/RAG, monitoring, reports, billing, responsive behavior, and accessibility smoke. No production data was used or mutated.

## 6. RBAC and tenant isolation

The six workspace roles are owner, admin, engineer, operator, analyst, and viewer. Permissions are enforced in backend dependencies and services, not only by frontend route guards. Owner assignment is owner-only; the last owner cannot be demoted or removed; viewers are read-only; and audit visibility is restricted to the intended roles. Platform billing operations require a separate platform-operator capability.

Repository tests cover swapped identifiers, other-company objects, factory-scoped relationships, user and invitation boundaries, dataset/model/prediction/RAG/report/billing access, and expected 401/403/404/409 behavior. The full backend suite passes; no tenant-boundary failure was observed.

## 7. API and error posture

The backend contains 202 declared production-facing route handlers. FastAPI validation, typed schemas, permission dependencies, company-scoped repository queries, pagination where list volumes require it, authentication and mutation rate limits, upload limits, safe error mappings, and disabled production API docs are established patterns. Automated tests include broad 400/401/403/404/409/422/429 coverage. Public responses should continue to omit stack traces, SQL, filesystem paths, credentials, tokens, raw provider payloads, and unnecessary internal topology.

Before a future release, regenerate and diff OpenAPI, review every new endpoint for authentication, object-level tenant scope, limits, safe errors, pagination, and audit behavior, and remove dead routes only through a reviewed change.

## 8. Security posture

- HTTPS redirects are active; the certificate matched the production hostname and was valid from 2026-07-29 through 2026-10-27.
- HSTS, CSP, frame denial, MIME sniffing prevention, referrer policy, and permissions policy were observed.
- Production payment integration is fail-closed and disabled.
- Current Python dependency audit found no known vulnerabilities; current npm audit found none.
- Bandit found 32 low-severity findings, zero medium, and zero high. Existing release evidence covers Gitleaks, Semgrep, Trivy, containers, and SBOM/license collection.
- Authentication uses password hashing, rotating server-managed sessions, secure production cookies, verification/reset expiry, generic recovery responses, and rate limits.
- Upload/RAG/reporting boundaries are validated and sensitive logging is redacted by design.
- No credential or private-key signature was found by the audit's bounded repository text scan. Ignored local environment and backup files remain sensitive and must never be committed.

`SEC-2026-002` is approved only for the frozen revision through 2026-08-26 under its compensating controls. Re-scan and close, renew, or replace it before expiry or any new release. `SEC-2026-001` and `SEC-2026-003` were closed on 2026-08-12 after Black and npm audit passed without their former suppressions.

## 9. Backup and recovery

Current verified state is PASS: application-level encrypted backup, private off-host S3 copy, checksum comparison, restore-reader retrieval, decryption in disposable storage, isolated PostgreSQL restore, readable schema/data, cleanup, and preserved S3/local copies.

The dedicated bucket controls were previously verified as Block Public Access, BucketOwnerEnforced, versioning, default SSE-KMS with the dedicated key, TLS-only policy, 14-day current/noncurrent expiry, and incomplete multipart cleanup. The EC2 writer role is prefix-scoped; the separate restore-reader path is used for recovery validation. Never put the passphrase, AWS credentials, or object URL in Git or a ticket.

Historical backup reports that predate the completed S3 gate are not current operational truth. Use the current runbook and the latest dated evidence.

## 10. Deployment, migration, and rollback

The supported deployment entry point is:

```bash
./scripts/deploy-production.sh --env-file .env.production --https
```

It validates Compose, pulls/builds, waits for data services, runs `alembic upgrade head`, starts services, recreates the proxy, and verifies production. A deployment requires an approved clean revision, backup, rollback revision, two-person review, maintenance/monitoring window, and explicit migration authorization. This audit did not run it.

Application rollback uses `scripts/rollback-production.sh REVISION --env-file .env.production`; it prepares an isolated worktree, checks PostgreSQL image compatibility, leaves volumes and migrations unchanged, and verifies health. Never downgrade production migrations as a routine rollback. For schema-incompatible changes, use a reviewed roll-forward plan or an explicitly approved disaster-recovery procedure.

The migration chain has one head: `0033_billing_phase2_contracts`. Production remained at that revision throughout the audit.

## 11. Capacity and scaling triggers

The approved launch envelope is 1–20 initial users with at most one actively executing training job. Existing benchmark evidence passed smoke, normal, stress, and soak scenarios without request failures; a 20-VU spike exceeded the p99 target at 3.43 seconds. A later isolated report measured higher conditional capacity, but it does not supersede the conservative launch envelope.

Review capacity when any of the following persists: CPU above 70%, memory above 75%, disk above 70% or fast growth, database pool above 70%, queue oldest-age outside the runbook target, p95/p99 latency or 5xx SLO burn, repeated worker retry/dead-letter events, or more than 20 active users. Scale only after identifying the bottleneck. Preserve the one-training-job constraint until a multi-worker/load/locking validation is approved.

## 12. Public website, SEO, brand, and contact

The candidate adds a semantic, responsive FactoryMind landing route at `/` with factual industrial-AI positioning and clear sign-in, account creation, and business-inquiry actions. Authenticated home moved to `/dashboard`. The HTML shell now includes the meaningful FactoryMind title and description, canonical `https://factorymind.ddnsgeek.com/`, index/follow directives, OpenGraph/Twitter metadata, structured data, favicon, Apple icon, and web manifest. Real `robots.txt` and `sitemap.xml` assets use the canonical production origin. Public claims avoid guaranteed prevention, zero hallucinations/downtime, PDF parsing, live IoT, automatic deployment, recurring billing, and live Paymob claims.

The approved contact details supplied for this release are used without inventing a physical address or different domain. These changes are candidate state only until an authorized deployment; the frozen production revision has not changed.

After deployment, the owner must verify the exact HTTPS origin in Google Search Console, submit `https://factorymind.ddnsgeek.com/sitemap.xml`, inspect/request indexing for the canonical root, and monitor coverage/Core Web Vitals. The owner should also verify the domain in Bing Webmaster Tools and link the exact origin from the intended LinkedIn presence. Verification and ranking are not claimed by this handoff.

## 13. UX, responsive, accessibility, and browser evidence

Curated desktop/mobile screenshots and existing frontend tests support responsive navigation, labeled forms, visible focus treatment, semantic headings, accessible names, theme switching, error text, and representative dark/light layouts. No P0/P1 accessibility blocker was found in code/evidence. A full keyboard/screen-reader/contrast audit remains advisable before general availability, especially modal focus restoration, live error announcements, chart alternatives, and future RTL/localization.

Fresh automated critical-journey validation passed in Chromium, Firefox, and WebKit. Each engine recorded 89 passes, 23 explicit real-staging-only skips, and zero failures. A WebKit run exposed and closed a dark-theme primary-hover contrast defect, a test focus-policy assumption, and missing lazy-route render synchronization. The in-app interactive browser remained unavailable and is recorded as a tooling limitation, not an engine failure.

## 14. Test and quality summary

Closure results against the release-candidate tree:

| Gate                                   | Result                                                                                                                                        |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Backend pytest                         | PASS — 1,106 passed, 3 skipped                                                                                                                 |
| Focused RAG regression/quality         | PASS — 19 passed; capability status now uses the canonical `local_extractive` / `grounded-extractive-v2` constants                            |
| Playwright Chromium                    | PASS — 89 passed, 23 real-staging-only skipped                                                                                                |
| Playwright Firefox                     | PASS — 89 passed, 23 real-staging-only skipped                                                                                                |
| Playwright WebKit                      | PASS — 89 passed, 23 real-staging-only skipped                                                                                                |
| Frontend ESLint                        | PASS                                                                                                                                          |
| Frontend Prettier                      | PASS                                                                                                                                          |
| Frontend TypeScript                    | PASS                                                                                                                                          |
| Frontend release build/budget          | PASS — 308,867-byte initial JS; 360,093-byte total initial assets                                                                             |
| Ruff                                   | PASS                                                                                                                                          |
| Black                                  | PASS — 475 files unchanged                                                                                                                    |
| mypy                                   | PASS — 305 source files                                                                                                                       |
| `pip check`                            | PASS                                                                                                                                          |
| Alembic heads                          | PASS — one head at `0033_billing_phase2_contracts`                                                                                            |
| Compose base/staging/production config | PASS using `.env.example` placeholders                                                                                                        |
| Python production/local audits         | PASS — no known vulnerabilities; local project package is not published on PyPI                                                              |
| npm dependency audit                   | PASS — no high/critical vulnerabilities                                                                                                       |
| Bandit                                 | PASS at release severity — 0 medium/high; 32 low findings                                                                                     |

The 23 skipped cases per browser are guarded real-backend/staging scenarios and were not forced against production. Earlier frozen-release evidence separately records 23/23 real-backend browser cases, security scans, and safe load testing. Total current automated browser outcomes are 267 passed, 69 intentionally skipped, and zero failed.

## 15. Repository and configuration handoff

The closure sprint reviewed the pre-existing 109 tracked changes and 16 untracked groups. Legitimate product, security, operational, documentation, test, and protected evidence changes are included in the single closure candidate. Two byte-identical generated media trees, their zip, and duplicate temporary demo assets were moved recoverably to ignored `.local-artifacts/factorymind-closure-20260812/`; they were not treated as source or deleted. `.gitignore` now prevents those raw generators from re-entering the candidate. Protected `artifacts/screenshots/phase-h-*.png`, `BILLING_AUDIT.md`, and curated final-acceptance evidence remain preserved.

The release candidate is the commit containing this handoff; obtain its identifier with `git rev-parse HEAD`. A clean `git status --short`, bounded secret scan, and final diff review are required immediately after that local commit and before any push or deployment.

Keep `.env.production`, passphrases, AWS credentials, test passwords, local backups, caches, and generated deployment state ignored. Preserve protected `artifacts/screenshots/phase-h-*.png` and `BILLING_AUDIT.md`. Review duplicate video/screenshot packages and stale reports deliberately; do not bulk-delete evidence.

The exhaustive variable contract is `.env.example` plus validated settings. Operational categories are:

| Class                                 | Examples                                                                                                                      |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Required production identity/security | `APP_ENV`, `ENVIRONMENT`, public/API URLs, allowed hosts/CORS, database/Redis URLs, secret/JWT values, secure-cookie settings |
| Required production email             | provider, sender/reply/support addresses, provider secret, retry/reconciliation controls                                      |
| Required recovery                     | backup target/URI, SSE-KMS selector/key identifier, retention, passphrase supplied only at runtime                            |
| Required worker/storage               | dataset/model/AI/MLflow roots, queue names, retry/stale limits, one-worker/global-slot controls                               |
| Production-only                       | HTTPS domain/ports, observability environment, external receiver secrets when approved                                        |
| Optional feature controls             | tracing, schedules, retention/reconciliation intervals, demo switches (off in production)                                     |
| Development/test only                 | capture email, exposed local tokens, demo tools, local seed credentials, fixture providers                                    |
| Sandbox-only                          | Paymob sandbox credentials/callbacks and sandbox compose values; never load into production                                   |

Dangerous defaults to continue preventing in production: insecure cookies, wildcard hosts/CORS, enabled API docs/demo tools, exposed verification/reset tokens, local email capture, and any payment provider other than `disabled`. The existing production environment file was not inspected or modified during this audit.

## 16. Evidence index

- [Final screenshot package](docs/final-acceptance/screenshots/README.md)
- [Final acceptance checklist](docs/FINAL_ACCEPTANCE_CHECKLIST.md)
- [Production runbook](docs/PRODUCTION_RUNBOOK.md)
- [Release validation](docs/release/release-validation-report.md)
- [Final test evidence](artifacts/final-test-report.md)
- [Capacity recommendations](artifacts/capacity-recommendations.md)
- [Security review](artifacts/security-review.md)
- [Security exception register](docs/security/security-exception-register.md)
- [Backup and recovery design](docs/backups-and-disaster-recovery.md)
- [Operational readiness](artifacts/operational-readiness-report.md)
- [Billing model](docs/product/billing-commercial-model.md)

Historical evidence may describe an earlier migration or blocked gate. The dated current verified state at the top of this document takes precedence; historical files should be retained but labeled superseded during repository cleanup.

## 17. Findings and closure decision

### P0 — 0

No active outage, production data integrity failure, known tenant breach, exposed secret, or failed recovery control was found.

### P1 — 2

1. **P1-LEGAL/OWNER:** Nine customer-facing legal documents remain explicit unapproved placeholders. The owner and qualified counsel must approve the contracting/licensing position, document content and versions, public contacts, and which documents require acceptance before unrestricted customer onboarding.
2. **P1-ALERT/EXTERNAL:** Alertmanager has only local null receivers. An owner-controlled, secret-managed TLS receiver and harmless warning/critical/resolved delivery proof are required before final operational closure.

### P2 — 2

1. Google Search Console and Bing ownership, sitemap submission, and canonical indexing verification require the domain owner after deployment; none is fabricated here.
2. `SEC-2026-002` must be rescanned and closed, renewed, or replaced before 2026-08-26 or any new image/revision approval.

### P3 — 4

1. Remove the synthetic “Demo production line” wording to avoid terminology drift.
2. Add a formal screen-reader and chart-alternative audit before broader localization.
3. Decide intentionally whether `www` should redirect; it is currently unconfigured.
4. Add screenshot checksums/automated visual-regression provenance to future evidence packages.

## 18. Legal classification and accepted operational risks

| Classification                | Current items                                                                                                                                                                                          | Required input / implementation                                                                                                                                                       |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `LEGAL_COUNSEL_REQUIRED`      | Terms, privacy, cookies, data processing, retention, refunds/cancellation, subscription/billing, AI limitations, support; governing law, subprocessors, transfers, required notices and acceptance scope | Approved versioned text, effective dates, legal entity/jurisdiction, approved claims and disclosures, and counsel's decision on acceptance versus notice                              |
| `OWNER_DECISION_REQUIRED`     | Software licence/delivery model, IP and asset provenance, approved contracting/support contacts, commercial/refund/support policy choices, Search Console/Bing/domain ownership                          | Named owner approvals and evidence references without secret values                                                                                                                  |
| `SAFE_TECHNICAL_IMPLEMENTATION` | After requirements are approved: publish immutable document versions; add explicit unchecked acceptance where required; persist document version, user, workspace, UTC timestamp and source; audit it | Backend-authoritative schema/API and immutable audit event, historical version retrieval, frontend validation, tenant/RBAC tests, and migration approval. This is blocked on scope. |

| Risk                               | Owner                                   | Acceptance                                            | Expiry / trigger                                                     | Controls                                                                                        |
| ---------------------------------- | --------------------------------------- | ----------------------------------------------------- | -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `SEC-2026-002` base-image findings | Security risk owner                     | Approved for frozen revision                          | 2026-08-26 or any revision/image change                              | Frozen revision, current scans, HTTPS, restricted exposure, monitoring, documented reassessment |
| External alert delivery unproven   | FactoryMind production operations owner | Controlled 1–20-user launch only, recorded 2026-08-12 | 2026-08-19 or before expanding beyond 20 users, whichever is earlier | Manual health checks, preserved logs, disabled payments, one training worker, named follow-up   |

The legal and external-alert P1 findings are not silently accepted risks.

## 19. Exact remaining closure actions

1. Have the business owner and qualified counsel approve the contracting entity, licence/ownership, all nine versioned legal documents, support/contact terms, and acceptance requirements. Then authorize the scoped acceptance/audit implementation if counsel requires it.
2. Configure one owner-controlled Alertmanager destination through secret management and TLS. Trigger uniquely named harmless warning and critical alerts, confirm delivery/grouping/resolution, remove the temporary rule, and retain sanitized proof.
3. Review the local closure commit, create immutable image digests, approve migration/application rollout and rollback evidence, and explicitly authorize deployment; this sprint did not deploy.
4. After deployment, verify the exact HTTPS property in Google Search Console and Bing, submit `/sitemap.xml`, inspect/request indexing for the canonical root, and retain ownership/submission evidence.
5. Reassess `SEC-2026-002` before 2026-08-26 or any new image/revision approval.

## 20. First 30 days of controlled production

- Daily: customer-path health, 5xx/latency, CPU/RAM/disk, database connections, Redis, queue depth/oldest age, worker heartbeat/retries, backup freshness, certificate horizon, email failures, and payment-disabled assertion.
- Every backup cycle: confirm encrypted S3 publication and alert on failure; perform checksum retrieval checks. Keep restore drills disposable.
- Weekly: review tenant/auth/audit anomalies, RAG refusals/citation issues, training duration/failures, data growth, support tickets, security advisories, and capacity triggers.
- Before day 7: prove external alert delivery and resolution notifications.
- Before 2026-08-26: close/renew `SEC-2026-002` with a new scan and authorized decision.
- At day 30: review SLO warm-up data, support load, backup history, restore evidence, capacity envelope, legal/SEO closure, and whether expansion beyond 20 users is justified.

Technical closure status: **PASS**. Project closure still requires P0 = 0 and P1 = 0. Current status: **OWNER ACTION REQUIRED**.
