# Ring 0 specification (v0.1 Kit)

**Status:** v0.1, written by the benchmark session for the v0.1 Kit (#29). It fixes the terms that design v2.2 and PREREG-v0.4 leave undefined for the developer tiers T0 and T1. PREREG-v0.4 governs every frozen quantity. Where this text and DESIGN differ, `docs/ERRATA-v2.2.md` records the difference and its basis. Nothing here changes a board rule, a bar or a completion slot.

**What Ring 0 is** (PREREG §6 l.383-388; DESIGN §9.1). Ring 0 is the public developer packs. Every Ring 0 result carries these labels:
- "not predictive of the full tier; never certifies";
- "filters: not run (v0.2)";
- "rungs: uncalibrated (v0.2)";
- "voice: template".

Each lever takes one uncalibrated value in v0.1. The developer tiers carry no decision bar.

## 1. The scripted reader

The scripted reader answers T0 and T1 probes without a model. It is deterministic. Its result measures **evidence availability** at probe time: whether the system put the right evidence in front of the agent. It is not a model's judgement.

**Inputs.** The reader reads exactly two things.
- **The probe-time context:**
  - In **memory-layer mode** (T0 by default), the context is the output of the system's query surface for the item: `adapter.query(task, now)`, plus any context block the system injects for that turn (a provider's prefetch block, say).
  - In **Hermes mode** (T1, and T0's fallback), the reader makes the system's **declared recall call**: a tool from the system's declared read-tool list, with arguments filled from the item's argument template and the item prompt only. The context is the bytes of the harness's next request after that call: the tool result plus everything the harness put in the request (its system prompt with any injected memory, and the session's messages).
- **The item's option list.** Each item ships a list of options. An option has an id, a list of **locked tokens** (the numbers, names, dates and codes the renderer passed through unchanged; DESIGN §4.4), and either a typed QA envelope or a scripted action plan. One option may have an empty token list. It means UNKNOWN, "never observed" or refrain, according to the item type.

**What it never reads:** the generator's manifest, the answer key, the world database, the ledger, the system's store or any file the system wrote. Its one gold-derived input is the option order (below). The order can choose only among options whose tokens are present in the context. A token that is absent from the context can never be emitted, so a system whose context lacks the evidence cannot score as if it had it.

**Presence.**
- An option is **present** when every one of its locked tokens occurs in the context.
- A token occurs when the context contains it as an exact, case-sensitive substring of the UTF-8 text, after Unicode NFC normalisation of both.
- **Build check:** the generator refuses any locked token shorter than 4 characters. It also refuses any token that occurs in the rendered life outside its own evidence events, the probe prompts included.

**Policy (lenient).** Options are listed in a fixed **priority order**: the gold option first, then the competing options in keyed order (`keyed.shuffle` over the item id).
1. The reader selects the first present option with a non-empty token list.
2. If none is present, it selects the empty-token option. If the item has no empty-token option, the reader emits UNKNOWN.

The order encodes one leniency: when the gold evidence and a stale or decoy value are both present, the reader acts on gold. A lossless store that keeps the stale value beside the current one therefore loses nothing here. The **competing-token diagnostic** records it: every option with a non-empty token list that is present but not selected is listed on the item's result. The card prints the share of items with a competing option present, per system and per track. Lenient scoring under-tests supersession, and the card says so; the live tiers (T2 and up, v0.2) judge it with a model.

**Outputs:**
- **A QA item** yields its typed envelope, from the selected option:
  - a selected option with tokens is asserted, at confidence 1.0;
  - the empty-token option is an UNKNOWN envelope at confidence 0.
  The envelope cites, as a quote match, the context span where the selected option's first token occurs (DESIGN §7.5). It is scored by the real QA scorer (PREREG §3).
- **An action item** yields its scripted action plan, from the selected option. The plan is compiled into the harness's tool dialect by the tool-call compiler (DESIGN §6.2d) and executed in the sandbox at the item's action point. The real action scorer scores it from the trace and the end state, twin minimum included (PREREG §3). The empty-token option's plan is to refrain, which executes no action.
- **recall@5** is a report-only diagnostic for memory-layer mode, wherever the query returns ranked citations: the share of the item's evidence events whose quote is matched in the top 5 citations. Hermes mode reports presence in context instead.
- **Stages** (DESIGN §7.3a) are attributed per failed item:
  - stored and retained, from the span search of our snapshot copy of each declared surface;
  - retrieved, from presence in the probe-time context.
  The reader uses whatever is present, so "used" never fails at Ring 0: a failure is attributed to retrieval or an earlier stage, or reads unknown.

