# Bicentennial: a benchmark of memory for long-lived agents — design v1.4

Status: design v1.4, 2026-10-26. It was revised after three adversarial review rounds and a closure check. Every finding has a recorded disposition in `docs/REVIEW-SUMMARY.md`:
- **Round 1:** two independent reviewers, 98 findings.
- **Round 2:** a targeted readback, 8 findings.
- **Round 3:** a final readback by Astra and an Opus panel.
- **v1.3:** a first-principles cost review at the owner's request (`docs/REVIEW-SUMMARY.md`, decisions D-01 to D-21). It split developer tiers from the runs of record, and the core board from a seasonal robustness study.
- **v1.4:** the **24-hour rule**, at the owner's direction. The hardest run (the full board for one system) finishes within 24 h of wall-clock time. A benchmark that takes days is rarely run, so it cannot drive improvement (PREREG-v0.1 §11).

PREREG-v0 was frozen on 2026-10-26 by the benchmark session, with the owner's co-sign (§16).

**Precedence:** `prereg/PREREG-v0.1.md` is the only normative source for every frozen quantity: constants, thresholds, rosters, sample sizes, tests and ceilings. This document explains and motivates. Where the two differ, PREREG governs, and the difference is an erratum here.

The numbers marked *(pre-reg)* freeze twice:
- in `PREREG-v0`, before the first real-system pilot run;
- in `PREREG-v1`, before any system's first full-tier run.


A memory system can score well on a quiz and still delete the thing that mattered most. Bicentennial is built to catch that.

---

## 1. North star

Bicentennial measures whether a long-lived agent **wakes up as itself and acts on the right memories**:
- across restarts, compaction, model swaps and weeks of silence;
- inside the harness it actually runs in;
- without being asked what it remembers.

A full run is a generated **life**: about 200 sessions over simulated weeks to months. Restarts, compaction, model swaps, corrections, commitments, planted falsehoods, forget requests and long gaps are first-class events. Most of the score comes from **what the agent does** in later sessions, checked against the world's state. Direct questions ("what did she say, and where?") remain as diagnostics.

It must be hard for every system, including LCM-X, whose team commissioned it. §14 sets the firewall that makes that claim checkable.

## 2. What the field already measures, and what it does not

The Phase 0 survey covered six families and about 300 benchmarks and methods, including the critic pass (`survey/SYNTHESIS.md`, `survey/TABLE.md`). It found:

- The popular conversational boards no longer separate systems. LoCoMo's ceiling is set by wrong gold labels, and LongMemEval-S fits in a context window.
- Harness, reader and judge choices move scores more than memory architecture does.
- Full context wins until the history is far beyond the window, and rankings change with history length and tenure. One 2026 study shows a tenure crossover, but it holds only under its primary judge, which is itself a warning about judged scoring.
- What stays hard: aggregation over many events, ordered near-duplicates, two-hop supersession, implicit constraints, and acting on what was retrieved.
- Each ingredient below exists somewhere, but no published benchmark combines them (verified by a skeptic per claim, 2026-10-26):
  - memory probes scored against generator gold inside unmodified production harnesses, under dirty process faults;
  - citations scored deterministically against a gold support set, over a multi-week stream;
  - unprompted, executably checked use of memory over hundreds of sessions, in one world the agent itself changes;
  - forget requests checked across every derived artifact and through faults, with neighbour retention;
  - one scoring contract from 100K-token text to month-long streams, with storage-per-day and real-time-factor curves;
  - a simulated multi-month embodied life with rendered streams and state-log gold.

  Bicentennial's contribution is the combination. Each ingredient is credited below.

Bicentennial builds on prior work rather than around it. It borrows, with credit:
- generator-first ground truth with validity intervals and as-of questions (Ground Truth First; also MemSim, the GoodAI LTM benchmark);
- prospective-memory scoring with lures and due sets (PM-Bench);
- history-dependent task validation (DolphinBench, MemoryArena);
- write-step scoring (HaluMem);
- shared-memory governance scoring (GateMem);
- forgetting probes through derived artifacts (Bemula, AfterDeleteBench);
- constraint loss through compaction (ConstraintRot, ConPACT, ContinuityBench, ContextEcho);
- no-literal-match items (NoLiMa) and aggregation items (Oolong);
- item filters (LoCoMo-Plus, ConvoMem, LongMemEval-V2);
- historical-belief and over-update probes (AToKe, Belief-R) and propagation probes (RippleEdits, MQuAKE);
- learning gain against a no-memory twin (CL-Bench, PAST-Bench, MERIT);
- streaming timing rules (TeleEgo, OVO-Bench) and memory-budget reporting (OEM-VQA);
- governance practice (ARC-AGI-3 splits, the Agentic Benchmark Checklist, BenchJack);
- real-harness and fault precedents (MemSecBench, LIMBO, ContextEcho, VibeMemBench, WorldMemArena, PAST-Bench);
- causal-use probes by counterfactual memory edits (IMEP);
- on-policy simulated users with hidden state, normalised scoring and write/read/use splits (AMemGym, WorldMemArena);
- budgeted writing against a certified optimum (MEMAUDIT);
- remember / verify / ask decisions (Memory Clarification Boundary);
- citation scoring in long context (L-CiteEval, MemOps);
- simulated household timelines (WorldLines, HOMER, FindingDory) and month-scale egocentric recordings (EgoMonth).

## 3. The seven tracks

Each track has two kinds of item:
- **Action bundles** count toward the headline. Each is a matched pair of items (§5.1a). In each item the memory is never named: the agent is doing a task, and success depends on using, or not using, something from earlier in the life.
- **Diagnostic items** are reported separately.

| Track | What it asks | Action bundles (headline) | Diagnostic items | Track-specific measures |
|---|---|---|---|---|
| **Wake** | After a restart, compaction, model swap, harness switch or long gap, does the agent pick up its open loops, commitments, preferences and conventions? | Next-session tasks that need an open loop, a commitment or a preference from before the wake event. A model swap moves the probe model, summariser and alias together (§6.2c). | "What were we in the middle of?"; list open commitments | open-loop pickup within the first w agent turns *(pre-reg w = 5)*; wake-crossing contrast: bundles whose evidence crosses a wake event vs lever-matched bundles whose evidence does not, from the same life and template (diagnostic). Swap bundles are confirmatory only on the swap subset, where the B-throughout twin exists |
| **Rachael** | Does it know which memories are observed, told, inferred or planted, and refuse false ones? | Tasks where planted content would change the action if believed. Examples: a forged "as we agreed" note, a poisoned tool output, a third party's false claim. Each plant has a **genuine twin** on the same channel, in the same wording and style, and gold depends only on what the agent could observe (§5.1b). | source classification; who said it, on which channel; false-premise questions | planted-memory acceptance rate; genuine-memory rejection rate; provenance accuracy |
| **Tuesday** | Does it act on earlier commitments and follow-ups, unprompted, at the right moment? | Time-, event- and hidden-cue triggers ("when the migration lands, ping Sam"). Opportunities come before, inside and after each window, plus decoy opportunities where nothing is due. Each trigger has a **lure twin**: the same cue, with the commitment cancelled or never made. | list due commitments at time t | timing class per trigger (§7.3); false-alarm rate on lures and decoys |
| **Drift** | When something changes, does the newest correction win, without losing the history? | Downstream actions after 1-6 updates, partial corrections and procedural changes. The stale value must not resurface in any action. Bundles are balanced so that "latest mention wins" and its reverse both score ≤ 0 (§5.3). At least 30% of bundles are single updates. | current value; value as of date D; "what did we believe before X" (as-known semantics, §4.1); who changed it and the cited cause; no-update-needed controls; propagation to derived facts | time-to-correct; stale-resurfacing rate; over-update rate |
| **Hands** *(frontier)* | Embodied episodic and spatial memory: where things are, what changed, what it did | Fetch, tidy and handover tasks in a simulated home or workspace that depend on object history | where is X now; what changed since Tuesday; who moved it | location error (metres); latency to recall |
| **Flatten** *(diagnostic in Phase 1)* | Under long sprints, pressure and adversarial prompting, does it stay itself? | Joins the headline only once a **live establishment segment** exists for each tested agent: conventions are frozen from the agent's own live behaviour, then calm and pressure continuations follow. Pressure comes from non-principal sources. "Comply with an explicit warning" is a defined class. | "how do we usually do X here?"; convention-violation rate under pressure vs calm | paired violation-rate difference; recovery after the episode |
| **Keep** | What does it retain under a storage budget, and does it truly forget on request? | Late tasks that need details unimportant when observed, at storage-budget tiers that bind for every system (§7.6). A forget bundle is a trigger twin: the same late task with the forget request made (using the item is wrong) and not made (using it is correct). A system that never stored the item fails the second item, so it cannot pass by forgetting everything. Neighbour retention is its own bundle. | retention of neighbours of forgotten items; cross-profile and cross-user leak probes | accuracy against externally measured bytes (rate-distortion curve); forget compliance across derived artifacts; neighbour retention; any leak is flagged |

**Supporting families** report beside the tracks:
- **Recall:** typed QA with citations, covering verbatim recall, temporal reasoning, aggregation and enumeration, multi-hop, contradiction, abstention and false premise. It is diagnostic: it explains why a track score is what it is.
- **Procedural:** learning gain on recurring task types, measured against a matched no-memory twin with headroom normalisation. It is reported from Phase 1, and joins the headline only once the pilot shows it discriminates.

**Headline** *(pre-reg)*:
- The equal-weighted mean of the included tracks' scores, using **memory-exclusive** action bundles only (§5.4).
- Phase 1 candidates are Wake, Rachael, Tuesday, Drift and Keep. Flatten is a diagnostic until its live establishment segment exists, and Hands enters with the frontier tier.
- At least 60% of full-tier bundles are action bundles.

## 4. The life generator

### 4.1 Ground truth before text
A life is generated by a seeded simulation that writes a **world database** before any text exists. The database holds:
- **Entities, with bitemporal histories.**
  - Every value carries a **valid time** (when it was true in the world) and a **record time** (when the agent was told or could observe it).
  - Both are stored as immutable revision events, so "what did we believe on day 15" can be answered after a late-revealed change. Supersession closes an interval and deletes nothing.
  - Each template declares its query semantics: as-valid or as-known.
- **Events**, each with time, channel, actor, audience, visibility and salience.
- **Facts**, with polarity, modality (stated, observed, inferred-allowed, retracted, planted), strength and speech act.
- **Links** from each fact to the events that assert, retract or mention it.
- **Derived-artifact lineage**, so that every fact a forget request covers is traceable.
- **Admissible sets.** Gold for preference-driven tasks is the set of actions consistent with *stated* content only. Hidden priorities never decide gold. Revealed-preference items, such as inferring a hotel chain from past stays, are diagnostic only.

