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
