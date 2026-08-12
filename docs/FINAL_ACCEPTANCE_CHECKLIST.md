# FactoryMind final acceptance checklist

Reusable before every major production release. Replace the result/evidence for the candidate being approved; never inherit a PASS from an older revision. `FAIL` blocks acceptance when classified P0/P1. `N/A` requires a written reason and approver.

Current audit: 2026-08-12

Frozen production revision: `af3f48f4247809bae45cb06957799bf883f6c68c`
Current decision: **TECHNICAL PASS / OWNER ACTION REQUIRED**

## Release identity and safety

| Result | Check                                                                                         | Current evidence                                                                   |
| ------ | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| PASS   | Production URL, commit, image references, owner, and UTC window recorded                      | [Handoff](../FINAL_PROJECT_HANDOFF.md)                                             |
| PASS   | Candidate is a clean, reviewed, reproducible Git commit                                       | Single local closure commit; verify identifier and clean status before push/deploy |
| PASS   | Production health, container health, migration, and payment-disabled state verified read-only | [Handoff §3](../FINAL_PROJECT_HANDOFF.md#3-architecture-and-production-deployment) |
| PASS   | No destructive production action performed during acceptance                                  | Audit record in handoff                                                            |
| PASS   | Rollback revision and migration-compatible approach documented                                | [Runbook §4](PRODUCTION_RUNBOOK.md#4-application-image-rollback)                   |

## Public entry, SEO, brand, and legal

| Result | Check                                                                                                                           | Current evidence                                                                                         |
| ------ | ------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| PASS   | New visitor sees an accurate public product explanation and clear signup/login actions                                          | Candidate landing route and three-engine `public-seo` acceptance                                        |
| PASS   | HTTPS redirect, hostname-valid certificate, HSTS, and security headers                                                          | Read-only HTTP/TLS audit summarized in [handoff §8](../FINAL_PROJECT_HANDOFF.md#8-security-posture)      |
| PASS   | Product title, description, canonical, robots meta, OpenGraph/Twitter, icons, and structured data reviewed                      | Candidate metadata/assets and [handoff §12](../FINAL_PROJECT_HANDOFF.md#12-public-website-seo-brand-and-contact) |
| PASS   | Real `robots.txt`, `sitemap.xml`, and manifest return correct content/types                                                     | Static candidate assets plus three-engine HTTP assertions                                                |
| PASS   | No accidental noindex/disallow; canonical pages are technically crawlable                                                       | Public HTTP audit; indexing is separate from ranking                                                     |
| FAIL   | Production domain ownership/submission/indexing is recorded after candidate deployment                                          | Search Console/Bing owner action remains; verification is not fabricated                                |
| FAIL   | Versioned counsel-approved legal documents and required acceptance/audit behavior are live                                      | Public pages explicitly say unapproved placeholder                                                       |
| FAIL   | Contracting identity, support contact, brand ownership/licence, and approved public contact are consistent                      | [Legal readiness checklist](release/legal-readiness-checklist.md) remains open                           |
| PASS   | Public claims avoid zero-hallucination/downtime, PDF, live IoT, recurring billing, automatic deployment, and live Paymob claims | Code/docs review; recheck final copy before release                                                      |

## Customer lifecycle and UX

| Result | Check                                                                                                            | Current evidence                                                       |
| ------ | ---------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| PASS   | Signup, duplicate registration, email verification/resend/expiry/reuse, and welcome flow                         | Current production acceptance plus auth tests/screenshots              |
| PASS   | Login, invalid login, logout, refresh/session continuity, expiry, and password reset                             | Auth suite and [auth evidence](final-acceptance/screenshots/README.md) |
| FAIL   | First-time customer can legally and clearly complete onboarding                                                  | Legal acceptance/public entry blocker                                  |
| PASS   | Empty/loading/error/recovery states and back/refresh behavior reviewed                                           | Frontend E2E and curated evidence                                      |
| PASS   | Dark/light and representative desktop/mobile layouts reviewed                                                    | [Screenshot evidence](final-acceptance/screenshots/README.md)          |
| PASS   | Fresh critical journeys pass in Chromium, Firefox, and WebKit                                                    | Each engine: 89 passed, 23 explicit real-staging-only skips, 0 failed |
| PASS   | Pragmatic labels, focus, headings, contrast, keyboard semantics, errors, alt/ARIA reviewed with no P0/P1 blocker | Code/test/evidence review; deeper screen-reader audit remains P3       |

## Core manufacturing and data workflow

| Result | Check                                                                                                                          | Current evidence                                                                                        |
| ------ | ------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| PASS   | Canonical hierarchy is Factory → Machine/Production Asset → Sensor                                                             | API/models/tests and [hierarchy screenshot](final-acceptance/screenshots/product-factory-hierarchy.png) |
| PASS   | No `ProductionLine` entity/API/UI contract exists                                                                              | Repository search; one synthetic fixture label is P3 wording only                                       |
| PASS   | Factory, machine, and sensor create/edit/validation/relationship/deletion/invalid-ID behavior                                  | Manufacturing API tests                                                                                 |
| PASS   | Structured CSV select/parse/map/validate/import handles types, timestamps, missing/invalid fields, unknown sensors, and replay | ETL/API tests and onboarding screenshots                                                                |
| PASS   | Data quality findings, remediation, empty/invalid inputs, and representative larger data behavior                              | Data quality/ETL evidence                                                                               |
| PASS   | Dataset registry metadata, ownership, lifecycle, selection, training availability, invalid/missing dataset, and tenant scope   | Dataset suite and [registry screenshot](final-acceptance/screenshots/product-dataset-registry.png)      |

## AI, knowledge, monitoring, and reports

| Result | Check                                                                                                        | Current evidence                                                |
| ------ | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------- |
| PASS   | Guided AI configuration, submission, queue, success/failure/cancel/retry, and result                         | AI governance/worker tests and screenshots                      |
| PASS   | At most one training message executes on the production worker at a time                                     | Compose `--processes 1 --threads 1`; AutoML global slot 1       |
| PASS   | Model registry metadata, exact dataset/training relation, selection, invalid IDs, and tenant scope           | Model/governance tests                                          |
| PASS   | Evaluation shows only implemented metrics with safe missing/error states                                     | Evaluation tests/evidence                                       |
| PASS   | Prediction validates feature inputs/types/model/auth and returns safe formatted output                       | Prediction tests/evidence                                       |
| PASS   | Knowledge ingestion truthfully supports UTF-8 text; empty/invalid/encoding/failure/READY and tenant behavior | Dataset/RAG tests; no PDF claim                                 |
| PASS   | RAG relevant answers have citations/source relation and unsupported requests explicitly refuse               | RAG quality/tenant tests and grounded/refusal screenshots       |
| PASS   | Monitoring displays implemented prediction/model signals and truthful empty/error states                     | Monitoring tests/evidence; no invented OEE/MTBF/MTTR/energy/IoT |
| PASS   | Retraining behavior is identified as governed scheduling/request workflow, not automatic deployment          | Retraining tests/docs                                           |
| PASS   | Executive dashboard and reports use implemented data, roles, empty states, retrieval, and tenant checks      | Dashboard/report tests/screenshots                              |

## RBAC, audit, settings, and billing

| Result | Check                                                                                                                        | Current evidence                                                                                          |
| ------ | ---------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| PASS   | Owner/admin/engineer/operator/analyst/viewer permissions and route guards match backend enforcement                          | `test_six_role_rbac.py` and permission matrix                                                             |
| PASS   | Representative swapped tenant/factory/object IDs cannot leak data                                                            | Tenant-aware API/service tests                                                                            |
| PASS   | Invitations, verification, role changes, removals, limits, and last-owner protection                                         | Team/invitation/RBAC tests                                                                                |
| PASS   | Audit log includes actor/time/tenant/action, controlled visibility, and safe metadata                                        | Audit tests and [audit screenshot](final-acceptance/screenshots/product-audit-log.png)                    |
| PASS   | Settings controls are functional/scoped and unfinished options are not misleading                                            | Settings UI evidence and API tests                                                                        |
| PASS   | Starter/Professional/Enterprise prices, quotas, gating, expiry/active behavior, and audit events match the canonical catalog | Billing phase tests and [billing evidence](final-acceptance/screenshots/product-billing-entitlements.png) |
| PASS   | Renewal is described as prepaid/manual, not recurring                                                                        | Billing copy/evidence                                                                                     |
| PASS   | `PAYMENT_PROVIDER=disabled`; no real Paymob transaction performed                                                            | Live container assertion                                                                                  |

## API, errors, security, and configuration

| Result | Check                                                                                                                          | Current evidence                                                                                                        |
| ------ | ------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------- |
| PASS   | Route inventory reviewed for auth, object scope, validation, pagination, limits, status/error shape, and sensitive fields      | 202 route handlers; broad API tests                                                                                     |
| PASS   | Representative 400/401/403/404/409/422/429 and safe 500 cases reveal no stack/SQL/path/secret/token data                       | Backend test coverage                                                                                                   |
| PASS   | Auth/mutation rate limits, CORS, cookies, CSRF posture, upload/request limits, IDOR/injection/XSS/SSRF-relevant paths reviewed | Security/config/auth tests and [security evidence](../artifacts/security-review.md)                                     |
| PASS   | Current Python and npm dependency audits meet policy                                                                           | No known Python/npm vulnerabilities at audit time                                                                       |
| PASS   | Static security scan has no medium/high Bandit finding and frozen container exception is approved                              | 0 medium/high; `SEC-2026-002` to 2026-08-26                                                                             |
| PASS   | Security exception register is current and every exception is closed or unexpired with accurate evidence                       | `SEC-2026-001`/`003` closed 2026-08-12; `SEC-2026-002` remains approved only through 2026-08-26                         |
| PASS   | Required/optional/dev/sandbox/production variables are documented without values; dangerous defaults fail closed               | `.env.example`, settings validation, [handoff §15](../FINAL_PROJECT_HANDOFF.md#15-repository-and-configuration-handoff) |
| PASS   | Secret scan/evidence review finds no committed key credential signature; ignored sensitive files remain uncommitted            | Bounded audit plus prior Gitleaks/Trivy evidence                                                                        |

## Infrastructure, recovery, observability, and performance

| Result | Check                                                                                                                     | Current evidence                                                                           |
| ------ | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| PASS   | EC2 type/CPU/RAM/disk, services, limits, health, restart counts, networks, volumes, proxy, DB, Redis, and worker verified | [Handoff §3](../FINAL_PROJECT_HANDOFF.md#3-architecture-and-production-deployment)         |
| PASS   | Reverse-proxy external network relationship is declarative and survives recreation                                        | Live network inspection and Compose configuration                                          |
| PASS   | Encrypted local backup and private SSE-KMS S3 copy pass checksum/retrieval/isolated restore/read/cleanup                  | Current verified backup state and [runbook §6–7](PRODUCTION_RUNBOOK.md#6-encrypted-backup) |
| PASS   | S3 public block, ownership, versioning, TLS-only, lifecycle, writer, and restore-reader controls are recorded             | Current verified backup gate                                                               |
| FAIL   | External warning/critical/resolved delivery reaches the owned on-call receiver                                            | Unproven; local receivers are null                                                         |
| PASS   | Logs, healthchecks, CPU/RAM/disk observation, worker/queue/backup/HTTP failure procedures exist                           | [Production runbook](PRODUCTION_RUNBOOK.md)                                                |
| PASS   | Existing safe performance evidence supports controlled 1–20-user launch and documents spike limitation                    | [Capacity recommendations](../artifacts/capacity-recommendations.md)                       |
| PASS   | Scaling triggers and one-training-job constraint are documented; no resize performed                                      | Handoff/runbook                                                                            |

## Database, Redis, workers, Compose, and repository

| Result | Check                                                                                                                                        | Current evidence                                      |
| ------ | -------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| PASS   | One migration head at `0033_billing_phase2_contracts`; chain/schema tests pass; production not migrated by audit                             | Alembic check and live read-only verification         |
| PASS   | Tenant keys, uniqueness/indexes/FKs/nullability/cascade behavior reviewed through models/migrations/tests                                    | Migration/domain suites                               |
| PASS   | Redis queue retry/timeout/stale/idempotency/reconciliation and worker restart behavior tested                                                | Worker/background integration tests                   |
| PASS   | Base/staging/production Compose renders from `.env.example`; healthchecks, explicit volumes/networks, and pinned runtime references reviewed | Compose config gate                                   |
| PASS   | Full backend suite passes                                                                                                                    | 1,106 passed, 3 skipped                              |
| PASS   | Frontend lint/format/type/build/budget pass                                                                                                  | Current audit gates                                   |
| PASS   | Backend lint and formatting pass                                                                                                             | Ruff pass; Black 475 files unchanged                  |
| PASS   | mypy, `pip check`, and migration head checks pass                                                                                            | Current audit gates                                   |
| PASS   | Repository is clean and contains no unexplained duplicates/stale generated artifacts                                                         | Raw duplicates moved recoverably under ignored `.local-artifacts/`; single closure commit |
| PASS   | Documentation is fully current and historical reports are clearly superseded                                                                 | Handoff/runbook/checklist updated for the candidate   |

## Evidence package

| Result | Check                                                                                                             | Current evidence                                                       |
| ------ | ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| PASS   | Sanitized final screenshot directory exists and covers required major milestones                                  | [29 PNG files plus provenance](final-acceptance/screenshots/README.md) |
| PASS   | Handoff document exists and includes architecture, workflows, operations, risks, tests, evidence, and 30-day plan | [Final handoff](../FINAL_PROJECT_HANDOFF.md)                           |
| PASS   | Production runbook contains all required incident/recovery procedures without secrets                             | [Production runbook](PRODUCTION_RUNBOOK.md)                            |
| PASS   | This reusable acceptance checklist exists                                                                         | This file                                                              |

## Finding decision

| Severity | Current count | Acceptance rule                                              |
| -------- | ------------: | ------------------------------------------------------------ |
| P0       |             0 | Must be 0                                                    |
| P1       |             2 | Must be 0                                                    |
| P2       |             2 | Must have owner/priority; accepted risks require date/expiry |
| P3       |             4 | May be backlog                                               |

Current P1 findings are owner/external only: nine unapproved legal/customer-contract documents and unproven external Alertmanager delivery. Exact actions are in [handoff §19](../FINAL_PROJECT_HANDOFF.md#19-exact-remaining-closure-actions).

## Approval record for the next release

Fill this section with no secret values:

| Field                                       | Value |
| ------------------------------------------- | ----- |
| Candidate commit/tag                        |       |
| Immutable image digests                     |       |
| Production migration before/after           |       |
| Backup ID and restricted evidence reference |       |
| Isolated restore evidence reference         |       |
| Test report reference                       |       |
| Security report and exception expiry        |       |
| Browser/viewport evidence reference         |       |
| External alert delivery evidence            |       |
| Capacity envelope                           |       |
| Rollback revision/trigger                   |       |
| Change window (UTC)                         |       |
| Release owner                               |       |
| Independent reviewer                        |       |
| Risk owner approvals                        |       |
| P0/P1 counts                                |       |
| Final decision and timestamp                |       |

Final acceptance is allowed only when all applicable controls are evidenced for the exact candidate and P0 = 0, P1 = 0.