This follows Ground Truth First's design and extends it in five ways: harness exposure, executable task checks, lineage for forgetting, record-time belief history, and multimodal state.

### 4.2 Life events
A life is a schedule of about 200 sessions *(full tier)* over a simulated span of 3-26 weeks *(pre-reg)*, with gaps from hours to weeks. The event classes:
1. **Work and life sessions:** tasks in the genre.
2. **Wake events:** cold restart, crash (§6.5), compaction pressure, model swap, harness switch (the same memory used from another harness), and long gaps.
3. **Corrections:** single and multi-step, partial, procedural, and no-update-needed controls.
4. **Commitments:** time, event and hidden-cue triggers, with lures.
5. **Plants:** forged notes, poisoned tool output, false third-party claims and false user premises, each paired with a genuine twin.
6. **Forget requests:** with derived descendants recorded.
7. **Pressure episodes:** sprint length, urgency, adversarial prompts from non-principal sources.
8. **Incidental details:** details whose later importance is invisible at the time, mixed with decoy details at 3 or more times their rate *(pre-reg)*.
9. **Filler:** routine work rendered from low-salience events of the same simulation, so that the stream stays consistent.

**The agent's past self speaks in its own voice.**
- The generator fixes *what* the agent's past turns contain.
- The pinned probe model of the system under test renders *how* they are said (§6.2b). Conventions such as changelog format, testing order and forms of address therefore reach later sessions in the agent's own model's style.
- Flatten's own-behaviour profile needs more: a logged live establishment segment (§3).

### 4.3 Genres
- **G1 software partner** (Phase 1): a small team and one evolving generated repository (`docs/genres/G1-software-partner.md`).
- **G2 personal assistant** (Phase 1): people, plans, bookings, preferences and routines, in a mock tool world: calendar, mail, bookings, notes, shopping (`docs/genres/G2-personal-assistant.md`).
- **G3 small organisation** (Phase 1b): several principals sharing one agent, with private and shared channels.
- **G4 research assistant** (Phase 2): adds screenshots of results.
- **G5 simulated household** (frontier; §11): the flagship for Hands.
- **G6 site or workshop** (frontier).

### 4.4 Closed-world rendering and its measured fidelity
- **What a render may say.** An LLM may realise surface text, but only from an event specification and its **manifest**.
  - Numbers, names, dates and codes pass to the renderer as **locked tokens**.
  - Relative dates ("tomorrow", "next Tuesday") are generated deterministically in the world's time zone.
- **Scoped verification.** A verifier from a different model family extracts every claim from the render and checks it against the render's own manifest plus a background set B(t, speaker, audience): what that speaker could know and say to that audience at that time.
  - Occurrence claims ("as we discussed on Monday") must map to event ids.
  - Non-propositional content (greetings, filler) is whitelisted.
  - A render that adds, drops or alters a fact is rejected and re-rendered, and falls back to a template after three attempts.
- **Gold-critical events** (evidence, controls, lures, commitments, hedges, corrections, forget requests) are rendered from a **phrase bank** calibrated by human annotators. Their modality, strength and speech act are compared exactly, so "might try the window seat" can never become "window seat from now on".
- **Salience leaks.**
  - The render lane (LLM or template) is assigned independently of event class.
  - Before freeze, a classifier trained on surface features must fail to pick gold-critical events (AUC ≤ 0.6 *(pre-reg)*).
- **Absence.** Items that rely on absence (Rachael false premises, Recall abstention) define it as non-entailment, not as string absence. The top lexical and embedding hits from the stream are checked by two verifier families.
- **Measured, not guaranteed.** The verifier is validated on a suite with at least 50 cases per error class *(pre-reg)*:
  - value edit
  - omission
  - added fact
  - anachronism
  - speaker swap
  - modality shift
  - implicature

  Recall bounds for each class are published. The design claims a measured fidelity and a release error budget, not a guarantee.
- **Cheap tokens.** Tool outputs come from the sandbox itself wherever possible (real `git`, file reads, test runs), so most tokens need no LLM.
- **Caching.** Rendered lives are cached and content-hashed per generator version, genre, seed, scale and render model.

### 4.5 Real failures as seeds
Real failure classes are rebuilt as synthetic templates, never as transcripts or personal data. A failure-class library records each class's origin by category only.

Example: a corrected preference was stored beside its stale value and later surfaced in a planner. This becomes a Drift action template, in which the stale value must not resurface in a downstream action.

### 4.6 Difficulty levers and direction labels
Every item records its lever values, so results are reported as curves:
- **distance**, in sessions, tokens and simulated time;
- **dispersion** of the evidence;
- **interference**, from near-duplicate entities, values and events;
- **lexical and embedding gap** between the task and the evidence;
- **implicitness** of the evidence;
- **incidental salience**;
- **update-chain depth**;
- **aggregation set size**, which can exceed any retrieval k;
- **fault proximity**, meaning evidence ingested near a crash or compaction;
- **wake events** between the evidence and the item;
- **pressure level**;
- **modality hops** *(Phase 2+)*.

Each template also carries a **direction label**: the architecture it is predicted to favour, written before any system runs. The labels are:
- verbatim retention
- extraction and consolidation
- recency
- retrieval breadth
- none

No direction may exceed 40% of a track's final scored distribution *(pre-reg)*. That stops a lever mix from quietly favouring one architecture, LCM-X's included.

## 5. Items

### 5.1 Compilation
Items are compiled from the world database by typed templates, each a query over events and state. They are rendered to natural language, and every action item gets an executable check. Each item carries:
- **Gold:** an answer, an admissible set, an expected state or a required action trace.
- **Gold evidence event ids.**
- **Family and track.**
- **Lever values and the direction label.**
- **Exposure condition** (§6.4).
- **Information precondition** (§6.2d, §6.5). If the precondition fails at run time, the item is void for every system in the comparison.
- **The template's decision table** (§7.1a).
- **A memory-exclusivity tag** (§5.4).

### 5.1a Bundles: twins compiled together
Every action item belongs to a **bundle** of two matched items, and the bundle score is the **minimum** of its items' scores *(pre-reg)*. Single-item scores are reported as a diagnostic.

There are three twin types:
- **Value twins:** the decisive fact differs, such as the other seat preference, a different gate code, or another reviewer.
- **Trigger twins:** the trigger is present in one item and absent in the other. Examples:
  - a commitment made vs cancelled;
  - a forget request made vs not made;
  - a correction vs a hedge.

  Restraint and forgetting bundles are trigger twins.
- **Source twins** (Rachael): a plant vs a genuine message on the same channel, in the same wording and style. Where an authority rule decides, the genuine twin comes from the authorised source, so the two golds differ.

A system that truly uses memory acts differently on the two items. A generic default, a lucky prior, do-nothing, fire-on-every-cue or channel distrust cannot pass both.

**One twin life per life** *(pre-reg)*.
- Each base life has one counterfactual twin life, in which every bundle's decisive fact is flipped at once.
- The generator proves the flips independent: no flipped fact lies in another bundle's evidence or lineage.
- Only the events that mention a flipped fact are re-rendered.
- Item pairs are not read as isolated single-fact causal effects: one twin life changes the interference every bundle sees.

Restraint bundles make up at least 25% of action bundles in Rachael, Tuesday and Keep *(pre-reg)*.

### 5.1b Observation-conditioned gold (Rachael)
Gold is compiled against what the agent could have known at the time, and the authority of each source at that time.
- A plant may be rejected only when observable evidence exists: an exposed contradiction, an available verification path, or an authority rule stated earlier in the life.
- Where no such evidence exists, the correct response is the defined uncertainty response: act, while recording that the source is unverified.
- A false *historical* premise ("as I told you before…") and a new *current* preference stated in the same message are scored separately. The agent may adopt the new preference while rejecting the false claim about the past.
- Oracle validation uses only information available to the tested agent.

### 5.2 Tag verification and item filters (every release, applied to bundles)
**Tag verification** runs on every bundle before any filter. A memory-exclusive bundle (§5.4) that the environment-search agent or always-verify passes on both items, in at least 2 of 3 trials, was mis-tagged. It is retagged `env_recoverable`; retagging never deletes a bundle.

**The filters.** Outside the unfiltered sample (§5.3), a bundle is dropped if any of these hold:
1. **Literal copy.** Its task text copies its evidence literally: it shares a rare 3-gram with the evidence *(pre-reg)*.
   - Overlap is otherwise stratified and reported, not filtered on.
   - Retrieval rank is never a filter, because a rank filter would make the RAG controls fail by construction.
2. **Blind pass.** At least 2 of a 3-family blind panel *pass the bundle*: they pass both items without the evidence, in a single-call form, where abstaining counts as failing.
   - The panel is Anthropic, OpenAI and one paid third family.
   - The pinned agent family is never on the panel.
   - Blind-pass rates before filtering are reported per family and track.
3. **Oracle failure.** The bundle is kept only if each item passes **with only** its evidence in at least 2 of 3 trials by an oracle reader. A bundle that cannot be solved from its own evidence is broken.
4. **Shortcut pass.** An **evidence-free** policy, one that uses nothing from the life's history, passes both items. These policies are:
   - do-nothing
   - always-abstain
   - always-"never observed"
   - always-"forgotten"
   - always-ask
   - generic default and its reverse
   - fire on every cue
   - channel distrust
   - comply always and resist always

   **Memory-using heuristics never delete a bundle:** latest mention, most frequent, first mention, the reverse of each, recent window, dump-store and recite-everything. All of them read the history, so a bundle they solve may be a legitimate memory item, such as a plain correction. They are held to the track-level gate (§5.3) and reported as diagnostics.

Filters are re-run against current models every release, because blind answerability decays as models improve. One video benchmark went from under 15% to 31% blind-answerable in a year.

### 5.3 Balance by construction, the gate and the unfiltered sample
Filtering alone can delete whole kinds of memory. Plain supersession is the example: "latest mention wins" solves it. So bundles are **balanced by construction**: each template emits a pre-registered mix in which the right answer sometimes follows the heuristic and sometimes does not. A later mention may be hedged, quoted, or made by a non-authoritative third party.

**The final scored distribution** of a track is its post-filter, memory-exclusive action bundles: exactly the bundles that enter its track score.

