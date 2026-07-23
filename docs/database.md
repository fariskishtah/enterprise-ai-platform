# Database architecture

Version `0.9.0` uses PostgreSQL 16 with pgvector in supported Docker
deployments. SQLAlchemy models are authoritative for runtime persistence;
Alembic owns the ordered schema history.

## Migration chain

```text
0001_create_users_and_refresh_tokens
0002_create_manufacturing_domain
0003_create_sensors
0004_create_sensor_data_platform
0005_create_mlops_foundation
0006_add_ai_jobs_and_promotion
0007_add_ai_prediction_monitoring
0008_add_controlled_retraining
0009_add_monitoring_orchestration
0010_add_automl_management
0011_adjust_automl_trial_uniqueness
0012_add_dataset_registry
0013_integrate_dataset_training
0014_add_secure_rag_chat
```

Every revision has one predecessor; `0014_add_secure_rag_chat` is the sole head.
Historical revisions are not rewritten. Apply migrations before starting the
new application revision:

```bash
cd backend
alembic upgrade head
alembic current
alembic check
```

The production deploy path runs migrations once before API/worker startup.
Routine application rollback does not run Alembic downgrade. Downgrade support
is exercised for development/release validation, but operators must assess data
loss and compatibility before using it. Prefer a compatible application rollback
or verified backup restore.

## Domain table groups

### Identity

- `users`: normalized email, Argon2 password hash, role, active state.
- `refresh_tokens`: user, JWT ID/hash, expiry, rotation/revocation state.

There are no tenant-membership, invitation, MFA, or identity-provider tables.

### Manufacturing and sensor data

- `companies`, `factories`, `machines`, `sensors`
- `upload_jobs`, `sensor_readings`

Foreign keys enforce hierarchy identity. Readings and upload jobs retain source,
status, timestamps, and aggregate validation counts.

### MLOps, training, and model governance

- `experiments`, `training_runs`, `model_artifacts`
- `training_jobs`, `model_promotion_audits`
- `automl_studies`, `automl_trials`, `automl_execution_slots`

Persisted training specifications remain authoritative across queue delivery and
retry. Registry artifacts live in MLflow/local storage; database records retain
safe identity, lineage, status, metrics, and governance state.

### Prediction monitoring and retraining

- `prediction_events`, `model_reference_profiles`
- `model_monitoring_evaluations`, `monitoring_alerts`,
  `monitoring_job_locks`, `prediction_outcomes`
- `model_retraining_policies`, `model_retraining_requests`,
  `model_retraining_audits`

Prediction events store bounded summaries and hashes, not raw matrices.
Evaluations and retraining audits retain immutable decision evidence.

### Dataset registry

- `datasets`, `dataset_versions`
- `document_records`, `document_chunks`
- `dataset_usage_references`

Datasets are owner-scoped. Versions are immutable after terminal processing.
Object bytes live in the application-managed dataset volume; tables retain
opaque object metadata, digests, schema, lineage, lifecycle, and safe errors.
Usage references protect dependent training and RAG resources.

### RAG and chat

- `rag_knowledge_bases`, `rag_knowledge_base_dataset_versions`
- `rag_index_builds`, `rag_indexed_chunks`, `rag_chunk_embeddings`
- `rag_conversations`, `rag_messages`, `rag_message_citations`

Migration `0014` creates PostgreSQL extension `vector` and stores fixed-width
`vector(256)` embeddings. SQLite uses a JSON type variant only for isolated
unit/migration tests; it is not the production vector-query implementation.
Production retrieval applies ownership, knowledge-base, active-build, attached
version, and ready-state constraints before pgvector cosine ranking.

## Consistency rules

- UUIDs remain stable across API, queue, and persistence boundaries.
- Workers claim resources through conditional state transitions.
- State-version and uniqueness constraints bound repeated delivery and
  idempotent submission.
- Ready dataset versions, terminal model evidence, evaluations, audits, and
  citations are immutable by product contract.
- PostgreSQL is authoritative. Redis queues, leases, rate-limit buckets, and
  heartbeat keys are recoverable coordination state.
- MLflow, model artifacts, dataset objects, and PostgreSQL must be treated as
  one application recovery set.

## Validation

Release tests upgrade a clean database to head, inspect required tables,
downgrade to the pre-dataset/RAG boundary, and re-upgrade:

```bash
cd backend
pytest -q tests/test_release_readiness_gate.py
```

SQLite coverage does not prove PostgreSQL extension behavior. The staging
runtime and production verification script confirm pgvector on PostgreSQL.
