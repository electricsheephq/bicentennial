# PREREG v0 completion record (draft, provisional entries)

**Status: DRAFT.** This is not the v0 completion record. Every entry below is labelled **provisional**. The v0.1 Kit's Ring 0 tiers run under these entries. Ring 0 is a developer tier, with no decision bar, that never certifies.

**When it binds.** The record binds only when the benchmark session commits it, with the hash of every artifact it names, before any real memory system's first pilot run (PREREG-v0.5, Freezes, as in v0.4). Its hash is then posted on lcm-x #1964.

**The firewall.** No entry here comes from any system's score. The entries rest on:
- each slot's own rule in PREREG-v0.5, which is unchanged from PREREG-v0.4 for every slot filled here;
- spike measurements of cost, timing, serving and harness overhead (S4, S6a and S6b; the Freezes allow these);
- vendor documentation, for the tool lists and for the swap model's effort levels;
- vendor documentation and shipped source defaults, for the route table;
- the track design, for the cells.

**Slots C-3, C-4, C-8 to C-15 and C-16 to C-18 are open, and C-1 and C-2 are partly filled.** Ring 0 v0.1 needs none of them:
- it runs with no model, so C-1, C-2 and C-3 are unused. C-1's and C-2's provisional entries prepare the live tiers;
- it has no full tier, so C-4 is unused;
- it has no board, so C-8 to C-15 are unused;
- it uses no validation family, image reader or veto panel, so C-16 to C-18 are unused (#314 fills them by rule).

## C-1: the pinned agent family and the route table (provisional, partial)

**The rule** (PREREG-v0.5 line 16, unchanged from v0.4): each system's vendor-documented defaults.
- The pinned model must be servable through the director on a subscription lane (S1, S4).
- The vision reader is pinned once for every row (S8).
- S8 chooses the vision-capable main model from the census, and it is pinned here before any Image board.

**How it was read.** Each system's shipped source defaults and documentation were read at its registry pin, at that commit, with no system run. Paths are in each vendor's repository at the pin named.

**The pinned model** (DV42): OpenAI `gpt-6.1-sol` at reasoning effort `medium`, on the Codex Responses wire through the director, on dedicated benchmark accounts.
- S6b served it end to end on that subscription lane: a 64-turn write run with no auth failure, rate refusal or overload.
- Outside runners use the public Responses API with the same model and effort.
- It is every system's **probe model** in segment `seg0`, under the alias `bicentennial-main`, and so it is the pinned reader.

**The summariser per system** (DESIGN §6.2c: the model the system's own compaction or extraction uses, at its vendor's documented default):

| System and pin | Calls | Vendor default | `seg0` route | Source |
|---|---|---|---|---|
| hermes-native: Hermes v0.22.2 (`d923a5e`) | context compression and its summary: one call, task `compression` | `auxiliary.compression`: provider `auto` and model `""`, which is the main chat model; reasoning effort `""`, the provider's default | the pinned model, alias `bicentennial-summariser` | `hermes_cli/config_defaults.py:20-30`, `:755-765`; `agent/auxiliary_client.py:4677-4700`; `agent/context_compressor.py:3890-3924`; `website/docs/user-guide/configuration.md:1014-1015`, `:1386` |
| lcm-x v0.28.1 (the same defaults at v0.29.0 and v0.29.1-rc4) | summaries and rollups; the synthesis in `lcm_expand_query` | `LCM_SUMMARY_MODEL` `""`: LCM-X sends no model, so Hermes's auxiliary route for task `compression` picks the main chat model, as above. `LCM_EXPANSION_MODEL` `""` falls back to it | the pinned model, alias `bicentennial-summariser` | `config.py:1048`; `model_routing.py:76-78`; `escalation.py:681-693`; `expand_query_tools.py:308`, `:604`; `skills/hermes-lcm/references/configuration.md:195` |
| mem0-oss: plug-in 1.3.0 (`43849c6`), mem0ai 2.2.1 | Hermes's host context compression, task `compression`, as for hermes-native; memory extraction: one call per synced turn (`add` with `infer=True`) | compression: the main chat model, as above. Extraction: OpenAI `gpt-5-mini` with `is_reasoning_model: true`; no reasoning effort sent; chat-completions with a JSON response format | compression: the pinned model, alias `bicentennial-summariser`; extraction: `gpt-5-mini`, alias `bicentennial-extraction` | `integrations/hermes-plugin-mem0/_oss_providers.py:11`, `_setup.py:111-144`, `_openai_llm.py:30-59`; `docs/integrations/hermes.mdx:155`, `:178`; mem0ai `mem0/llms/openai.py:39-40`, `mem0/memory/main.py:958-963` |
| holographic 0.13.0 | Hermes's host context compression, task `compression`, as for hermes-native; the plug-in makes none | compression: the main chat model, as above; the plug-in: no model call | the pinned model, alias `bicentennial-summariser` | `hermes_cli/config_defaults.py:578`, `:765`; `src/bicentennial/systems/hermes_plugin.py:38`, `:41`, `:454-456`; `src/bicentennial/harness/hermes/config.py:73-75`, `:90`; the registry entry (`own_model_routes = []`) |
| omega 1.5.20 | Hermes's host context compression, task `compression`, as for hermes-native; the plug-in makes none through the director | compression: the main chat model, as above; the plug-in reads a staged local model cache (four SHA-256-checked bge-small ONNX files), whose digest the run discloses | the pinned model, alias `bicentennial-summariser` | as for holographic; the registry entry; the developer guide §§6-7 |

**Calls the vendor defaults switch off:**
- **LCM-X:**
  - extraction, assertion extraction and the selective compiler (`config.py:978-980`, `:996-999`, `:1197-1198` at v0.28.1);
  - pre-answer evidence and reranking (`:1188`, `:1089`).

  So the registry's `bicentennial-extraction` alias for LCM-X goes unused at these defaults.
- **Hermes:** `session_search`, which uses no model (`hermes_cli/config_defaults.py:760`; `website/docs/user-guide/sessions.md:847`).
- **Mem0:**
  - the reranker and vision (mem0ai `mem0/configs/base.py:46-48`, `mem0/configs/llms/base.py:24`);
  - procedural memory. It runs only when `add` gets `memory_type="procedural_memory"` with an agent id, and the plug-in never passes one (mem0ai `mem0/memory/main.py:771`, `:855-856`).

**Other model calls the vendor defaults make,** on the probe model, under every registered Hermes stack. The harness turns Hermes's built-in memory on for hermes-native and for the Mem0, Holographic and OMEGA plug-ins alike (`src/bicentennial/harness/hermes/config.py:83`):
- **Hermes's title generation:** task `title_generation`, alias `bicentennial-aux-title_generation`.
  - It uses the main model, with reasoning off and a JSON response.
  - It runs once per session, with up to three calls while the title is still a placeholder.
  - Sources: `hermes_cli/config_defaults.py:773-787`; `agent/title_generator.py:514-530`, `:753-763`.
- **Hermes's background review:** a fork of the agent on the main route (`agent/background_review.py:245-268`). It has two sides:
  - **the memory side:** every 10 user turns while the built-in memory is on (`hermes_cli/config_defaults.py:801-811`, `:1311-1324`);
  - **the skill side:** after every 10 tool iterations while `skill_manage` is offered (`agent/agent_init.py:1381-1383`; `agent/turn_finalizer.py:762-790`). The T1 toolsets do not offer `skill_manage`. Whether the full tier's toolset does is checked when C-4 is filled.

**Embeddings,** for which the route table has no field yet:
- **mem0-oss:** OpenAI `text-embedding-3-small`, 1536 dimensions, on `/v1/embeddings`, alias `bicentennial-embeddings` (`_oss_providers.py:16`, `_setup.py:145-148`; mem0ai `mem0/embeddings/openai.py:15-19`). Its spend is the labelled embedding row (DV47).
- **lcm-x:**
  - none at v0.28.1 (`config.py:1083`);
  - from v0.29.0, and at v0.29.1-rc4, its default turns on local fastembed embeddings. These run in-process and reach no route (`skills/hermes-lcm/references/configuration.md:59-75`, `:265` at v0.29.0; `config.py:1193-1195`). The local model is downloaded or staged, so its identity and digest belong in the run lock, as OMEGA's staged cache does.

**After the swap (segment `seg1`): a provisional reading.**
- **The probe model and the alias** move to the swap model (C-2), under the alias `bicentennial-swap`, for every system (DESIGN §6.2c).
- **Every other route keeps its vendor-default binding:**
  - a route the vendor binds to the main model moves with it: Hermes's and LCM-X's summariser, Hermes's host compaction under Mem0, Holographic and OMEGA, and Hermes's title and review calls;
  - a route the vendor binds to a fixed model stays on that model: Mem0's extraction on `gpt-5-mini`, and its embedder.
- **Why.** PREREG §10 gives each system and segment "the summariser (the vendor's documented default)" (PREREG-v0.5 line 688). Mem0's vendor default is `gpt-5-mini` whatever the main model is.
  - DESIGN §6.2c says the swap "moves the probe model, the summariser and the alias". That sentence assumes a summariser on the main model. That holds for Hermes's host compaction under every Hermes stack and for LCM-X, but not for Mem0's extraction. Whether host compaction counts as a plug-in system's "own compaction" (§6.2c) is open. That question does not change what moves: host compaction is bound to the main model, so it moves under the reading above either way. The same DESIGN erratum settles the wording.
  - PREREG governs DESIGN (DESIGN, Precedence), so the difference goes to a DESIGN erratum. The erratum covers every place DESIGN repeats the sentence: §6.2c, §3's Wake row and §13's swap-lane count. §13 puts all of a life's requests on the swap lane from the swap session on, so under this reading it overstates Mem0's share of that lane and stays an upper bound.
  - The other reading, in which every summariser moves, would need that erratum the other way, or a PREREG-v0.6 rule. Either is settled before the first live swap.
- **Disclosure.** Swap bundles are confirmatory only on the swap subset (DESIGN §3), and the moved routes differ by system, so swap-subset results list, for each system, the routes that moved and the routes that stayed.
- **Vision never moves.** The route table refuses a row that moves it (`src/bicentennial/director/routes.py:36-37`).
- **Embeddings must not move,** so a store keeps one embedding space for the whole life. This follows from §6.2c, which moves only the probe model, the summariser and the alias. Today the director serves embeddings with the route's probe model, which does move (Still open).

**Reasoning effort per route** (open, settled before the first live run).
- **The mechanism today.**
  - The route table has no effort field.
  - The director holds one effort per upstream. It records whether a request carries that effort (`effort_is_pin`), on the Responses wire only, and neither enforces nor rewrites it (`src/bicentennial/director/upstream/forward.py:32`, `:42`; `src/bicentennial/director/upstream/__init__.py:175`).
  - The benchmark's Hermes configuration sets no effort (`src/bicentennial/harness/hermes/config.py:73-90`).
  - At vendor defaults:
    - Hermes's and LCM-X's summary calls send none, so the provider's default applies (Hermes `agent/auxiliary_client.py:6414-6416`; LCM-X `summary_reasoning_effort` `""`, `config.py:1050`);
    - Hermes's title call turns reasoning off (`agent/title_generator.py:530`);
    - Mem0's extraction sends none;
    - Hermes's background review carries the main agent's reasoning configuration (`agent/background_review.py:832`).
- **What follows from the rules:** each segment's probe route runs at its model's pinned effort. That is `medium` for the pinned model (DV42), and C-2's effort for the swap model. PREREG §11's "the same pinned model at its pinned effort" pairs a model with its effort.
- **What does not follow yet: the effort on the auxiliary routes.**
  - C-1's rule is the vendor default. At the vendor default, the summary and extraction calls send no effort, so the provider's default applies. That default is undocumented for the pinned model, and is `max` for the swap model. The title call turns reasoning off. The background review, while it stays on the main model, inherits the main agent's reasoning configuration verbatim (`hermes_cli/config_defaults.py:807-810`; `agent/background_review.py:824-835`).
  - **The proposal, for an erratum or PREREG-v0.6:** a pinned model's effort applies to every route that model serves, overriding a harness's per-task default. A call that turns reasoning off keeps it off where the model allows that.
  - Until the rule is settled, the auxiliary routes are recorded at their vendor default.
- **What the measurements on record sent:**
  - S6a's GLM run of record (r6) set no effort in its replay configuration (`spikes/s6a/replay.py:69-75`). Its write turns went out with `reasoning_effort: medium`, Hermes's own default. Its compaction and title calls carried no recorded effort.
  - S6b's Sol configuration pinned the agent, and the compression and title-generation tasks, at `medium` (`spikes/s6a/replay.py:78-82`). The title request still carried no reasoning field, because Hermes's reasoning-off ranks above the pin (`:79-81`).
  - A fixed vendor model (Mem0's `gpt-5-mini`) keeps its vendor default.

**Still open:**
- **The vision provider and the pinned vision reader** (S8, not yet run), and **S8's vision-capable main model**.
- **The pinned model's tokenizer** (RING0 §9, K02).
  - C-5 counts with `o200k_base` until the tokenizer is named.
  - The check: count a recorded Sol request with `o200k_base`, and compare the count with the input tokens the provider reported for that request.
- **Director support before the live tiers:**
  - The director serves every role except the summariser and vision with the route's probe model (`src/bicentennial/director/core.py:331-334`). That includes embeddings, and Mem0's `bicentennial-extraction` calls, which map to the role `extraction` (`core.py:70`; `route_role.py:43-44`). So Mem0's extraction and its embedder each need their own route, and today the swap would move them (#344).
  - A pinned effort on every route and wire that the effort rule covers (#343).
  - Upstream forwarding for embeddings (#344) and for Anthropic Messages (with the Claude Code adapter, v1.0): the upstream supports only chat-completions and Responses (`src/bicentennial/director/upstream/forward.py:39`, `:97`).
  - Served-identity capture on every wire, including the fixed-vendor routes (`gpt-5-mini`, `text-embedding-3-small`).
- **The route-table schema** (`schemas/route-table.schema.json`):
  - it has one `alias` per row, while the routes above use one alias per role;
  - `summariser` is one required non-empty string, while Mem0 under Hermes has two such routes on different models: the host compaction and its extraction;
  - it has no embedder field and no effort field.
- **Rows not yet entered:**
  - **the control arms:**
    - the no-memory floor;
    - oracle evidence, with the swap-route anchor;
    - naive RAG and its embedder, which is not yet named;
    - the wiped-store control;
    - the full-history oracle ceiling;
    - the raw-archive marker;
  - LCM-X at its last release before the public generator (§10);
  - the whole-life swap-model comparator and the replication-family branches, with GLM in `seg0`;
  - the Claude Code sub-row (alias `bicentennial-cc-main`, `spikes/s4/results/summary.json:4`), with its effort on the Anthropic wire, once the director can forward that wire (listed under Still open).
- **Mem0's paid lane.**
  - `gpt-5-mini` and `text-embedding-3-small` default to the OpenAI API: extraction on chat-completions (`_openai_llm.py:47`, `:59`), embeddings on `/v1/embeddings` (mem0ai `mem0/embeddings/openai.py:22-27`, `:55`). The sources do not show billing. If OpenAI charges per token, DV47 makes this a paid lane (`docs/DECISIONS-v2.md:428`).
  - Its extraction calls count against the paid-lane ceiling. DESIGN §13 lists the extraction competitors' vendor models as a paid row. Its embedding spend is a labelled paid row under the owner's standing embedding grant of up to $100 per run, outside the paid-lane ceiling (PREREG-v0.5 line 874; `docs/DECISIONS-v2.md:430`).
  - C-11 needs its capacity.
- **LCM-X's local embedding model** (from v0.29.0): its staged cache and digest go in the run lock.
- **External memory providers:** it is unchecked whether Hermes's memory background review also fires when an external provider holds the memory slot.
  - Hermes's default text says the interval is "0 when an external provider auto-extracts" (`hermes_cli/config_defaults.py:1321`). That suggests the user sets it, not the code.
  - The trigger checks only the interval, the `memory` tool and a built-in store (`agent/turn_context.py:757-766`).

## C-2: the swap model (provisional)

**The rule** (PREREG-v0.5 line 17, unchanged from v0.4):
- a model from a family other than the pinned family;
- servable through the director;
- named after S4;
- its effort pinned with it, and its cost and run-time terms measured at that effort (S6).

**The provisional entry: Zhipu `glm-5.3` at reasoning effort `high`,** under the alias `bicentennial-swap`.
- DV42 names GLM (Zhipu) as the swap model and as the replication family.
- S4 chose and served this model id (`spikes/s4/anthropic_director.py:334`; `spikes/s4/results/summary.json:2-4`).
- It is a named choice, not a vendor default.

**How it meets the rule:**
- **Another family:** Zhipu, not OpenAI. Met.
- **Servable through the director:** met on two wires, both through spike directors. The benchmark director's own upstream forwards only chat-completions and Responses (`src/bicentennial/director/upstream/forward.py:39`, `:97`), so Anthropic forwarding is listed under Still open.
  - **Anthropic Messages,** for the Claude Code sub-row, through S4's own spike director (`spikes/s4/anthropic_director.py`). S4 ran Claude Code 2.1.306 with 9 of 9 steps valid, no field stripped, and every reply served as `glm-5.3` (`spikes/s4/REPORT.md:3`, `:29`, `:48`). That run predates the director's credential fixes (`:90`).
  - **OpenAI chat-completions,** for Hermes: S6a (`spikes/s6a/REPORT.md:12`; the director's upstream at `spikes/s6a/director.py:8`, `:236`).
  - No GLM route uses the Responses wire, and none was tested on it.
- **Named after S4:** S4 proposed GLM (`spikes/s4/REPORT.md:83`), DV42 named the family, and this entry names the model.

**The effort, `high`** (provisional).
- **What Z.ai documents.**
  - GLM-5.3 has three levels: `low`, `high` and `max`, with `max` the default. Sources: the GLM-5.3 page, and the chat-completion API reference, which supports only those three levels for GLM-5.3. Both were read on 2026-11-01.
  - What GLM-5.3 does with any other value is undocumented. The reference documents a compatibility mapping for GLM-5.2 only: `low` and `medium` go to `high`, and `xhigh` goes to `max`.
- **What the runs on record sent.**
  - S6a's run of record (r6) sent `reasoning_effort: medium` on its write turns. The served level was not recorded.
  - r3's requests carried no effort, so they ran at the provider's default. Z.ai documents `max` as GLM-5.3's default; the served level was not recorded (`spikes/s6a/REPORT.md:51`). Against r3, r6 cut mean write-turn latency by 59% and completion tokens by 86% (`spikes/s6a/REPORT.md:15`, `:49-51`). That argues r6 was not served at `max`.
  - Every GLM run-time figure used in the projections comes from r6. S4's Claude Code run sent `thinking` and `output_config` on the Anthropic wire, not a `reasoning_effort` (`spikes/s4/REPORT.md:48`).
- **Why `high`:**
  - it is a documented GLM-5.3 level, which outside runners can send on the direct API;
  - it is the level that Z.ai's GLM-5.2 mapping gives `medium`, the effort r6 requested;
  - every projection rests on r6, whose served level is unrecorded, so the projections are unvalidated at `high` and at `max` until S6d measures them (`spikes/s6a/REPORT.md:45-51`).

**Cost and run-time terms at that effort: not met.**
- **S6 has no results yet.**
  - Every result section waits for its part (b) (`spikes/s6/REPORT.md`).
  - Part (b) runs on Sol only, with a wiring-only swap, so it does not measure the GLM lane (`:5`, `:62`).
  - S6d, the GLM lane soak, has not started (#25). It alone carries C-2's measurement.
- **Desk projections from S6a r6's measurements are on record:**
  - $0 at the margin on the plan;
  - 338.061 lane-hours for the swap's share at ×1 latency, from S6a's timings, or 42.3 h at concurrency 8 (`spikes/s4/results/model_b.json:132-137`);
  - 52.8 h on one plan for a swap at session 100 (DV47).
- S6d measures them at `high`, and records the level served.

**Context window:** Z.ai documents 1M tokens of context and 128K of output. Which window the plan's endpoints serve is unchecked. S4's Claude Code assumed 200K for an unknown alias (`spikes/s4/REPORT.md:46`).

**For S6d to check:**
- **Title calls.**
  - GLM-5.3 cannot turn thinking off (Z.ai's thinking guide), while Hermes's title call turns reasoning off (`agent/title_generator.py:514-530`).
  - S6a served 12 Hermes title calls on `glm-5.3` over the plan's chat-completions route, with a mean of 5.1 s. One timed out at 34.8 s and fell back to the main route (`spikes/s6a/REPORT.md:34`, `:53`).
  - S6d checks the title calls at the pinned effort, on the account pool it uses.
- **The Anthropic endpoint.** Z.ai's GLM-5.3 page says previous or expired coding-plan subscribers reach the model API only over chat-completions. The Claude Code sub-row needs the Anthropic endpoint on the account it uses.
- **The served effort level,** which no run has recorded.
- **The auxiliary routes' effort.** C-2's terms hold only for the configuration the board runs, and "at `high`" covers the probe route alone. S6d runs the auxiliary routes at the effort the per-route rule settles (#343), or measures both that and the vendor default. In r6, which sent them no effort, the two compaction calls in `write` took 79 s and 119 s, with completions that were mostly reasoning (`spikes/s6a/REPORT.md:33`).

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