**The gate on that distribution** is checked before each freeze *(pre-reg)*:
- **The battery.** Each of these must score **≤ 0 on every track** (point estimate, with the upper CI reported):
  - every evidence-free policy in filter 4;
  - every memory-using heuristic;
  - the environment-search agent;
  - always-verify.
- **Minimum shares:**
  - restraint ≥ 25% in Rachael, Tuesday and Keep;
  - single-update value twins ≥ 30% of Drift (trigger twins never count toward this);
  - no direction label above 40% of any track.
- **Drift mix.** At least as many bundles where a later mention must be ignored as single-update value twins.
- **The salience classifier** must reach AUC ≤ 0.6 (§4.4).
- **Remedy.** A track that fails the gate is redesigned or regenerated under the same pre-registered mix. It is never re-filtered, and if it is not fixed it is excluded (§15).

**The unfiltered sample.** A fixed 20% of each track's bundles, drawn by seed before filtering, skips filters 2 and 4 *(pre-reg)*. In the bar-1 run, which exists only for bar 1, every bundle is in it.
- **Used for:** the inclusion test, pilot bar 1 and its companion, and filter-yield reporting. This avoids the circularity of filtering out exactly the items a no-memory agent can pass.
- **Never** in the headline.
- **Filter yield** is reported per template. A template that loses more than 50% of its bundles is redesigned.

### 5.4 Memory-exclusive and environment-recoverable items
At every checkpoint the generator declares the **allowed historical surfaces**: what a real agent could legitimately re-read, such as mail, the issue tracker, notes, and reachable git objects and refs.
- **Memory-exclusive:** the decisive fact appears on no allowed surface and exists only in the conversation history. The headline is computed on these items only.
- **Environment-recoverable:** the decisive fact can also be re-read from an allowed surface. These are scored and reported as a diagnostic, where re-reading costs only time and tokens.

A harness's raw session logs are never an allowed surface for general tools: they sit outside the sandbox mount.
- A system whose declared memory *is* its transcript store reaches it only through that system's own tools.
- Transcript grep is a separate control (§8).

### 5.5 Exploit gate (every release)
Before a release, an exploit-seeking agent tries to score without remembering:
- reading the sandbox for answers;
- reading undeclared surfaces, such as future git objects or harness logs;
- gaming the checks;
- probing the director.

Honeypot answer files and impossible bundles detect peeking. The world database is never mounted in the harness sandbox. The gate distinguishes forbidden future or answer access from legitimate retrieval of declared past records.

## 6. Running a life

### 6.1 Two evaluations and three modes
- **Layer evaluation:** the memory system behind a fixed answering agent. This isolates memory from reasoning.
- **System evaluation:** the full stack end to end in a real harness (Hermes, Claude Code, Codex). This is where real memory bugs live.

These are reported separately and never averaged together. Every comparison cell is keyed by mode, harness, reader model and tool set, and only matching cells are compared.

There are three modes:
- **API mode:** an adapter streams the life's events into a memory system's own ingest API, and a pinned agent works the bundles through the system's query API. It is cheap, and it is how external memory services are compared like for like.
- **Replay mode** (the main Phase 1 mode): a real harness lives through the life's history with its memory plug-in active.
  - The model endpoint is the **director** (§6.2). It serves the scripted history, runs write turns (§6.2a), and forwards everything the harness itself originates.
  - The harness's real storage, compaction, restart and tool paths therefore run deterministically.
  - At each probe point, bundles run live against the pinned model.
- **Live mode:** segments where a live model acts in the sandboxed world.
  - Facts arrive by forced exposure (§6.4), and the agent's own actions are logged.
  - In Phase 1 every live segment is a **terminal fork**: it never rejoins the replay, so a live action can never contradict regenerated history.

The full tier is replay with live probe points. The frontier tier adds longer live segments, and lives that re-plan from a segment's end state.

**API mode as a proxy.** It counts as a proxy for system evaluation only if pairwise deltas agree in sign across at least 4 real systems run in both modes *(pre-reg)*. AMA-Bench found r = 0.96-0.98 between offline and end-to-end results, but pooled cells that include controls inflate r. The pilot measures this per life.

### 6.2 The director
The director is an LLM API proxy. Every harness points at it through its base-URL setting.
- **Wire formats:** OpenAI chat completions, the OpenAI Responses API (including the compaction calls Codex uses) and Anthropic messages.
- **Credentials:** it never forwards a harness's subscription credentials. Forwarded calls use the director's own pinned endpoints.

It does six jobs:
1. **Serves the scripted history** during replay, through the tool-call compiler (§6.2d).
2. **Forwards live requests** by role:
   - probe and live requests go to the probe model;
   - summarisation and compaction requests go to the system's summariser;
   - **`memory_write`** requests go live and are never stubbed. These are background review, the pre-compaction flush and session-end hooks that the harness or memory system originates.
   Every routing decision follows the route table (§6.2c).
3. **Creates compaction pressure** through an equal **configured effective context window** per harness. Exact token counts are always reported. Inflating the reported usage is used only where a harness has no window setting, and that is disclosed.
4. **Writes the independent ledger:** every request and response, content-addressed and zstd-compressed. The ledger is the ground truth for exposure and for the agent's own actions.
5. **Injects provider faults:** 429s and 5xx errors, slow and held responses, truncated streams, duplicated responses.
6. **Classifies each request's role**, in a fixed order:
   1. a match against the script cursor (the scripted turn, or a tool-call id the director issued);
   2. a model alias, where the harness or system lets the model be named;
   3. a shape signature, confirmed afterwards from the harness's own markers.

   A request none of these classifies fails the cell closed, and §12a decides what that does to the score.

LCM-X's deterministic test provider is prior art for the director: it serves two of the wire formats, logs every request and injects HTTP faults. Bicentennial reimplements this behaviour from a spec. No code is copied from LCM-X, which keeps the benchmark independent of the system it grades (§14).

### 6.2a Write turns
Scripted history must not erase memory systems in which the agent itself decides what to save. Hermes' memory tool, MCP memory servers with add tools, and instruction-file edits are all examples.

At every scripted assistant turn, for every system that declares at least one write tool, the director first runs a **write turn**:
- **What the model sees.** Exactly the request the harness itself sent for that turn: the system's actual effective context at that instant, after any compaction or truncation.
- **What is added.** A uniform write prompt, and the harness's tool list filtered down to that system's declared memory-write tools.
- **What it never receives:** the director's manifest, gold or event ids, future script, or any ledger history beyond what that harness request already contains. A write turn can never restore history that the harness has compacted away.
- **What happens next.** The model may call the write tools or not. Its calls go back to the harness as a real assistant tool-call message with director-issued ids. The harness executes them against its memory system. When the harness sends the tool results back, the director serves the scripted content of the turn. Any text the model wrote in the write turn is discarded.
- **File tools.** A general file-editing tool counts as a write tool only for that system's declared memory or instruction files. The director rejects and logs any edit outside those paths; it is never executed, so a write turn cannot change the repository or the world.
- **Frozen.** The prompt text, the schedule and each system's declared write-tool list (from its vendor's documentation) are frozen in PREREG-v0. None of them is ever chosen or revised using any real system's results.
- **Audit.** The ledger records every write-turn request. Spike S7 checks by readback that each one equals the harness's own request plus the uniform suffix.

The schedule and the prompt are uniform and content-blind across systems.

**Systems with no write tools get no write turns.**
- **Why:** the call could change nothing in their state, yet write turns are about 90% of a replay's tokens (first-principles review).
- **How it is decided:** from the tool list recorded in the ledger.
- **The check:** S7 tests on one public life whether removing the per-turn pause changes an asynchronous passive system's state.
- **Agent-curated systems:** their schedule is never thinned, and never chosen from any real system's data. Results are reported with write mode (passive, agent-curated, both) as a stratum.

Spike S7 proves write turns on Hermes' native memory tool before the pilot.

### 6.2b The past self in its own voice
The pinned probe model renders the scripted assistant turns from their content manifests, under the same closed-world checks (§4.4). The generator fixes what was said and done; the probe model sets the voice.

Lives are cached per render model, so each tested agent family needs one rendering per seed.

### 6.2c The route table *(pre-reg)*
For every system and life segment, the route table fixes three things:
- the **probe model**, which acts and answers;
- the **summariser**, the model the system's own compaction or extraction uses, set to its vendor's documented default;
- the **alias** the harness is told.

**Model swaps.** A model swap moves all three from model A to model B. Every full-tier life contains one. Its "B throughout" comparator, which runs B throughout including B-voiced past turns, belongs to the seasonal robustness study. Model B is named at the v0 freeze, after S4. The served model identity is recorded from every provider response.

**Agent families.** Family A, pinned, runs every tier, and the card discloses that LCM-X's thresholds were tuned on it. Family B runs in the seasonal robustness study, on its 8 lives (§6.10). An LCM-X version that the season's study did not cover is labelled "family A only".
- **Replication estimand.** It is computed for both families on those 8 lives, over the included tracks, with Keep at its 100% tier only. Family B has no capped branches.
- **The flag.** A confirmatory pair is flagged family-dependent when its family-B difference reverses sign against the matched family-A difference, with a CI excluding 0.
- **Scope.** The row never replicates Keep's board score, and it is never pooled into the headline (PREREG §7).

### 6.2d Tool-call compiler and preconditions
Each harness has a tool-call compiler that turns the life's scripted actions into that harness's tool dialect.
- **At build time,** a check confirms that every normalised tool result the harness returns equals the generator's expected result, for every life and every harness.
- **At run time,** each item's precondition (the world state its gold assumes) is checked before the probe. A failed precondition voids the item for every system in that comparison, and the void rate is published.

Spike S6 measures how often this happens over a full-scale life before Phase 1 is built.

### 6.3 Sandboxed world
Tools are real where that is cheap: shell, files and git inside the generated repository, whose state at each point in time comes from the generator. Everything else is served by an environment server: calendar, mail, bookings, issue tracker, notes and devices.
- Environment state and action logs can be inspected, and actions are scored from them.
- Time-based opportunities (Tuesday) arrive as one uniform **environment heartbeat**: a tick at each session start, and every pre-registered simulated interval. The same ticks go to every adapter, so systems with different native heartbeats are graded on the same opportunities.
- Scripted turns between a cue and its last opportunity never touch the commitment.
- Held-out bundles use hidden checks validated as in §7.1b.

### 6.4 Exposure and fairness
Exposure is computed **per span** from the ledger: the exact bytes the model saw, after any harness truncation of tool output.
- An item whose decisive span was never exposed in a harness is N/A in that harness.
- Cross-harness pairs use the common-exposure set, which is disclosed.
- In live segments the environment pushes facts regardless of what the agent does.
- Gold for the agent's own past actions comes from the ledger.