## 2. The scripted model (T1)

At T1 every request the harness or the system sends is answered by a deterministic responder in the director. The responder is chosen by the request's S1 role (`spikes/s1/REPORT.md`). No upstream socket opens, and no credential is loaded.

| S1 role | Responder |
|---|---|
| `replay_main` | the scripted turn at the cursor, through the tool-call compiler, as in S6a |
| `write_turn` | the content-blind write rule (below) |
| `probe_main` | the scripted reader's recall call (§1), then the envelope, or the action plan one step per request and then the text `Noted.` (a refrain plan has no step). A probe reply is never empty: Hermes answers an empty main reply with retries that wait on the simulated clock |
| `compaction`, `summariser`, `extraction` | the extractive stub (below) |
| `memory_write` | the content-blind write rule. This role is added when the classifier is promoted (R01): S1's background-review marker, and any pre-compaction-flush or session-end marker, map to it instead of `aux` |
| `title` | the fixed title `Session` |
| `aux` | an empty assistant message with no tool call |
| `unknown` | refused, as the director does on every tier |

A request reaches `replay_main` or `probe_main` by the cursor rule: its last user text equals the scripted turn's. Pinned Hermes appends a turn's prefetched memory to that text: a blank line, then a `<memory-context>` fence that opens with Hermes's system note. A script whose user text holds the wrapper is refused, so the first such wrapper is Hermes's own block. If the exact text matches no turn, the rule compares the text before it. So an exact retry is never read as the next turn. The block, and anything after it, stays in the request, so it is part of the Hermes-mode context (§1). Text appended without that wrapper still fails closed.

Embedding requests (an embeddings endpoint on a declared alias) go to the hashed-vector stub.

**The content-blind write rule.** It applies to every write turn, and to every harness- or system-originated memory-write request (DESIGN §6.2's `memory_write`: background review, the pre-compaction flush, session-end hooks).
- **When the request offers at least one of the system's declared write tools,** the responder makes exactly one call, to the first declared write tool on the system's list (C-6). The call carries the latest user message in that request verbatim, as the tool's content argument. That message is the last user-role message in the harness's own request, and never a director-added suffix. The content is that message's own text. When pinned Hermes has appended a prefetched memory block (below), after the text or as its own text part, the block is not part of the content.
- **A `memory_write` request is recognised by its last user message,** which is the harness's own memory-write prompt (Hermes's background review sends its review prompt as that message). So for `memory_write` the content is the latest user message *before* that prompt, and a request with none gets an empty reply. The harness's prompt is never stored.
- **One write per user message.** When a tool result follows the request's last user message, the write was already issued, so the reply is empty whatever the tool answered.
- **When the tool documents a per-call length limit,** the content is cut at that limit, by character.
- **The per-system mapping:**
  - Hermes native: `memory`, with `action: "add"`, `target: "memory"` and `content`;
  - Holographic: `fact_store`, with its add action and the content argument;
  - Mem0 OSS: `mem0_add`, with its content argument.
  The exact argument names come from each pinned release's tool schema, recorded with the route table.
- **The tool's answer is not acted on.** A refusal, a full budget or an error is the system's own answer: the ledger records it, and the call is never retried.
- **Text the model writes** in a write turn is discarded, as on every tier.

The rule cannot see content: every system gets the same call on the same turns. A system whose declared write-tool list is empty gets no write turns (PREREG §10).

**The extractive stub.** One stub serves the compaction, summariser and extraction roles.
- Its output is built from the request's own message text, in order:
  - each user and assistant message's text, cut to its first 240 characters;
  - joined with newlines;
  - cut to the request's output-token limit, measured with the token estimator (§9). A request with no limit is cut at 4,096 characters.
- **Where a system parses a structured reply,** the stub fills the declared format with the same text. Pinned Mem0 OSS (mem0ai 2.2.1) makes one additive extraction call and reads a `memory` list from the reply. The stub answers that call with a fact list, which Mem0 does not read, so Mem0's automatic extraction stores no vector memories at Ring 0 (E11, #208). Its explicit `mem0_add` writes, which the content-blind write rule fills, are stored verbatim and carry what Ring 0 measures. Each system's formats are recorded in its registry entry.

