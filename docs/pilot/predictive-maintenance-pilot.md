# Predictive Maintenance Risk Pilot

## Objective and claim boundary

The controlled pilot demonstrates a governed anomaly/risk indication for one
CNC machine from current temperature and vibration values. It does not claim to
predict real equipment failure. Customer historical data, failure labels,
maintenance procedures, and acceptance thresholds are required before an
operational claim can be made.

## Deterministic demonstration

The seed creates one company, factory, CNC machine, temperature and vibration
sensors, 24 fixed-timestamp readings, one immutable 12-row tabular dataset
version, one three-tree regression model, an exact feature schema, a challenger
alias, normal and elevated-risk assessments, an acknowledged alert, and a
small ready maintenance knowledge base. Data is clearly marked `DEMO` and is
safe to rerun.

Run the staging-like environment and seed:

```bash
export E2E_ADMIN_EMAIL=admin@pilot.example
export E2E_ENGINEER_EMAIL=engineer@pilot.example
export E2E_OPERATOR_EMAIL=operator@pilot.example
export E2E_PASSWORD='<local-strong-password>'
./scripts/staging-local.sh start
./scripts/staging-local.sh seed
```

## Supported CSV schema

The pilot tabular input is numeric:

| Column | Unit | Purpose |
| --- | --- | --- |
| `temperature_c` | °C | required feature, allowed 0–120 |
| `vibration_mm_s` | mm/s | required feature, allowed 0–30 |
| `risk_score` | unitless 0–1 | training target only |

The exact registered model version persists ordered names, numeric types,
required fields, units, ranges, missing-value behavior, target metadata, and
training dataset version. Normal prediction uses the generated structured form.
Raw matrices remain an advanced engineer path.

## Workflows

**Operator**

1. Open the factory, machine, then **Machine risk**.
2. Review state, assessment time, model version, contributing values, freshness,
   monitoring availability, and the recommended action.
3. Acknowledge a warning/critical indication and add an operational note.
4. Follow the customer's site safety and maintenance procedures.

**Engineer**

1. Verify dataset version/schema and completed job evaluation.
2. Review the exact model version, feature contract, prediction event, and
   monitoring information.
3. Investigate the machine and add an engineer note when resolving the alert.
4. Retrain/promote only through existing controlled lifecycle policies.

**Administrator**

1. Maintain the company users and roles.
2. Review/export audit history.
3. Approve model lifecycle changes and resolve alerts under site policy.
4. Verify daily backups and monthly restore evidence.

## Risk and alert policy

The bounded demo maps a score below 0.40 to Normal, 0.40–0.65 to Observe,
0.65–0.85 to Warning, and 0.85 or higher to Critical. Warning and Critical
create a factory/machine alert. Active alerts are deduplicated per
company/machine/model version and use a one-hour redetection cooldown.
Acknowledgement and resolution preserve actor, notes, and timestamps in
operational and unified audit records. The platform does not create a work
order.

## Pilot acceptance checklist

- [ ] Tenant users and roles behave as documented.
- [ ] Company B cannot access Company A resources.
- [ ] Historical dataset version is ready and immutable.
- [ ] Training job succeeds and exact model version exists.
- [ ] Feature schema rejects missing, unknown, non-finite, typed, and range
      invalid inputs.
- [ ] Structured prediction produces a machine-linked assessment.
- [ ] Operator risk view is readable without ML controls.
- [ ] Warning/critical alert can be acknowledged and resolved with notes.
- [ ] Prediction and lifecycle audit events are visible.
- [ ] Encrypted backup and disposable restore validation pass.
- [ ] Customer validates sensor units, thresholds, procedures, and success
      criteria.

## Success criteria and limitations

Technical acceptance requires all checklist automation and release gates to
pass. Business acceptance must be defined with the pilot customer, including
data completeness, false-positive tolerance, response time, and who may act on
an indication.

The pilot is local numeric tabular inference. It has no PLC/MQTT/Kafka
connector, CMMS work-order integration, mobile push notification, calibrated
probability guarantee, HA cluster, SSO/MFA, or validated customer failure
labels. “Insufficient data” and “Model unavailable” are supported display
states, but automated sensor-to-feature aggregation remains outside this
bounded flow.

