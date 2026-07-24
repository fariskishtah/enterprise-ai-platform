# Demo Product Baseline

The demo product builds on the controlled predictive-maintenance pilot. It is
intended for local demonstrations and reviewed internal staging only; it is not
a production-readiness claim.

## Roles and product modes

| Role | Product mode | Purpose |
| --- | --- | --- |
| Operator | Simple, fixed | Machine attention, alerts, and assigned operational work |
| Engineer | Expert, default and fixed | Data, model, prediction, monitoring, and lifecycle work |
| Administrator | Expert by default; may select Simple | Company administration or manager-oriented operational overview |

Simple and Expert Mode change presentation and navigation only. Backend role
checks and company scope remain authoritative. Changing browser preferences
does not grant API access. A separate manager role is intentionally not added
because the current authorization model has no safe manager privilege boundary;
administrators use Simple Mode for the manager-oriented view.

## Demo accounts and deterministic resources

The staging seed expects administrator, engineer, and operator email addresses
from environment variables. Passwords are never documented or printed. The
deterministic domain seed creates or reuses one marked demo company, factory,
CNC machine, temperature and vibration sensors, bounded readings, registered
datasets, one small model and exact feature schema, normal and warning risk
assessments, an alert, and maintenance knowledge.

Sprint 2 extends the same seed with operational actions, timeline entries,
maintenance feedback, and a shift handover without duplicating records on a
second run.

## Required feature controls

Enable the demo experience explicitly in a local shell or disposable staging
environment:

```bash
export SIMPLIFIED_EXPERIENCE_ENABLED=true
export OPERATIONS_WORKFLOW_ENABLED=true
export DEMO_TOOLS_ENABLED=true
```

All three controls default to `false`. `DEMO_TOOLS_ENABLED=true` is rejected
when `ENVIRONMENT=production`. Feature-disabled API mutations fail closed; the
frontend does not treat hidden navigation as authorization.

## Start, seed, rerun, and reset

For the disposable staging-like stack:

```bash
export E2E_ADMIN_EMAIL=admin@demo.example
export E2E_ENGINEER_EMAIL=engineer@demo.example
export E2E_OPERATOR_EMAIL=operator@demo.example
export E2E_PASSWORD='<local-strong-password>'
./scripts/staging-local.sh start
./scripts/staging-local.sh seed
./scripts/staging-local.sh seed
```

The second seed is the idempotency check. Stop while retaining its disposable
data with `./scripts/staging-local.sh stop`. Only
`./scripts/staging-local.sh clean` removes resources owned by that disposable
staging project, and it refuses to run without its ownership marker.

For the ordinary local Compose project, export the feature controls before
starting and run `./scripts/seed-demo.sh`. The seed never deletes unrelated
records or Docker volumes.

## Safeguards and limitations

- Demo seeding must be invoked explicitly and is not exposed as an uncontrolled
  production API.
- Demo tools cannot be enabled in production.
- Product mode is a per-user browser preference and is not shared between
  browsers.
- Customer thresholds, maintenance procedures, and risk claims remain
  unvalidated.
- No live simulator, smart CSV onboarding, notifications, CMMS integration,
  localization, executive reporting, explainability, or industrial protocol
  connector is included in these sprints.
