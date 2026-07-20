# Release checklist

Use this checklist for `v1.0.0`. Record links to CI runs and release evidence in
the release review; do not put credentials, tokens, or environment files in that
record.

## Before tagging

- [ ] Working tree is clean and the reviewed commit is on the intended release
  branch.
- [ ] Required CI jobs are green for the exact release commit.
- [ ] Focused E2E passes: `cd backend && pytest -q tests/test_end_to_end_workflow.py`.
- [ ] Demo seed succeeds twice; the second run reports reused resources, zero new
  readings, the same training job/version, and the same prediction audit.
- [ ] Base and production Compose models validate, including the production
  observability profile.
- [ ] `docker compose exec backend alembic current` reports the expected head,
  and `alembic check` reports no missing model migration.
- [ ] Frontend lint, format check, and production build pass.
- [ ] Backend dependency check/audit, Ruff, Black, mypy, and Pytest pass.
- [ ] Repository secret scanning passes with no unresolved findings. CI does not
  currently provide a dedicated secret-scanning job, so record the approved
  local or repository-host scan used for this release.
- [ ] README, changelog, architecture, deployment, demo, security, backup, and
  operational runbooks have been reviewed for accuracy.
- [ ] Remaining release limitations are accepted: no selected license,
  single-host deployment, no automatic HTTPS/HA/external paging, and no canonical
  consolidated version source.

## Publish

- [ ] Create an annotated `v1.0.0` tag on the reviewed commit.
- [ ] Push the tag only after approval and re-confirm its commit SHA.
- [ ] Create a GitHub release from that tag using the `CHANGELOG.md` v1.0.0
  section; do not claim unsupported capabilities or publish containers/packages.

## After publishing

- [ ] Deploy or start the exact tagged revision in the approved environment.
- [ ] Apply/check migrations once through the documented deployment path.
- [ ] Run the bounded post-release smoke checks: frontend response, backend
  `/health`, authentication, one authorized manufacturing read, one model-version
  lookup/prediction when seeded, worker health, and required telemetry endpoints.
- [ ] Confirm dashboards, logs, traces, alerts, backups, and rollback revision are
  available, then attach the smoke-test evidence to the release record.
