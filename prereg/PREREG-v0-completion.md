# PREREG v0 completion record (draft, provisional entries)

**Status: DRAFT.** This is not the v0 completion record. Every entry below is labelled **provisional**. The v0.1 Kit's Ring 0 tiers run under these entries. Ring 0 is a developer tier, with no decision bar, that never certifies.

**When it binds.** The record binds only when the benchmark session commits it, with the hash of every artifact it names, before any real memory system's first pilot run (PREREG-v0.4, Freezes). Its hash is then posted on lcm-x #1964.

**The firewall.** No entry here comes from any system's score. The entries rest on:
- each slot's own rule in PREREG-v0.4;
- spike measurements of harness overhead (the Freezes allow these);
- vendor documentation, for the tool lists;
- the track design, for the cells.

**Slots C-1 to C-4 and C-8 to C-15 are open.** Ring 0 v0.1 needs none of them:
- it runs with no model, so C-1, C-2 and C-3 are unused;
- it has no full tier, so C-4 is unused;
- it has no board, so C-8 to C-15 are unused.

## C-5: the developer-tier window (provisional)

**The rule** (PREREG-v0.4 line 20): the smallest of 16K, 24K, 32K, 48K and 64K that is at least twice the harness's fixed overhead (system prompt plus tool schemas) on the pinned model, as measured in S6a.

**The measurement** ($0, offline, no model call). The fixed overhead is counted in the first main request that S6a recorded from Hermes v0.22.2 (commit d923a5e).

| Configuration | Tools offered | System prompt (chars) | Tool schemas (chars) | o200k_base tokens: system + tools | Provider-reported prompt tokens (provisional model, S6a) | Rule gives |
|---|---|---|---|---|---|---|
| Hermes defaults | 19 | 5,810 | 36,690 | 1,253 + 8,218 = 9,471 | 10,260 | 24K |
| T1 toolset: ACP toolsets `memory`, `session_search`, `todo`, which Hermes presents as `memory`, `tool_search`, `tool_describe` and `tool_call` | 4 | 5,355-5,367 | 5,478 | 1,160-1,164 + 1,223 = 2,383-2,387 | 2,610-2,647 | 16K |

**The provisional entry: W = 16K at Ring 0**, for the T1 toolset.
- Both counts agree on the selection. The tokenizer is `o200k_base`, provisional until C-1 names the pinned model's tokenizer (RING0 §9). The provider count is from S6a's provisional model.
- **Re-check, before any comparative run:**
  - each external system adds its own provider tools to the T1 toolset (R13a, R13b);
  - the full C-5 ladder is then applied to the **largest** measured fixed overhead among the predeclared, pinned T1 configurations;
  - that one common W is frozen before the first comparative run. A largest overhead above 32,768 tokens has no qualifying window and is reported as such.
- **What a system's tools can do:** they can raise the common W for every system. Sharing one W prevents unequal windows but does not remove that influence, and the card discloses each system's overhead.
- **Never resized:** W is never changed after any result is seen, or when a row is added to an existing comparison.
- **What it is not:** the bar-1 window, which C-5 also covers. That is set in the final record, under the same rule, for the harness configuration of the bar-1 run.

## C-6: write-turn tools (provisional)

The **write-turn prompt text** is open. Ring 0 runs with a scripted model and sends no write prompt (RING0 §2). The text binds the live tiers, and is fixed here before them.

**Declared write tools,** at action level, from each vendor's documentation:

| System | Declared write tools | Not write tools (listed for contrast) | Source |
|---|---|---|---|
| Hermes native memory | `memory`: actions `add`, `patch`, `remove`, and the batch form `operations` over those actions. Also a file-editing tool, for `MEMORY.md` and `USER.md` only, under PREREG §10's file-tool rule. The restricted T1 toolset offers no file tool, so that path is unavailable at T1 | `session_search`; `todo` (a task list, not memory) | the pinned release's tool schema (v0.22.2); S5 |
| Holographic | `fact_store`, 14 write actions: `add`, `change`, `end`, `correct`, `revert`, `merge`, `forget`, `update`, `remove`, `alias`, `rename`, `delete_entity`, `split` and `rebuild_entities`. `fact_feedback`: `helpful`, `unhelpful` and `confirmed` (it moves trust scores and records that the person confirmed a fact) | `fact_store`'s 12 read actions: `search`, `probe`, `related`, `reason`, `contradict` (it suggests and never edits), `history`, `list`, `stats`, `export`, `review`, `entities` and `enrich` (it lists facts that have no keywords; `update` writes them) | the plugin's README at commit 5e003b4; R13a re-enumerates it at the pinned release |
| Mem0 OSS | `mem0_add`, `mem0_update`, `mem0_delete` | its search tools | the vendor's plugin documentation, as surveyed in S5 |

**The content-blind write rule** calls the first declared write tool on each list, with its add action (RING0 §2).

## C-7: Ring 0 v0.1 levers (provisional, partial)

**The rule** (PREREG-v0.4 line 22; §9): every template's decision table, the lever-mix shape and the direction labels, and each cell's rung lever values. They are taken from the template build, before any real system runs on a template, and rungs are calibrated on the no-memory floor, oracle evidence and naive RAG only.

**The lever-mix shape at Ring 0 v0.1:**
- each cell varies only its primary lever (`docs/inventory/CELLS-v0.md`), at one uncalibrated value;
- every other lever sits at its neutral value: no interference unless the cell is an interference cell, and at least one wake between the evidence and the item;
- packs are labelled "rungs: uncalibrated (v0.2)".

