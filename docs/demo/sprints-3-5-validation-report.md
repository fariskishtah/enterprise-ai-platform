# Sprints 3–5 validation report

Status: validated for reviewed internal staging.

## Observed results

- Focused Sprint 3–5 backend tests: **6 passed**, 0 failed.
- Related pre-existing backend tests: **18 passed**, 0 failed.
- Focused real-backend Sprint 3–5 browser acceptance: **4 passed**, 0 failed.
- Combined real-backend browser suite: **22 passed**, 0 failed in 1.1 minutes,
  with a single worker to isolate the stateful deterministic machine scenario.
- Backend Ruff, Black, and Mypy checks passed.
- Frontend ESLint, Prettier, TypeScript, and production build passed.
- Disposable PostgreSQL migration validation passed for upgrade from 0017 to 0020,
  downgrade from 0020 to 0017, and re-upgrade to 0020. `alembic check`
  reported no pending upgrade operations.
- The seed ran twice. The second run reused the user, hierarchy, datasets,
  knowledge base, training job, model, aliases, prediction, imports, layout,
  report, alert, and operational records; it created zero sensor readings and
  zero structured risk cases.
- Encrypted backup checksums passed for the database and all four artifact
  archives. Disposable restore validation passed.

## Unified validation

Command:

```bash
./scripts/validate-release.sh --full --allow-dirty
```

Observed exit code: **0**.

- Backend: **800 passed, 3 skipped**, 0 failed in 117.21 seconds.
- Mock-backed browser/accessibility suite: **36 passed, 22 skipped**, 0 failed
  in 20.8 seconds. The skipped cases require a real backend.
- Real-backend browser suite: **22 passed**, 0 failed in 1.1 minutes.
- Production smoke: health, readiness, documentation policy, login, identity,
  hierarchy, and logout passed. Prediction smoke was intentionally skipped
  because it requires explicit opt-in.
- Dependency audits passed. The backend audit retained the two documented
  security exceptions and skipped only the local, unpublished application
  package.
- Bandit passed; Gitleaks found no leaks; Semgrep ran 225 rules over 397 files
  with zero findings.
- Repository, backend image, frontend image, and reverse-proxy image Trivy gates
  passed. Candidate images built, SBOM generation passed, and Nginx
  configuration tests passed.
- The isolated staging runtime, seed repetition, encrypted backup, disposable
  restore, real-backend browser acceptance, and production smoke passed.
- Validation-owned containers, networks, and disposable volumes were removed
  after the run. No pre-existing Docker project was started, stopped, or
  modified.

Evidence:

- `artifacts/release/sprints-3-5-full-validation.log`
- `artifacts/release/restore-20260724T123936Z-bb6d184d.txt`

## Current limitations

- Anomaly detection is not exposed by Guided AI because no approved backend training
  contract is present.
- Scheduled email delivery fails closed because no supported mail provider exists.
- Live demo updates use bounded polling rather than a new real-time infrastructure
  stack.
- Guided AI hands an eligible dataset to the existing Training Jobs studio; it
  does not introduce a second training engine.
- Reports contain only metrics supported by current company-scoped records and
  make no ROI, savings, or unsupported efficiency claims.
- The current recommendation is **ready for reviewed internal staging**, not
  controlled pilot or production.
