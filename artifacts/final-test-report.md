# Final test report

Validation date: 2026-07-29

Host: macOS ARM64, 8 logical CPUs / 8 GiB RAM

Toolchain: Python 3.12.7, Node 22.23.1, npm 11.12.1, Docker Desktop

## Clean full release gate

Command: `./scripts/validate-release.sh --full`

| Check | Result |
| --- | --- |
| Release/version/exception governance | PASS; 3 expiry dates checked |
| Ruff | PASS |
| Black | PASS; 465 files unchanged |
| mypy | PASS; 303 source files |
| Python dependency consistency | PASS |
| Frontend ESLint / Prettier | PASS / PASS |
| TypeScript + Vite release build | PASS |
| Initial asset budget | PASS; 303,911 B JS, 347,958 B total initial assets |
| Local/staging/production Compose configs | PASS |
| Backend pytest | **918 passed, 3 skipped**, 1,662 third-party warnings, 181.49 s |
| Alembic | PASS; `0031_entitlement_overrides` head |
| Fixture Playwright | **63 passed, 23 gated skips**, 38.2 s |
| Real-backend production-bundle Playwright | **23 passed**, 1.4 min |
| Public runtime smoke | PASS; health, readiness, docs policy, login, refresh rotation, identity, hierarchy, logout |
| Empty-volume migration and idempotent seed | PASS |
| Encrypted isolated restore | PASS |
| Nginx frontend/proxy syntax | PASS |
| Candidate image build and SBOM | PASS for backend, frontend, proxy |

The three backend skips require optional direct Redis/PostgreSQL integration
contexts; equivalent dependencies are exercised by the disposable runtime. The
23 fixture-suite skips are explicitly gated real-backend cases and then pass in
the separate real stack. Warnings are known MLflow/Pydantic and joblib/NumPy
deprecations, not test failures.

## Security results

| Check | Result |
| --- | --- |
| `pip-audit` production lock | 93 dependencies, 0 vulnerabilities |
| `pip-audit` local environment | 0 unignored; 2 dev-only Black exceptions |
| Bandit | 57,516 LOC; 0 medium/high, 30 low below release threshold |
| Semgrep | 225 rules, 449 targets, 0 findings |
| Gitleaks | 153 commits / ~6.57 MB, 0 leaks |
| npm audit | 2 HIGH entries for one RSC-only Router advisory under `SEC-2026-003` |
| Trivy filesystem actionable | 0 HIGH/CRITICAL after reviewed exception |
| Backend image actionable | 0; raw 23 occurrences / 12 unfixed Debian CVEs |
| Frontend / proxy images | 0 HIGH/CRITICAL |

## Email and billing acceptance

Sixty-two transactional-email contract tests passed, including provider
semantics, multipart output, durable retries, terminal failure, metrics, worker
execution, and log redaction. No live delivery was attempted because credentials,
verified sender, and acceptance recipient were unavailable.

Paymob provider/lifecycle tests cover server-owned EGP values, intention payloads,
checkout URLs, HMAC verification, fail-closed configuration, retries,
idempotency/concurrency, activation, cancellation/failure, refunds/reversals,
history, worker execution, and card-free logs. No sandbox transaction was
attempted because no Paymob credentials/public webhook were available.

## Load results

| Profile | Requests | Error rate | p95 | p99 | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| Smoke | 98 | 0% | 83.81 ms | 870.53 ms | PASS |
| Normal | 1,428 | 0% | 156.04 ms | 265.55 ms | PASS |
| Stress | 2,038 | 0% | 382.00 ms | 886.07 ms | PASS |
| Spike | 788 | 0% | 949.03 ms | 3,430.82 ms | **FAIL p99** |
| Soak | 2,588 | 0% | 150.19 ms | 236.02 ms | PASS |

Total: 6,940 requests and zero request failures. Peak backend usage was 51.35%
CPU / 415.8 MiB. No measured restart delta, final application queue depth, 5xx,
or ERROR event was observed. The spike result is retained as a blocker, not
averaged away.

## Accessibility and screenshots

Key public, legal, account, billing, hierarchy, operational, data, AI, reporting,
and role-aware journeys passed serious/critical axe checks where asserted,
responsive overflow checks, and unexpected page/console/HTTP diagnostics. Eighteen
tracked PNG screenshots use deterministic non-sensitive fixtures; they do not
prove external provider acceptance.
