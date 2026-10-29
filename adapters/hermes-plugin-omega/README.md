# OMEGA Hermes provider

Benchmark-authored provider over `omega-memory==1.5.20` core. OMEGA's maintainers
are invited to review it. Adapter and OMEGA core: Apache-2.0; staged BAAI
bge-small-en-v1.5 model: MIT. No upstream code is copied here. Dependencies live
in the benchmark-owned `systems/locks/omega.txt`, constrained against pinned
Hermes on Python 3.14; omit the conflicting `[server]` extra.

| Fidelity row / card property | Behaviour and reason |
|---|---|
| `omega.query_expansion` | Off: `expand_query=False`, `OMEGA_QUERY_EXPANSION=0`; no LLM key, matching OMEGA without one. |
| `omega.reranker` | Off: the shipped default would download the cross-encoder at first query; the benchmark runs offline with every model pinned. `rerank=False`, `OMEGA_CROSS_ENCODER=0`, `OMEGA_RERANKER_AUTODOWNLOAD=0`. |
| `omega.query_cache` | Off: `use_cache=False`; monotonic TTL, results unchanged. |
| `omega.deferred_startup` | Off through a subclass hook; the no-op startup thread is joined before initialization returns. OMEGA's auto-backup files would retain deleted memories; INV-FORGET here is an upper bound on OMEGA's forget behaviour as shipped. |
| `omega.onnx_threads` | `OMEGA_ONNX_THREADS=1`. |
| `omega.store_defaults` | As shipped: `skip_inference=False`, `allow_supersession=True`, dedup; local heuristic inference and supersession. `forgetting_log` and every other deletion residue remain. |
| `omega.prefetch` | Empty: shipped `hooks/auto_capture.py` captures prompts, without querying; `data/hooks-core.json` routes UserPromptSubmit there. File-edit surfacing is a different hook. Explicit writes only. |

`omega.adapter` identifies benchmark authorship on both T0 and T1 cards' JUnit
properties. `OMEGA_HOME` is set before OMEGA imports to
`HERMES_HOME/plugin-data/omega`; its `omega.db` and all auxiliary state are
covered by the HERMES_HOME `.` surface. Availability checks only model files
and ONNX import before initialization; initialization requires OMEGA's active
backend to be `onnx`, refusing silent hash fallback. Results preserve upstream
order and full content, expose integer SQLite rowids, and omit UUIDs and scores.
The thin tools mirror MCP names `omega_store`, `omega_query`; upstream deletes
through `omega_memory(action="delete", memory_id=...)`, so this adapter uses the
specified `omega_delete(memory_id=...)` name. No core Hermes tool has these names.

| Delivered field (#213) | T0/T1 `.fields` | Acceptance |
|---|---|---|
| actor | `not_delivered` | `actor_stored`: declared unsupported, never a storage pass |
| text | `full` | `text_full_length`: must pass live; no schema maxLength |
| time | `session_clock` | harness clock, no event timestamp argument |

`.write_clipped` must be 0; `.write_max_length` is absent. Live ingest round trips,
adapter invariants and two-run card identity await the owner's measured pins.
Do not change upstream UUIDs or timestamps if identity fails: stop and report.
Run `scripts/prepare_omega.py --help` for pinned model staging and the dedicated
Hermes recipe. Use a detached benchmark checkout at commit A as plugin source;
commit B records its archive hash and the twice-measured fresh-install hash.
