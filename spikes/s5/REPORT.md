# S5 report: memory-system surfaces (desk survey)

## Claim

**Claim class: `advisory`.** 27 candidate memory systems are surveyed from public sources on 2026-10-26. Every row of [`candidates.csv`](candidates.csv) cites its sources and says what an adapter would need. 17 rows still carry at least one field marked `unverified`. No system was installed, run, timed or scored.

## Method

- **Desk research only.** The survey read READMEs and docs through the GitHub REST API, vendor documentation pages, and public download statistics. Nothing was installed or run. No model was called, and no score was read or recorded.
- **Pinned Hermes.** Release v0.22.2 (commit `d923a5e`, tagged 2026-10-15). The survey read its memory docs, its two bundled memory providers and its plugin catalog.
- **LCM-X.** Its public README and the Hermes catalog entry only, never its source.
- **Candidate pool:**
  - Hermes native memory and LCM-X.
  - The 2 memory providers bundled in pinned Hermes.
  - The vendor-maintained memory providers in the pinned catalog.
  - The open-source systems named in the dispatch, each checked against its own repository.
  - Agent Memory Leaderboard (AML) entrants. The AML site returned HTTP 522 on 2026-10-26, so entrant names and repository links come from the data file in the AML Hugging Face Space (revision `d01a321`, last modified 2026-08-18).
- **Survey cut for AML entrants.** The survey covers open-source entrants whose repository resolved and had at least 1,000 GitHub stars: 7 repositories, one of them Mem0. It also covers the open-source projects behind commercial-track entries (MemPalace, claude-mem). This cut only bounds the survey. It is not the C-9 adoption metric, and no row is ranked.
- **Field rules:**
  - A claim with no primary source is marked `unverified`.
  - Write tools come from vendor documentation (plugin READMEs, MCP references), as C-6 requires. The read tools are listed for contrast.
  - State paths use `$HERMES_HOME` and `$HOME`.
- **Adoption.** Taken on 2026-10-26:
  - GitHub `stargazers_count` from the REST API.
  - PyPI last-month downloads from pypistats, only for package names the project's own README names.
  - npm last-month downloads from the npm downloads API, for the window 2026-09-23 to 2026-10-22.
- **Checker.** [`check_candidates.py`](check_candidates.py) (standard library only) checks the header, at least 12 rows, no empty cell, https-only sources and the adoption date, and prints the counts used below. `python3 spikes/s5/check_candidates.py` exits 0.

## Results

**Machine state.** No timing was measured, so no number below depends on load. The busy marker was read 5 times during the survey (02:28 to 02:48 UTC). Each time it gave exit 10 (`"state": "row"`, `"glm": false`). The 1-minute `vm.loadavg` ranged from 6.81 to 14.58, and the 15-minute value from 12.78 to 15.37. This report was written from the CSV at 04:14 UTC, with the marker at exit 0 (`"state": "idle"`, `"glm": false`) and a 1-minute load of 17.49. All work was light and single-process.

### Per-system summary (n = 27 rows)

Surfaces and adoption. Downloads are PyPI last month, or npm for 2026-09-23 to 2026-10-22.

