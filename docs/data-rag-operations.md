# Data Registry, RAG, and Chatbot Operations

This guide describes the v1 self-hosted dataset registry, retrieval-augmented
generation (RAG), and grounded chatbot path. The implementation is intentionally
bounded and deterministic: PostgreSQL is the system of record, uploaded objects
remain on local managed storage, Redis/Dramatiq runs durable processing work, and
the initial embedding and answer providers make no external network calls.

## 0.9 controlled-pilot architecture

```text
Admin or engineer
  → FastAPI /ai/datasets
  → PostgreSQL dataset/version lineage + generated opaque object key
  → local dataset object store (shared named Compose volume)
  → Redis/Dramatiq UUID-only processing message
  → worker validates/extracts/chunks/embeds
  → PostgreSQL schema, documents, chunks, and fixed-width embeddings

Admin or engineer
  → FastAPI /ai/rag knowledge base + index build
  → Redis/Dramatiq UUID-only build message
  → worker publishes one active immutable build
  → owner/build/readiness filters execute in PostgreSQL
  → exact ranking over the bounded authorized candidate set
  → /ai/chat local extractive answer + persisted citations
```

Dataset and knowledge-base resources are owner-scoped. Administrators have the
documented administrative visibility; engineers operate only on their own
resources. Operators cannot use these APIs. Cross-owner resources are hidden as
not found where appropriate.

The registry maintains immutable dataset versions, content digests, lineage,
processing status, inferred tabular schema or document records, and safe
processing summaries. Training and AutoML can resolve a ready tabular registry
version instead of accepting an untracked payload. RAG attaches ready document
versions to a knowledge base and records every index build, conversation,
message, retrieval result, and citation.

## Supported inputs and configured limits

Only the following upload formats are supported:

| Dataset kind        | Media type   | v1 behavior                                                                                              |
| ------------------- | ------------ | -------------------------------------------------------------------------------------------------------- |
| Tabular             | `text/csv`   | Strict UTF-8 CSV validation, schema inference, and deterministic training/evaluation split               |
| Document collection | `text/plain` | Strict UTF-8 extraction, normalized line endings, deterministic character chunking, and local embeddings |

The default runtime limits are:

| Limit                                        |              Default |               Configurable ceiling |
| -------------------------------------------- | -------------------: | ---------------------------------: |
| Upload size                                  |               10 MiB |                             50 MiB |
| CSV rows                                     |               10,000 |                            100,000 |
| CSV columns                                  |                  256 |                              1,000 |
| CSV cell length                              |    10,000 characters |                 100,000 characters |
| Plain-text document length                   | 1,000,000 characters |               5,000,000 characters |
| Chunk size                                   |     1,000 characters |                  200–4,000 allowed |
| Chunk overlap                                |       100 characters | 0–1,000 and smaller than the chunk |
| Chunks processed by one RAG build            |                2,000 |                Fixed service bound |
| Documents processed by one RAG build         |                  100 |                Fixed service bound |
| Attached dataset versions per knowledge base |                   20 |                Fixed service bound |
| Retrieval results (`top_k`)                  |                    5 |                                 20 |
| Authorized candidates ranked per query       |                2,000 |                Fixed service bound |

CSV input must contain at least four data rows. Validation rejects malformed
UTF-8/CSV, duplicate or oversized headers, ragged rows, non-finite training
values, oversized cells, entirely empty columns, and spreadsheet formula-like
cells. An optional split column accepts the documented training and evaluation
labels; otherwise a stable input-order boundary uses the configured evaluation
fraction (default 0.2, allowed 0.1–0.4). Both partitions retain at least two
rows. Target and split columns must exist in the inferred schema.

Plain text must be non-empty UTF-8 without NUL bytes. Chunk hashes, source object
digests, schema, row/document/chunk counts, and safe warnings make repeated
processing observable without exposing source contents in API errors or metric
labels.

## Generated local storage boundary

