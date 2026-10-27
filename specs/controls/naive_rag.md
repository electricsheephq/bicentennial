# Naive RAG baseline

This probe-only control is labelled **cached, API mode** on both T0 and T1.
It is a retrieval floor, never a real system or a Ring 0 decision bar.

```python
TOP_K = 5
CHUNK_CHARS = 240
EMBEDDER_NAME = "hashed-tfidf-v1"
```

No local neural embedder is pinned in v0.1: the dependency-free runtime has no
bit-reproducible local neural implementation. The pinned embedder is hashed
TF-IDF. A later neural embedder needs an owner-approved dependency, weights
pinned by sha256 with a licence check, CPU single-thread fixed kernels,
integer-quantised outputs, and a cross-process golden test.

Words are `\w+` matches over `str.lower()`. Each word's sha256 assigns its
first eight bytes, big-endian, to a coordinate in a 2^64 space; bit zero of
byte nine chooses the sign (set means negative). Term frequency is raw count.
IDF is `floor(1e6 ln(1 + (N - df + 1/2) / (df + 1/2)))`, using 24 atanh-series
terms after binary range reduction. Counts use only chunks visible at `now`.
All vector and ranking arithmetic is integer or exact rational arithmetic.

Chunks greedily pack whole whitespace-delimited words into at most 240
characters, retaining the exact substring between the first and last word.
A longer word occupies its own chunk and is never cut. There is no overlap,
and a chunk never crosses an event. Chunk ids are `[event_id, ordinal]`, with
ordinals starting at zero. Empty or whitespace-only events have no chunks.

Ranking uses cosine similarity, retains only positive dot products and
nonzero chunk norms, and returns at most five chunks. For a fixed query,
`dot² / chunk_norm²` orders them exactly. Ties sort by event-id string, then
chunk ordinal. The reader's recall query is the query prompt. Output joins
ranked chunks with newlines and cites event ids, including repeated ids.
A whitespace-bearing locked token can split across chunks or be disrupted by
the joining newline. These failures are disclosed and never repaired.

Recall is quote-aware: each evidence event requires every reader-key required
token occurring in that event to occur together in one retrieved chunk.
Matching is exact, case-sensitive substring matching; required tokens must be
ASCII. Events containing none of those tokens use event-id recall instead,
counted separately in reports. Reports say `recall_basis: "chunk_quote"`.

Near-solved rows are separate for every `(stage, track)`. With integer milli
scores `f`, `r`, `c` for floor, naive RAG and oracle evidence:

- `between = f < r < c`;
- `rag_near_solved = 10*r >= 10*f + 7*(c-f)`;
- `floor_near_solved = 10*f >= 7*c`.

A flag is null when an input it needs is missing. The pack is flagged when
no row is strictly between floor and ceiling. These are disclosures, never
Ring 0 gates; a flagged pack is not refused. The preregistered calibration
requirement is `r < f + 0.70*(c-f)` and `f < 0.70*c`.

The canonical cache pins embedder parameters and code, plus the common control
key. Parameter or code changes miss the cache. Corruption raises
`pinned_artifact_changed`. The entry hash and embedder hash travel inside
`pack.controls.naive_rag`; the embedder hash also travels as a JUnit property.
The card scalar follows the common single-track rule, otherwise null.
Controls never call forget, so covered values can remain retrievable.

Out of scope: a Hermes-mode shim, top-2 versus top-20 exploration, the CLEAR
cell-admission test, BM25, grep and recent-window controls, a neural embedder,
changes to the common controls, and writing into an installed pack.