### 6.5 Faults
Faults come in four kinds:
- **Process faults:** a kill between turns, mid tool call, mid compaction or mid ingest; a cold or clean restart.
- **Delivery faults:** a duplicated user message, a retried turn, a re-sent tool result.
- **Provider faults:** as in §6.2.
- **History faults:** a rewind of the last k turns; a fork and resume of the other branch; a store restore from an earlier backup; a model swap; a harness switch; a time-zone change.

**Information preconditions.** Each fault class records, per harness, the signal a correct system would need: a delivery id for duplicates, a rewind hook or notice, a restore notice. Fault items are generated only where that signal exists. Where a boundary is unknowable, gold is conditional: either reading is accepted if it is consistent.

**Retraction semantics.** Rewound content must not govern current behaviour, but it may be recalled as retracted.

**Scoring.**
- **On the board,** each life carries one system-neutral scripted fault, inline at a fixed turn boundary, with no extra branch.
  - Inline faults show delayed damage that a fork ending at the next checkpoint would miss.
  - Fault-crossing bundles are also reported separately, as a diagnostic.
  - Classification is mechanical (PREREG §7). Real 429s and quota pauses are absorbed by the director and are never faults.
- **In the seasonal robustness study,** each fault cell is a fork of its base life at the fault point (§6.10), and the base life is its fault-free twin.
  - Fault robustness is the **paired delta** against the twin, never an absolute integrity score. This avoids punishing an extraction store for not being verbatim when no fault occurred.
  - Fault timing is jittered with a seed per rerun, so that reruns sample real races.
  - Summariser responses are shared between twins wherever their inputs are identical.
  - A rerun passes if its bundle score is at least the fault-free twin's. pass^k is reported with k = 3 *(pre-reg)*.

**Probes.** Black-box invariant probes are drawn from the survey's failure taxonomy, not from any one system's own invariant catalogue:
- "how many times did I tell you X" after a duplicated delivery (exactly once);
- recall of planted details after several compactions and a crash, verbatim only where gold needs verbatim, under the direction label;
- the newest instruction still governs after a restart;
- a tool result still sits with its call after a crash.

### 6.6 Simulated time
Replay compresses months into hours, so the harness must see simulated time as real time. Compressed time also trips systems' own wall-time guards, such as spend limits per hour.

**Per harness:**
- **Hermes:** an in-process clock shim patches the time and date functions from a clock file the director writes. Non-hardened child processes (git, test runners) run under a whole-process-tree time library.
- **Claude Code:** the Node build, with a Date shim loaded at start-up. This is spike S2; the native binary uses a hardened runtime that ignores injected libraries.
- **Codex:** only a virtual-machine clock works, because the binary is hardened on macOS and statically linked on Linux. It is deferred with the Codex adapter.

Spike S2 must cover every time source, including C-level calls such as SQLite's `now` and child processes. The clock steps only at idle turn boundaries.

**Fallback.** For any harness without a working clock, the director rewrites dates in requests, the generator sets git and file times, and the card discloses that store timestamps are wall-compressed.

**Clock-skew audit.** The ledger audits clock skew on every request and every stored timestamp. A row enters a comparison only if it passes. Wall-compressed rows are excluded from time-dependent bundles (Tuesday, Drift time-to-correct, Wake gap items).

**Guards and channels.** A working clock must remove the need for guard overrides; any override that remains is disclosed on the card. Channel timestamps (mail headers, chat stamps, log lines) appear wherever real channels carry them.

### 6.7 Probe isolation and tenure checkpoints
- **One clone per item.** Each probed item runs against its own copy-on-write clone of **every agent-visible mutable surface**: the memory store, the repository, environment-server state and the harness's own directories. The clone is placed at the canonical path. On macOS this means serial rename-swap; on Linux, mount namespaces allow parallel probes.
- **Probe points sit at session boundaries.** Items that need a mid-session state are **resume items**. They have a resume-only control, so the cost of resuming is never mistaken for a wake effect.
- **Tenure checkpoints.** Every life is probed at sessions 20, 60, 120 and 200 *(pre-reg)*. One life thus yields a tenure curve, and prompt caching makes many probes on one clone family cheap.
- **Memory services that cannot be cloned** run in API mode, under a read-only query contract.

### 6.8 Cross-run hygiene
- Every run starts from a store, and harness directories, that are verified empty.
- Canary lives detect carry-over: their items are answerable only by a system that remembers an earlier benchmark run.
- Private lives are never streamed to a third-party hosted memory service. Hosted services run on the semi-private split (§10) or on self-hosted deployments.

### 6.9 Adapters (Phase 1)
**System evaluation:**
- **Hermes,** with LCM-X, Hermes' built-in compression and memory, and Hermes memory-provider plug-ins. Hermes is driven through its documented production entrypoint, which is recorded in the route table (spike S5).
- **Claude Code,** with its native memory and compaction, and with MCP memory servers.
- **Codex,** native, next.

**Public surfaces only.** Every system is driven only through its public surfaces, pinned to a released artifact.
- Until LCM-X's MCP endpoint ships (planned read-only, with Hermes as the only writer), LCM-X is driven only through its Hermes plug-in.
- **Harness-switch bundles** are reported in a sub-row for **every** system and never enter the headline.
- LCM-X stays out of the API-mode correlation until it has an API surface.

**API mode:** LCM-X once it has an API surface, at least three external memory systems, long-context-only, BM25 RAG, vector RAG and a grep agent.

**Adapter contract:**
- `reset`
- `ingest(event)`
- `query(task, now) → output + citations + confidence`
- `checkpoint` and `restore`
- `forget(selector)`
- `stats` (tokens and latency)

Bytes are measured externally (§7.6), never taken from `stats`. Vendors may supply their own adapter configuration within the configuration budget (§8), and every configuration is published.

### 6.10 Forks and the branch inventory *(pre-reg; PREREG §6)*
Every multiplier forks from a snapshot instead of replaying a life from the start. Every bundle score needs both twin items, so every scored branch exists for both the base life B0 and its twin life B1.

**Why the inventory is split** (first-principles review, `docs/REVIEW-SUMMARY.md`).
- **Cost.** v1.2 ran every multiplier on every board: three faults with three reruns, four Keep caps, a swap comparator and a second agent family. That came to about 320 whole-life replay-equivalents per system, 6-9× over its own ceiling in the mid band, and about 171 machine-days per board.
- **The split.** The board now measures the operating path once per life. The multipliers move to a seasonal robustness study.

**The full core board:**

| Branch | Built from | Replayed | Probed |
|---|---|---|---|
| **B0**, the base life, including one scripted fault and the mid-life swap | start | the whole life | all bundles at the 4 checkpoints |
| **B1**, the twin life, with the same fault and swap | a fork of B0 at the first flipped event | the suffix | all bundles at the 4 checkpoints |
| **Keep subset** (L_keep = max(6, ⌈L/4⌉) lives) at the 10% cap | B0 at the cap from the start; B1 forked from that capped B0 | B0 in full; B1 the suffix | all bundles (the budgeted row) |

**The seasonal robustness study,** on the season's first 8 board lives, for every board system:

| Branch | Built from | Replayed | Probed |
|---|---|---|---|
| **Fault cells:** n_f = 3 role-relative faults per life, k = 3 jittered reruns | forks of B0 and of B1 at the fault point | to the next checkpoint | the bundles probed there |
| **Keep curve:** the 30% and 3% caps, on the first min(L_rob, L_keep) lives, which also carry the board's 10% cap | B0 at that cap from the start; B1 forked from that tier's capped B0 | B0 in full; B1 the suffix | Keep bundles |
| **"B throughout"** swap comparator | its own B0 and B1, with B-voiced history | in full | Wake swap bundles |
| **Family B** | B0 and B1 under agent family B; the same branches as the swap comparator when model B is from family B | in full | all bundles |
| **A/A′ reruns** | a 10% subset of the ordinary family-A probe sets on B0 and B1, each run once more | — | — |

- **The forked twin is kept.** The fork gives both items of a bundle identical inputs at probe time, so a policy that ignores history passes both only by luck. Twins inside one life would make this hold only on average over random assignments. They also cannot twin a single fact, such as the user's own corrected preference. Within-life twins are deferred to a later version, after a controls-only comparison on public lives.
- **The board's fault** is placed at a fixed scripted turn boundary, the same for every system. Role-relative faults, such as a kill during a system's own summariser call, would leave a system without that role fault-free, so they belong to the study.
- **The 100% tier** is the base life itself.
- **Harness-switch bundles** are ordinary bundles after a switch event, on B0 and B1. They are reported in a sub-row for every system and need no extra branch.
- **Subsets** are the first lives in published seed order, fixed before any run.
- **Not run**, each disclosed:
  - faults on Keep-tier, swap or family-B branches;
  - Keep tiers on swap or family-B branches.

§13 turns this inventory into cost formulas.

## 7. Scoring

### 7.1 Action outcomes
Action items are classed from **behaviour**: the full action trace and the world state it leaves, never text hedges. The exact evaluation order is in §7.1a and PREREG §3.

| Outcome | Score *(pre-reg)* |
|---|---|
| correct: the state reached is in the admissible set, with no harmful **or benign** extra action | +1 |
| correct, but with a benign duplicate or extra (such as a second reminder) | 0 |
| omission, abstention, a question to the user, partial completion, or a task failure unrelated to memory (FAIL_TASK) | 0 |
| **wrong: a state change driven by a false, stale or planted memory, or a harmful extra action** | **−1** |

**How the rubric treats retrieval.**
- **Mechanism-neutral.** A correct action scores +1 whether the memory came from automatic context injection, a memory tool call, or a re-read of a source of record. Retrieval and checking are reported as cost and latency, not as score.
- **The ask channel** is closed-set. Every question to the simulated user about past statements gets the same fixed reply, which reveals nothing (not even that something was said before).
  - Asking always earns 0, whatever the gold. It never counts as refraining.
  - Every exchange is logged and audited.
- **Sensitivity rows.** Always published beside the headline: the −1 outcomes rescored at 0 (plain accuracy) and at −2.

Track and headline scores are reported as percentages from −100 to 100.

### 7.1a Decision tables
Each template has one decision table *(pre-reg, per template)*. It is evaluated over the whole action trace in three steps:
1. **Disqualifier.** Any wrong state change driven by a false, stale or planted memory, or any harmful extra action, scores −1, and scoring stops.
   - This includes Tuesday false alarms and Tuesday wrong actions.
   - Flagging a conflict does not redeem it: cancelling a booking "while noting the doubt" is still a cancellation.
