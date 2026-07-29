# Release-candidate load acceptance

These profiles are bounded to loopback targets in `acceptance.js`. Use the
disposable seeded staging stack, whose email and payment providers are disabled
and whose RAG implementation is deterministic/local.

```bash
export E2E_ADMIN_EMAIL='admin@load-validation.invalid'
export E2E_ENGINEER_EMAIL='engineer@load-validation.invalid'
export E2E_OPERATOR_EMAIL='operator@load-validation.invalid'
export E2E_SMOKE_EMAIL='smoke@load-validation.invalid'
export E2E_PASSWORD='<generated-disposable-password>'
./scripts/staging-local.sh start
./scripts/staging-local.sh seed

export BASE_URL='http://127.0.0.1:18080/api'
export TEST_EMAIL="$E2E_ADMIN_EMAIL"
export TEST_PASSWORD="$E2E_PASSWORD"
export RAG_TEST_EMAIL="$E2E_ENGINEER_EMAIL"
export RAG_TEST_PASSWORD="$E2E_PASSWORD"
for profile in smoke normal stress spike soak; do
  ACCEPTANCE_PROFILE="$profile" ./scripts/run-load-tests.sh acceptance
done
```

Raw summaries are written to the ignored `artifacts/load-runs/` directory.
Before and after the profiles, record Docker stats/restarts, PostgreSQL
connections and slow activity, Redis memory/clients, Dramatiq queue depth, and
Prometheus target/alert state. Publish only aggregated, non-sensitive evidence.
