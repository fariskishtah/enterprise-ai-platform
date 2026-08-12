# Phase 4 RAG quality evaluation

Date: 2026-08-11

## Evaluated pipeline

Plain-text document upload is validated and stored as an immutable dataset version.
The dataset worker extracts bounded UTF-8 text into a ready document record. A
knowledge-base build uses deterministic overlapping chunks and local 256-dimensional
hash embeddings. Retrieval queries the active build through owner- and company-scoped
SQL joins, applies cosine ranking and duplicate suppression, and returns at most the
requested top-k chunks. The local extractive generator treats retrieved text as data,
selects only sufficiently overlapping evidence, and persists citations using ranks
that were present in the authorized retrieval response.

No external model, embedding service, browsing, or tool execution is in this path.

## Deterministic fixture

Synthetic Factory A and Factory B documents intentionally use the same
`Compressor-01` name while specifying different maintenance intervals, temperature
limits, shutdown steps, alarm codes, production targets, and safety rules. Separate
Factory A conflict and prompt-injection documents exercise disagreement and hostile
source content. No production or customer data is used.

## Case results

| Case | Assertion | Result |
| --- | --- | --- |
| A | Direct fact retrieves the expected Factory A source | Pass |
| B | Two complementary chunks are combined and both cited | Pass |
| C | “How often … serviced” retrieves “maintenance interval” | Pass |
| D | Ambiguous competing values produce a cautious conflict response | Pass |
| E | Unsupported question is refused without citations | Pass |
| F | False 7-day premise is corrected with the registered 14-day fact | Pass |
| G | Conflicting 14-day/21-day sources are surfaced and both cited | Pass |
| H | Foreign knowledge base is hidden at the service/query boundary | Pass |
| I | Same-name equipment returns 82 C for A and 96 C for B | Pass |
| J | Archived source is absent from subsequent retrieval | Pass |
| K | Persisted citation title and rank match the authorized source | Pass |
| L | Lexically distracting but irrelevant evidence is not cited | Pass |
| M | Document prompt injection is discarded while a separate fact remains usable | Pass |
| N | System-prompt/credential extraction request is refused without citations | Pass |
| O | Long irrelevant context does not displace the relevant late source | Pass |

## Measured evidence

- Expected-source top-k hit rate: 3/3 (100%) for direct, paraphrase, and same-name
  integration queries.
- Direct/same-name top-1 relevance: 2/2 (100%).
- Required A–O deterministic assertions: 15/15 passed.
- Unsupported/sensitive refusal assertions: 3/3 (100%), with zero citations.
- Citation correctness assertions: 2/2 source/rank checks passed.
- Same-name confusion: 0/2 generated answers.
- Cross-tenant retrieval leakage: 0.
- Cross-tenant generated-answer leakage: 0.
- Representative local SQLite timing: retrieval 3.57 ms, full persisted generation
  path 11.72 ms, complete two-tenant case 74.99 ms. These are development-machine
  observations, not production capacity claims.
- External paid model calls: 0.

## Ingestion and lifecycle observations

Plain text (`.txt`, `text/plain`) is the only supported document format. Empty,
oversized, malformed/NUL-containing, and unsupported-format inputs fail safely. Very
short documents and multi-chunk documents are accepted within configured bounds. A
second upload is rejected while the first version is still processing, preventing a
duplicate active-processing side effect. Active RAG usage prevents source archival;
after the knowledge base is archived and the dataset is archived, the source no longer
participates in retrieval. Successful rebuilds atomically replace the active index;
failed builds do not become active.

## Remaining limits

The local hashing model is lexical, not a general semantic model. The bounded alias
set improves common manufacturing paraphrases but will not cover every synonym or
multilingual query. Conflict detection currently targets differing numeric facts with
recognized engineering units. Plain-text-only ingestion limits source usability, and
the quality fixture is intentionally small rather than a capacity/load test.

The RAG UI build and static checks pass. It now uses a readable knowledge-base name,
keeps document titles and excerpts in citations, explains why unsupported answers are
unavailable, links writers to add trusted knowledge, and distinguishes the guided
workflow from technical model tools. A mocked focused Playwright assertion was added,
but this session had no browser instance available to execute it.
