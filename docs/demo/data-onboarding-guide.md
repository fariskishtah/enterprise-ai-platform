# Smart data onboarding

The guided flow is available to administrators and engineers at
`/sensor-data/onboarding`. Operators remain read-only and cannot access ingestion or
training controls.

## Supported input

- UTF-8 CSV only, with an explicit server limit of 10 MiB and 10,000 rows by
  default.
- Comma, semicolon, tab, and pipe delimiters are detected; the user can confirm a
  one-character override.
- Headers are required, non-empty, and unique after case-insensitive normalization.
- Long format maps timestamp, machine, sensor, and value.
- Wide format maps timestamp and machine plus one or more feature columns.
- Optional target, operating state, and batch/shift mappings are preserved for
  readiness review. Existing sensor units remain authoritative.

Selecting a file never imports it. The user must complete upload, preview, mapping,
validation, and explicit confirmation.

## Quality rules

Blocking findings include missing or invalid timestamps, missing or non-numeric
values, non-finite values, formula-like cells, and unknown machine/sensor pairs.
Warnings include duplicate rows, median-absolute-deviation outliers, materially
inconsistent sampling, a newest timestamp older than 30 days, and a target class
below 10%.

Outliers use a robust MAD threshold of 3.5. This is a review signal, not a claim of
statistical certainty. Blocking findings prevent import; warnings must be accepted
explicitly. At most 20 safe error samples are retained. JSON and CSV quality
summaries are available through the authenticated API.

## Guided AI

The readiness wizard exposes predictive maintenance, energy monitoring, quality
prediction, and condition monitoring because they map to the current regression or
classification training engine. Anomaly detection is not shown because the backend
does not provide an approved anomaly-training contract.

Fast demo, Balanced, and Thorough describe existing bounded paths. They do not add
unapproved hyperparameters. Training registers a model version but never promotes or
deploys it automatically.

## Cleanup and limitations

Failed uploads retain bounded metadata and the root-confined stored object for
diagnosis. There is no unlimited rejected-row archive, automatic repair, Excel or
Parquet ingestion, arbitrary Python, or client-side executable interpretation.
