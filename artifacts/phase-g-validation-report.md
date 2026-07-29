# Phase G entitlement and usage validation

Date: 2026-07-29

## Delivered

- One central plan/override/subscription-state entitlement service.
- Resource quotas for members, factories, machines, documents, and stored bytes.
- Idempotent atomic monthly RAG usage metering with UTC period reset.
- Training feature and active-job concurrency enforcement.
- Advanced-report and scheduled-report enforcement.
- Structured quota errors with usage, limit, period, and recommendation.
- Read-only downgrade/suspension behavior without destructive cleanup.
- Audited, expiring tenant overrides and admin usage inspection.
- Migration `0031_entitlement_overrides` and production fail-required setting.

## Automated evidence

Dedicated entitlement suite:

```text
12 passed
```

Integration regression across billing, manufacturing, invitations, datasets,
RAG, AI training, AutoML, reports, and production settings:

```text
91 passed
```

Static validation:

```text
ruff: all checks passed
mypy: success, 303 backend source files
```

Full backend regression:

```text
909 passed, 3 skipped
```

Existing MLflow/Pydantic/joblib deprecation warnings remain unrelated.
