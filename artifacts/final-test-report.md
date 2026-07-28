# Final test report

Validation date: 2026-07-28  
Host: macOS ARM64, 8 CPUs, 8 GiB RAM

| Check | Result |
| --- | --- |
| Initial backend suite | 824 passed, 3 skipped |
| Final backend suite | 856 passed, 3 skipped in 312.74s |
| Billing/auth focused suite | 22 passed |
| Billing catalogue + migration | 4 passed |
| Transactional email/support/security focused suite | 25 passed |
| Verification/email/security focused suite | 31 passed |
| Six-role RBAC/auth focused suite | 39 passed |
| Invitation lifecycle/migration focused suite | 4 passed |
| Ruff on changed backend modules | Passed |
| Black on changed backend modules | Passed |
| mypy `app` | Passed, 287 source files |
| Frontend ESLint | Passed |
| Frontend Prettier | Passed |
| TypeScript + Vite production build | Passed |
| Focused account-recovery Playwright | 2 passed |
| Full fixture Playwright | 47 passed, 23 intentionally skipped in 34.0s |
| Docker Compose config | Passed |
| Billing migration empty SQLite round trip + Alembic check | Passed |
| Transactional email migration empty SQLite round trip + Alembic check | Passed |
| Email verification migration/backfill/downgrade + Alembic check | Passed |
| Six-role migration/backfill/downgrade + Alembic check | Passed |
| Team invitation migration/downgrade + Alembic check | Passed |
| API/frontend local probes before rebuild | HTTP 200 |
| Changed service Docker rebuild | Passed |
| Current PostgreSQL migration | `0027_add_team_invitations` (head) |
| Rebuilt API `/health` and `/billing/plans` | HTTP 200 |
| k6 current load run | Blocked: k6 not installed |

The 23 browser skips require the explicit disposable real-backend/staging mode;
they are not failures. Python emitted 1,662 known third-party deprecation
warnings, principally joblib/NumPy and MLflow/Pydantic. Dependency/container
security workflows, Paymob sandbox, real email delivery, production TLS, and
customer-scale load were not executed in this change.
