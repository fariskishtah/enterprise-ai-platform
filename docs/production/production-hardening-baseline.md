# Production hardening baseline

Recorded 2026-07-24 before product changes.

## Repository

- Branch: `production-hardening`
- Baseline and current commit: `83110eba9a482e7ca90303b0789554c34df6df39`
- Remote baseline: `origin/main` at the same commit
- Working tree: clean
- Alembic head: `0020_add_executive_reports`

## Existing safeguards

- `demo_tools_enabled` defaults to `false`.
- Production settings reject enabled demo tools, enabled API documentation, local
  CORS origins, wildcard CORS, and credential-bearing origins.
- Demo API routes are protected by authenticated feature and role checks.
- Frontend feature discovery fails closed and hides disabled demo navigation.
- Production Compose removes internal public ports, uses an unprivileged
  read-only runtime, drops capabilities, bounds resources, and rotates logs.
- HTTPS preparation, smoke verification, encrypted backup, disposable restore,
  source scanning, dependency scanning, image scanning, and unified validation
  scripts already exist.

## Current implementations

- Email: no supported outbound provider or narrow mail abstraction.
- Reports: synchronous bounded generation into existing root-confined object
  storage; authenticated one-hour downloads; dependency-free CSV, XLSX, and PDF.
- PDF: A4 pages, escaped text, page numbers, and simple vector bars. It lacks
  labelled axes, legends, deliberate report sections, and robust visual checks.
- Profile: the top-right identity control invokes logout immediately. Settings
  contains password and session lifecycle controls.
- Sidebar: centralized navigation and icons exist, but no semantic motion mapping.
- Load testing: one pinned k6 tool with bounded smoke, API, authentication,
  training, data/RAG, stress, and soak entry points.

## Last merged validation evidence

- Backend: 800 passed, 3 skipped.
- Mock-backed browser/accessibility: 36 passed, 22 real-backend cases skipped.
- Real-backend browser: 22 passed.
- Migration upgrade/downgrade/re-upgrade and Alembic check passed.
- Seed repetition, encrypted backup, disposable restore, security scans, image
  scans, and production smoke passed.

These totals are inherited evidence from the merged Sprint 3–5 validation; they
were not rerun during this baseline-only checkpoint.

## Observed blockers

1. The demo seed script does not independently refuse a production environment.
2. Production Compose does not explicitly pass demo-disable or mail settings.
3. Clicking the topbar identity control logs out without opening an account menu.
4. No Contact Support persistence, delivery status, or Resend provider exists.
5. User records have no optional full-name field.
6. PDF charts are basic unlabeled bars and require stronger rendering validation.
7. Production-oriented journey, load, soak, recovery, and real-domain evidence
   for this milestone has not been observed.
