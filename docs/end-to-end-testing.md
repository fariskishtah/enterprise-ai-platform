# End-to-end workflow testing

The focused local test covers registration and login, creation of one company,
factory, machine, and sensor, four API sensor readings, one background Random
Forest regression job, worker completion, exact model-version lookup, one
prediction, and its privacy-preserving monitoring audit event.

Run it from the repository root:

```bash
cd backend && pytest -q tests/test_end_to_end_workflow.py
```

Expected runtime is under two minutes. The poll budget is 90 seconds with a
250 ms interval. Training is deterministic and limited to four training rows,
two evaluation rows, three trees, one job, and one worker thread; prediction uses
one row. No external service is contacted.

The test uses the existing isolated SQLite, temporary MLflow, and temporary
artifact fixtures. All database records and model artifacts disappear when the
test fixtures are torn down, so no cleanup API calls or persistent Docker volumes
are involved. The worker runs locally in-process while the workflow polls through
the real HTTP API. Retraining is not triggered; the supported prediction audit
record is verified instead, preventing an accidental retraining loop.
