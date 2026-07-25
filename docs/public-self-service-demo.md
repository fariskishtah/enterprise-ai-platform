# Public self-service demo

FactoryMind supports public account creation without granting public
administrative access. This mode uses the existing company boundary: every new
account creates a distinct company marked as a public-demo workspace. Existing
companies and accounts remain unmarked and unchanged.

## Signup and roles

Visitors use **Create Account** from the login page and provide a name, email,
password, and one of the backend-validated roles:

- **Operator** — read-only factory, machine, sensor, reading, and operations
  access supported by the current RBAC policy.
- **Maintenance & Data Engineer** — the existing `engineer` role, including
  company-scoped data, training, model, prediction, monitoring, maintenance, and
  knowledge workflows.

Admin, owner, viewer, data-scientist, and invented role values are rejected.
There is no public role-promotion path. User management and destructive
manufacturing operations remain admin-only.

Registration and login use the configured Redis-backed authentication limit.
Authenticated mutations, predictions, RAG requests, and uploads use the
configured mutation limit. Upload byte/row/column bounds remain authoritative
on the server.

## Synthetic workspace

After the first login, the browser calls the authenticated, idempotent workspace
preparation endpoint. It creates only:

- one `Cairo Smart Plant` factory;
- `CNC-01`, `PRESS-02`, and `PUMP-03`;
- seven sensors per machine: `temperature_c`, `vibration_mm_s`,
  `pressure_bar`, `power_kw`, `rpm`, `production_rate_units_h`, and
  `quality_score_pct`;
- six bounded `SIMULATION` readings per sensor, for 126 total readings.

The service locks the company row during preparation, reuses matching resources,
and checks deterministic timestamps before insertion. Repeated sequential or
concurrent production calls therefore do not intentionally create duplicate
demo assets. Every query continues through the existing company-scoped
repositories.

If preparation is temporarily unavailable after signup, the valid session is
preserved and Settings exposes a retry action. Onboarding can be dismissed and
restarted from Settings.

## Compute and model governance

Public-demo training is limited to one active job and three submissions per user
per rolling 24-hour period. An idempotent retry of the same job does not consume
another slot. General mutation limits continue to protect prediction, RAG, and
retraining endpoints. Public accounts use the bounded background training path;
the legacy synchronous training and AutoML study-creation paths are disabled
because their compute budgets are not bounded for an unauthenticated audience.

An engineer may request evaluation or retraining only through the existing
controlled workflow. The first eligible demo request creates the existing
conservative default policy: champion source required, critical drift by
default, at least 20 current samples, one active request, one request per day,
three per week, and a 24-hour cooldown. This never promotes or replaces a model
automatically.

## Data and knowledge workflows

Guided CSV import previews before mutation, requires explicit column mapping,
validates registered machine and sensor names, separates blocking issues from
warnings, and reports bounded row examples. Long format uses:

```csv
timestamp,machine,sensor,value,unit
2026-07-25T08:00:00Z,CNC-01,temperature_c,61.2,°C
```

Dataset display names preserve safe Unicode punctuation, including en dashes.
Processed tabular versions report numeric/non-numeric features, target type,
class distribution, single-class warnings, and compatibility with the current
numeric training workflows.

Knowledge bases accept bounded UTF-8 plain-text versions only. TXT is supported;
PDF is deliberately not advertised because no reviewed PDF parser is present.
The current provider is deterministic local hashing plus extractive generation,
not a hosted LLM. Retrieval is question-specific, company/owner scoped,
deduplicates near-identical chunks, returns citations, and records an
insufficient-evidence outcome instead of fabricating an answer.

## Local validation

Apply the additive migration before exercising signup:

```bash
docker compose exec backend alembic upgrade head
```

The focused backend coverage is:

```bash
cd backend
.venv/bin/pytest -q \
  tests/test_auth_api.py \
  tests/test_public_demo_workspace.py \
  tests/test_public_demo_migration.py \
  tests/test_dataset_readiness.py \
  tests/test_ai_training_jobs.py \
  tests/test_rag_service.py \
  tests/test_sprints_3_5.py
```

Production deployment must still follow the backup, migration, verification,
and rollback procedures in the existing deployment runbooks. Public signup does
not make a single-VM deployment highly available, add billing/entitlements, or
turn the deterministic RAG provider into a production-grade general assistant.
