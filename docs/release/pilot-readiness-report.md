# Controlled Pilot Readiness Report

## Candidate

- Version: 0.9.0
- Branch: `pilot-readiness-foundation`
- Commit: uncommitted working-tree candidate
- Environment: local disposable staging-like Docker Compose
- Recommendation: **Eligible for reviewed internal staging / controlled pilot;
  not approved for production**

## Validation result

The final unified validation completed with exit code 0 on 2026-07-24 using
Node.js 22.22.2:

```bash
eval "$(fnm env --shell bash)"
fnm use 22
./scripts/validate-release.sh --full --allow-dirty
```

Observed results:

- backend: 789 passed, 3 skipped;
- fixture browser/accessibility suite: 36 passed, 9 real-backend tests skipped
  until the disposable runtime stage;
- real-backend browser suite: 9 passed;
- production smoke: health, readiness, documentation policy, login, current
  user, hierarchy read, and logout passed; the destructive/charged prediction
  smoke remained explicitly opt-in and was skipped;
- Ruff, Black, mypy, pip consistency, ESLint, Prettier, TypeScript, release
  build, frontend performance budget, and Compose configuration passed;
- pip-audit, npm audit, Bandit, Gitleaks, Semgrep, repository Trivy, actionable
  image Trivy scans, SBOM generation, and Nginx configuration passed.

## Migration and data isolation

- Alembic head is `0015_add_pilot_identity_audit`.
- A disposable PostgreSQL 16/pgvector database was exercised through
  `0014 -> 0015 -> 0014 -> 0015`; existing users were assigned to the migrated
  company, tenant indexes/checks were present, downgrade removed the new
  objects, and `alembic check` reported no pending operations.
- Focused identity/audit coverage passed 4/4; the broader authentication,
  manufacturing, dataset, model, prediction, monitoring, alert, retraining,
  AutoML, and RAG scope set passed 115/115.
- Cross-company factory, machine, model-schema, machine-risk, user-management,
  and audit reads return no other-company data. Company administrators cannot
  mutate users outside their company, and the last active company
  administrator cannot be demoted or deactivated.

## Identity, session, and audit controls

- Password reset request responses do not reveal account existence.
- Reset tokens are stored hashed, expire, and are single-use.
- Password change revokes prior refresh tokens; revoke-other-sessions and user
  deactivation revoke the relevant refresh sessions.
- Audit reads are company-scoped, filterable, paginated, stable-ordered, and
  exportable as bounded CSV or JSON. No normal update/delete audit API exists.
- Critical tested events include identity lifecycle, manufacturing hierarchy,
  dataset/version registration, training completion, feature-schema save,
  model aliasing, structured prediction, alert acknowledgement/resolution,
  knowledge-base lifecycle, and retraining domain actions.
- Audit metadata sanitization excludes password, token, credential,
  authorization, secret, document-text, and prediction-payload keys.

## Deterministic pilot data and flow

The first fresh seed created:

- one company; admin, engineer, and operator users;
- one factory, one machine, two sensors, and 24 bounded readings;
- one tabular dataset version and one document dataset version;
- one succeeded Ridge regression training job, model version 1, two-feature
  schema, and challenger alias;
- one compatibility prediction audit, normal and warning structured-risk
  cases, one acknowledged alert with operator note, and one ready knowledge
  base.

The immediate second seed created no domain resources, no readings, no dataset
versions, no training job, no model/alias/prediction duplicate, and no
structured-risk duplicate.

The browser pilot verified role-aware navigation, company user administration
and audit visibility, schema-driven prediction, warning risk and recommended
operator action, training/evaluation metrics, bounded AutoML, Dataset Registry,
RAG retrieval, citations, and grounded chat. Missing feature names, unknown
feature names, nonnumeric values, and feature-count/schema mismatches return
validation errors in focused backend coverage.

## Recovery evidence

- Encrypted backup: `pilot-20260724T023843Z-a28d8563`.
- Disposable restore: `restore-20260724T023905Z-64b3325b`.
- Restored revision: `0015_add_pilot_identity_audit`.
- Restored counts: one company, three users, one factory, two datasets, and one
  training job.
- Manifest, archive paths, and checksums passed; restored backend readiness and
  authenticated smoke passed.

See [restore-validation-report.md](restore-validation-report.md) for the
operator evidence summary.

## Active security exceptions

- `SEC-2026-001`: development-only Black 24.10.0 advisories
  `PYSEC-2026-2120` and `PYSEC-2026-2121`; expires 2026-08-31.
- `SEC-2026-002`: listed unfixed Debian findings in the official
  `python:3.12-slim` backend/worker base; expires 2026-08-06. The unfiltered
  report is retained and every fixed HIGH/CRITICAL finding remains blocking.

## Remaining limitations and release blockers

- The 119-entry working tree is uncommitted and requires reviewable commits,
  code review, clean-tree CI, and staging approval before a pilot deployment.
- Production password-reset email delivery is not configured.
- MFA, OIDC/SAML, SCIM, invitation delivery, and platform-level tenant
  administration are unsupported.
- Customer data, risk thresholds, feature definitions, recommended actions, and
  maintenance procedures are not operationally validated.
- Automatic sensor aggregation into the model feature vector is not provided.
- CMMS/work-order integration and external alert delivery are not provided.
- Backup scheduling, off-host S3-compatible custody, retention/object lock,
  restore drills, and operational paging require deployment configuration.
- The two active security exceptions must be reviewed by their expiry dates.
- High availability, multi-region recovery, and general multi-tenant SaaS
  certification remain outside this controlled-pilot scope.

This evidence supports a controlled pilot only after review and clean CI. It
does not support a production release.