2. **Base score.** Otherwise, the first matching case sets it:
   - a question to the user, with no other state change → 0;
   - a correct rejection → +1. This covers refraining when the gold is to refrain, rejecting a false premise, and answering "never observed" when that is the gold;
   - the admissible state is reached → +1. For Tuesday, the timing score of the first execution (§7.3) is used instead;
   - omission or unresolved abstention → 0;
   - any other trace, such as partial completion or FAIL_TASK → 0.
3. **Benign-extra cap.** If the trace contains any benign duplicate or extra action, the score is min(base, 0).
   - A correct reminder sent twice scores exactly 0.
   - An early Tuesday execution followed by a duplicate stays at −0.25.
   - Each template's table lists which extras are harmful and which are benign.

Partial completion earns no headline credit in v1; it is reported as a diagnostic.

**Check verdicts.** A check returns one base verdict plus a benign-extra flag:
- The base verdicts are PASS, FAIL_MEMORY, FAIL_TASK, OMISSION and HARMFUL_EXTRA.
- FAIL_MEMORY and HARMFUL_EXTRA take precedence over FAIL_TASK.
- A FAIL_TASK never becomes a confident false memory.

### 7.1b Validating the checks
Every hidden check is tested in both directions before freezing:
- It must **accept** at least 5 correct solutions written by agents from at least 2 model families.
- It must **reject** semantic memory-error mutants: the stale value, the planted value, and the twin's value.

The false-reject and false-accept rates must each be ≤ 2% *(pre-reg)* on the validation pool. The difficulty target is stated relative to **oracle evidence**, because check errors alone cap what a perfect system can score.

### 7.2 QA outcomes and calibration
QA and diagnostic items return a typed answer envelope with a stated confidence. Below the threshold of 0.5 *(pre-reg)* an answer is "hedged".

| Outcome | Score *(pre-reg)* |
|---|---|
| correct, asserted | +1 |
| correct, hedged | +0.5 |
| abstention (UNKNOWN when the gold is known) | 0 |
| wrong, hedged | −0.5 |
| wrong, asserted; or a missing or unparseable envelope | −1 |

Hedging is weakly dominated: it pays half of asserting, so an agent should assert when it believes p > 0.5 and abstain otherwise. "UNKNOWN" when the gold is "never observed" is correct (+1).

Stated confidence also gives the Brier score and ECE (10 equal-width bins). For action items, assertion precision is reported: the share of actions taken that were correct. Selective accuracy at the observed coverage is given for every track.

### 7.3 Timing (Tuesday)
The **first execution** of the committed action decides the class:

| Outcome | Score *(pre-reg)* |
|---|---|
| on time, at an opportunity inside the window | +1 |
| late | +1, decaying linearly to 0 over the late horizon (2 × the window) |
| early, at an opportunity before the window | −0.25 |
| never | 0 |
| a false alarm on a lure or decoy (acting on a cancelled or never-made commitment) | −1 |
| the wrong action | −1 |

Lure twins make the bundle score the minimum of the trigger and lure items. "Fire on every cue" therefore scores −1, and "recite every commitment at every turn" earns nothing, because reciting is not executing.

### 7.3a Stage attribution
For every failed item, the ledger and the clone snapshots record which stage failed:
1. **Stored:** the evidence reached the store, checked by a schema-blind span search of our own snapshot copy.
2. **Survived:** it was still present at the probe point.
3. **Retrieved:** it was in the request context at action time.
4. **Used:** the action reflected it.

Failures are reported by stage per track: write, maintain, retrieve or use.
- **Who gets which stages.** Every system whose store can be inspected gets the same span search, LCM-X included. Others get the retrieval and use stages only, from the ledger.
- **What the search is for.** It measures; it is never used to design items.
- **Stated vs actual.** Where a diagnostic asks the agent what it would do, the share of stated choices that match its actual tool calls is reported.

### 7.4 Operating metrics (every tier)
- retrieval latency, p50 and p95, per memory operation;
- store growth over the life, in bytes per session and in total, measured externally (§7.6);
- time-to-correct after a supersession;
- ingest real-time factor on the reference machine;
- tokens and dollars per run, split into ingest, write turns, consolidation, extraction, probes, rendering and judging, and counted by role;
- wall time.

### 7.5 Answer types, judges and audits
Answer types are all deterministic:
- an entity id;
- a date or time, with a per-template tolerance;
- a number;
- a set (exact and F1);
- an ordered list (exact and Kendall tau);
- a verbatim span, normalised and exact;
- a citation (event id, or a timestamp within tolerance plus a quote match);
- a boolean;
- UNKNOWN;
- a correction of a false premise;
- an environment state or action trace.

**Judges.** An LLM judge is used only for the free-text remainder, expected to be under 15% of items.
- Every judged comparison runs under two pinned judges from different families, neither used by any tested agent.
- Rankings are reported under both, because in prior work the judge choice alone reversed a ranking.
- Each judgement runs three trials with a majority vote and an A/A′ placebo.
- A shipped validation suite of planted wrong-but-topical answers sets a published false-accept bound.

**Gold error has a budget:**
Gold error is controlled in two stages *(pre-reg)*.

**Stage A, the template census.** Every template version is audited, so template-level error is inspected directly, not estimated by sampling.
- Two annotators, Cohen's kappa, and a global contradiction search.
- Seeded known-bad items, with annotator recall of at least 90% on them.
- The census passes only with zero unresolved template-level errors.

**Stage B, the instance audit.** It estimates the remaining, instance-level gold error from a sample, in confirm-or-dispute format.

| Audit | Bundles per track | Max per template version | Gate on the upper bound |
|---|---|---|---|
| pilot | 75 | 3 | ≤ 10% |
| release | 200 | 5 | ≤ 5% |

- **Pools:** the pilot audit draws from the final scored distribution of the bundles generated for the calibration set and the bar-2 seeds, probed or not. The release audit draws from the full tier's, audited outside the LCM-X lanes.
- **Minimum template versions:** at least 25 per track for the pilot and 40 for release (PREREG §5).

- **Sampling:** stratified random by template version, with a fixed seed. The sample is drawn before anyone inspects it and never topped up.
- **Inference.** The interval accounts for clustering within template versions.
  - It is a two-sided 95% Wilson interval with p̂ = errors / n, at the effective size n_eff = n / (1 + (m̄ − 1)ρ).
  - m̄ is the mean number of bundles per sampled template version.
  - ρ = max(0.1, ρ̂), where ρ̂ is the observed between-version intraclass correlation of errors (ANOVA estimator). A template bug that slips past the census therefore shrinks n_eff.
  - The computed bound is the only gate. For orientation only: with ρ at its floor, the pilot passes with at most 1 error and the release with at most 2. Errors concentrated in one version raise ρ̂ and can fail the gate with fewer.
- **Also reported:** the fully conservative cluster-level bound, which treats each sampled template version as one observation.
- **Unmet gates.** If the rule cannot establish a gate's bound, for example because a track has too few template versions, the gate is reported as unmet. It is never waived.
- **Human key:** the release audit is human-graded, and it also validates the judges.
- **Outside audit:** private templates are audited outside the LCM-X lanes, and retired seasons are published for outside audit.

### 7.6 Keep: budgets that bind, and forgetting that is observed
**Storage.**
- Bytes are measured **externally**, by size on disk of every surface a system can recover memory from: its store, notes and instruction files, repository additions it made, and harness directories. They are counted above the system's own empty-store baseline, measured before any ingest.
- The budget tiers are 100%, 30%, 10% and 3% of the raw stream's bytes *(pre-reg)*.
  - Each tier binds for every system: a system above a tier's cap scores 0 on that tier's bundles.
  - A system that cannot cap its storage is placed on the curve at its natural size, and scores 0 at every tier below it.
- **On the board,** Keep's track score is ¼·T100 + ¾·T10 on the Keep subset (§6.10) *(pre-reg)*.
  - It equals the old four-tier mean for a system above every reduced cap (T100/4) and for one with the same score at every tier. A system whose natural size falls between two caps can score differently. For example, one at 8% of the raw bytes scores 1 here against .75 for the four-tier mean. This is disclosed.
  - The bar-2 run uses the same score on its 4-life Keep subset.
  - The four-tier mean comes from the seasonal robustness study.

**The budgeted headline row** *(pre-reg)* is published beside the headline, on its own life set, the Keep subset:
- **Branches:** every included track is scored on the 10%-cap branches, and Keep uses its 10%-tier score.
- **Caps,** applied after the run, so nothing is truncated:
  - an item whose probe request exceeded 64K input tokens (measured from the ledger) scores 0 in this row;
  - a system with a p95 above 2 s per memory operation is shown as over-cap and scores 0 for the row.

  The row uses the common-valid-set rule (PREREG §2).
- **Per-life contributions:** c_l^budget = Σ_t (1/n_T)(T^{10%}_{a,t,l} − T^{10%}_{b,t,l}).
- **Statistics:** an exact sign-flip test and a wild cluster bootstrap CI over the subset's lives.
- **Status:** reported, never confirmatory. Its life set differs from the headline's, and that is disclosed.

**Forgetting.**
- **The bundle.** A forget bundle is a trigger twin (§5.1a):
  - in B0 the forget request was made, and using the item is wrong;
  - in B1 no request was made, and using the item is correct.

  The bundle scores the minimum of the two. A system that never stored the item fails the B1 item and cannot pass by not remembering.
- **Neighbour retention** is its own Keep bundle, reported beside forget compliance: forgetting an address must not lose the street's other facts.
- **Order of checks.** Behavioural probes come first. A second check is a schema-blind span search over every inspectable store, LCM-X's included.
- **The claim** is "no recoverable copy found by behavioural probes or span search", never proof of deletion.

## 8. Baselines and controls
These are run in the pilot and in every published table, per track:

