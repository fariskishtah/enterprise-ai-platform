# Production hardening checklist

| Workstream | Status | Evidence or blocker |
| --- | --- | --- |
| Baseline and safety | Validated | Branch and merged-main ancestry verified at `83110eb`; migration head `0021`. |
| Production and demo separation | Validated | Production denial, staging enablement, hidden navigation, seed refusal, and explicit credential requirement pass focused checks. |
| Professional UI polish | Implemented | Existing semantic surfaces were retained; account/support states and all target viewport gates are in focused browser coverage. |
| Semantic sidebar icon motion | Validated | Central mappings, stable layout, keyboard feedback, and reduced-motion behavior passed focused browser checks. |
| Profile and account menu | Validated | Disclosure behavior, outside click, Escape, keyboard navigation, profile, mobile layout, and explicit logout passed focused checks. |
| Contact Support and Resend | Implemented | Persistence, tenant scope, escaping, idempotency, provider failure, admin retry, and audit pass; real Resend delivery awaits deployment credentials/domain verification. |
| PDF and chart quality | Validated | A4 vector PDF, labelled chart, metadata, page footer, XLSX typing/styling, CSV safety, extraction, and rendered-image inspection passed. |
| Realistic data and training | Validated | 1k/50k/250k deterministic generation observed; bounded import, replay, three-job queue, prediction, and reporting workflows passed. |
| Load and soak | Validated | Smoke, normal, stress, import, reporting, training, and a 30-minute authenticated five-user soak passed bounded thresholds. |
| Failure and recovery | Validated | Backend, frontend, and Redis recovered under bounded health checks; stale queued broker delivery was reproduced, repaired, and covered by focused tests plus real reconciliation. |
| Domain and server preparation | Implemented | Exact HTTPS URLs/hosts/origins and cookie intent are validated; external TLS, DNS, object storage, password-reset email, and Resend remain deployment work. |
| Full journey review | Validated | Mock browser coverage passed 42 tests with 23 intentional real-backend skips; the disposable real-backend suite passed all 23 journeys. |
| Unified final validation | Validated | `./scripts/validate-release.sh --full --allow-dirty` exited 0 on 2026-07-24; observed evidence is recorded in `production-hardening-validation-report.md`. |