| System | Licence | Hermes surface | MCP server | Ingest and query API | AML entrant | Adoption, 2026-10-26 |
|---|---|---|---|---|---|---|
| Hermes native memory | MIT | built in | none | none (files and SQLite) | no | 257,080 stars (the harness; not a memory metric) |
| LCM-X | MIT | context-engine plugin; the catalog pins 0.24.3, the latest stable is v0.28.1 | none documented | none (Hermes plugin only) | no | 100 stars |
| ByteRover | Elastic-2.0, repo archived | bundled | yes | CLI | no | 4,945 stars; npm 6,249 |
| RetainDB | Apache-2.0 with a BSL 1.1 part | bundled | yes | HTTP | no | 55 stars |
| Honcho | AGPL-3.0 | catalog, vendor | yes (hosted; self-hosted unverified) | REST and SDKs | no | 7,770 stars; PyPI 542,206 |
| Mem0 | Apache-2.0 | catalog, vendor | hosted only | library; REST on the self-hosted server | yes, both tracks | 67,806 stars; PyPI 2,020,516 |
| Hindsight | MIT | catalog, vendor | yes | REST and SDKs | yes (commercial; a third-party open-source adapter) | 53,760 stars; PyPI 28,563 |
| OpenViking | AGPL-3.0 (plugin MIT) | catalog, vendor | yes | HTTP, SDKs and CLI | no | 40,811 stars; PyPI 435,659 |
| Holographic | MIT | catalog | no | none | no | 22 stars |
| Supermemory | MIT | catalog, vendor | yes (hosted) | REST, also on Supermemory local | yes (commercial) | 31,397 stars; npm 448,344 |
| Cognee | Apache-2.0 | catalog, vendor | yes | REST and SDKs | yes (commercial) | 32,752 stars; PyPI 86,048 |
| Graphiti (Zep) | Apache-2.0 | none | yes (reference server) | library; reference REST | no | 32,216 stars; PyPI 619,128 |
| Letta (Letta Code) | Apache-2.0 | none: its own harness | agent messaging, not memory | none | no | 3,709 stars; npm 595,798 |
| MemOS | Apache-2.0 | vendor plugin outside the catalog | none found | REST (self-hosted) | yes (commercial) | 12,092 stars; npm 8,762 |
| LangMem | MIT | none | none | library | no | 1,720 stars; PyPI 773,504 |
| Memobase | Apache-2.0 | third-party catalog provider | yes | REST and SDKs | no | 2,937 stars; PyPI 2,503 |
| A-MEM | MIT | none | none | library | no | 1,207 stars |
| MemoryOS | Apache-2.0 | none | yes | library | no | 1,613 stars; PyPI 44 |
| Basic Memory | AGPL-3.0 | none (attachable through Hermes' MCP client) | yes (primary surface) | CLI and MCP | no | 4,352 stars; PyPI 27,770 |
| MemPalace | MIT | none | yes (47 tools) | CLI and MCP | yes (commercial) | 59,737 stars; PyPI 53,048 |
| claude-mem | Apache-2.0 | none: targets other harnesses | yes (reads only) | local worker HTTP | yes (coding track, commercial) | 103,139 stars; npm 63,865 (SDK only) |
| TencentDB Agent Memory | MIT | model-API proxy, no plugin | none | REST (v3 tools API) | yes, both tracks | 29,929 stars |
| MemoryBear | Apache-2.0 | none | none found | REST | yes (open source) | 8,575 stars |
| MemMachine | Apache-2.0 | none | yes | REST and SDKs | yes (open source) | 3,076 stars; PyPI 263 |
| SimpleMem | MIT | none | yes | library | yes (open source) | 3,849 stars; PyPI 74 |
| LightMem | MIT | none | yes | library | yes (open source) | 1,203 stars |
| M-flow | Apache-2.0 | none | yes | REST | yes (open source) | 4,508 stars |

What an adapter would need, per row. "Settle" marks a row whose writes become searchable only after background processing.

| System | Adapter mode | Write tools (C-6 candidates) | Own model calls · local embeddings | State to snapshot | Also needs |
|---|---|---|---|---|---|
| Hermes native memory | Hermes | `memory` (add, patch, remove); edits to MEMORY.md and USER.md under the file-tool rule | background review and the compression summariser · no | `memories/` and `state.db` in `$HERMES_HOME` | route both calls through the director; keep `memory.write_approval` false |
| LCM-X | Hermes (context engine, release artifact) | none documented: 16 tools, all reads or diagnostics | summariser through the Hermes model · yes (FastEmbed) | `lcm.db` and the externalized-payload directory (path not in the README) | route the summariser; pin or disable local embeddings |
| ByteRover | Hermes with a pinned brv CLI | `brv_curate` | agentic LLM loop on curate and query · unverified | `$HERMES_HOME/byterover/` and the brv settings directory | point its LLM at the director; licence check; whether the plugin stays in the Hermes release used |
| RetainDB | Hermes against RetainDB Local | `retaindb_remember`, `_forget`, `_upload_file`, `_ingest_file`, `_delete_file` | unverified · unverified | `$HOME/.retaindb` | the plugin defaults to the hosted API; whether it works against Local is unverified; BSL check |
| Honcho | Hermes with a self-hosted server | `honcho_conclude`, `honcho_profile` (update) | background reasoning and dialectic chat · unverified | the server's Postgres | settle (reasoning queue); config resolves from both `$HERMES_HOME` and `$HOME` |
| Mem0 | Hermes (OSS mode) or API | `mem0_add`, `mem0_update`, `mem0_delete` | extraction on add and embeddings, hosted by default · optional | the Qdrant directory (default under the system temp dir) and `$HOME/.mem0/history.db` | move both paths into the sandbox; telemetry off; add and search map onto ingest and query |
| Hindsight | Hermes (local mode) | `hindsight_retain` | retain and reflect; auto-retain every turn · yes, plus a reranker | the embedded Postgres data directory; one bank per life | settle (`retain_async` is on by default) |
| OpenViking | Hermes with a pinned server | `viking_remember`, `viking_forget`, `viking_add_resource` | embedder and VLM; extraction on session commit · optional | the workspace directory; `$HOME/.openviking` | start the server before Hermes, or the plugin spawns it with the full Hermes environment |
| Holographic | Hermes | two: `fact_store` (25 actions; C-6 must say which count as writes) and `fact_feedback` (moves trust scores, records confirmations) | none by default · no | `memory_store.db`, plus scoped databases beside it | keep embeddings and rerank off (the offline default) |
| Supermemory | Hermes with Supermemory local | `supermemory_store`, `supermemory_forget` | extraction and profiles · yes (local mode) | `$HOME/.supermemory` | settle; capture is at-least-once, so check for duplicates; telemetry off |
| Cognee | Hermes (local mode) | `cognee_remember`, `cognee_forget`, `cognee_switch_dataset` | with an LLM key, extraction and embeddings by the provider; without one, local extraction · yes when no key is set | `$HOME/.cognee`, shared across profiles | isolate `$HOME`; manage the detached server; settle (graph built in the background); telemetry off |
| Graphiti (Zep) | API (graphiti-core), or MCP for a Claude Code cell | (MCP) `add_memory`, `add_triplet`, `delete_entity_edge`, `delete_episode`, `clear_graph`, `summarize_saga`, `build_communities` | extraction on every episode and embeddings · no by default | a graph database per clone | the simulated `reference_time` on every episode; new code for a Hermes cell |
| Letta (Letta Code) | harness adapter | ordinary file tools on its MemFS (names not documented) | self-rewrite and background dreaming subagents · unverified | the MemFS git repository; `$HOME/.letta` | outside the Phase 1 Hermes scope |
| MemOS | Hermes through the vendor installer, or API | none documented: capture on turn sync (tool names unverified) | background auxiliary LLM · yes | `$HERMES_HOME/memos-plugin/` | a Node.js bridge daemon; `MEMOS_HOME` in the sandbox; settle (background capture) |
| LangMem | API (new code) | `manage_memory` (create, update, delete) | background manager and store embeddings · depends on the store (unverified) | the backing LangGraph store | a persistent store (the in-memory store loses state on restart) |
| Memobase | Hermes (third-party provider) with a server | none for the agent: the provider's tools are reads, and writes come from turn sync | 3 LLM calls per flush, plus embeddings · unverified | the server's Postgres and Redis | settle (`flush(sync=True)` at checkpoints); low repository activity |
| A-MEM | API (new code) | none (library only) | notes, links and memory evolution · yes | a ChromaDB collection (location unverified) | research code; checkpointing unverified |
| MemoryOS | API (library or MCP) | `add_memory` | summaries and profile analysis · yes | the caller's `data_storage_path`, one per life | point its OpenAI-compatible base URL at the director |
| Basic Memory | MCP (a Claude Code cell, or Hermes' MCP client) or file ingest | `bm_write`, `bm_edit`, `bm_move`, `bm_delete`, `bm_project` (create) | none required · yes | `$HOME/basic-memory` and a SQLite index (location unverified) | the file-tool rule applies, because notes are plain files |
| MemPalace | MCP or CLI | 20 of its 47 tools change state, for example `mempalace_add_drawer`, `mempalace_kg_add`, `mempalace_diary_write`, `mempalace_mine` | none in raw mode · yes | `$HOME/.mempalace` | C-6 must pick from the 20 |
| claude-mem | Claude Code cell | none: hooks capture, and the MCP tools are reads | observation summaries · Chroma (model unverified) | `$HOME/.claude-mem` | route its summary model; isolate `$HOME` |
| TencentDB Agent Memory | proxy chaining: harness, then the proxy, then the director | none: capture happens in the proxy | two LLM groups (memory and proxy) · unverified | Docker volumes (unverified) | S1 must class the proxy's own calls; it changes the request path the director sees |
| MemoryBear | API | none (no agent tools) | triple extraction and BERT embeddings · unverified | Postgres, Neo4j, Elasticsearch and Redis | four datastores and seven worker types per clone, so S3 clone cost matters |
| MemMachine | API | (MCP) `add_memory`, `delete_memory` | any configured LLM provider · unverified | Neo4j and SQL | both stores per clone |
| SimpleMem | API (ingest and retrieval, not `ask()`) | (MCP) `memory_add`, `memory_add_batch`, `memory_clear` | compression, answers from `ask()`, EvolveMem tuning · yes | LanceDB tables and a user database | EvolveMem self-tunes on development questions |
| LightMem | API | (MCP) `add_memory`, `offline_update` | an LLM memory manager and a compression model · yes | the configured retriever store (unverified) | pinned local models; research code |
| M-flow | API | (MCP) `memorize`, `save_interaction`, `ingest`, `update_data`, `delete`, `prune`, `learn` | extraction and embeddings · unverified | the configured store | one store per clone |

### Aggregate counts (n = 27 rows)

| Field | Count |
|---|---|
| Hermes surface | 1 built in (native) · 2 bundled (ByteRover, RetainDB) · 9 plugins: 8 in the pinned catalog (LCM-X as a context engine, Honcho, Mem0, Hindsight, OpenViking, Holographic, Supermemory, Cognee) and MemOS's own installer · 1 third-party catalog provider (Memobase) · 1 model-API proxy (TencentDB Agent Memory) · 13 none |
| MCP server | 17 yes · 1 hosted only (Mem0) · 1 not a memory surface (Letta) · 8 none |
| Ingest and query API | 14 REST or SDK · 5 library only · 3 CLI · 1 local worker HTTP (claude-mem) · 4 none |
| AML entrant | 13 |
| Write tools documented | 20 rows name at least one write path (Letta Code's are unnamed file tools) · 7 document none for the agent (LCM-X, MemOS's Hermes adapter, Memobase's Hermes provider, claude-mem, TencentDB Agent Memory, A-MEM, MemoryBear) |
| Own model calls in the default path | 22 · 1 only with an LLM key (Cognee) · 3 none by default (Holographic, Basic Memory, MemPalace raw mode) · 1 unverified (RetainDB) |
| Local embeddings by default | 11 · 2 optional · 3 none · 11 unverified or configuration-dependent |
| Licence | 11 MIT · 11 Apache-2.0 · 3 AGPL-3.0 · 1 Elastic-2.0 (source-available) · 1 Apache-2.0 with a BSL 1.1 part |
| Adapter mode | 13 Hermes (Mem0 and MemOS also have an API mode) · 9 API · 2 MCP or CLI · 2 harness · 1 proxy |
| Adoption recorded | stars 27 of 27 · downloads 18 of 27 |

**Pinned Hermes (v0.22.2).**
- The catalog has 613 entries. 65 are in category `memory`, all community tier. The survey covers 9 of them.
- **Bundled providers.** Two memory providers are bundled: ByteRover and RetainDB. The upstream standalone repository of each is marked unmaintained and leaving Hermes core on 2026-10-15. ByteRover's CLI repository is archived and licensed Elastic-2.0.
- **LCM-X catalog pin.** The catalog pins LCM-X at 0.24.3. LCM-X's latest stable release is v0.28.1 (2026-10-20). The pilot installs LCM-X from its release artifact, as PREREG §10 already requires.
- **MCP client.** Hermes is an MCP client (`mcp_servers` in `config.yaml`), so an MCP-only system can be attached as tools. Attached that way, it gets none of the provider hooks: no prefetch, turn sync or pre-compress.

**AML board (data file, revision `d01a321`).**
- The textual track has 50 open-source entries and 15 commercial entries.
- Across both tracks, the open-source entries link 51 distinct repository URLs:
  - 45 resolve and 6 do not (some look truncated in the data file);
  - 7 of the 45 have at least 1,000 stars.
- 13 rows of this survey are AML entrants. They are the natural first users of the v1.x AML-compatible adapter in the roadmap.

### Gap patterns

Each pattern names the rows it rests on.

1. **Settle before probe.** In 6 rows, a write becomes searchable only after background processing:
   - Honcho: background reasoning;
   - Hindsight: `retain_async` is on by default;
   - Cognee: the graph is built in the background;
   - MemOS: background capture;
   - Memobase: buffered until a flush;
   - Supermemory: capture is retried at least once.

   The adapter contract in DESIGN §6.9 (reset, ingest, query, checkpoint and restore, forget, stats) has no settle step. A checkpoint or a probe taken without one would read a state that is still moving.
2. **State outside `HERMES_HOME`.** 9 of the 13 rows with a Hermes surface keep state outside it: a server database, a dot-directory in `$HOME`, or Mem0's default vector path in the system temp directory. Only Hermes native, LCM-X, Holographic and MemOS stay inside it (LCM-X's externalized-payload directory is plugin-managed, and the README does not name its path). Snapshots and S3 clones must therefore cover `$HOME` and server data, not only `HERMES_HOME`.
3. **Model routing.** 22 rows call a model in their default path. Several default to a hosted provider: Mem0, Graphiti and LangMem, and Cognee once an LLM key is set. At $0, each needs a route-table entry (§10) that points it at the director or a pinned local model, and S1 must class those requests.
4. **Local embeddings.** 11 rows embed locally by default. The busy marker forbids local-embedding ingest at exit 10, so S5b timings for these rows need marker exit 0.
5. **Non-Hermes shapes.**
   - TencentDB Agent Memory is a model-API proxy. It would sit in front of the director and send its own memory-model calls.
   - Letta Code is a harness, and claude-mem targets Claude Code and other harnesses, not Hermes.
   - 11 of the 13 rows with no Hermes surface are API, library or MCP systems for API mode.
6. **Write-tool granularity for C-6.**
   - Some write tools take many actions: Hermes `memory` has 3, Holographic `fact_store` 25, Basic Memory `bm_project` 3. Their lists need action-level entries.
   - A row can have more than one write tool: Holographic's `fact_feedback` changes trust scores and records confirmations, so it belongs on Holographic's list beside `fact_store`.
   - MemPalace has 20 state-changing tools out of 47.
   - Some tools answer with the system's own model: SimpleMem `memory_query`, Hindsight `hindsight_reflect`, Honcho `honcho_reasoning`. In the layer evaluation the pinned agent answers instead.
   - SimpleMem's EvolveMem self-tunes on development questions. That falls under the equal configuration budget (§10).
7. **Licences.** 5 rows are AGPL-3.0, Elastic-2.0 or partly BSL. PREREG §10 requires an open-source competitor, and it does not yet say whether a source-available licence (Elastic-2.0) or a BSL part qualifies. C-9 has to settle that.
8. **The choice of adoption metric changes orderings.**
   - LangMem has 1,720 stars and 773,504 PyPI downloads in the last month.
   - MemoryOS has 1,613 stars and 44.
   - claude-mem's npm count covers its SDK only.

   This survey ranks nothing. C-9 fixes the metric on the completion date.

### What an adapter would need

Across the 27 rows, the adapter needs reduce to these additions to the Phase 1 build:

- **Five adapter modes,** not one: 13 Hermes rows, 9 API rows, 2 MCP or CLI rows (Basic Memory, MemPalace), 2 harness rows (Letta Code, claude-mem) and 1 proxy row (TencentDB Agent Memory). The API rows need new code per system; for example graphiti-core, Mem0 and MemMachine document add and search calls that map onto `ingest` and `query` directly.
- **A settle step** in the adapter contract, for the 6 rows in pattern 1, run before every checkpoint and every probe.
- **Snapshot scope** that covers `$HOME`, server databases and Docker volumes as well as `HERMES_HOME` (pattern 2), with an isolated `$HOME` per life wherever a row keeps a dot-directory there.
- **Route-table entries** for every row with its own model calls (pattern 3), including summarisers, extraction, VLMs and answer-synthesising tools, and an S1 class for each.
- **Machine gating** for the 11 local-embedding rows (pattern 4), and pinned local models where a row ships them.
- **Pinned releases and servers.** Every row must be pinned to a released artifact. Rows with a server, daemon or datastore (for example Honcho, Hindsight, OpenViking, Memobase, Graphiti, MemoryBear, MemMachine, MemOS's bridge, Cognee's detached server) need one instance per clone and a start order before the harness.
- **Telemetry switches** where a row documents one: Mem0, Supermemory and Cognee.
- **Declared write tools at action level** (pattern 6). 7 rows document no agent write tool, so under §10 they get no write turns.

## What is deferred

- **S5b,** the p50 latency of each surface. It needs installs, and marker exit 0 for the 11 local-embedding rows.
- **The `unverified` fields in 17 rows.** The main ones:
  - local-embedding defaults for 9 rows;
  - RetainDB's model calls, and whether the bundled plugin works against RetainDB Local;
  - TencentDB Agent Memory's state paths;
  - whether Supermemory local's server source is in its MIT repository;
  - the tool names of MemOS's Hermes adapter;
  - the path of LCM-X's externalized-payload directory.
- **The declared write-tool lists (C-6) and the competitor selection (C-9).** This survey supplies candidates only.
- **Rows not surveyed:**
  - 56 of the 65 catalog memory entries;
  - 44 of the 51 AML open-source repository URLs (below the survey cut, or unresolved);
  - hosted-only services such as Zep Cloud.
- Whether attaching an MCP-only system to Hermes as tools is an acceptable Hermes cell, given that it gets no provider hooks.

## Does not prove

- The latency or quality of any system.
- That any surface works as its documentation says: nothing was installed or run.
- The competitor selection, which follows the C-9 rule on the completion date.
- That stars or downloads measure adoption. Both are proxies, read once on 2026-10-26.