**The hashed-vector stub.** For text t and dimension D (the system's configured embedding dimension, recorded in its registry entry):
1. The text is split into lower-case word tokens on Unicode word boundaries.
2. D must be at least 2. Each token adds ±1 to coordinate 1 + (h mod (D−1)), where h is the first 8 bytes of sha256(token), read as an unsigned big-endian integer. The sign is the lowest bit of the 9th byte: set means −1. Coordinate 0 is reserved.
3. If the token counts' sum of squares is zero (no tokens or complete cancellation), return the zero vector. Otherwise let u be the unit vector of the counts over coordinates 1..D−1. The output is g(u) = (u/√2, 1/√2), with the shared 1/√2 in coordinate 0 and u/√2 in coordinates 1..D−1. Coordinates are scaled by `VECTOR_SCALE` and rounded to the nearest integer (an exact half rounds toward zero) using integer arithmetic only. Moving from D to D−1 token buckets changes collisions, so order relative to the old vectors is not preserved.

Similarity is then lexical overlap c, reported as (1 + c)/2. This is a declared synthetic convention, the standard map of cosine into [0, 1]; it is not a claim about any trained embedder's scale. Order by similarity alone is the order by c. A system that adds other signals to the similarity weighs similarity differences half as much as on the raw scale, and its absolute thresholds and signal weights are not validated at Ring 0. Mem0 2.2.1 can add a keyword (BM25) score and entity boosts when its optional features are installed; the locked install (E9) has neither, so at Ring 0 Mem0 ranks by similarity alone, and its 0.1 threshold is the only absolute value it applies. It is crude, model-free and the same for every system.

**Labels.** Every T1 card prints "scripted model: wiring-only".
- The stubs prove that requests route and that the plumbing holds. They never measure extraction or summary quality.
- A store that the stubs leave empty or degenerate is reported as found. The wiped-store control is then labelled "uninformative" for that system (§5).

## 3. Stages and the Act label

| Stage (PREREG §2) | What it is at T0 and T1 |
|---|---|
| **Remember** | QA items whose evidence crosses only cold restarts and simulated gaps before the probe |
| **Survive** | QA items whose evidence crosses at least one fault-lite stress before the probe: a compaction, the SIGKILL, or the wiring-only swap (§6) |
| **Act** | action items, probed at their action point |

The stage of an item follows from the life's schedule, never from its result. The stages are reported separately and never summed.

Act results at T0 and T1 carry the label **"evidence-conditioned scripted action; not an Act judgement"**:
- PREREG §3 takes the action class from the trace and the end state;
- a scripted policy's trace measures whether the evidence was available, not what a model would do with it.

The live tiers (v0.2) carry the Act stage proper.

## 4. Stable and volatile result fields

**Stable** fields are everything in `card.json`.
- **Pins and hashes:** the benchmark, generator, director and scorer commits; the pack and seed hashes; the harness and system artifacts; the route table; the write-turn package; the environment boundary hash; the repository boundary hash.
- **The masked ledger digest:** sha256 over the stable projection of every ledger record, in canonical order (below).
- **Per item and per bundle:** the outcome, in integer milli-points (`canon.milli`), with the selected option, the competing-option list and the stage.
- **Aggregates:** stage and track aggregates, the sensitivity rows (PREREG §3), per-item accuracy, coverage, the controls, and the gate verdict (§6).

Everything in `card.json` is written by `canon.canon`, with no floats.

**Volatile** fields are in `receipt.json`: wall times, latency, load, the busy-marker readings, token counts, spend, store growth in bytes, process ids, ports and temporary paths.

**The stable projection** of a ledger record keeps its role, served kind, cursor position and the sha256 of its canonical request and response bodies. Before that hash is taken, these values are masked:
- Hermes session ids;
- random ids anywhere in body text: every lower-case hyphenated UUID becomes `{UUID}`. Hosts and systems mint these, so they differ on every run. Examples are a Hermes session id that the compressor writes into a summary or that `session_search` returns, and a memory store's record ids in a recall result;
- tool-call ids that the harness generated;
- response ids that the harness generated;
- every wall-clock timestamp field;
- the run's sandbox root and the director's port, wherever they occur in body text. Each is replaced by a fixed placeholder (`{SANDBOX_ROOT}`, `{DIRECTOR_PORT}`), so a path or port embedded in a tool result does not reach the digest.

Each mask is a named entry in the masks table of the stable-field schema (K14): a JSONPath for a field, a literal substitution for body text, or a pattern for random ids in body text. A value is masked only through that table, never ad hoc. Ids that the director issues (`keyed.mint_id`) are stable and never masked. The raw-body digest goes to `receipt.json`.

**Canonical order:** (life, branch, session, cursor turn, role, served kind), then the sha256 of the masked canonical record bytes as the tie-break. The arrival sequence is never used, since concurrent auxiliary calls reorder it.

**The claim:** two T1 runs on the same machine, with the same pin set, produce byte-identical `card.json`. Determinism is claimed only per machine and pin set. SQLite page layout and vector indexes make cross-machine byte identity unlikely, and no claim is made there.

**What determinism needs:**
- keyed ids (`keyed.py`);
- a logical-tick simulated clock that stays behind wall time (R05);
- the masked digest (R02).

The determinism check names the first stable field that differs.

## 5. Verified empty, and the wiped-store control

**Declared surfaces.** Each system's registry entry lists its **declared state surfaces**: every file tree the harness and the system write. Examples:
- `HERMES_HOME`;
- Mem0's vector directory and its history database, moved inside the sandbox (S5 finding 2);
- a server's data directory.

**The fresh-install hash.** A surface's fresh-install hash is sha256 over a canonical listing of its tree, computed after install and configuration and before the first ingest (for when that is at v0.1, see §13 E1). The listing has one line per path: relative path, mode, size and the sha256 of the content. The only paths left out are those the registry entry declares volatile, such as logs and lock files; each one is listed on the card. The run's director port is masked in two benchmark-written files (§13 E4).

**Verified empty** means every declared surface hashes to its fresh-install hash, as taken in the same run (§13 E4). A run starts only from verified-empty surfaces (DESIGN §6.8).

**The wiped-store positive control.** An arm identical to the system arm, except at every **wake**: every declared surface is restored from the fresh-install snapshot and verified by hash before the harness starts.
- **A wake** is any harness start on existing state: the start of every session after the first (each T1 session is a new process, as in S6a), the restart after the SIGKILL, and the start of every probe session.
- **Its replay is not skipped.** It drives every write path the system has. A surface that the registry failed to declare survives the wipe, and the control then catches it.
- **Expected result:** every scored item's evidence crosses a wake (§6), so on memory-exclusive bundles this arm must score the no-memory value.
- **The gate:** the T1 gate must return FAIL on it. If it passes, the run is **invalid**.
- **Uninformative:** a system whose own arm has zero wake-crossing recall makes the control uninformative. That is disclosed, and it is not a pass.

## 6. T1 composition and the probe budget

**Lives:** one public G1 base life and one public G2 base life, each with 20 sessions of about 5 assistant turns.
- Each base life B0 has its twin life B1. B1 is replayed in full from session 1. When replay is deterministic, that is identical to forking at the first flipped event. Forking is a v0.2 optimisation.
- That makes 80 replay sessions per replaying arm.

**Fault-lite points,** the same for every system:
- **The SIGKILL:** a kill of the harness process at the first turn boundary of session ⌈0.55 × 20⌉ = 11, on B0 and B1, then a cold restart. This is the board rule (PREREG §6) scaled to 20 sessions.
- **Compaction sprints:** at least 2 per life, one before session 11 and one after it. Each is at least 1.25 × W in history tokens, at the provisional C-5 window W (§9; K02). Compaction then fires inside sessions.
- **One wiring-only swap:** at the start of session 15, the route table moves the harness's alias from `bicentennial-main` to `bicentennial-swap`. The scripted model serves both aliases identically, so the swap exercises the harness's model-switch path and not a model.
- **Delivery faults** (DESIGN §6.5) are not in fault-lite, so T1 has no exactly-once invariant (v0.2).

**Checkpoints:** after sessions 10 and 20. One is before the kill and one is after it.

**Placement** (G17):
- every scored item's evidence lies in an earlier session than its probe, so it crosses at least one wake;
- at least two scored bundles per life have their evidence in session 1 or 2, so a store whose budget fills early still has wake-crossing items.

**The probe budget** per (life, branch, checkpoint): at most 6 QA items and 2 action items.
- **The QA items** run in one probe session, in the pack's fixed item order, on a clone of every declared surface that is discarded afterwards.
  - **Isolation is per checkpoint, not per item** (DESIGN §6.7), and the card says so.
  - **Carry-over:** an earlier probe's recall result or answer can stay in the session, or be captured by the system's store, and make a later option present. The reader's context is still the one §1 defines, so this is measured, not removed.
  - **The carry-over diagnostic:** for each QA item, the result records whether its selected option's tokens also occur in an earlier probe exchange of the same session, from the ledger. The card prints the share per system.
  - **Fixed order:** a run with the same pack gives the same carry-over, so determinism holds. The live tiers keep one clone per item.
- **Each action item** runs in its own probe session on its own clone, because its plan changes the world.
- That makes at most 3 probe sessions per (life, branch, checkpoint), and 24 per arm.

**Arms:**
- the system;
- the wiped-store control;
- the no-memory floor, a cached control: the reader on an empty context, computed once per pack.

The oracle-evidence, full-history and naive-RAG columns are cached with the pack. The baselines rule (PREREG §2) puts all four baselines in every table:
- **naive RAG** at T1 is the cached API-mode control (S09) over the same lives, labelled "cached, API mode";
- until S09 lands, the column reads "not run in v0.1", and the card discloses that the baseline set is incomplete. No value is invented.

**Also run:** the public regression corpus, and the write-turn audit (R10).

**Forgetting is not exercised at T1.** The scripted model only adds (§2), so no deletion is ever requested.
- KEEP-FORGET and KEEP-NEIGH items are reported "not exercised at T1" and sit outside the T1 gate. They are never scored as a system failure.
- T0 exercises forgetting through the adapter contract (§7).
- A content-blind delete for T1 waits for v0.2: it needs a declared forget plan per system and a forget target that a script can carry without a gold token.

**The T1 gate** is PASS only when all of the following hold:
- every S05 invariant passes:
  - recall verbatim after compaction and after the crash, where gold needs verbatim;
  - the newest correction governs after a restart;
  - a tool result sits with its call after the crash;
- no restart-crossing bundle scores below the system's own baseline card;
- every corpus case meets its expectation;
- the wiped-store control FAILs.

**Order of evaluation:**
1. The wiped arm is evaluated on its own invariants, corpus cases and bundles, never on the control condition itself.
2. The control condition then applies to the system arm only.

A first run has no baseline card. If every other condition holds, it is a labelled conformance PASS.

**Verdicts** (§13 E3): PASS, or the labelled conformance PASS; FAIL; INVALID, when the wiped control passed; BLOCKED, when benchmark infrastructure failed after its reruns and no known failure exists. A known failure wins over a blocked entry: the verdict is then FAIL, and the run status still lists every blocked entry.

**Budget:** ≤ 10 min and $0. That is an engineering budget, not a bar (PREREG §6). For scale, take S6a's measured fixed time per Hermes session, about 30 s on a shared machine, and its mean probe session, about 26 s. At those figures, 2 × 80 replay sessions and 2 × 24 probe sessions come to about 100 min run serially, and about 25 min across 4 parallel sandbox roots. Scripted responders remove S6a's upstream time, so the real figure should be lower, but it is not measured. Loop time is measured and published idle and busy, and a miss is disclosed. If the measured T1 misses by more than 2×, v0.2 cuts the probe budget first, then B1's full replay.

## 7. T0 surfaces

- **Packs:** micro-lives of 1-3 sessions per track and ability, from the pack catalogue (G18).
- **Default mode, memory-layer:**
  - **API systems** go through the adapter contract (§11), settle included.
  - **Hermes plug-in systems** go through an in-process memory host. It calls the provider's documented lifecycle hooks, in their documented order, to ingest each scripted turn. The content-blind write rule (§2) fills its write tools, and the reader's recall call uses its read tools.
  - **Hermes native memory** is driven through its documented agent tools, `memory` and `session_search`, called in process with the arguments an agent would send. The host also gives the reader the session-start memory snapshot that pinned Hermes injects into the system prompt, rendered by Hermes's own code at session open. Other harness prompt injection is not exercised, and the run discloses this in its JUnit properties (§13 E7).
- **The fallback** is Hermes replay through the T1 adapter, with a clone per probe. It does not meet the 60 s target, and the miss is disclosed. It ships in v0.2 (§13 E5).
- **Forgetting:** at each forget-request event, the runner calls `forget(selector)` with the target's locked tokens as the selector.
  - Each adapter maps the call onto the system's documented deletion surface: Hermes native's `memory` `remove`, Mem0's delete after its own search, Holographic's forget or remove action (C-6).
  - A plug-in host handles each distinct written text once per call, and keeps one row for each unselected event with the same text. With a search backend it searches that text again after each pass that issued a delete, until a pass issues none, at most 10 searches per text. Rows past one result page are reached only while each pass deletes a row: a page filled with kept or unowned rows ends the search. Systems that record searches see the extra ones: Holographic adds a retrieval to each row a search returns, including rows the forget keeps, and Mem0 makes an embedding request for each search.
  - The forgetting invariant is then checked by byte search of the declared surfaces, beside the KEEP-FORGET and KEEP-NEIGH items.
- **Scoring:** the scripted reader and the S05 invariants, forgetting included.
- **Budget:** ≤ 60 s per pack and $0, with no upstream credential loaded.
- **Outputs:** `junit.xml`, `card.json` and `receipt.json`.

## 8. Exit codes

The T0 and T1 runners use these exit codes:

| Code | Meaning |
|---|---|
| 0 | pass |
| 1 | fail: the gate is FAIL or INVALID (the wiped control passed), or an invariant or corpus case failed |
| 2 | BLOCKED: benchmark infrastructure failed after its reruns, with no known failure (PREREG §7) |
| 3 | guard refused: the busy marker, the load guard, a pinned-artifact hash mismatch, `PYTHONHASHSEED` not 0, or a refused system (§12) |

- The runners exit 70 when an unexpected exception stops them, print `tool_failure` first on stderr, and leave no result file. `keyed.assert_hashseed` also exits 70 when a library process starts without the seed. Any other code still means the tool itself failed, and no result exists. The runners check their own preconditions before work and exit 3.
- A result file is written only for codes 0-2.

## 9. Windows and the token estimator

- **The developer window W** is the provisional C-5 entry (K02). The C-5 rule is the smallest of 16K, 24K, 32K, 48K and 64K that is at least twice the harness's fixed overhead (system prompt plus tool schemas) on the pinned model.
  - S6a's figures were measured on a provisional model: 24K at Hermes defaults, and 16K for its 4-tool configuration.
  - K02 re-measures the frozen T1 toolset's overhead at $0. A recording stub captures the harness's own first request, and the token estimator counts it, until C-1 names the pinned model's tokenizer.
- **The generation-time estimator** is a pinned offline BPE: `o200k_base`, provisional until C-1 names the pinned model's encoding.
  - Its rank file is vendored with its sha256.
  - It is used only to size sprints, windows and stub cuts.
  - Every reported token count comes from the ledger's usage fields or is labelled an estimate.
  - The card names the estimator and its hash.

## 10. Canary placement

- **Where it goes:** the canary GUID (`CANARY`) sits in the header or manifest field of every public data file under `packs/`, `corpus/` and `schemas/fixtures/`. `scripts/public_check.py` enforces this.
- **Where it never goes:** text that an agent can see. The renderer never copies a header or manifest field into a rendered turn, and a build check refuses a rendered life that contains the GUID. If a store or a model output does contain it, it came from contamination and not from a run.

## 11. External systems in v0.1

**Selection.** Ring 0 v0.1 runs on Hermes native memory and two external systems. An external system qualifies by mechanics only:
- an OSI-approved licence;
- a pinned released artifact;
- $0 to run locally;
- all of its state isolatable in declared surfaces inside the sandbox;
- every model call of its own (extraction, summary, embeddings) routable to the director;
- not LCM-X.

**The choices,** from the S5 survey:
- **Holographic** (MIT; a Hermes provider with no model calls of its own; `memory_store.db`) for the class with no model calls.
- **Mem0 OSS** (Apache-2.0; Hermes OSS mode). It covers the class with its own extraction and embedding calls, all served by the director's stubs, with its vector directory and history database moved into the sandbox and telemetry off.
- **Fallback:** **Hindsight local** (MIT; embedded Postgres; settle, since `retain_async` is on by default). It is used if Mem0 OSS cannot run under the stubs, or its store is degenerate under them.

Each route deviation is disclosed. For Mem0 that is the hosted extraction model replaced by the director's stub.

**The adapter contract** gains one step: `settle`, before every checkpoint and every probe, for systems whose writes become searchable only after background work (S5 finding 1; `docs/ERRATA-v2.2.md`).
- **Settled** means the system was observed to report its queue drained, within its declared bound.
- **Reaching the bound without that observation** is a SYSTEM_FAILURE for the items that settle precedes, even if the settle call itself returns normally. No probe reads a store that has not settled. At v0.1 this holds for scoring, not for execution (§13 E2).

**What this selection is not.** It is not C-9. It confers no roster place, ranks nothing, and is not the public adoption metric.

## 12. LCM-X

- LCM-X is in the system registry, as its Hermes plug-in release.
- The benchmark session never runs it at Ring 0. The runners refuse it under the benchmark operator's identity, with exit 3.
- LCM-X's own lanes may run the public kit, on equal terms with every other system (PREREG §10, the firewall).
- No unit configures, tunes or advises on LCM-X.

## 13. v0.1 errata

These record where the v0.1 Kit's runners depart from the text above, and why. Each one is disclosed on the card.

- **E1. Verified empty is taken before configuration** (§5). Hermes writes `config.yaml` when the harness first starts, and there is no hook before the first turn. So for Hermes native memory and the controls, the verified-empty proof is the marker-only home, taken before configuration. The configuration files are benchmark-written. For a Hermes plug-in, the baseline is its install snapshot, taken after the plug-in's own install-time files and the benchmark's configuration are written. Card disclosure: "verified empty: before configuration; configuration is benchmark-written".
- **E2. Unsettled checkpoints still run their probes** (§11). The scripted director accepts only the next expected turn and cannot skip a session. So an unsettled checkpoint's probe sessions still run, on clones. Every item of that checkpoint is a SYSTEM_FAILURE (`unsettled`) whatever its reader result. Scoring reads the class before any reader result.
- **E3. The gate's verdicts and exit codes** (§6, §8). INVALID, when the wiped control passed, exits 1. BLOCKED, when infrastructure failed after its reruns with no known failure, exits 2. A known failure wins over a blocked entry, so a rerunnable fault never masks a known failure. The card's `gate_verdict` accepts `BLOCKED` only with run status `BLOCKED`.
- **E4. The fresh-install hash masks the director port** (§5). Hermes' `config.yaml` and Mem0's `mem0.json` are benchmark-written and carry the run's director port, which differs on every run. In the reported fresh-install hash (the registry pin), every `127.0.0.1:<director port>` that is not followed by another digit, in a `config.yaml` or `mem0.json` at a surface's root, is replaced by `127.0.0.1:{DIRECTOR_PORT}`, and that file's size and content hash are taken from the masked bytes. Nothing else is masked. Verified empty compares each surface with the unmasked tree hash taken earlier in the same run. Card disclosure: "fresh-install hash: director port masked in config.yaml and mem0.json".
- **E5. The T0 Hermes-replay fallback ships in v0.2** (§7). Every v0.1 system runs T0 in the default memory-layer mode: the API references through the adapter contract, and Hermes native, Holographic and Mem0 through the in-process memory host, which also drives each one's deletion surface. The fallback would inherit T1's forgetting limit (§6: the scripted model only adds), so it would certify less than the default mode, and it misses the 60 s target by design. In v0.1, `bicentennial t0 --mode hermes` refuses with exit 3 and code `mode_unavailable:hermes`. When the fallback ships, INV-FORGET, KEEP-FORGET and KEEP-NEIGH are "not exercised" in it, as at T1, and a timeout is charged to the system unless the ledger shows a benchmark-owned fault (PREREG §7).
- **E6. A runner failure exits 70** (§8). An unexpected exception inside `bicentennial t0` or `bicentennial t1` exits 70, not Python's 1, so it cannot read as a gate FAIL. Results are written to `staging/` and moved into place only when every file is written (T1 moves the system arm last), so a failed run leaves no result file.
- **E7. Hermes native reads its session-start memory snapshot** (§7, #185). The memory-layer host renders enabled, non-empty memory and user-profile blocks with pinned Hermes's own code at session open, in that order, joined by a blank line. It gives the frozen snapshot to the reader before recall and prefetch context; mid-session writes do not change it, and it adds no recall citations. This also applies when T1 reuses the host for its regression corpus. Disclosure, the JUnit run property `t0.injection`: "The session-start memory snapshot is read; other harness prompt injection is not exercised."
- **E8. Corpus stocking requires content-word evidence** (§6). A catalogue row is stocked only when both the reference store and a stocking-only reference that removes a fixed, content-blind English stop list select every gold option; replay and stored expectations are unchanged. It changes which cases the public corpus file holds, not how a case is run, so no card field changes.

- **E9. Plug-in Python dependencies come from a benchmark lock** (#190). Mem0's archived tree declares dependency ranges only, so the benchmark resolves them, including the `qdrant` extra required by the configured local store, into `systems/locks/mem0-oss.txt`, a hash-locked file pinned by `benchmark_commit`. It is installed into a per-system copy of the pinned Hermes checkout, prepared from Hermes's own lockfile with the `mcp` extra. A run refuses when the worker lacks an applicable locked version. Every real-worker run discloses the worker's distribution set through JUnit run properties (`<tier>.worker_dists` and `<tier>.worker_dists_sha256`), and a locked system also discloses the lock digest and applicable count (`<tier>.plugin_deps`). Mem0's optional `nlp` and `extras` features are not installed; the plug-in's own install does not install them either. Holographic's archived tree declares numpy and snowballstemmer; without numpy it loads but turns off its holographic vectors and structural recall. So `systems/locks/holographic.txt` locks both at the versions pinned Hermes's own lockfile pins, and Holographic runs on its own prepared copy of pinned Hermes in the same way (#210).
- **E10. The hashed-vector stub reports cosine as (1 + c)/2** (§2, #207). Tokens hash into D−1 coordinates and every non-empty vector is g(u) = (u/√2, 1/√2), where u is its unit token vector, so the cosine of two non-empty texts is (1 + c)/2, where c is the cosine of their token vectors. Before this, a query and a related memory that shared one or two words scored about 0.1, and Mem0 OSS, which drops a candidate below 0.1 before it ranks, did not return the later correction in the T1 drift corpus cases (each such correction scored 0.083–0.089). The cause is an incompatibility between the stub's synthetic scale and an absolute threshold; it says nothing about trained embedders. Under E10, order by similarity alone is preserved for the new token vectors; the D−1 rehash changes some collisions; a ranking that adds other signals to the similarity can change (Mem0's locked install adds none); and a zero-overlap text now scores about 0.5, so a thresholded system can return more context. These effects are measured, not assumed: controls, forgetting and determinism are observed on the revised stub. The empty text is still the zero vector. Only systems with an embeddings route are affected; today that is Mem0 OSS. Disclosure: the JUnit run property `<tier>.embeddings`.
- **E11. Mem0's automatic extraction is not exercised** (§2, #208). The stub replies to Mem0 2.2.1's single extraction call in a format Mem0 does not read, so Mem0 stores the conversation in its history database but no extracted vector memories. Mem0 results therefore cover explicit-write storage and recall wiring, not extraction; neither credit nor blame for extraction is assigned. Disclosure: the JUnit run property `<tier>.extraction`.

- **E12. Adapter ingest round trips and delivered fields** (#213). Conformance appends `text_full_length` and `actor_stored`, each on a fresh adapter with a settle before every probe or checkpoint. The former queries a distinct tail token and requires the whole long event byte for byte, citing only that event; its fixture is at least 8,192 characters and strictly longer than every event in the public T0 and T1 packs, enforced by a pack-building test. The latter requires sentinel actor bytes in the checkpoint. A system API that cannot carry actor is declared by `UNSUPPORTED_FIELDS = frozenset({"actor"})`; only actor can be declared. Its check is skipped, `run()` returns `True` for compatibility, and `declared()` reports `{"actor_stored":"declared"}` separately, never a storage pass. Exact NoMemory and OracleEvidence classes are exempt from both checks as well as the three retrieval checks; controls' expected results are fixed in tests. The Hermes memory host declares actor unsupported: its checkpoint includes the benchmark's event copies, which cannot prove actor delivery to the plug-in. It counts successful ingests whose written text differs from the event text without retaining any additional text. JUnit properties `<tier>.write_clipped`, conditional `<tier>.write_max_length` (only when the write tool declares `maxLength`), and `<tier>.fields` disclose that count, limit and canonical delivered-field JSON: `{"actor":"not_delivered","text":"full","time":"session_clock"}`, with `text` set to `clipped:<limit>` when a limit is declared. T0 sums every host built across the invocation, including invariants, baselines, retries and probe clones; each selected pack reports that total. T1 sums every corpus host per gated arm, including retries and clones. Reference systems and the no-memory floor get none of these properties. The three v0.1 systems declare no limit, so their count is 0 and their limit property is absent. Cards and schemas are unchanged.

## References

- PREREG-v0.4:
  - §2: stages, the estimand and the bundle minimum;
  - §3: action, QA and Tuesday scoring;
  - §6 l.383-409: Ring 0, the fault rule and the regression corpus;
  - §7: failure classes;
  - §10: write turns, the declared tool lists and the firewall;
  - Freezes: C-5, C-6 and C-7.
- DESIGN v2.2:
  - §4.4: locked tokens;
  - §6.2 and §6.2a: the director and write turns;
  - §6.2d: the tool-call compiler;
  - §6.5: faults;
  - §6.7: probe isolation;
  - §6.8: hygiene;
  - §6.9: adapters;
  - §7.3a: stages;
  - §7.5: answer types;
  - §9.1: the developer rings.
- Spikes:
  - S1: request roles;
  - S5: surfaces, findings 1-3;
  - S6a: harness overhead, fixed times and the in-process driver;
  - S7 Part A: write-turn readback.
