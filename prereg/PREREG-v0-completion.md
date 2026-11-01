# PREREG v0 completion record (draft, provisional entries)

**Status: DRAFT.** This is not the v0 completion record. Every entry below is labelled **provisional**. The v0.1 Kit's Ring 0 tiers run under these entries. Ring 0 is a developer tier, with no decision bar, that never certifies.

**When it binds.** The record binds only when the benchmark session commits it, with the hash of every artifact it names, before any real memory system's first pilot run (PREREG-v0.4, Freezes). Its hash is then posted on lcm-x #1964.

**The firewall.** No entry here comes from any system's score. The entries rest on:
- each slot's own rule in PREREG-v0.4;
- spike measurements of harness overhead (the Freezes allow these);
- vendor documentation, for the tool lists;
- vendor documentation and shipped source defaults, for the route table;
- the track design, for the cells.

**Slots C-3, C-4 and C-8 to C-15 are open, and C-1 and C-2 are partly filled.** Ring 0 v0.1 needs none of them:
- it runs with no model, so C-1, C-2 and C-3 are unused. C-1's and C-2's provisional entries prepare the live tiers;
- it has no full tier, so C-4 is unused;
- it has no board, so C-8 to C-15 are unused.

## C-1: the pinned agent family and the route table (provisional, partial)

**The rule** (PREREG-v0.4 line 16): each system's vendor-documented defaults. The pinned model must be servable through the director on a subscription lane (S1, S4). The vision reader is pinned once for every row (S8), and S8 chooses the vision-capable main model from the census, pinned here before any Image board.

**How it was read.** From each system's shipped source defaults and documentation at its registry pin, read at that commit, with no system run. Paths are in each vendor's repository at the pin named.

**The pinned model** (DV42): OpenAI `gpt-6.1-sol` at reasoning effort `medium`, on the Codex Responses wire through the director, on dedicated benchmark accounts. S6b served it end to end on that subscription lane: a 64-turn write run with no auth failure, rate refusal or overload. Outside runners use the public Responses API with the same model and effort. It is every system's **probe model** in segment `seg0`, under the alias `bicentennial-main`, and so the pinned reader.

**The summariser per system** (DESIGN §6.2c: the model the system's own compaction or extraction uses, at its vendor's documented default):

| System and pin | Calls | Vendor default | `seg0` route | Source |
|---|---|---|---|---|
| hermes-native: Hermes v0.22.2 (`d923a5e`) | context compression and its summary: one call, task `compression` | `auxiliary.compression`: provider `auto` and model `""`, which is the main chat model; reasoning effort `""`, the provider's default | the pinned model, alias `bicentennial-summariser` | `hermes_cli/config_defaults.py:20-30`, `:755-765`; `agent/auxiliary_client.py:4677-4700`; `agent/context_compressor.py:3890-3924`; `website/docs/user-guide/configuration.md:1014-1015`, `:1386` |
| lcm-x v0.28.1 (unchanged at v0.29.0 and v0.29.1-rc4) | summaries and rollups; the synthesis in `lcm_expand_query` | `LCM_SUMMARY_MODEL` `""`: LCM-X sends no model, so Hermes's auxiliary route for task `compression` picks the main chat model, as above. `LCM_EXPANSION_MODEL` `""` falls back to it | the pinned model, alias `bicentennial-summariser` | `config.py:1048`; `model_routing.py:76-78`; `escalation.py:681-693`; `expand_query_tools.py:308`, `:604`; `skills/hermes-lcm/references/configuration.md:195` |
| mem0-oss: plug-in 1.3.0 (`43849c6`), mem0ai 2.2.1 | memory extraction: one call per synced turn (`add` with `infer=True`) | OpenAI `gpt-5-mini` with `is_reasoning_model: true`; no reasoning effort sent; chat-completions with a JSON response format | `gpt-5-mini`, alias `bicentennial-extraction` | `integrations/hermes-plugin-mem0/_oss_providers.py:11`, `_setup.py:111-144`, `_openai_llm.py:30-59`; `docs/integrations/hermes.mdx:155`, `:178`; mem0ai `mem0/llms/openai.py:39-40`, `mem0/memory/main.py:958-963` |
| holographic 0.13.0 | none | no model call | none | the registry entry (`own_model_routes = []`) |
| omega 1.5.20 | none through the director | it reads a staged local model cache (four SHA-256-checked bge-small ONNX files), whose digest the run discloses | none | the registry entry; the developer guide §§6-7 |