**Direction labels:** each template carries one, written before any system runs. No label exceeds 40% of a track's scored items in a pack (PREREG §4, §9).

**Decision tables:** from the template build, per template. They bind before any real system runs on that template.

**Partial entries (frozen 2026-10-27, Ring 0 v0.1).** `specs/ring0/c7-partial.json` holds one entry per v0.1 template, keyed by template ref (`template_id-vN`). Each entry records the template's ref, genre, cell and track lever (`cell`), direction label, item kind, its decision tables, every field of the template, the template class and the sha256 of that class's source file, the sha256 of every package source file that defines a class in the template's hierarchy (source hashes read CRLF line endings as LF), and the lever mix (the cell's primary lever as written in the inventory and as its lever key, and the template's own lever mix where it declares one). Each entry carries `entry_sha256`, the sha256 of its canonical JSON without that field. The file is generated from the template build by `python -m bicentennial.items.c7`, with the same bytes under any hash seed, and a test fails when the committed file no longer matches the templates. It was frozen before any real memory system ran on any template.

| Template ref | Genre | Cell | Direction | Kind |
|---|---|---|---|---|
| drift-asof-v1 | G2 | DRIFT-ASOF | verbatim retention | qa |
| drift-booking-v1 | G2 | DRIFT-CUR | recency | act |
| drift-chain-fault-v1 | G1 | DRIFT-CUR | verbatim retention | act |
| drift-chain-v1 | G1 | DRIFT-CUR | recency | act |
| drift-config-v1 | G1 | DRIFT-CUR | extraction and consolidation | act |
| drift-no-update-v1 | G2 | DRIFT-CUR | extraction and consolidation | act |
| drift-quote-v1 | G1 | DRIFT-CUR | verbatim retention | act |
| keep-forget-v1 | G2 | KEEP-FORGET | none | act |
| keep-incidental-v1 | G2 | KEEP-INC | verbatim retention | act |
| keep-neighbour-v1 | G2 | KEEP-NEIGH | retrieval breadth | act |
| recall-count-v1 | G2 | RECALL-AGG | retrieval breadth | qa |
| recall-value-v1 | G1 | RECALL-VERB | verbatim retention | qa |
| tue-passport-v1 | G2 | TUE-EVENT | extraction and consolidation | act |
| tue-ticket-v1 | G1 | TUE-EVENT | retrieval breadth | act |
| wake-loop-v1 | G1 | WAKE-LOOP | extraction and consolidation | act |

**How the entries bind.**
- The T0 and T1 runners will refuse a real system on any template that has no entry here, or whose entry's hash does not match the template build (exit 3). Controls are not refused. Until those runners land, the only check is the repository test that fails when the committed file no longer matches the template build.
- A template change that alters any recorded field is a new template version with its own entry, written before a real system runs on it.
- T0 relation rows (the invariance and direction rows) sit at other distance and wake values as diagnostics, not rungs. Rungs come with calibration in v0.2.

**Limits stated at the freeze.**
- The direction cap (no label above 40% of a track's scored items in a pack) is a pack-level gate over both genres. At Ring 0 v0.1 it is not met wherever one label holds more than 40% of a track. The pack build's distribution check will report it per pack; until that lands, this record is the disclosure. That holds for Wake (one template), for Tuesday and Recall (two templates with two labels, so 50% each) and for Keep at T1, which uses only `keep-incidental-v1`. The Drift share depends on which Drift templates a pack selects, and is known only once a pack is built.
- The memory-using heuristic gate (DESIGN §5.3: every memory-using heuristic scores at most 0 on every track) applies at Ring 0 v0.1 to the Drift action rows of latest mention, its reverse and first mention. The policy battery will report every other heuristic row without gating it. Until the battery lands, the only heuristic coverage is the existing test of the G1 Drift templates.
- Duty items are declared by `wake-loop-v1` and by both Tuesday templates (each live commitment). An omission on one of them counts as a harmful omission.
- The lever-mix shape's neutral secondary levers are not enforced at v0.1. Lever values are computed per item and recorded in each item's `levers`. `keep-incidental-v1`, for example, places same-predicate decoys on other places, so its items carry non-zero interference. Each entry's `lever_mix.other_levers` says so.
- Planted mutants are the generator-placed distractors. Mutants built from a world's planted material come later.
- `keep-forget-v1`, `keep-neighbour-v1` and the two Tuesday templates are not exercised at T1. The Tuesday templates are structure-only until their trigger render lands.

## Pending proposals (not completion entries)

These two values come from DESIGN §4.2, and no PREREG-v0.4 rule or slot covers them (`docs/ERRATA-v2.2.md` E5). They are generator configuration proposed for PREREG-v0.5, not completion entries:
- a full-tier life spans 3-26 simulated weeks;
- incidental details are mixed with decoys at 3 or more times their rate.

Neither is ever chosen or revised from any real system's results.

## C-12: the Text profile's declaration (draft, provisional)

The draft is in `docs/inventory/CELLS-v0.md` ("Text profile: the C-12 draft"):
- 14 required Act cells across Wake, Drift, Tuesday, Rachael and Keep, pooled with equal weights;
- the four baselines;
- the operating metrics.

It is taken from the track design alone, independent of the census, and never from any system's documentation or results (PREREG-v0.4 line 27).
