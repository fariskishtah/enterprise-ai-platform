# Sprints 3–5 implementation checklist

This checklist tracks only the Smart Data Onboarding, Live Demo, and Executive
Reporting milestone. Statuses reflect implementation and observed validation,
not intended capability.

## Sprint 3 — Smart Data Onboarding and Guided AI

| Capability | Status | Notes |
| --- | --- | --- |
| Bounded CSV upload, preview, and safe storage | Implemented | Reuses root-confined dataset object storage. |
| Long- and wide-format column mapping | Implemented | Original headers preserved; confirmation required. |
| Pre-import data-quality report and export | Implemented | Bounded issue samples; JSON/CSV summaries. |
| Idempotent import state machine | Implemented | Company-scoped terminal state and explicit cancel rules. |
| Data-quality monitoring views | Implemented | Expert history and simplified report metrics. |
| Guided AI templates and readiness gate | Implemented | Only regression/classification-backed templates exposed. |
| Deterministic Sprint 3 seed data | Implemented | Small valid, warning, and rejected examples; existing completed training reused. |
| Focused backend and frontend validation | Validated | Backend 6/6 passed; real-backend browser acceptance passed. |

## Sprint 4 — Live Demo and Visual Factory Experience

| Capability | Status | Notes |
| --- | --- | --- |
| Feature-gated deterministic simulator | Implemented | Disabled by default and rejected in production. |
| Eight bounded scenario definitions | Implemented | Fixed values; no arbitrary scripts or infinite jobs. |
| Demo Control Center | Implemented | Admin/engineer control with one active scenario per machine. |
| Live operational updates | Implemented | Three-second bounded polling while active. |
| Company-scoped 2D factory layout | Implemented | Keyboard-accessible list fallback; no 3D or CAD import. |
| Authenticated read-only TV mode | Implemented | No editing or expert diagnostics. |
| Lightweight guided demo tour | Implemented | Optional, restartable, skippable, and remembered locally. |
| Tagged demo-only reset | Implemented | Exact generated-resource ledger; admin-only. |
| Focused backend and frontend validation | Validated | Backend lifecycle/RBAC and real-backend browser acceptance passed. |

## Sprint 5 — Executive Reporting and Communication

| Capability | Status | Notes |
| --- | --- | --- |
| Grounded executive dashboard | Implemented | No ROI, savings, or unsupported efficiency claims. |
| Bounded reporting periods | Implemented | UTC and custom ranges bounded to 366 days. |
| Six authorized report types | Implemented | Existing company-scoped operational and governance data only. |
| PDF, XLSX, and CSV exports | Implemented | Authenticated expiring download; formula-injection protection. |
| Bounded report schedules | Implemented | Daily, weekly, or monthly only; admin-only. |
| Email delivery behavior | Implemented | Fails closed because no supported provider is configured. |
| Deterministic incident summary | Implemented | Unknown facts are explicitly marked unknown. |
| Deterministic Sprint 5 seed data | Implemented | Successful report and failed unavailable-email schedule example. |
| Focused backend and frontend validation | Validated | Export, schedule, and real-backend download tests passed. |

## Final gate

| Capability | Status | Notes |
| --- | --- | --- |
| Migration cycle and disposable PostgreSQL validation | Validated | 0017 → 0020, 0020 → 0017, and 0017 → 0020 passed; Alembic reported no pending operations. |
| Deterministic seed run twice | Validated | Second run reused all records and created zero readings or risk cases. |
| Real-backend Playwright scenarios | Validated | 22/22 passed serially against the isolated staging runtime. |
| Unified release validation | Validated | Exit code 0; complete log retained under `artifacts/release/`. |
| Security and generated-artifact scans | Validated | Blocking source, dependency, secret, configuration, and image gates passed; runtime output remains ignored. |
