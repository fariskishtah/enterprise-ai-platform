# Final test report

Validation date: 2026-07-28  
Host: macOS ARM64, 8 CPUs, 8 GiB RAM

| Check | Result |
| --- | --- |
| Initial backend suite | 824 passed, 3 skipped |
| Final backend suite | 849 passed, 3 skipped in 177.82s |
| Billing/auth focused suite | 22 passed |
| Billing catalogue + migration | 4 passed |
| Transactional email/support/security focused suite | 25 passed |
| Verification/email/security focused suite | 31 passed |
| Ruff on changed backend modules | Passed |
| Black on changed backend modules | Passed |
| mypy `app` | Passed, 287 source files |
| Frontend ESLint | Passed |
| Frontend Prettier | Passed |
| TypeScript + Vite production build | Passed |
| Focused account-recovery Playwright | 2 passed |
| Full fixture Playwright | 46 passed, 23 intentionally skipped in 40.7s |
| Docker Compose config | Passed |
| Billing migration empty SQLite round trip + Alembic check | Passed |
| Transactional email migration empty SQLite round trip + Alembic check | Passed |
| Email verification migration/backfill/downgrade + Alembic check | Passed |
| API/frontend local probes before rebuild | HTTP 200 |
| Changed service Docker rebuild | Passed |
| Current PostgreSQL migration | `0025_add_email_verification` (head) |
| Rebuilt API `/health` and `/billing/plans` | HTTP 200 |
| k6 current load run | Blocked: k6 not installed |

The 23 browser skips require the explicit disposable real-backend/staging mode;
they are not failures. Python emitted 1,662 known third-party deprecation
warnings, principally joblib/NumPy and MLflow/Pydantic. Dependency/container
security workflows, Paymob sandbox, real email delivery, production TLS, and
customer-scale load were not executed in this change.
