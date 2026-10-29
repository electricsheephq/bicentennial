# OMEGA Hermes provider

Benchmark-authored provider over `omega-memory==1.5.20`'s documented Python API. OMEGA's maintainers
are invited to review it. Adapter and OMEGA core: Apache-2.0; staged BAAI
bge-small-en-v1.5 model: MIT. No upstream code is copied here. Dependencies live
in the benchmark-owned `systems/locks/omega.txt`, constrained against pinned
Hermes on Python 3.14; omit the conflicting `[server]` extra.

| Fidelity row / card property | Behaviour and reason |
|---|---|
| `omega.adapter` | Benchmark-authored Hermes provider using the documented `store`, `query_structured`, `delete_memory` API; OMEGA's maintainers are invited to review it. |
| `omega.writes` | `omega.store(content, session_id=...)` retains shipped memory event type, dedup, supersession, 90-day TTL, auto-relate and milestones; return the rowid and outcome word so callers can distinguish writes from dedup and blocks. |
| `omega.reads` | `omega.query_structured(query, limit=10)` delivers full content in OMEGA's order, including injected constraints/preferences, and records accesses. The markdown query/MCP previews default to 200 characters, hiding long event text. |
| `omega.query_expansion` | `OMEGA_QUERY_EXPANSION=0`: off because no LLM key is provided, matching OMEGA without one. |
| `omega.reranker` | `OMEGA_CROSS_ENCODER=0`, `OMEGA_RERANKER_AUTODOWNLOAD=0`: off because the shipped default downloads a cross-encoder at first query; runs are offline with every model pinned. |
| `omega.query_cache` | `query_structured` retains shipped caching: identical queries can use elapsed-time TTLs of 60 s (300 s at high confidence); writes, deletes and non-empty reads clear it. |
| `omega.deferred_startup` | `omega.type_stats()` opens the shipped store; join `omega-deferred-init` before returning so integrity check, WAL checkpoint and backup finish before the first turn. A non-empty store is backed up if no backup is under 24 h old; backups retain deleted memories. |
| `omega.ttl` | `omega.store` retains the shipped 90-day memory TTL on the worker's wall clock; nothing expires within a run. |
| `omega.onnx_threads` | `OMEGA_ONNX_THREADS=1` bounds ONNX worker threads for reproducible resource use. |
| `omega.telemetry` | `ORT_DISABLE_TELEMETRY=1` turns off onnxruntime 1.29.0's usage uploads to Microsoft because runs are offline (owner measurement). |
| `omega.forget` | `omega.delete_memory(node_id)` retains shipped deletion, including `forgetting_log`'s 200-character preview; disclose the residue. |
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