**Calls the vendor defaults switch off:**
- lcm-x's extraction, assertion extraction and selective compiler (`config.py:978-980`, `:996-999`, `:1198` at v0.28.1). So the registry's `bicentennial-extraction` alias for lcm-x goes unused at these defaults.
- Hermes's `session_search`, which uses no model (`hermes_cli/config_defaults.py:760`; `website/docs/user-guide/sessions.md:847`).
- Mem0's reranker, vision and procedural memory (mem0ai `mem0/configs/base.py:46-48`, `mem0/configs/llms/base.py:24`).

**Other model calls the vendor defaults make,** on the probe model:
- Hermes's title generation, task `title_generation`, alias `bicentennial-aux-title_generation`: the main model, with reasoning off and a JSON response, once per untitled session (`hermes_cli/config_defaults.py:772-786`; `agent/title_generator.py:514-530`).
- Hermes's memory background review: a fork of the agent on the main route, every 10 user turns while the built-in memory is on (`hermes_cli/config_defaults.py:801-811`, `:1311-1324`; `agent/background_review.py:242-256`).

**Embeddings,** for which the route table has no field yet:
- mem0-oss: OpenAI `text-embedding-3-small`, 1536 dimensions, on `/v1/embeddings`, alias `bicentennial-embeddings` (`_oss_providers.py:16`, `_setup.py:145-148`; mem0ai `mem0/embeddings/openai.py:15-19`). Its spend is the labelled embedding row (DV47).
- lcm-x: none at v0.28.1 (`config.py:1083`). At v0.29.1-rc4 its default turns on local embeddings, which run in-process and reach no route (`skills/hermes-lcm/references/configuration.md:66-75`).

**After the swap (segment `seg1`):** the probe model, the summariser and the alias move to the swap model (C-2), under the alias `bicentennial-swap`, for every system, Mem0's extraction included (DESIGN §6.2c, §13). Vision never moves, and the route table refuses a row that moves it (`src/bicentennial/director/routes.py`). Embeddings do not move either, so a store keeps one embedding space for the whole life.

