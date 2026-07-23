# Release validation report

## Candidate identity

| Field | Value |
| --- | --- |
| Version | 0.9.0 |
| Source baseline | `4d3ec92306e2362cc3532b945881075445bcf41c` |
| Branch at audit start | `main` |
| Branch validated | `release-readiness-0.9` |
| Validation date | 2026-07-23 |
| Unified full-validation exit code | `0` |
| Recommendation | **Ready for internal staging** |

The candidate's executable release gates pass, including a clean disposable
staging runtime. It is not recommended for a customer controlled pilot until
the legal/asset-provenance decisions and the open base-image security exception
are resolved.

## Environment

| Tool | Observed version |
| --- | --- |
| Host | macOS (local developer workstation) |
| Python | CPython 3.12.7 |
| Node.js | 22.22.2 |
| npm | 10.9.7 |
| Docker | 29.4.3 |

Python 3.12 and Node 22 are the declared backend and frontend release runtimes.

## Validation evidence

| Area | Command | Result |
| --- | --- | --- |
| Canonical version | `backend/.venv/bin/python scripts/check-release-version.py` | Passed |
| Documentation consistency | `backend/.venv/bin/python scripts/check-release-docs.py` | Passed |
| Backend lock install | `python3.12 -m pip install --require-hashes -r backend/requirements/dev.lock` | Passed |
| Installed dependency consistency | `cd backend && python -m pip check` | Passed |
| Backend formatting/lint/type | `black --check .`; `ruff check .`; `mypy app` | Passed; mypy checked 244 source files |
| Backend tests | `cd backend && pytest -q` | 784 passed, 3 skipped, 1,662 warnings in 67.54 seconds |
| Alembic chain | clean upgrade to head, `alembic check`, downgrade to `0011`, re-upgrade | Passed; head is `0014_add_secure_rag_chat` |
| Frontend lint/format | `npm run lint`; `npm run format` | Passed |
| Frontend release build | `npm run build:release` under Node 22 | Passed |
| Frontend budget | Included in `build:release` | Passed: 243,535 B initial JS; 243,535 B largest JS; 173,218 B login image; 280,129 B initial assets |
| Fixture browser/accessibility suite | `npm run test:e2e` | 34 passed, 7 real-backend tests correctly skipped in 36.6 seconds |
| Compose validation | base, staging, production, and production observability profiles | Passed |
| Nginx validation | `nginx -t` in exact frontend and reverse-proxy candidate images | Passed |
| Dependency/source security | pip-audit, npm audit, Bandit, Gitleaks, Semgrep, Trivy filesystem | Passed under the exception policy described below |
| Image security | Trivy full report plus blocking actionable scan for all three candidate images | Passed under `SEC-2026-002` |
| SBOM | Syft SPDX JSON for all three candidate images | Generated: 187 backend, 69 frontend, and 69 reverse-proxy package records |
| Real-backend browser suite | staging runtime plus `real-backend.spec.ts` | 7 passed in 38.8 seconds |
| Production smoke | `scripts/smoke-production.sh` against disposable staging | Passed; destructive prediction probe intentionally requires opt-in |
| Shell validation | `bash -n` for every top-level shell helper | Passed |

The initial real-backend execution found a release-test race: the RAG scenario used a
non-waiting visibility probe while its routed page was still loading and silently skipped
the build action. The final artifact showed a healthy `draft` knowledge base, two ready
attachments, no index build, and an enabled build control. The test now waits for that
semantic control to be visible and enabled and confirms the accepted request leaves
`draft`; no product timeout, bypass, or worker behavior changed.

## Final unified-run outcome

The exact final invocation was:

```bash
eval "$(fnm env --shell bash)"
fnm use 22
./scripts/validate-release.sh --full --allow-dirty
```

It completed with exit code `0`. `--allow-dirty` was required because this validation
covered the uncommitted release-readiness changes. Once reviewed changes are committed,
the clean-candidate command is `./scripts/validate-release.sh --full`.

### Passed

- Repository diff check, canonical-version check, documentation consistency, shell
  syntax, and Python compilation.
- Ruff, Black, mypy, pip dependency consistency, and all 784 executed backend tests.
- Frontend ESLint, Prettier, TypeScript build, Vite production build, and all enforced
  performance budgets.
- All 34 executed fixture-browser tests, including the configured accessibility checks.
- Base, staging, production, and observability Compose configuration validation.
- Production and development Python audits under the registered exception policy, npm
  audit, Bandit, Gitleaks, Semgrep, and Trivy filesystem checks.