The backend owns the dataset object root (`../data/datasets` by default). Docker
Compose mounts the named `dataset-data` volume at `/app/data/datasets` in the API
and worker; callers never supply a filesystem path.

For each upload the storage adapter:

- generates an opaque two-level key rather than using the original filename;
- confines all reads and writes to the resolved storage root and rejects
  traversal, invalid keys, and symbolic links;
- streams in 64 KiB chunks while enforcing the byte limit and calculating
  SHA-256;
- writes to a same-directory temporary file, flushes it, and atomically replaces
  the destination;
- uses restrictive directory permissions; and
- exposes filename, media type, size, and digest as metadata, never the raw
  storage path or key in public API responses.

The volume is persistent local storage, not an object-store cluster. Production
backup, encryption-at-rest, and volume access controls remain deployment-owner
responsibilities. Operational recovery must not delete the volume.

## Worker lifecycle and reconciliation

Dataset versions move through `pending → processing → ready|failed`. Document
records additionally expose `extracting`, `chunking`, and `embedding` stages.
Knowledge-base builds move through `queued → running → succeeded|failed`,
with explicit cancelled states where supported.

API transactions persist domain state before enqueueing only the resource UUID.
Workers reload all authoritative data from PostgreSQL, claim transitions
conditionally, and persist safe terminal status. Duplicate delivery is therefore
a no-op after another worker has claimed or completed the resource.

The worker hosts two fenced periodic reconciliation loops in addition to normal
message handling:

- dataset reconciliation runs every 60 seconds by default and repairs versions
  still processing after 900 seconds; and
- RAG reconciliation runs every 60 seconds by default, examines at most 100
  builds, repairs queued work older than 300 seconds, and handles running work
  older than 900 seconds.

The scheduler lease is stored in Redis so multiple worker processes do not all
run the same scan. PostgreSQL remains authoritative, and every repair uses
conditional state transitions. Dataset and RAG messages use the configured
queues, both `ai-training` by default; operators may separate them without
changing application contracts.

## Deterministic local retrieval and answers

The baseline embedding provider is `local_hashing` / `hashing-v1`. It produces
normalized 256-dimensional lexical vectors using bounded tokenization and
BLAKE2b hashing. It is deterministic, dependency-free, downloads no model, and
opens no network connection. It is not represented as a semantic transformer.

The baseline generation provider is `local_extractive` /
`grounded-extractive-v1`. It selects one bounded sentence from retrieved
evidence, returns an explicit `insufficient_evidence` outcome when terms do not
overlap, and persists the cited rank and source metadata. Retrieved text is data,
not executable instruction: the provider has no tools, shell access, browsing,
or arbitrary endpoint support.

Authorization is enforced before ranking. PostgreSQL constrains the knowledge
base, active build, owner, attached dataset version, and ready resource states,
then pgvector performs cosine-distance ordering over the bounded authorized
candidate set. Embeddings are fixed-width `vector(256)`. SQLite uses a JSON type
variant only for isolated unit tests and does not represent production vector
queries.

Chat submission is asynchronous. The API persists idempotent user/assistant
message state and returns `202`; the worker moves the assistant reply through
queued, retrieving, generating, and succeeded/failed states. Conversations and
messages remain owner-scoped, retain bounded recent history, and return
persisted citations rather than hidden reasoning. Reconciliation transitions
stale active messages to a safe terminal state.

## Observability and operations

Prometheus metrics use fixed, bounded labels and never include resource IDs,
user data, filenames, prompts, document text, exception messages, or object
paths. The new operational series cover:

- dataset lifecycle outcomes and stage duration;
- RAG index lifecycle outcomes and stage duration;
- retrieval outcome, duration, and retrieved-chunk count;
- grounded/insufficient-evidence/chat failure outcomes and duration;
- bounded subprocess timeouts; and
- reconciliation repairs and failures.

