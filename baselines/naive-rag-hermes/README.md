# naive-rag-dev v1

Version 1.0.0 is the benchmark-owned naive-RAG control's algorithm implemented
as a Hermes `MemoryProvider` plug-in. Author: Bicentennial benchmark.
License: Apache-2.0. It needs only Python's standard library and Hermes's
`agent.memory_provider`; it never imports the benchmark package.

This is a developer-loop baseline, never a contestant and never on a roster
or board. It has no registry entry. A version is pinned as an archive of this
repository subtree at a commit, including all five files. For example:

```sh
git archive --format=tar COMMIT baselines/naive-rag-hermes > naive-rag-v1.tar
```

The archive's digest and commit identify the version for the later external
entry loader (`--entry PATH`). The loader, entry configuration, worker loading
and T0/T1 runs are outside this source-only implementation's offline proof.

`register(ctx)` registers `NaiveRagProvider`. Initialization uses the supplied
Hermes home. Retrieval happens only through `naive_rag_search`: `prefetch`
returns an empty string and `sync_turn` stores nothing. Scripted write turns
call `naive_rag_add`; there is no automatic capture.

| Tool | Arguments | Result |
|---|---|---|
| `naive_rag_add` | `content` (string, no length limit) | `{"id": "m000001"}` |
| `naive_rag_search` | `query` (string), `whole` (optional boolean) | `{"results": [...]}` |
| `naive_rag_delete` | `memory_id` (string) | `{"deleted": true}` or `{"deleted": false}` |

Default search ranks every stored chunk, returning up to five objects with
`id`, `ordinal` (zero-based) and chunk `content`. `whole: true` instead ranks
memories by their best chunk and returns up to five distinct memories with
whole, exact `content` and no `ordinal`, for the forget path. No scoring chunk
means an empty results list. Scores are not returned.

The algorithm uses `\w+` over `str.lower()`, signed SHA-256 coordinates,
raw word counts, and the control's 24-term Fraction logarithm and integer IDF.
IDF counts chunks across the entire stored corpus. Chunks split at whitespace
word boundaries when adding a word would exceed 240 characters; a single
longer word remains intact. Positive dot products with positive chunk norms
rank by the exact Fraction `dot² / norm²`, then memory id's numeric counter
and chunk ordinal. The counter comparison preserves insertion order even
when ids grow beyond six digits.

The JSONL store is `plugin-data/naive-rag/store.jsonl` under the supplied
Hermes home. Its first object is `{"counter": N}`, followed by one object per
memory with `id` and `content`. The persisted counter assigns increasing ids
and survives deletion of every memory. Each change writes a temporary file in
the same directory, flushes and fsyncs it, then atomically replaces the store.
Ordinary completion and raised write errors clean up the temporary file; an
abrupt process kill can leave an unreferenced temporary file, but cannot expose
a partially written store. Calls within a provider instance are serialized.

Three known differences from the control remain:

- v1 indexes what the scripted writes store; the control indexes every event.
- Ties fall in memory insertion order rather than event-id order. Equivalence
  tests map insertion order to event order when comparing the same corpus.
- The control retrieves the top five chunks for every probe prompt. v1
  retrieves only when `naive_rag_search` is called, with the caller's query,
  and its prefetch returns nothing. A scripted recall that searches with the
  probe prompt matches the control; in a live run the model decides whether
  and what to search.
