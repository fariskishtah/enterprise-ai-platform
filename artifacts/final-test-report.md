# Final test report

Validation date: 2026-07-29
Host: macOS ARM64, Python 3.12.7, Node 22, Docker Desktop

| Check | Result |
| --- | --- |
| Full backend pytest | 909 passed, 3 skipped in 190.32s |
| Phase F lifecycle suite | 7 passed |
| Phase G entitlement suite | 12 passed |
| Phase H focused Playwright | 14 passed |
| Full fixture Playwright | 61 passed, 23 explicitly gated real-backend skips in 30.1s |
| Billing browser axe audit | No critical or serious violations |
| Billing browser console/page errors | None |
| Billing unmatched API requests | None in primary workspace test |
| Frontend ESLint | Passed |
| Frontend Prettier | Passed |
| TypeScript + Vite production build | Passed |
| Ruff, full backend app/tests | Passed |
| Black, full backend app/tests | Passed (432 files checked) |
| mypy `app` | Passed, 303 source files |
| Empty database Alembic upgrade | Passed through `0031_entitlement_overrides` |
| `0029` downgrade → `0030`/`0031` upgrade | Passed |
| Alembic schema drift check | No new upgrade operations detected |
| Local PostgreSQL migration | Upgraded from `0029` to `0031` (head) |
| Local + production Compose config | Passed with explicit required production placeholders |
| Backend, training-worker, frontend image rebuild | Passed |
| Recreated local backend/worker/frontend | Running |
| Billing worker actor | `process_billing_webhook` registered |
| Rebuilt API health | HTTP 200, `{status: ok}` |
| Rebuilt public billing catalogue | HTTP 200, exact EGP catalogue |
| Protected billing probes without session | HTTP 401 as expected |
| Rebuilt frontend probe | HTTP 200 |
| Phase H screenshots | 15 generated and reviewed |

The three backend skips require Redis/PostgreSQL integration contexts not enabled
in the direct unit run. The 23 browser skips require the explicit disposable
real-backend/staging mode and are not hidden failures. Backend tests emitted 1,662
known third-party deprecation warnings, principally joblib/NumPy and
MLflow/Pydantic.

The local Dramatiq worker starts and registers the billing actor. It also emits an
existing duplicate AutoML reconciliation middleware warning; no error, exception,
or traceback was observed after the rebuilt services started.

No Paymob sandbox/live transaction or real provider refund was executed because
deployment-owned credentials are unavailable. Browser payment flows use
deterministic non-sensitive API fixtures and do not replace that acceptance gate.