The provisioned **Data and RAG Operations** Grafana dashboard visualizes these
signals. The matching Prometheus rules alert on dataset processing or embedding
failures, index-build failures, retrieval/chat error rates, process timeouts, and
failed reconciliation. Existing platform logs retain request/correlation IDs and
fixed worker operation names. OpenTelemetry spans use a fixed vocabulary and
drop arbitrary identifiers and content attributes.

Readiness reports dataset storage, embedding provider, generation provider, and
RAG index status as optional components. These probes aid diagnosis but do not
make an optional AI feature outage claim the database/Redis-backed API is wholly
unready. Sensitive auth, dataset, RAG, and chat responses carry
`Cache-Control: no-store`.

Source-controlled observability assets are:

- `infrastructure/observability/grafana/dashboards/data-rag-operations.json`
- `infrastructure/observability/prometheus/rules/data-rag-alerts.yml`

## Recovery and reprocessing

Use the following order when work is delayed or fails:

1. Check backend and worker readiness, Redis/PostgreSQL availability, queue depth,
   and the Data and RAG Operations dashboard.
2. Inspect structured logs using request/correlation IDs and the resource's safe
   persisted status; do not put IDs or source content into metric labels.
3. Leave the named dataset volume intact and let the periodic reconciler repair
   eligible stale work. Re-running reconciliation is safe because claims and
   terminal transitions are conditional.
4. For a deterministic validation failure, correct the input and create a new
   immutable dataset version or index build. Do not mutate a ready version in
   place.
5. Before restoring from backup, verify the PostgreSQL metadata and local object
   volume belong to the same recovery point. Validate stored SHA-256 digests
   before reprocessing.

Archiving is the supported non-destructive lifecycle operation. Configurable
retention metadata does not currently run an automated secure-deletion policy.

## Proposed SLOs and error budgets

The following are initial operating targets, not enforced contracts or existing
burn-rate recording rules. Establish a 30-day baseline, validate exclusions, and
obtain service-owner approval before adopting them:

| Proposed objective (30-day rolling)                                     | Target | Error budget |
| ----------------------------------------------------------------------- | -----: | -----------: |
| Dataset processing terminal success, excluding rejected invalid uploads |  99.0% |         1.0% |
| RAG index-build terminal success                                        |  99.0% |         1.0% |
| Authorized retrieval completion                                         |  99.5% |         0.5% |
| Chat completion (`grounded` or `insufficient_evidence`)                 |  99.0% |         1.0% |
| Authorized retrieval completed within 1 second                          |  95.0% |         5.0% |

Treat an `insufficient_evidence` answer as a technically successful, honest
outcome, not a generation error. Exclude authorization denials, client
validation errors, and deliberate cancellation from availability denominators.
Track their product impact separately. Add multi-window burn-rate rules only
after traffic and latency distributions are representative.

## Current limitations

- Uploads are CSV and one plain UTF-8 text object per dataset version. Parquet,
  PDF, DOCX, OCR, archives, and multi-file bundles are not implemented.
- Storage is a local filesystem adapter on a named Compose volume. There is no
  S3/MinIO adapter, multi-node replication, or application-managed
  encryption-at-rest/backup policy.
- PostgreSQL uses pgvector exact cosine ranking over at most 2,000 authorized
  candidates. An approximate-nearest-neighbor index and multi-node vector
  service are not included.
- Hash embeddings are lexical, and the extractive provider is not a general LLM.
  No external provider adapters, tools, browsing, agents, or arbitrary URLs are
  enabled.
- Chat generation runs in the existing Dramatiq worker. There is no separately
  scalable external generation service or cooperative mid-generation cancel.
- Dataset and RAG work share the default worker queue and conservative local
  worker topology unless operators configure separate queues/processes.
- Operators cannot use dataset, RAG, or chatbot APIs. Fine-grained organization
  membership beyond the existing user/owner/admin boundary is not introduced.
- Optional AI readiness checks do not gate overall readiness. SLO recording and
  burn-rate alerts remain future operational work.
- Automated retention execution and secure object deletion are not implemented;
  archiving and immutable replacement are the supported lifecycle controls.
