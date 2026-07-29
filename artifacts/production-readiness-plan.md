# Production readiness plan

Updated: 2026-07-29

Branch: `feature/production-saas-upgrade`

Candidate version: `0.9.0`

Classification: **release candidate only — production not approved**

## Current assessment

The repository is a validated controlled-pilot SaaS release candidate. Identity,
six-role authorization, tenant isolation, durable transactional email, Paymob
integration, subscription lifecycle, enforced entitlements, secure refresh-cookie
sessions, deployment validation, encrypted recovery, security scanning, load
evidence, operational runbooks, and legal-review placeholders are implemented.

The clean all-in-one release gate passes. That does not replace deployment-owned
acceptance. Real email and Paymob transactions, public DNS/TLS, immutable off-host
backup, external alert delivery, legal approval, and customer capacity acceptance
remain open. The local 20-VU abrupt-spike profile also exceeds its p99 target.

## Phase status

| Phase | Outcome | Remaining gate |
| --- | --- | --- |
| Product/identity/email foundation | Implemented and locally validated | Real verified-sender delivery; feedback/billing lifecycle wiring |
| Billing/entitlements | Implemented and locally validated | Credential-backed Paymob sandbox transaction and signed public callback |
| Public deployment | Compose/Nginx/TLS contracts pass | Public DNS, certificate, firewall, and external reachability evidence |
| Backup/recovery | Encrypted local backup and isolated restore pass | Immutable off-host publication and restore-owner sign-off |
| Security review | Automated gates pass under three expiring exceptions | Resolve accepted base/Router risks and progressive lockout/malware gaps |
| Capacity | Smoke/normal/stress/soak pass with zero request errors | Spike p99 remediation and deployment-sized certification |
| AutoML/workers | Duplicate middleware removed; one execution per job proved | None for controlled-pilot scope |
| Operations | Rules, dashboards, metrics, and runbooks validated | Real pager receiver, queue-age alert, backup-freshness alert |
| Legal | Explicit unapproved placeholders linked in product | Qualified counsel approval and versioned customer acceptance |
| Final validation | Clean full release gate passes | External gates above prevent production approval |

## Production blockers

1. Complete the Resend/SMTP acceptance procedure with deployment-owned credentials,
   a verified sender domain, a real acceptance recipient, provider event evidence,
   and the remaining feedback/billing notification wiring.
2. Complete a Paymob sandbox checkout/refund lifecycle using merchant-owned test
   credentials and a public HTTPS webhook endpoint.
3. Deploy the candidate behind authoritative DNS and a renewable trusted TLS
   certificate; validate redirects, headers, health, firewall posture, and public
   callback URLs externally.
4. Publish an encrypted backup to immutable off-host storage and restore from that
   object under the designated recovery owner.
5. Configure a real Alertmanager receiver and deliberately fire representative
   critical alerts. Add bounded queue depth/age and backup freshness/failure
   metrics and alerts.
6. Obtain legal approval for the terms, privacy, data-processing, refund, billing,
   retention, AI-limitations, cookie, and support documents. Record versioned
   customer acceptance where required.
7. Investigate the 3,430.82 ms local spike p99 result, set the deployment capacity
   envelope, and repeat capacity acceptance on production-sized infrastructure.

## Accepted and deferred risks

- `SEC-2026-001`: development-only Black advisories, expires 2026-08-15.
- `SEC-2026-002`: 23 unfixed backend-image occurrences across 12 Debian CVEs,
  expires 2026-08-06; actionable/fix-available scan is zero.
- `SEC-2026-003`: React Router RSC-only advisory in a static SPA deployment,
  expires 2026-08-15.
- No progressive account-specific login lockout.
- No malware quarantine/scanner for accepted CSV/plain-text uploads.
- Single-host deployment only; no HA or multi-region recovery.
- Deterministic lexical/extractive RAG only; no production semantic/LLM provider.

## Deployment acceptance sequence

1. Freeze a reviewed commit and rerun `./scripts/validate-release.sh --full` with
   Python 3.12 and Node 22.
2. Close or renew every security exception before its expiry date.
3. Inject secret-managed production configuration; never copy local `.env` or
   disposable acceptance credentials.
4. Deploy, migrate the empty/target database to `0031_entitlement_overrides`, and
   validate DNS/TLS and reverse-proxy behavior externally.
5. Complete email and Paymob sandbox acceptance with redacted evidence.
6. Publish and restore the off-host backup; record RPO/RTO and owner sign-off.
7. Fire alerts into the real on-call path and exercise incident, rollback, email,
   payment, database, Redis, worker, queue, disk, and recovery runbooks.
8. Repeat load acceptance at the approved capacity target and resolve the spike
   boundary.
9. Obtain legal and business approval. Only then may the release be classified as
   production approved.

## Evidence index

- `artifacts/final-production-acceptance-report.md`
- `artifacts/final-implementation-report.md`
- `artifacts/final-test-report.md`
- `artifacts/security-review.md`
- `artifacts/load-test-report.md`
- `artifacts/operational-readiness-report.md`
- `artifacts/email-acceptance-report.md`
- `artifacts/paymob-sandbox-acceptance-report.md`
- `artifacts/deployment-validation-report.md`
- `artifacts/backup-restore-validation-report.md`