- Backend, frontend, and reverse-proxy candidate image builds, SBOM generation, complete
  image reports, and actionable high/critical image gates.
- Nginx syntax for the exact frontend and reverse-proxy candidate images.
- Disposable migrations/startup, backend/readiness/frontend health, worker-backed seed,
  all 7 live-backend browser scenarios, and production smoke checks.
- Ownership-guarded cleanup of all disposable staging containers, networks, and volumes.

### Skipped

- 3 backend tests that require direct Redis/PostgreSQL integration variables in the
  normal unit-test process. Their live service paths were exercised by staging.
- 7 real-backend Playwright tests in the fixture-only browser invocation. The same 7
  tests subsequently passed against the disposable real backend.
- The production smoke prediction probe, which is intentionally destructive/chargeable
  opt-in. Login, current-user, hierarchy, health, readiness, docs policy, and logout
  smoke checks all passed.

### Failed

- None in the final unified run.

## Security evidence

- Production Python audit: 91 dependencies, zero known vulnerabilities.
- Development Python audit: zero findings other than the two time-bounded Black
  advisories in `SEC-2026-001`.
- npm audit: zero vulnerabilities at all severities.
- Bandit: zero issues.
- Gitleaks: zero findings across the repository history; two synthetic fixture/example
  fingerprints are documented with exact-match allow-list entries.
- Semgrep: zero unsuppressed findings. Its SARIF retains two representations of one
  source-suppressed false positive where a typed ML engine method named `execute` was
  mistaken for a Django database cursor.
- Trivy filesystem scan: zero high/critical vulnerabilities and zero misconfigurations.
- Frontend and reverse-proxy candidate images: zero high/critical findings.
- Backend candidate image: 23 high/critical Debian package findings without vendor fixes;
  zero actionable findings when the blocking pass ignores only unfixed items. This is
  the short-lived, fully reported exception `SEC-2026-002`.

## Evidence locations

Local generated security and SBOM evidence is written to `artifacts/release/` and is not
committed. CI retains equivalent reports as 30-day workflow artifacts. Expected files
include:

- `backend-sbom.spdx.json`
- `frontend-sbom.spdx.json`
- `reverse-proxy-sbom.spdx.json`
- Trivy filesystem and image reports
- Gitleaks and Semgrep SARIF
- Bandit and dependency-audit JSON
- backend and frontend license inventories

## Failures, skips, and unresolved warnings

- The repository has no owner-approved software license or asset provenance evidence.
- Security exception `SEC-2026-001` temporarily retains development-only Black 24.10.0
  until the fixed formatter's source-equivalence failure is resolved; it expires
  2026-08-31.
- Security exception `SEC-2026-002` covers 23 unfixed high/critical Debian package
  findings in the official Python 3.12 slim base and expires 2026-08-06.
- The backend suite emitted 1,662 non-failing warnings, predominantly third-party
  joblib/NumPy deprecations plus two MLflow/Pydantic warnings. These should be reduced
  before a production recommendation.
- Three backend integration tests are skipped by the normal unit-suite environment
  because they require direct Redis/PostgreSQL integration variables. The disposable
  staging browser suite exercises the live Redis, PostgreSQL/pgvector, worker, and RAG
  paths instead.
- Seven real-backend Playwright scenarios are intentionally skipped only during the
  fixture-browser invocation; all seven pass separately against the disposable runtime.

## Current release blockers

1. Software ownership, redistribution licensing, and third-party licence review are
   unresolved.
2. FK login asset provenance is unresolved.
3. The official backend base image has an open, time-bounded security exception that
   requires owner/security acceptance and rapid rescan.
4. HA, off-host durable artifact/dataset storage, enterprise identity, and complete
   audit capture remain explicitly outside this controlled-pilot scope.

## Reproduction

For the current uncommitted review state:

```bash
eval "$(fnm env --shell bash)"
fnm use 22
./scripts/validate-release.sh --full --allow-dirty
```

For a committed clean candidate, omit `--allow-dirty`. Bootstrap a missing local
environment first with `./scripts/bootstrap.sh`. The full command creates and removes
only its explicitly owned disposable staging runtime and volumes. It does not require or
read production credentials. Generated security reports and SBOMs remain under the
ignored `artifacts/release/` directory and are retained by CI as workflow artifacts.
