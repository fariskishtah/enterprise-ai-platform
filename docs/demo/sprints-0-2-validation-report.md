# Demo Product Sprints 0–2 Validation

Validation date: 2026-07-24

Branch: `demo-experience`

Baseline commit: `bd84694e2dc8`

Result: **PASS — exit code 0**

## Focused validation

- Operations migrations `0016` and `0017`: upgrade from `0015`, schema
  constraints and indexes, downgrade to `0015`, re-upgrade, and Alembic
  consistency passed.
- Backend product foundation, migration, and workflow tests: 5 passed.
- Backend Ruff and Black checks on affected Python passed.
- Frontend ESLint, Prettier, TypeScript, production build, and performance
  budget passed.
- Deterministic staging seed: the first run created 24 bounded sensor readings
  and the demo workflow; the second run created 0 readings and reused the
  datasets, training job, model, prediction audit, alert, action, feedback,
  note, and shift.
- Focused operations browser coverage: 9 passed, including role/mode behavior,
  action and alert workflows, timeline, shift handover, accessibility,
  responsive layouts, and cross-company denial.
- Combined real-backend browser gate after synchronization hardening: 18
  passed.

## Unified validation

Exact command:

```bash
fnm exec --using 22 bash -o pipefail -c \
  './scripts/validate-release.sh --full --allow-dirty 2>&1 | tee artifacts/release/demo-sprints-0-2-full-validation.log'
```

Observed results:

- Repository governance, shell syntax, Compose configuration, and migration
  head validation passed; the final head was
  `0017_add_alert_shift_workflow`.
- Backend: 794 passed, 3 skipped. The skips were pre-existing bounded test
  conditions; no backend test failed.
- Mock-backed Playwright: 36 passed, 18 skipped. The skipped cases are the 9
  real-backend and 9 demo-operations cases, which run in the later disposable
  staging phase.
- Dependency audits reported no known actionable vulnerabilities. The local
  backend package was not queried on PyPI because it is not a published
  dependency.
- Bandit, Gitleaks, Semgrep, repository Trivy, candidate image Trivy, license
  inventory, SBOM generation, and Nginx configuration passed. Semgrep reported
  0 findings.
- The deterministic seed passed twice with the second run reusing all bounded
  demo workflow state.
- Encrypted backup creation, checksums, manifest validation, and disposable
  restore validation passed.
- Real-backend Playwright: 18 passed, covering the existing staging scenarios
  and the complete demo operations workflow.
- Production smoke passed health, readiness, docs policy, login, identity,
  hierarchy read, and logout. Prediction smoke was skipped by its existing
  explicit opt-in policy; governed prediction was exercised successfully in
  the real-backend browser suite.
- The owned staging containers, networks, and disposable volumes were removed
  by the validation cleanup.

Evidence:

- `artifacts/release/demo-sprints-0-2-full-validation.log`
- `artifacts/release/restore-20260724T064602Z-acbe27ef.txt`

## Remaining limitations

- Secure action-note attachments were not implemented because no narrow,
  reusable secure-storage path was available.
- Product-mode, recent-item, and favorite preferences are local to one browser
  and are presentation state only.
- The administrator Simple Mode supplies the manager-oriented view; there is no
  separate manager authorization role.
- Customer-specific risk thresholds, maintenance procedures, and operational
  claims remain unvalidated.
- Live simulation, smart CSV onboarding, notifications, CMMS integration,
  localization, executive reporting, explainability, and industrial protocol
  connectors remain outside Sprints 0–2.

## Recommendation

**Ready for reviewed internal staging.** This result is not a production
readiness claim.