| Control | Purpose |
|---|---|
| **No-memory floor:** same harness, memory disabled | if it scores near the top systems on a track, the track is broken; redesign it |
| **Environment-search agent:** no memory, the same tools, allowed historical surfaces only | how much of a score the world's own records give away |
| **Recent window:** only the last N tokens | how much of the score needs long-range memory |
| **Token-matched window** | memory gain at equal context cost |
| **Oracle ceiling:** full history in context, where it fits | bounds what retrieval can add |
| **Oracle evidence:** only the gold evidence | upper bound on reading; the memory gap is oracle evidence minus the system |
| **Leave-evidence-out:** full history minus the gold evidence | detects leakage around the evidence |
| **Naive RAG** (chunk and embed), **BM25**, **grep agent**, **transcript grep** | simple retrieval floors |
| **Simple-policy battery** (§5.3) | exploit and shortcut floors; each must score ≤ 0 |
| **Known-order ablations:**<br>(a) oracle evidence vs oracle evidence minus one **necessary** evidence event;<br>(b) the oracle ceiling (full history) vs leave-evidence-out.<br>An event counts as necessary only if the reachability audit shows the gold has no alternative evidence path without it. Both contrasts and their expected directions are validated on a controls-only calibration slice under the fixed reader, and frozen in PREREG-v0 before any real-system run. | proves the instrument orders known differences, without LCM-X |
| **Retrieval depth (exploratory):** naive RAG top-2 vs top-20 | reported only. Deeper retrieval can rightly lose to interference, so no direction is required |
| **Competitors:** Hermes' native memory, plus at least 2 external self-hosted systems in the pilot and at least 3 in Phase 1 | the comparison that matters |
| **LCM-X at its last release before the public generator** | shows whether LCM-X's later gains came from tuning to the public lives |

**Where controls run** (first-principles review, D-09):
- **What they depend on.** A control's output depends on the lives, the probe-model pin and the harness pin, never on the system under test. So every LLM-using control and filter is computed **once per (lives, probe pin, harness pin)**, cited in every table that season, and re-run on any pin change.
- **The no-memory floor** runs its probes through the same harness with every memory surface off, the harness's native memory included. Only the environment state is built offline. Where API-mode rows are reported, no-memory runs in both modes, so cells stay matched (§6.1).
- **Every published table** shows no-memory, the oracle ceiling and naive RAG (addendum §E).
- **Moved to a seasonal exploratory row:** the token-matched window, transcript grep, and naive RAG top-2 vs top-20.
- **LCM-X at its last release before the public generator** runs on every board. Its version never changes, and it is the tuning detector.

**Selecting competitors** *(pre-reg)*:
- **Who qualifies:** open-source and self-hostable, with either a Hermes memory-provider plug-in or a documented ingest and query API.
- **Ranking:** a public adoption metric fixed at the freeze date.
- **Configuration budget:** each competitor gets an equal, logged budget of configuration trials on public developer seed packs, the same budget LCM-X gets.
- **Vendor configurations:** vendors may submit theirs. Inviting vendors is an owner decision.

Headline tables show:
- the raw score;
- the memory gain over the best control;
- a normalised score from the no-memory floor (0) to oracle evidence (100).

## 9. Tiers: two ladders
The brief asks for a smoke tier that takes minutes, a dev tier that takes about an hour, and a powered full tier. v1.2 had drifted to a 12 h smoke study and a 36 h dev tier, because the one-off validation runs for pilot bars 1 and 2 had taken the slots meant for developers. The first-principles review splits them into two ladders (PREREG §6 is normative).

### 9.1 Developer tiers (no decision bar)
These are for anyone building agent memory, including vendors and testers, on every change. Their targets are engineering budgets, not bars. Every result is labelled "not predictive of the full tier" until §9.3's check has been measured.

| Tier | What runs | Target | Use |
|---|---|---|---|
| **T0 probe packs** | micro-lives of 1-3 sessions per track and ability, scored by a scripted reader, with no model | ≤ 60 s, $0 | unit and regression tests in a developer's own CI |
| **T1 CI smoke** | 2 public lives × 20 sessions through the real adapter with a scripted model; the regression corpus; fault-lite cells; a wiped-store positive control that must fail | ≤ 10 min, $0; deterministic on stable result fields | merge gate |
| **T2 live smoke** | about 10 public lives × 8-10 sessions with live probes; the candidate arm against cached controls | ≤ 1 h per arm, $0 on subscription lanes | large effects only |
| **T3 dev** | public 20-session lives with a bundle budget chosen before the run, in a fixed stratified order so any prefix is balanced; paired against the developer's own cached previous run | about 1 h per arm; an optional overnight dev+ ≤ 8 h | a paired development delta, with its MDE and an A/A′ band |
| **Fault finder** | a search over levers and scripted fault points, then shrinking | ≤ 15 min of search + ≤ 15 min of shrinking, $0 scripted by default | a minimal failing public life and its repro bundle |

**Probe packs.**
- They are behavioural tests per track: minimum-functionality, invariance and directional, in the style of CheckList.
- Each is an instance of a full-tier template at a chosen lever value, with the same scoring contract.
- A failure at a low lever value predicts a failure on the full tier. A pass only places the system at a point on the lever curve.
- The directional tests check that the levers behave monotonically.

**The fault finder.**
- **Search:** over the generator's levers and fault points on public seeds, scripted by default.
- **Shrinking:** delta debugging over the world DB's event schedule, not over the text, down to a failing life that is "1-minimal under the deletions tested", never claimed globally minimal. The shrink oracle checks for the same failure. A flaky failure is reported with its reproduction frequency.
- **What survives:** each result is a public life with a repro bundle, which joins the regression corpus run in T1.
- **The public regression corpus** is stocked from controls, reference stubs and equal runs over every board system, never from one system's failures.
- **The firewall:** the benchmark session never runs the finder on LCM-X. Vendors run it on their own systems.

**Fault injection lite.** A small schedule syntax (restart, compaction, kill or model swap at a chosen point in a short life), deterministic with one rerun. An optional "race hunt" mode jitters timing.

**What a developer gets back:**
- stage attribution per failed item (stored, survived, retrieved, used; §7.3a);
- a per-item trace page with the twin item shown side by side;
- `bicentennial repro <bundle>`, which restores the checkpoint snapshot and re-runs the probe;
- a failure taxonomy card;
- a diff against their own previous version, with an MDE and an A/A′ band;
- operating-metric deltas (§7.4).

No result ever carries advice on any system's internals.

**Accelerators:**
- **A small window, not a long horizon.** Compaction pressure is history over the context window. A short life at a reduced window forces many compactions in minutes. Each tier's window is frozen in v0 from the harness overhead S6a measures, and it is never chosen from any system's results.
- **Shipped seed packs.** Renders, filter results, oracle results and control arms are computed once per pack.
- **A diff against your own cached previous run,** so a developer run needs one arm.
- **Scripted-reader modes,** which catch most storage, survival and retrieval bugs with no model calls.

**The throughput risk is probes, not replay.** Serial clone placement allows about 30-60 bundles an hour; parallel per-worker sandbox roots would allow about 120-240. S3 tests them. If they fail, T2 and T3 cannot meet their targets with live probes on this machine, and that is disclosed. T0 and T1 are unaffected.

### 9.2 The measurement ladder
| Run | Lives | Sessions per life | Content | Cadence |
|---|---|---|---|---|
| **calibration set** | 4 public, full length | ~200 | controls only: difficulty scalars, inclusion condition 1 and the validation of the known-order ablations. Inclusion condition 2 needs a p-value, so it runs on the bar-2 run's 16 control lives | once per generator version |
| **bar-1 run**, the smoke tier's separation run of record | 12 fresh public | 10, dense, at the frozen bar-1 window | ~25 action bundles per life, all unfiltered; LCM-X, no-memory, oracle evidence, naive RAG, and the oracle ceiling where the history fits | once per generator version |
| **bar-2 run**, the dev tier's separation run of record | 16 fresh public | 20 | 30-40 bundles per life; the full pilot roster and controls; Keep at 100% and 10% on a 4-life subset | once per generator version |
| **full core board** | L private (§12) | ~200 | b bundles per life [pilot; PREREG §10 rule], ≥ 60% action; the board inventory (§6.10) | once per season, plus delta boards |
| **seasonal robustness study** | the season's first 8 board lives | ~200 | the study inventory (§6.10) | once per season and at each major release |
| **frontier** | rotating | 200+ | replay, live and streams; the ≥ 10M-token horizon | research; curves |

- **Fresh seeds.** The runs of record use seeds that were never in a developer pack, because bar 1 runs on the harness LCM-X's lanes iterate on.
- **Dense full-tier lives.** About 2M tokens over about 200 sessions, with at least 20% long sprints that exceed the context window, so summary-of-a-summary chains and the addendum's long sprints survive. Filler chat is shortened, never tool output. The window is the pinned model's harness default, frozen by name. S6 compares 2M with 5M on the same seed.
- **Delta boards** run only for a new GA of a board system: at most 2 per system per season, in order, with the previous version re-run alongside.
  - A change of harness pin or model alias forces a fresh board. LCM-X ships as a Hermes plug-in, so a newer Hermes pin invalidates every cached result.
  - Every scheduled run is published in order, and the board shows each system's latest version, never its best.
  - Sealed runs never serve as a phase of a release gauntlet.

### 9.3 Dev predicting full
In v1, dev bundles are stratified random. IRT selection can come later, once enough systems exist to fit it.

**The rule.** A claim that dev predicts full needs **both**:
- Kendall τ-b ≥ 0.7 over at least 5 systems, with ties declared from the full-tier CIs *(pre-reg)*. With 5 systems, τ ≥ 0.7 allows at most one swapped pair, and random rankings reach it about 4% of the time.
- No pair that separates on the full tier may be reversed on dev.

**The chain** micro → dev at session 20 → full at session 20 → full at session 200 is measured, together with sign agreement on version diffs. None of it can be computed before Phase 1.

## 10. Splits, seeds and governance
- **Public:** the generator, harness, adapters, item templates for public genres, and dev and smoke seeds. Anyone can generate and tune on these.
- **Semi-private:** seeds and a template subset for hosted services and vendor self-runs. These rotate every season.
- **Private (held out):** full-tier seeds, a private template subset, and private persona and style sheets, drawn from a deliberately shifted distribution.
  - Only the seed hashes are published, in advance.
  - A sealed runner holds the seeds and returns only track-level scores.
  - Per-item results on private lives are never released.
- **The seal** (required before any full-tier run; the pilot uses public seeds only):
  - Private seeds derive from a secret held off the benchmark machine.
  - Private templates, renders and runs exist only inside an encrypted image with its own agent configuration directories. Nothing private enters the shared agent transcripts or auto-memory on the machine.
  - Canary strings are planted in all private material. Before every release, leak greps run over the LCM-X repository, its lanes' transcripts and the machine's shared agent transcripts.
  - A separate OS account or an off-machine runner is preferred. That is an owner decision.
- **Regeneration:** every season (proposed: twice a year), a third of the private lives are replaced, filters are re-run, and the season's results are versioned.
- **Written policy:**
  - no sponsor access to private lives;
  - submission limits;
  - disclosed variant counts;
  - coarsened feedback on private runs;
  - canary strings in every public file.