**Reasoning effort per route** (open, settled before the first live run). The route table has no effort field. The director holds one effort per upstream and checks it only on the Responses wire (`src/bicentennial/director/upstream/forward.py`, `src/bicentennial/director/upstream/__init__.py:175`). The harness sets no effort today, and the vendor defaults send none on Hermes's and LCM-X's summary calls or on Mem0's extraction. **The provisional reading:**
- every route served by the pinned model runs at `medium`, and every route served by the swap model runs at C-2's effort, since DV42 and C-2 pin each model with its effort;
- S6a's replay set the agent and every auxiliary task to `medium` (`spikes/s6a/replay.py:78-82`), so the measurements on record assume this;
- a fixed vendor model (Mem0's `gpt-5-mini`) keeps its vendor default.

**Still open:**
- **The vision provider and the pinned vision reader** (S8, not yet run), and **S8's vision-capable main model**.
- **The pinned model's tokenizer** (RING0 §9, K02). C-5 counts with `o200k_base` until it is named. The check: count a recorded Sol request with `o200k_base`, and compare with the input tokens the provider reported for it.
- **Director support before the live tiers:**
  - the director serves the embeddings wire with the route's probe model (`src/bicentennial/director/core.py:331-334`), so Mem0's embedder needs its own route;
  - the effort reading above needs a pinned effort on every route and wire.
- **External memory providers:** whether Hermes's memory background review also fires when an external provider holds the memory slot is unchecked.

## C-2: the swap model (provisional)

**The rule** (PREREG-v0.4 line 17): a model from a family other than the pinned family, servable through the director; named after S4. Its effort is pinned with it, and its cost and run-time terms are measured at that effort (S6).

**The provisional entry: Zhipu `glm-5.3` at reasoning effort `high`,** under the alias `bicentennial-swap`. DV42 names GLM (Zhipu) the swap model and the replication family. S4 chose and served this model id (`spikes/s4/anthropic_director.py:334`; `spikes/s4/results/summary.json:2-4`). It is a named choice, not a vendor default.
- **Another family:** Zhipu, not OpenAI. Met.
- **Servable through the director:** met on two wires.
  - Anthropic Messages, for the Claude Code sub-row. S4 ran Claude Code 2.1.306 with 9 of 9 steps valid, no field stripped, and every reply served as `glm-5.3` (`spikes/s4/REPORT.md:3`, `:29`, `:48`). That run predates the director's credential fixes (`:90`).
  - OpenAI chat-completions, for Hermes: S6a (`spikes/s6a/REPORT.md:12`).
  - No GLM route uses the Responses wire, and none was tested on it.
- **Named after S4:** S4 proposed GLM (`spikes/s4/REPORT.md:83`), DV42 named the family, and this entry names the model.
- **The effort, `high`** (provisional).
  - Z.ai documents three levels for GLM-5.3: `low`, `high` and `max`, with `max` the default. Its direct API rejects any other value, and its coding plan maps `medium` and `high` to `high` (Z.ai's thinking guide and GLM-5.3 page, read on 2026-11-01).
  - Every GLM figure on record was taken with `reasoning_effort: medium` sent on the plan (S6a's run of record, r6), which that mapping serves as `high`. No served level was recorded.
  - Against r3, which sent no effort and so ran at the default `max`, r6 cut mean write-turn latency by 59% and completion tokens by 86% (`spikes/s6a/REPORT.md:15`, `:49-51`). At `max`, none of the run-time figures on record would hold.
- **Cost and run-time terms at that effort: not met.**
  - S6 has no results yet: every result section waits for its part (b) (`spikes/s6/REPORT.md`). S6d, the GLM lane soak, has not started (#25).
  - On record are desk projections from S6a r6's token counts: $0 at the margin on the plan; 338.061 lane-hours for the swap's share at ×1 latency, or 42.3 h at concurrency 8 (`spikes/s4/results/model_b.json:132-137`); and 52.8 h on one plan for a swap at session 100 (DV47).
  - S6d measures them at `high`.
- **Context window:** Z.ai documents 1M tokens of context and 128K of output. Which window the plan's endpoints serve is unchecked; S4's Claude Code assumed 200K for an unknown alias (`spikes/s4/REPORT.md:46`).
- **For S6d to check:**
  - GLM-5.3 cannot turn thinking off (Z.ai's thinking guide), while Hermes's title call turns reasoning off (`agent/title_generator.py:514-530`). Check that the swap segment's title calls are served.
  - Z.ai's GLM-5.3 page says previous or expired coding-plan subscribers reach the model only over chat-completions. The Claude Code sub-row needs the Anthropic endpoint on the account it uses.

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
- The memory-using heuristic gate (DESIGN §5.3: every memory-using heuristic scores at most 0 on every track) is not yet evaluated on any pack. At Ring 0 v0.1 it is planned for the Drift action rows of latest mention, its reverse and first mention, with every other heuristic row reported without gating. Today the only check is a template-level test over the four G1 Drift action templates; it does not cover the G2 Drift templates or a pack's selection, so whether a v0.1 pack meets the gate is unknown until the pack build runs it.
- Duty items are declared by `wake-loop-v1` and by both Tuesday templates (each live commitment). An omission on one of them counts as a harmful omission.
- The lever-mix shape's neutral secondary levers are not enforced at v0.1. Lever values are computed per item and recorded in each item's `levers`. `keep-incidental-v1`, for example, places same-predicate decoys on other places, so its items carry non-zero interference. Each entry's `lever_mix.other_levers` says so.
- Planted mutants are the generator-placed distractors. Mutants built from a world's planted material come later.
- `keep-forget-v1`, `keep-neighbour-v1` and the two Tuesday templates are not exercised at T1. The Tuesday templates are structure-only until their trigger render lands.

## Pending proposals (not completion entries)

These two values come from DESIGN §4.2, and no PREREG-v0.4 rule or slot covers them (`docs/ERRATA-v2.2.md` E5). They are generator configuration proposed for PREREG-v0.6 (PREREG-v0.5 carries only DV48), not completion entries:
- a full-tier life spans 3-26 simulated weeks;
- incidental details are mixed with decoys at 3 or more times their rate.

Neither is ever chosen or revised from any real system's results.

## C-12: the Text profile's declaration (draft, provisional)

The draft is in `docs/inventory/CELLS-v0.md` ("Text profile: the C-12 draft"):
- 14 required Act cells across Wake, Drift, Tuesday, Rachael and Keep, pooled with equal weights;
- the four baselines;
- the operating metrics.

It is taken from the track design alone, independent of the census, and never from any system's documentation or results (PREREG-v0.4 line 27).
