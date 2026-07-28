# Final test report

Validation date: 2026-07-28  
Host: macOS ARM64, 8 CPUs, 8 GiB RAM

| Check | Result |
| --- | --- |
| Initial backend suite | 824 passed, 3 skipped |
| Final backend suite | 840 passed, 3 skipped in 160.51s |
| Billing/auth focused suite | 22 passed |
| Billing catalogue + migration | 4 passed |
| Transactional email/support/security focused suite | 25 passed |
| Ruff on changed backend modules | Passed |
| Black on changed backend modules | Passed |
| mypy `app` | Passed, 287 source files |
| Frontend ESLint | Passed |
| Frontend Prettier | Passed |
| TypeScript + Vite production build | Passed |
| Focused account-recovery Playwright | 2 passed |
| Full fixture Playwright | 45 passed, 23 intentionally skipped in 43.8s |
| Docker Compose config | Passed |
| Billing migration empty SQLite round trip + Alembic check | Passed |
| Transactional email migration empty SQLite round trip + Alembic check | Passed |
| API/frontend local probes before rebuild | HTTP 200 |
| Changed service Docker rebuild | Passed |
| Current PostgreSQL migration | `0023`; `0024` runtime migration pending rebuild |
| Rebuilt API `/health`, `/billing/plans`, frontend `/pricing` | HTTP 200 |
| k6 current load run | Blocked: k6 not installed |

The 23 browser skips require the explicit disposable real-backend/staging mode;
they are not failures. Python emitted 1,662 known third-party deprecation
warnings, principally joblib/NumPy and MLflow/Pydantic. Dependency/container
security workflows, Paymob sandbox, real email delivery, production TLS, and
customer-scale load were not executed in this change.