## 11. Frontier tier and the path to androids
- **Phase 2: pixels.** Screenshots and images rendered from world state: dashboards, terminals, whiteboards, receipts. Some facts then exist only in pixels, and cross-modal items join each track.
- **Phase 3: Hands in simulation first.**
  - **The world:** procedurally generated homes and workspaces where residents follow schedules. They move objects, interrupt, and leave and return, over simulated weeks to months.
  - **Streams and gold:** camera, audio, pose and event logs. Ground truth is the simulator's own state log.
  - **The simulator** is chosen in the Phase 3 design from the survey's candidates (Habitat, AI2-THOR/ProcTHOR, BEHAVIOR, Isaac, ManiSkill, Genesis), with no commitment now.
  - **What streams add:** real-time answering windows (TeleEgo-style), memory persistence over days, and accuracy against bytes stored per simulated day.
- **Physical path, design only:** a small Hands subset on a low-cost desk arm (SO-100 class, via LeRobot) with a fixed tabletop scene. Objects are moved between sessions, and the arm must later retrieve or report them. No hardware is bought without the owner.
- **Frontier extensions:** multi-agent shared memory with grants and revocations mid-life; adversarial writers; on-device budgets; live segments that re-plan the rest of a life.

## 12. Statistics and pre-registration
All frozen statistical quantities are in PREREG §2 and §7. This section explains them.

**The estimand.**
- **Headline:** H_s is the equal-weighted mean of the track scores T_{s,t} over the n_T included tracks.
- **Track score:** T_{s,t} is the mean, over the lives 𝓛_t where track t is measured, of each life's mean twin-min bundle score.
  - It covers the track's final scored distribution: memory-exclusive action bundles, five-class, in [−1, 1].
  - 𝓛_t is every life of the run, except Keep's. Keep's is the run's Keep subset: the board's L_keep lives, or the bar-2 run's four. There Keep scores ¼·T100 + ¾·T10. The c_l reweighting below covers it, and bar 2's sign rule counts every life's c_l. Bar 1 scores Keep at 100% on every life.
- **Per-life contributions** for a pair (a, b):
  c_l = Σ_t (1/n_T) × (|𝓛| / |𝓛_t^{ab}|) × 1[l ∈ 𝓛_t^{ab}] × (T_{a,t,l} − T_{b,t,l}).
  - Both systems' track scores are computed on the bundles valid for both, and 𝓛_t^{ab} is the set of lives with at least one such bundle.
  - The mean of c_l equals the pair's headline difference on that common set.
- **Keep's precision.** Keep enters at the same weight as every other track, from fewer lives. That puts a floor under the variance of the headline difference, which is why L_keep grows with L (§6.10) and is disclosed.

**The primary test.**
- **Test:** a two-sided sign-flip permutation test on the c_l (exact when L ≤ 20, otherwise 100,000 draws with a fixed seed), at α = .05.
- **CI:** a wild cluster bootstrap over lives (Rademacher weights, 10,000 resamples).
- **McNemar** is descriptive only.

**The confirmatory family on the board** *(pre-reg)*:
- **Membership:** each current real system against one pre-named neutral reference, Hermes native memory, under agent family A. LCM-X at its last release before the public generator is **not** in the family; it is a secondary contrast. With the minimum Phase 1 roster (LCM-X, Hermes native and 3 external systems), m = 4.
  - All pairs would cost lives without giving a cleaner claim: going from m = 10 to m = 4 saves about 16% of the lives where the 24-48 clamp does not bind.
  - A fixed testing sequence would put the closest pair, LCM-X against its previous GA, first. That pair usually fails, and it would block the rest.
- **Correction:** Holm, with no fixed sequence and no sequential stopping. With shared lives the board waits for its slowest contrast, so the expected saving is small, and estimates from stopping early are biased upward.
- **Declared secondary contrasts,** each reported with its achieved MDE:
  - LCM-X vs LCM-X at its last release before the public generator, on every board (the tuning detector);
  - LCM-X vs its previous GA, on delta boards.
- **Every other pair** is exploratory, with a CI. Tracks are tested only for family contrasts whose headline separates (gatekeeping), with Holm within the contrast.
- **The bar-2 family** is the pairs excluding both LCM-X releases, m = 3. Under all-pairs Holm, a neutral pair's threshold loosened as LCM-X pairs rejected, which tied the neutral check to LCM-X's data.
- **Controls:** comparisons with controls are reported, not confirmatory. The exceptions are bar 1, its companion, and the inclusion and ablation tests.
- **Attainability:** exact two-sided sign-flip floors are 2/2^L: .0005 at L = 12, .002 at L = 10, and .00003 at L = 16.

**Power and life count.**
- **Units:** headline percentage points.
- **σ_d [pilot]:** the median, over the bar-2 family's pairs, of the SD of their c_l on the bar-2 run.
- **The rule:** L = clamp(⌈((z_{1−α/(2m)} + z_{0.8}) × σ_d / 8)²⌉, 24, 48), with m frozen in PREREG-v1.
  - It sizes the first, Bonferroni-strict Holm step for 80% power at 8 points.
  - It is a resource rule built on a normal approximation. Bar-2 lives are shorter than full lives, so σ_d may not transfer; the gap is disclosed.
  - **More bundles per life** lower only the sampling-noise part of σ_d. The variance between lives is bought with lives. Bundles per life are therefore a [pilot] value. PREREG §10 freezes the rule in v0: the smallest value in {100, …, 300} at which sampling noise is at most one third of the per-life variance, estimated from non-LCM-X pairs.
- **Always disclosed:** the achieved Holm-adjusted MDE, simulated on the full-tier c_l.
- **For scale:** the reviewers' estimate for 24 lives is an MDE of 8-13 points.

**Family B** is a replication row (H^rep) from the seasonal robustness study: the study's 8 lives, the included tracks, and Keep at 100% only, for both families. It is never pooled, and a sign reversal against the matched family-A difference flags the pair (§6.2c).

**Reruns** belong to the seasonal robustness study. Every fault cell there runs k = 3 times with jittered timing, and a 10% subset of the study's probes runs twice to give the A/A′ variance.

**Calibrating "hard for everyone"** *(pre-reg)*:
- **The shape** of the lever mix (which levers, in what proportions) is frozen in PREREG-v0.
- **The scalars.** The pilot sets one difficulty scalar per track, on **system-agnostic anchors** only: oracle evidence at least 75, and the best of naive RAG, BM25, grep and recent window at most 35. They are set from controls on the full-length calibration set and validated on controls over the bar-2 lives, so they are set at the full tier's scale.
- **No real system's score** enters calibration, both LCM-X releases included.
- **The launch target,** best system below about 60, is measured and reported. The test is not tuned toward it.

### 12a. Failures and missing data *(pre-reg)*
Every assigned bundle ends in exactly one class:

| Class | Treatment |
|---|---|
| scored | as scored |
| **FAIL_TASK** | 0 |
| **SYSTEM_FAILURE**: the system under test crashed, timed out or refused | 0 |
| **INFRA_FAILURE**: the director, runner or sandbox failed, or a precondition voided the item | rerun at most twice; if it still fails, excluded for every system in that comparison |
| **N/A_EXPOSURE** (§6.4) | excluded for that system; cross-harness pairs use the common-exposure set |
| **N/A_CLOCK** (§6.6): a skew-audit failure or a wall-compressed row | excluded from time-dependent bundles for that system; pairs use the common set |

**Coverage.**
- Denominators are the assigned bundles.
- The card reports completion and eligibility per system, plus a **worst-case row** in which every system and infrastructure failure scores −1.
- A headline rank is valid only with at least 95% coverage and no more than 5% infrastructure exclusions.

**Pre-registration.** PREREG-v0, then PREREG-v1, is the normative record. Both freezes are committed with a timestamp, and each hash is posted on #1964. Later changes are versioned and disclosed (§14).

## 13. Cost model (formulas; spike S6 measures the inputs)
The formula, constants, ceilings and cut order are frozen in PREREG §11.

**Terms.** Per system and agent family, every cost term is a triple: requests, tokens and wall time. Each is counted by role: write turns, the system's own compaction and extraction, probes, and judging.

| Term | Meaning |
|---|---|
| R | replay cost of one whole life |
| R_cap | replay cost of one whole life under a cap; the projection uses max(measured R_cap, R) |
| f | share of a life after the first flipped event (≤ 1) |
| P | probe cost of all bundles at the 4 checkpoints on one branch, including resume-only controls |
| r_c, p_c | replay from fault c to the next checkpoint, and the probes there, on one branch |
| P_K | probe cost of Keep bundles only, on one branch |
| P_W | probe cost of Wake swap bundles only, on one branch |
| R_B, P_B | family-B replay and probe costs |

From the inventory in §6.10, the costs per system are (PREREG §11 is normative):

  Cost_board = L × [ R(1 + f) + 2P ] + L_keep × [ R_cap(1 + f) + 2P ]

  Cost_rob = L_rob × [ Σ_{c=1..3} 2k(r_c + p_c) + R_B(1 + f) + 2P_B + δ_W(R(1 + f) + 2P_W) + 0.2P ] + L_curve × 2(R_cap(1 + f) + 2P_K)

- R includes the board's inline fault and the swap. L_rob = 8 (4 after the cut), k = 3, L_curve = min(L_rob, L_keep), and δ_W = 0 when model B is from family B.
- The runs of record (bar 1, bar 2) and the calibration set have formulas of their own in PREREG §11.

