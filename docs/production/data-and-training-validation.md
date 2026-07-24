# Data and training validation

Deterministic data is generated outside Git:

```bash
python scripts/generate-production-validation-data.py \
  --profile small --format onboarding --output /tmp/fk-small.csv
python scripts/generate-production-validation-data.py \
  --profile medium --format training --output /tmp/fk-medium.csv
python scripts/generate-production-validation-data.py \
  --profile large --format onboarding --scenario faults \
  --output /tmp/fk-large-faults.csv
```

## Generator observations

| Profile | Rows | Format/scenario | Bytes | Generation | Peak footprint |
| --- | ---: | --- | ---: | ---: | ---: |
| Small | 1,000 | onboarding/normal | 72,531 | 0.04 s | 9.7 MB |
| Medium | 50,000 | training/normal | 2,050,070 | 0.12 s | 9.6 MB |
| Large | 250,000 | onboarding/faults | 18,123,096 | 0.85 s | 9.6 MB |

The large fault profile injected 498 invalid numerics, 719 missing values, one
timestamp gap, and 251 stale timestamps. The medium target is deliberately
imbalanced (49,484 majority rows). These are synthetic validation characteristics,
not measured business accuracy.

The application currently bounds guided imports to 10,000 rows and datasets to
configured byte/row limits. Therefore 50,000- and 250,000-row files are generator
and rejection-boundary evidence, not successful import capacity. Do not raise
those limits without measured memory, queue, database, and UX evidence.

## Observed staging workflow

- First deterministic seed: 38.28 s; repeat: 28.56 s with no duplicate domain,
  reading, dataset, model, prediction, alert, action, feedback, note, shift, or
  import records.
- Three concurrent ten-row uploads completed with a 207.31 ms upload p95; exact
  idempotent replays returned the original IDs.
- The seeded valid/warning/rejected onboarding cases completed mapping,
  validation, confirmation where allowed, and data-quality persistence. An
  attempted repeat mapping returned the expected conflict while validation and
  confirmation remained recoverable.
- Three tiny, serial worker jobs all reached `succeeded` in 6.7 s total. Their
  random-forest artifacts were 3,217 bytes each; the seeded demonstration model
  artifact was 1,073 bytes. These sizes and synthetic metrics are not business
  accuracy evidence.
- The governed prediction completed in 13.92 ms; the structured normal and
  warning cases completed in 64.60 ms and 23.77 ms and produced the expected
  persisted prediction/alert state.
- Three PDF/XLSX report jobs completed synchronously at 282.66 ms create p95;
  authenticated download p95 was 65.56 ms. A representative A4 PDF was 4,296
  bytes and rendered to a non-blank 73,330-byte PNG for visual inspection.

Focused security coverage passed for tenant-isolated imports, predictions,
reports, support references, and authenticated downloads. The final unified
gate records the complete suite result.
