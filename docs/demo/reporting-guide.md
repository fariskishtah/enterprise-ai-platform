# Executive reporting

Administrators use `/executive` for grounded management metrics and `/reports` for
exports. Engineers may use report APIs where authorized, but schedules and the
Simple Mode executive dashboard remain administrator-only.

## Definitions and periods

Metrics come from company-scoped machines, alerts, actions, sensor readings,
maintenance feedback, and shifts. The current dashboard reports machine count, open
and critical alerts, overdue and completed actions, mean acknowledgement and
resolution time, data freshness, feedback count, and shift activity.

Supported product periods are current shift, previous shift, today, last 7 days,
last 30 days, and a custom positive range no longer than 366 days. UTC is used by
the API. Empty metrics remain empty rather than being estimated.

The product does not infer cost savings, profit, avoided downtime, ROI, energy
savings, or production efficiency.

## Reports and exports

Supported report types are Executive Factory Summary, Machine Health, Alert and
Action, Shift Handover, Data Quality, and Model and Prediction Governance.

- PDF is a structured deterministic A4 document with page numbers and explicit
  limitations.
- XLSX is macro-free and contains Summary, Machines, Alerts, Actions, Feedback,
  Shifts, Data Quality, and Model Governance sheets. Headers are frozen and filters
  are enabled.
- CSV is available for tabular summaries.

All spreadsheet-bound text is neutralized when it begins with `=`, `+`, `-`, or
`@`. Exports are bounded to 10,000 rows per sheet. Generated objects reuse the
root-confined dataset object store. Downloads require an authenticated authorized
request, are private/no-store, and expire after one hour. No raw model artifact,
secret, token, environment value, or internal stack trace is exported.

## Scheduling and email

Schedules accept only daily, weekly, or monthly cadence, a bounded recipient list,
and validated email addresses. There is no arbitrary cron expression.

The repository has no supported mail-delivery provider. Schedule definitions may be
saved disabled with a visible `delivery_unavailable` result. Enabling a schedule
fails closed. Production email delivery is therefore blocked and is not claimed as
ready. No attachment delivery, Teams, Slack, WhatsApp, or SMS adapter is included.

## Incident summaries

Incident summaries use only recorded machine timeline events, actions, notes, and
maintenance outcomes. Unknown facts are labeled unknown. No root cause is invented,
and no LLM is required.