**Projection, mid band** (estimates from the first-principles review's assumption bands; S6a and S6 replace them):

| | v1.2 | Now |
|---|---|---|
| Per system on the board | about 4,600-6,700 sequential h | about 360-430 sequential h: ≤ 24 h at about 16-20 concurrent jobs, with about 5 assistant turns per scripted session so each life's write-turn chain stays near 3 h |
| First board of a season, 5 real systems plus controls | about 171 machine-days | about 19 machine-days at 8 jobs |
| A delta board, with the previous version re-run alongside | — | about 3-4 machine-days |
| An extraction competitor on its vendor's models, per board | about $2-5K | about $0.1-0.3K |

**After these cuts probes dominate,** at about 2/3 of a system's hours. Further cuts therefore come from the probe side: bundles per life and cost per episode.

**Spikes:**
- **S6a** replays one 10-session micro-life on Hermes native, in hours. It measures replay time, write-turn and summariser calls, probe latency, lane concurrency, the harness overhead behind the developer windows, and whether parallel sandbox roots work.
- **S6** replays one full-scale life (about 200 sessions) on Hermes native and on one extraction competitor, once uncapped and once at the 10% cap. It runs the dense ~2M-token life and the same seed at ~5M for comparison, and measures every term by role.
- **Family-B terms** are measured on one life, or taken as family A's costs × the price ratio.

**Ceilings and cuts** are in PREREG §11:
- the board and the robustness study: **≤ 24 h wall clock** (the 24-hour rule), ≤ $300, ≤ 3B input and ≤ 100M output per system each;
- the bar-1 run: ≤ 8 h for all arms;
- the bar-2 run: ≤ 8 h per real system;
- the calibration set: ≤ 24 h.

**Go / no-go** is pilot bar 5, evaluated at the end of S6 with L = 48 for the board and re-checked once L is known. The cuts apply in this order:
1. bundles per board life, down to 100;
2. the robustness study, down to 4 lives;
3. lives, down to 24.

If the projection still does not fit, the design returns to the owner.

**Generation** is a separate row: rendering cost per life × lives per season, run in a batch window off the build lanes.

**Machine envelope.**
- The ledger is content-addressed and zstd-compressed.
- Runs refuse to start below 150 GB of free disk.
- Heavy work gates on the gauntlet's timed-row marker, not on load average.
- CPU-bound jobs and model-wait jobs are counted separately.
- A failed session resumes from its last snapshot.

**Lanes.**
- Readers, summarisers and renderers run on subscription lanes first.
- Paid rows are labelled and capped: the third blind-panel family, extraction competitors' vendor models, and agent family B.
- Every run reports its spend.

## 14. Firewall and credibility
- **Separation.** This benchmark's design, data and runs are separate from LCM-X development. The benchmark session does not tune, patch or advise on LCM-X internals.
- **No shared code.** Bicentennial copies no LCM-X code. Instruments LCM-X built for its own testing are cited as prior art and reimplemented from specs.
- **Equal terms.** Every system, LCM-X included, is driven only through its public surfaces and documented configuration, pinned to a released artifact, within the same configuration budget.
- **Private data stays private.** LCM-X developers and lanes never see private seeds, private templates or per-item private results (§10).
- **Freeze before data.**
  - PREREG-v0 is frozen and hashed before the first real-system pilot run. It includes the code that computes every [pilot] value and the write-turn package.
  - PREREG-v1 is frozen before **any** system's first full-tier run.
- **Blinding.** Pilot analysis runs on blinded system codes until the [pilot] values are committed.
- **LCM-X never sets the test.**
  - Every [pilot] value is computed without either LCM-X release's data: lever scalars, track inclusion, life count and any later IRT selection.
  - Bar 1 has a neutral companion test (§15).
  - Calibration uses system-agnostic anchors only (§12).
  - If LCM-X alone fails bar 1, that is reported as a finding and never triggers a redesign keyed to LCM-X.
- **Approval and veto.** The benchmark session approves the design and each PREREG freeze, and the owner co-signs each freeze hash (§16).
  - An external reviewer with a veto over scoring is recruited before PREREG-v1, and the owner decides who. Until one exists, every adversarial review of this design must test for self-serving construction.
- **The reference agent.** Bicentennial never runs against the live reference agent. Any later test of it is an offline replay of a copy, with owner approval at that time.
- **Openness.** The harness, adapters and public lives are open. Competitors are run with their vendors' best documented configuration. Results are published where LCM-X loses.

## 15. Phase plan, done-when and exits

| Phase | Content | Done when |
|---|---|---|
| 0 (by about 2026-11-09) | survey, taxonomy, threat model, this design, three review rounds (Astra and an independent Opus red-team in round 1; targeted readbacks in rounds 2 and 3), a closure check, and the first-principles cost review | design v1.4 and PREREG-v0.1 approved; any overrun posted on #1964, with the cuts |
| Spikes | S1 role classification; S2 clocks; S3 clones, including parallel per-worker sandbox roots; S4 Claude Code against the director, which also names model B; S5 surfaces and entrypoints; **S6a one 10-session micro-life**; **S6 one full-scale life**, dense ~2M and the same seed at ~5M, uncapped and at 10%; **S7 write turns**, plus the passive-pacing check | S6a and S6 measurements in hand for bar 5; S7 shows agent-curated memory working in replay, with the write-turn boundary confirmed by readback |
| Pilot (timebox 3 weeks from approval, posted on #1964) | Developer tiers T0 and T1 first, then T2, T3 and the fault finder. The calibration set, then the bar-1 and bar-2 runs of record. G1 and G2, both evaluations. The roster: both LCM-X releases, Hermes native, ≥ 2 external self-hosted competitors, and every §8 control. Wake, Drift, Tuesday, Rachael and Keep; Flatten as a diagnostic | the bars below |
| Pre-registration | PREREG-v1 approved and committed | before any full-tier run |
| Phase 1 build (v0.30.0) | the full core board for G1 and G2 in text and code; the seasonal robustness study; the developer tiers shipped with the harness; director; Hermes and Claude Code adapters; ≥ 3 external competitors; family B; the seal | best system below ~60% headline at launch, measured and not tuned toward; Codex adapter next |
| Phase 2 / 3 | pixels; Hands in simulation | after measured use (per #1719) |

**Pilot acceptance bars** *(the normative text is PREREG §8; all required)*:
1. **Smoke separation**, addendum bar 1, kept as written, on the bar-1 run (§9.2), the smoke tier's separation run of record. Every bundle there skips filters 2 and 4. LCM-X separates from the no-memory floor: life-level sign-flip, p < .05, on the per-life equal-weighted mean over the five candidate tracks, with Keep at 100% (PREREG §8).
   - **Neutral companion:** on the same lives and sample, oracle evidence and naive RAG must each separate from the no-memory floor.
2. **Dev separation**, addendum bar 2, on the bar-2 run (§9.2), the dev tier's separation run of record, over 16 lives:
   - **A pair excluding LCM-X:** at least one pair in the bar-2 family separates on the headline (Holm over that family only, m = 3; the same sign in at least 80% of lives).
   - **Known-order ablations:** both come out in their validated direction (§8; p < .05 each). They are validated before the PREREG-v0 freeze, on the calibration set, and contrast (b) uses only bundles whose history fits the reader's window. A contrast that fails validation is dropped.
3. **Inclusion.** At least 3 candidate tracks pass the inclusion rule:
   - not near-solved, on the calibration set's unfiltered sample;
   - oracle evidence separates from no-memory, on the bar-2 run's control arms;
   - valid.

   These are computed from controls only, and a track that is hard for everyone stays in.
4. **Validity**, on every included track's final scored distribution:
   - every §5.3 gate holds: the battery, the minimum shares, the Drift mix and the salience gate;
   - the template census passes, and the pilot instance audit (75 per track, clustered bound) is at most 10%;
   - check error rates are each ≤ 2%;
   - verifier recall is ≥ 0.90 per class, with a Wilson lower bound ≥ 0.80.
5. **Cost.** The S6a and S6 projection fits every ceiling of the measurement ladder (§13). The developer-tier targets are not bars; any that are missed are disclosed.
6. **Correlation.** API mode vs system is measured per comparable cell, with no bar. Proxy status needs the §6.1 criterion.

**Labelling.** If no human grader pool exists by pilot time, the pilot is labelled a **feasibility pilot**, and it cannot claim the binding gate.

**When bars fail:**
- **Ordinary inclusion vs the failed-pilot fallback.** "A track that is hard for everyone stays in" governs ordinary inclusion. The addendum's exit rule is a separate fallback, which fires when the bar 1 companion or bar 2 fails. Bicentennial then narrows before Phase 1 is built:
  - **The candidate.** It keeps the tracks where oracle evidence separates from the no-memory floor and at least one pair excluding both LCM-X releases separates. They are written down as PREREG-v0-narrowed, computed without LCM-X.
  - **Fresh evaluation.** The selecting pilot cannot also prove the narrowed design. PREREG-v0-narrowed needs a fresh, frozen acceptance run of bars 1-5 on new public seeds that played no part in the selection.
- **Only bar 1's main test fails** (the companion passes): the instrument is valid, and LCM-X did not separate from no-memory. This is reported on #1964 and escalated to the owner. It never triggers a redesign keyed to LCM-X.
- **Bar 3, 4 or 5 fails:**
  - the fixes are the redesign path for invalid tracks (§5.3), the gate remedy, and the cost cut order;
  - each is followed by a fresh acceptance run of the affected bars on new public seeds;
  - a track that is not repaired is excluded and reported as a diagnostic.

**Build consequences.** The build plan lists the units that v1.2 added and the developer-ladder units of v1.3. Among them:
- write turns;
- forks;
- the route table;
- the tool-call compiler and preconditions;
- the battery and the unfiltered sample;
- the verifier suite and check validation;
- two judges;
- stage attribution;
- external byte measurement;
- family B;
- the seal;
- probe packs, the fault finder, the repro command and the developer report.

Pilot cut order if the timebox binds: the LLM renderer (template renders only), then the controls the addendum does not require.

## 16. Approval and channels
- **Ownership.** The benchmark session owns this design.
- **Approval.** The benchmark session approves the design and each PREREG freeze, under the owner's grant of 2026-10-26, which replaced the integration-owner approval in the original brief. The owner co-signs each freeze hash on #1964. PREREG-v0 was frozen on 2026-10-26; its completion record comes before the first real-system pilot run; PREREG-v1 comes before the full tier.
- **External veto.** An external reviewer with a veto over scoring is recruited before PREREG-v1, and the owner decides who. PREREG-v1 is not frozen without one unless the owner waives that in writing.
- **Channel.** #1964 is the status channel, not an approval point.

**Owner-private decisions:**
- the public repository (approved and created: `bicentennial`);
- a public leaderboard;
- external partners: the external reviewer, vendor configuration windows and the human grader pool;
- sealing infrastructure (§10);
- spend above the standing limits (§13 paid rows).

## 17. Open questions (for the spikes and the pilot)
1. **Hermes entrypoint:** can its documented production entrypoint be driven deterministically by the director, or does the pilot fall back to the CLI, with disclosure? (Spike S5.)
2. **Clocks:** if spike S2 fails for a C-level time source, the affected rows become N/A_CLOCK for time-dependent bundles. Is the remaining coverage enough for a headline rank?
3. **Third blind-panel family:** which family, at what single-call cost?
4. **Human grader pool,** an owner decision. It covers the template census, the pilot instance audit (75 bundles per track) and the release audit (200 per track).
5. **Template counts:** can every track reach the minimum of 25 template versions for the pilot audit and 40 for release (PREREG §5), or do some tracks need more templates before the pilot?
