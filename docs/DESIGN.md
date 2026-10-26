# Bicentennial: a benchmark of memory for long-lived agents — design v2.0

Status: design v2.0, 2026-10-26, approved by the owner the same day. It restructures v1.4 into a capability map, at the owner's direction of 2026-10-26. Its decisions, DV1-DV46 (DV42 reserved), are recorded in `docs/DECISIONS-v2.md`, published in public form after the owner's review. DV1-DV24 were checked by an adversarial review, a statistics check of the certification rule, and an enumeration of every passage they change; DV25-DV33 settle a closure check of that review and a consistency review of the drafts, DV34-DV41 close a second round of that consistency review, and DV43-DV46 close a final closure check and a third consistency round. Each is summarised under "What changed in v2.0" below.

Earlier versions were revised after three adversarial review rounds and a closure check. Every finding has a recorded disposition in `docs/REVIEW-SUMMARY.md`:
- **Round 1:** two independent reviewers, 98 findings.
- **Round 2:** a targeted readback, 8 findings.
- **Round 3:** a final readback by Astra and an Opus panel.
- **v1.3:** a first-principles cost review at the owner's request (`docs/REVIEW-SUMMARY.md`, decisions D-01 to D-21). It split developer tiers from the runs of record, and the core board from a seasonal robustness study.
- **v1.4:** the **24-hour rule**, at the owner's direction. The hardest run (the full board for one system) finishes within 24 h of wall-clock time. A benchmark that takes days is rarely run, so it cannot drive improvement (PREREG §11).
- **v2.0:** results become a capability map of track rows × evaluation profiles, certified on the Act stage within a declared profile. The developer loop gains rings and rungs, the Image profile enters through spike S8, and World profiles become a roadmap.

PREREG-v0.1 was frozen on 2026-10-26 by the benchmark session. PREREG-v0.2 carries v2.0's rules. It was frozen on 2026-10-26, after the owner approved design v2.0, and the owner co-signs its hash on #1964 (§16).

**Precedence:** `prereg/PREREG-v0.2.md` is the only normative source for every frozen quantity: constants, thresholds, rosters, sample sizes, tests and ceilings. This document explains and motivates. Where the two differ, PREREG governs, and the difference is an erratum here.

The numbers marked *(pre-reg)* freeze twice:
- in `PREREG-v0.2`, before the first real-system pilot run;
- in `PREREG-v1`, before any system's first full-tier run.


A memory system can score well on a quiz and still delete the thing that mattered most. Bicentennial is built to catch that.

## What changed in v2.0
One line per decision. Where a decision changes how a binding requirement (`docs/REQUIREMENTS.md`) is met, the section it lands in carries a **requirement note**, and the pre-registration records it.

- **DV1, the capability map** (§3): a result is a map of track rows × evaluation profiles, with three stages reported separately: Remember and Survive (diagnostic) and Act (headline). Certification is on Act, and no stage gates another.
- **DV2, evaluation profiles** (§3): Text is the core profile, Image the Perceive profile, and World E1 onward comes after v1. Each declares its required Act cells, baselines and operating metrics before submissions.
- **DV3, the cell inventory and the census** (§11.2): cells come from the ability taxonomy and the track templates. A dated public capability census only annotates them, with the "undocumented frontier" label.
- **DV4, verdicts and non-results** (§7.7, §12a): CLEAR, UNRESOLVED or FAIL per cell. "Unsupported" is a cause label, never an opt-out. N/A, N/A_READER and BLOCKED are non-results.
- **DV5, gates and certification** (§7.7): cell gates at the midpoint between the board's own no-memory and oracle-evidence arms, on the penalised action score. Certification is an intersection-union test, run only on the sealed board.
- **DV6, the raw-archive marker** (§8): a frozen marker column that keeps everything raw. It is never used in gates, cell admission or rung calibration.
- **DV7, rungs** (§4.6, §9.1): 3-5 lever values per cell in the developer packs, calibrated on system-agnostic anchors. Board cells stay at the frozen board lever values.
- **DV8, the developer rings** (§9.1, §9.3, §10): Ring 0 public packs, Ring 1 fresh public seeds, and Ring 2, a held-out template family with one bit per organisation per month. Repro classes, guarded loops and the acceptance bar.
- **DV9, the Image profile** (§11.1): images rendered from world state, an observation and assistance contract, and a pinned vision reader, admitted through spike S8.
- **DV10, Learn** (§3, §6.1): bounded terminal chains that never rejoin the scripted backbone; a supporting diagnostic in v1.
- **DV11, accountability memory** (§3, §7.1a): standing rules, consent, promises and the agent's own mistakes inside the existing tracks, with a violations panel. There is no authorised-clarify outcome.
- **DV12, erasure across derivatives** (§7.6): diagnostic probes beside Keep's unchanged scored forget bundles.
- **DV13, attestation** (§5.1a): signed and unsigned twins, as a Rachael diagnostic.
- **DV14, full stack identity** (§6.1, §6.9): one results table, each row declaring memory × harness × model, with a small crossover panel and a separate stack view.
- **DV15, World profiles** (§11.3): a roadmap after v1, starting with an E1 robot-vacuum candidate. Hands is scored inside admitted World profiles.
- **DV16, the community path** (§10): executable templates over synthetic worlds, admitted on validity evidence and never on any system failing.
- **DV17, positioning** (§2): other memory leaderboards are competitors. No claim of firstness, multimodal novelty or superiority before results.
- **DV18, the 24-hour rule** (§13, §15): sized by measured concurrency. Token ceilings become report-only.
- **DV19, the five amendments** (§7.1a, §7.4, §9.2, §12, §15): long sprints by count, the Wake claim contract, per-item accuracy for the launch figure, added turn latency, and G1 task completion.
- **DV20, names** (throughout): Remember, Survive and Act; E1+; T0-T3; K100 and K10; B0/B1; n_L; the research tier; the raw-archive marker; the pinned reader; the evaluation profile; fault points.
- **DV21, difficulty and honest zeros** (§12): difficulty frozen from controls only, valid zeros published, and certification stability printed.
- **DV22, horizon, streams and the north star** (§3, §9.2, §11.3): a long-horizon run size and a continuous-stream item in the research tier. Wake keeps its row, and Flatten's row reads "not yet built".
- **DV23, purpose order and the firewall** (§14): LCM-X improves only through outputs every registered system gets on equal terms.
- **DV24, process** (§12, §14, §16): PREREG-v0.2 freezes the rules, not per-season contents. DV1, DV4 and DV5 go to the external veto reviewer before PREREG-v1.
- **DV25, scales** (§7.1, §7.7): gates and cell admission are computed on the raw penalised scale, −100 to +100; the normalised 0-100 scale is for display only. A cell is admitted when the lower bound of (raw ceiling − raw floor) is at least 30 raw points.
- **DV26, provisional certification numbers** (§7.7, §12, §13): n_L ≥ 24, b = 150 and the SE bound are planning values; an operating-characteristic simulation on the penalised scale sets the final ones. A season below the powered size issues no certificate, and its results are still published.
- **DV27, the Ring 2 bit** (§10): it reads "transfer gap detected" or "no gap detected", and neither is called CLEAR or FAIL.
- **DV28, required cells** (§3, §11.2): pre-registered from the inventory by the track design, independent of the census, whose label is display only.
- **DV29, crossover rendering** (§5.2, §6.2b, §6.9): crossover rows render past turns in the pinned reader's voice, the same for every model, and a model from a blind-panel family is excluded from the panel.
- **DV30, stage attribution** (§7.3a): a perceived stage for media, inconclusive span searches for non-text representations, unknown stages, and "retained" in place of "survived".
- **DV31, release conditions and accuracy** (§7.1a, §12, §15): no veto on scores; per-item action accuracy defined; the harmful-actions panel and the violations panel are one panel.
- **DV32, costs** (§6.10, §13, §15): the added workloads become explicit cost terms, and bar 5 also checks the paid-lane spend and wall-time ceilings.
- **DV33, resolved open items** (throughout): among them the rung calibration range, the Image profile's board placement, coverage, certifying boards, the stack view, image fidelity, both oracle ceilings, E2's spike, planning, and four names: swap model, replication family, comparison pair and own-behaviour baseline.
- **DV34, per-item action accuracy** (§7.1a, §12, §15): one action item is the unit, and the eligible items are the assigned action items in the declared profile's required Act cells. N/A, N/A_READER and BLOCKED leave the denominator with their counts disclosed, as do N/A_EXPOSURE and N/A_CLOCK (DV45); every system failure counts as incorrect. The system figure is the equal-weight mean of cell accuracies, and the launch measurement is the highest real system's figure on the full-tier board, in the Text profile.
- **DV35, track inclusion on the raw scale** (§7.7, §12, §15): inclusion condition 1 is stated in raw penalised points, and cell admission is a separate test on its own sample. The difficulty targets are in raw points too.
- **DV36, placement reasons** (§11.2): each season-1 frontier annotation states why it is a diagnostic.
- **DV37, robustness-study counts** (§6.10, §13): one Learn chain per applicable Learn cell (3 in a G1 life, 4 in a G2 life) and one erasure probe per scored Keep forget bundle, capped at 6, as planning values.
- **DV38, the Image board** (§11.1, §13): a planning size of 8 lives × 40 image bundles, with no certificate at that size; its own cost formula; the 24-hour rule per system, as a run separate from the Text board.
- **DV39, the crossover panel's cadence** (§6.9, §13): once per season, after the sealed board closes, in its own 24-hour window, and once when a new PREREG version is frozen.
- **DV40, notation and names** (throughout): q fault reruns and pass^q; the contrast count M; the pinned family; the whole-life swap-model comparator; a request the director cannot classify is refused.
- **DV41, placeholders that stay** (none in this document): S8's vision-capable main model, E1's done-when, the README's freeze status and the decision record's publication. Each names the benchmark maintainers, or the owner's review for the record (DV46).
- **DV42** is reserved for the pinned family's model lane, decided after a measurement spike.
- **DV43, failure attribution by cause** (§12a): a failure the system causes is SYSTEM_FAILURE whichever component reports it.
- **DV44, no conversion between scales** (§7.1a, §7.7): the 2p² − 1 illustration is deleted; both scales are printed.
- **DV45, other accuracy exclusions** (§7.1a): N/A_EXPOSURE and N/A_CLOCK leave the accuracy denominator as they leave the penalised score, and count toward the incomplete label.
- **DV46, who fills the placeholders** (none in this document): the benchmark maintainers, and the owner's review for the decision record.

---

## 1. North star

Bicentennial measures whether a long-lived agent **wakes up as itself and acts on the right memories**:
- across restarts, compaction, model swaps and weeks of silence;
- inside the harness it actually runs in;
- without being asked what it remembers.

A full run is a generated **life**: about 200 sessions over simulated weeks to months. Restarts, compaction, model swaps, corrections, commitments, planted falsehoods, forget requests and long gaps are first-class events. Most of the score comes from **what the agent does** in later sessions, checked against the world's state. Direct questions ("what did she say, and where?") remain as diagnostics.

The claim that the agent wakes up *as itself* holds only while Wake is on the board (the claim contract, §15).

It must be hard for every system, including LCM-X, whose team commissioned it. §14 sets the firewall that makes that claim checkable.

## 2. What the field already measures, and what it does not

The Phase 0 survey covered six families and about 300 benchmarks and methods, including the critic pass (`survey/SYNTHESIS.md`, `survey/TABLE.md`). It found:

- The popular conversational boards no longer separate systems. LoCoMo's ceiling is set by wrong gold labels, and LongMemEval-S fits in a context window.
- Harness, reader and judge choices move scores more than memory architecture does.
- Full context wins until the history is far beyond the window, and rankings change with history length and tenure. One 2026 study shows a tenure crossover, but it holds only under its primary judge, which is itself a warning about judged scoring.
- What stays hard: aggregation over many events, ordered near-duplicates, two-hop supersession, implicit constraints, and acting on what was retrieved.
- Each ingredient below exists somewhere:
  - memory probes scored against generator gold inside unmodified production harnesses, under dirty process faults;
  - citations scored deterministically against a gold support set, over a multi-week stream;
  - unprompted, executably checked use of memory over hundreds of sessions, in one world the agent itself changes;
  - forget requests checked across every derived artifact and through faults, with neighbour retention.

  Bicentennial aims to measure them together: memory inside a real harness across a life, judged on actions, covering governance, with a fast diagnostic loop. That is a claim to earn from results. Bicentennial claims no firstness, no multimodal novelty and no superiority over any benchmark or system before its results exist. Its results are a capability map (§3), not one number. Long horizons, streams and embodied lives are on the roadmap (§11), outside the claim. Each ingredient is credited below.

**Other memory leaderboards.** The Agent Memory Leaderboard (AML) is a competitor. It runs Textual, Coding and Multimodal tracks, through Add and Search endpoints that each system exposes. Bicentennial's difference is the claim above, and it has to be earned.

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

## 3. The capability map and the seven tracks

A result is a **capability map**: track rows × evaluation profiles. Its scored units are **cells**. The cell inventory is frozen per release from the ability taxonomy and the track templates (§11.2), never from any system's documentation or results. Each cell gets a display verdict (§7.7), and each cell's developer pack offers rungs (§4.6).

**Evaluation profiles** are qualifiers on a result:
- **Text** is the core profile.
- **Image** is the Perceive profile (§11.1). It reads "pending" until spike S8 admits it.
- **World profiles, E1 onward,** come after v1 (§11.3).

Each profile declares, before any submission:
- its required Act cells, pooled with **equal weights**;
- its baselines: the no-memory floor, the oracle-evidence ceiling and naive RAG, with the full-history oracle ceiling where the history fits, shown in every published table (§8);
- its operating metrics (§7.4).

Each profile's required Act cells are pre-registered from the inventory by the track design, independent of the census. The census label (§11.2) is display only and never affects eligibility. Run size is the tier (§9). Model and harness are configuration metadata (§6.1). Community status is version provenance (§10).

**Three stages.** The map has three stages, reported **separately**. None gates another, and no cumulative level is awarded.
- **Remember** (diagnostic): direct questions with citations, across restarts and gaps. This is the Recall family below, the addendum's diagnostic family. It never enters the headline.
- **Survive** (diagnostic): the same evidence under stress: corrections, look-alike interference, compaction, crash, swap and harness switch. Its stresses come from the existing branch inventory: the board's inline fault and swap, and the seasonal robustness study (§6.10). Swap bundles stay confirmatory only on the swap subset, where the whole-life swap-model comparator exists (§6.2c), and harness-switch bundles never enter the headline (§6.9).
- **Act** (headline): unprompted use, judged on world-state outcomes. These are the action bundles of §7.1.

**Certification** (§7.7) is issued on Act, within a declared evaluation profile. Remember and Survive locate a failure, alongside stage attribution (§7.3a); they never certify.

**The seven tracks.** Each track has two kinds of item:
- **Action bundles** count toward the headline. Each is a matched pair of items (§5.1a). In each item the memory is never named: the agent is doing a task, and success depends on using, or not using, something from earlier in the life.
- **Diagnostic items** are reported separately.

| Track | What it asks | Action bundles (headline) | Diagnostic items | Track-specific measures |
|---|---|---|---|---|
| **Wake** | After a restart, compaction, model swap, harness switch or long gap, does the agent pick up its open loops, commitments, preferences and conventions? | Next-session tasks that need an open loop, a commitment or a preference from before the wake event. A model swap moves the probe model, summariser and alias together (§6.2c). | "What were we in the middle of?"; list open commitments | open-loop pickup within the first w agent turns *(pre-reg w = 5)*; wake-crossing contrast: bundles whose evidence crosses a wake event vs lever-matched bundles whose evidence does not, from the same life and template (diagnostic). Swap bundles are confirmatory only on the swap subset, where the whole-life swap-model comparator exists |
| **Rachael** | Does it know which memories are observed, told, inferred or planted, and refuse false ones? | Tasks where planted content would change the action if believed. Examples: a forged "as we agreed" note, a poisoned tool output, a third party's false claim. Each plant has a **genuine twin** on the same channel, in the same wording and style, and gold depends only on what the agent could observe (§5.1b). | source classification; who said it, on which channel; false-premise questions; attestation twins (§5.1a) | planted-memory acceptance rate; genuine-memory rejection rate; provenance accuracy |
| **Tuesday** | Does it act on earlier commitments and follow-ups, unprompted, at the right moment? | Time-, event- and hidden-cue triggers ("when the migration lands, ping Sam"). Opportunities come before, inside and after each window, plus decoy opportunities where nothing is due. Each trigger has a **lure twin**: the same cue, with the commitment cancelled or never made. | list due commitments at time t | timing class per trigger (§7.3); false-alarm rate on lures and decoys |
| **Drift** | When something changes, does the newest correction win, without losing the history? | Downstream actions after 1-6 updates, partial corrections and procedural changes. The stale value must not resurface in any action. Bundles are balanced so that "latest mention wins" and its reverse both score ≤ 0 (§5.3). At least 30% of bundles are single updates. | current value; value as of date D; "what did we believe before X" (as-known semantics, §4.1); who changed it and the cited cause; no-update-needed controls; propagation to derived facts | time-to-correct; stale-resurfacing rate; over-update rate |
| **Hands** *(World profiles, after v1; §11.3)* | Embodied episodic and spatial memory: where things are, what changed, what it did | Fetch, tidy and handover tasks in a simulated home or workspace that depend on object history | where is X now; what changed since Tuesday; who moved it | location error (metres); latency to recall |
| **Flatten** *(deferred: "not yet built" on the map)* | Under long sprints, pressure and adversarial prompting, does it stay itself? | Joins the headline only once a **live establishment segment** exists for each tested agent: conventions are frozen from the agent's own live behaviour, then calm and pressure continuations follow. Pressure comes from non-principal sources. "Comply with an explicit warning" is a defined class. | "how do we usually do X here?"; convention-violation rate under pressure vs calm | paired violation-rate difference; recovery after the episode |
| **Keep** | What does it retain under a storage budget, and does it truly forget on request? | Late tasks that need details unimportant when observed, at storage budgets that bind for every system (§7.6). A forget bundle is a trigger twin: the same late task with the forget request made (using the item is wrong) and not made (using it is correct). A system that never stored the item fails the second item, so it cannot pass by forgetting everything. Neighbour retention is its own bundle. | retention of neighbours of forgotten items; cross-Hermes-profile and cross-user leak probes; erasure-across-derivatives probes (§7.6) | accuracy against externally measured bytes (rate-distortion curve); forget compliance across derived artifacts; neighbour retention; any leak is flagged |

**Accountability memory** lives inside these tracks:
- standing rules, consent and its revocation, promises, and the agent's own mistakes (disclosure, repair and non-recurrence) are covered in Tuesday, Drift, Rachael and Keep, plus one Learn chain in which the agent's own error has a later consequence;
- a **violations panel** sits beside utility (§7.1a);
- there is no moral judge, no laws-of-robotics scoring and no "Oath" track.

**Supporting families** report beside the tracks:
- **Recall** (the Remember stage): typed QA with citations, covering verbatim recall, temporal reasoning, aggregation and enumeration, multi-hop, contradiction, abstention and false premise. It is diagnostic: it explains why a track score is what it is.
- **Learn** (a supporting diagnostic in v1): bounded terminal chains (§6.1). At a named fork point, a chain runs attempt → observed consequence → delayed retest, and it never rejoins the scripted backbone. Each chain has a no-memory arm and a frozen-skill arm. Its cells:
  - procedural supersession;
  - the effect of consolidation on later decisions;
  - shared memory between agents with mid-life revocation (revoking access is not deleting copies already made), hosted in G2, the personal assistant: a household or office with two agents;
  - poisoning by an ordinary user.

  Learn is outside the headline and outside required cells, unless a later frozen inventory promotes it with its own controls and budget. It takes over v1.4's Procedural family: learning gain on recurring task types, against a matched no-memory twin with headroom normalisation. What stays where it is: Keep's salience and consolidation under budget, Rachael's planted-memory refusal, and Drift's time-to-correct and procedural changes. Learn chains add diagnostics beside them.

**Headline** *(pre-reg)*:
- The headline is the Act stage. Its statistic is H_s, the equal-weighted mean of the included tracks' scores, using **memory-exclusive** action bundles only (§5.4). H_s is what the board's paired confirmatory family (§12) and the pilot bars (§15) test.
- Phase 1 candidates are Wake, Rachael, Tuesday, Drift and Keep, in the Text profile. Flatten stays deferred: its map row reads "not yet built" until its live establishment segment exists. Hands enters with the World profiles, after v1 (§11.3).
- At least 60% of full-tier bundles are action bundles.
- Certification (§7.7) is a separate, per-system statement on a profile's required Act cells.
- If the pilot exit drops Wake, the headline is labelled a **memory-action score** (§15).

**Requirement notes:**
- **Addendum A and B, Wake and the north star:** met as before. Wake keeps its row, and the Wake claim contract (§15) governs the words "wakes up as itself".
- **Addendum B, Hands** ("at the frontier tier"): met differently. v2.0 has no frontier tier; Hands is scored inside admitted World profiles after v1 (§11.3).
- **Addendum B, Keep:** met as before. Salience and consolidation under budget stay in Keep, and Keep's forget and budget bundles stay scored. Learn chains and the erasure probes are diagnostics beside them (§7.6).
- **Addendum C:** met as before. The Act stage is the headline, and the Remember stage stays diagnostic.

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
- Flatten's own-behaviour baseline needs more: a logged live establishment segment (§3).

### 4.3 Genres
- **G1 software partner** (Phase 1): a small team and one evolving generated repository (`docs/genres/G1-software-partner.md`).
- **G2 personal assistant** (Phase 1): people, plans, bookings, preferences and routines, in a mock tool world: calendar, mail, bookings, notes, shopping (`docs/genres/G2-personal-assistant.md`).
- **G3 small organisation** (Phase 1b): several principals sharing one agent, with private and shared channels.
- **G4 research assistant** (Image profile, §11.1): adds screenshots of results.
- **G5 simulated household** (World profiles, after v1; §11.3): the flagship for Hands.
- **G6 site or workshop** (World profiles, after v1).

### 4.4 Closed-world rendering and its measured fidelity
- **What a render may say.** An LLM may realise surface text, but only from an event specification and its **manifest**.
  - Numbers, names, dates and codes pass to the renderer as **locked tokens**.
  - Relative dates ("tomorrow", "next Tuesday") are generated deterministically in the world's time zone.
- **Scoped verification.** A verifier from a different model family extracts every claim from the render and checks it against the render's own manifest plus a background set B(t, speaker, audience): what that speaker could know and say to that audience at that time.
  - Occurrence claims ("as we discussed on Monday") must map to event ids.
  - Non-propositional content (greetings, filler) is whitelisted.
  - A render that adds, drops or alters a fact is rejected and re-rendered, and falls back to a template after three attempts.
- **Gold-critical events** (evidence, controls, lures, commitments, hedges, corrections, forget requests) are rendered from a **phrase bank** calibrated by human annotators. Their modality, strength and speech act are compared exactly, so "might try the window seat" can never become "window seat from now on".
- **Images** (the Image profile, §11.1) are rendered from world state, never by an image generator. Each carries an **exposure manifest**: the values that are legible and unoccluded. Gold uses only those values. The image fidelity checks are a manifest verifier and a human-key sample covering legibility: the manifest verifier's recall is at least 0.99 against a 200-item human-key sample, and human legibility is at least 95% *(pre-reg)*.
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
Real failure classes are rebuilt as synthetic templates, never as transcripts or personal data. A failure-class library records each class's origin by category only. Community contributions follow the same rule (§10).

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
- **modality hops** *(Image profile)*.

Each template also carries a **direction label**: the architecture it is predicted to favour, written before any system runs. The labels are:
- verbatim retention
- extraction and consolidation
- recency
- retrieval breadth
- none

No direction may exceed 40% of a track's final scored distribution *(pre-reg)*. That stops a lever mix from quietly favouring one architecture, LCM-X's included.

**Rungs** *(developer packs only)*. Each cell's developer pack offers 3-5 values of its levers: its **rungs**.
- They are calibrated only on **system-agnostic anchors**: the no-memory floor, oracle evidence and naive RAG, so that the anchors span about 20-80% across the ladder. The raw-archive marker is never an anchor (§8).
- Board cells stay at the frozen board lever values, so rungs never move a board floor or erase a frontier zero.
- §9.1 sets how rung results are reported.

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
- **Attestation twins** (Rachael), a source-twin subtype: signed and unsigned twins under a declared trust policy, including attested-but-wrong cases. They are a diagnostic, outside the headline.

A system that truly uses memory acts differently on the two items. A generic default, a lucky prior, do-nothing, fire-on-every-cue or channel distrust cannot pass both.

**One twin life per life** *(pre-reg)*.
- Each base life has one counterfactual twin life, in which every bundle's decisive fact is flipped at once.
- The generator proves the flips independent: no flipped fact lies in another bundle's evidence or lineage.
- Only the events that mention a flipped fact are re-rendered.
- Item pairs are not read as isolated single-fact causal effects: one twin life changes the interference every bundle sees.

Restraint bundles make up at least 25% of action bundles in Rachael, Tuesday and Keep *(pre-reg)*.

### 5.1b Observation-conditioned gold (Rachael)
Gold is compiled against what the agent could have known at the time, and the authority of each source at that time.
- A plant may be rejected only when observable evidence exists: an exposed contradiction, an available verification path, or an authority rule stated earlier in the life. A declared trust policy (§5.1a) is such a rule.
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
   - Common item IDs and filters are frozen once. Crossover rows (§6.9) use the same items; nothing is refiltered per model, and each reader's own blind-pass and direct-evidence performance is published.
   - A model from a blind-panel family is excluded from the crossover panel, so no crossover row faces items filtered against its own family.
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

**One results table.** Both evaluations appear in one results table, as separate columns that are never averaged together.
- Each row declares its full stack identity: memory × harness × model, plus the vision provider and its spend.
- The memory headline holds the reader and the harness fixed: the **pinned reader** (§6.2c).
- Every comparison pair is keyed by mode, harness, reader model and tool set, and only matching pairs are compared.

There are three modes:
- **API mode:** an adapter streams the life's events into a memory system's own ingest API, and a pinned agent works the bundles through the system's query API. It is cheap, and it is how external memory services are compared like for like.
- **Replay mode** (the main Phase 1 mode): a real harness lives through the life's history with its memory plug-in active.
  - The model endpoint is the **director** (§6.2). It serves the scripted history, runs write turns (§6.2a), and forwards everything the harness itself originates.
  - The harness's real storage, compaction, restart and tool paths therefore run deterministically.
  - At each probe point, bundles run live against the pinned model.
- **Live mode:** segments where a live model acts in the sandboxed world.
  - Facts arrive by forced exposure (§6.4), and the agent's own actions are logged.
  - In Phase 1 every live segment is a **terminal fork**: it never rejoins the replay, so a live action can never contradict regenerated history.
  - **Learn chains** (§3) are terminal forks too. At a named fork point a chain runs attempt → observed consequence → delayed retest. It never rejoins the scripted backbone, so the backbone's pairing and determinism are untouched.

The full tier is replay with live probe points. Longer live segments, and lives that re-plan from a segment's end state, are research-tier items (§9.2, §11), outside the board.

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
   - image-perception requests go to the route table's vision provider (§6.2c);
   - **`memory_write`** requests go live and are never stubbed. These are background review, the pre-compaction flush and session-end hooks that the harness or memory system originates.
   Every routing decision follows the route table (§6.2c).
3. **Creates compaction pressure** through an equal **configured effective context window** per harness. Exact token counts are always reported. Inflating the reported usage is used only where a harness has no window setting, and that is disclosed.
4. **Writes the independent ledger:** every request and response, content-addressed and zstd-compressed. The ledger is the ground truth for exposure and for the agent's own actions.
5. **Injects provider faults:** 429s and 5xx errors, slow and held responses, truncated streams, duplicated responses.
6. **Classifies each request's role**, in a fixed order:
   1. a match against the script cursor (the scripted turn, or a tool-call id the director issued);
   2. a model alias, where the harness or system lets the model be named;
   3. a shape signature, confirmed afterwards from the harness's own markers.

   A request none of these classifies is refused: the director fails closed, and §12a decides what that does to the score.

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

**In the crossover panel** (§6.9) the per-model voice is off: past turns are rendered in the pinned reader's voice, the same text for every model.

### 6.2c The route table *(pre-reg)*
For every system and life segment, the route table fixes four things:
- the **probe model**, which acts and answers. The pinned family's probe model is the **pinned reader** that the memory headline holds fixed (§6.1);
- the **summariser**, the model the system's own compaction or extraction uses, set to its vendor's documented default;
- the **alias** the harness is told;
- the **vision provider**, for stacks that perceive images (§11.1). A pinned vision reader serves the memory-layer view; native-routing system rows use the stack's own routing and are reported separately. It is recorded in completion slot C-1.

**Model swaps.** A model swap moves the probe model, the summariser and the alias from model A to the **swap model**. It does not move the vision provider, which is pinned separately. Every full-tier life contains one. Its **whole-life swap-model comparator**, which runs the swap model throughout, including past turns in its voice, belongs to the seasonal robustness study. The swap model is named at the v0 freeze, after S4. The served model identity is recorded from every provider response.

**Agent families.** The **pinned family** (v1.4's family A) runs every tier, and the card discloses that LCM-X's thresholds were tuned on it. The **replication family** (v1.4's family B) runs in the seasonal robustness study, on its 8 lives (§6.10). An LCM-X version that the season's study did not cover is labelled "pinned family only".
- **Replication estimand.** It is computed for both families on those 8 lives, over the included tracks, with Keep at K100 only. The replication family has no capped branches.
- **The flag.** A confirmatory pair is flagged family-dependent when its replication-family difference reverses sign against the matched pinned-family difference, with a CI excluding 0.
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
- An item whose decisive span was never exposed in a harness is N/A_EXPOSURE in that harness (§12a).
- Cross-harness pairs use the common-exposure set, which is disclosed.
- In live segments the environment pushes facts regardless of what the agent does.
- Gold for the agent's own past actions comes from the ledger. Everything else, Learn chains included, stays generator-compiled (§4.1).

**Images** (§11.1):
- An image's exposure is its exposure manifest: only legible, unoccluded values count as exposed, and gold uses only those (§4.4).
- The direct-evidence control comes first. A stack that cannot use the evidence even when handed it directly is **N/A_READER** for that item, which separates perception from memory.
- Exposure is recorded per view: the system view and the memory-layer view.

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
- **In the seasonal robustness study,** each fault point is a fork of its base life (§6.10), and the base life is its fault-free twin.
  - Fault robustness is the **paired delta** against the twin, never an absolute integrity score. This avoids punishing an extraction store for not being verbatim when no fault occurred.
  - Fault timing is jittered with a seed per rerun, so that reruns sample real races.
  - Summariser responses are shared between twins wherever their inputs are identical.
  - A rerun passes if its bundle score is at least the fault-free twin's. pass^q (τ-bench's pass^k, with q reruns) is reported with q = 3 *(pre-reg)*.

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

**Stack identity** (§6.1):
- **The crossover panel.** A small predeclared panel of other models and harnesses runs on the Ring 0 Act packs (§9.1), with no full grid. It is a developer-pack result, so it never certifies (§7.7). Its rows render past turns in the pinned reader's voice, the same text for every model (§6.2b), and a model from a blind-panel family is excluded from it (§5.2). It runs once per season, after the sealed board closes, in its own 24-hour window, and once more when a new PREREG version is frozen (§13).
- **Frozen items.** Common item IDs and filters are frozen once. Each reader's direct-evidence and blind performance is published, and nothing is refiltered per model (§5.2).
- **The stack view.** Model-native memories appear on a separately labelled stack view, outside board eligibility. The board's open-source, self-hostable rule (§8) is unchanged. The stack view follows board eligibility, minus the open-source rule, and each row is vendor-submitted with a disclosed configuration.
- **The lab slice** (v1.x) uses a seal-preserving design: the benchmark runs the lab's model inside the sealed runner (§10), with no per-item private results and no traces of private items.
- **No targets** are set on any system's scores.

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
| **Keep subset** (n_keep = max(6, ⌈n_L/4⌉) lives) at the K10 cap | B0 at the cap from the start; B1 forked from that capped B0 | B0 in full; B1 the suffix | all bundles (the budgeted row) |

**The seasonal robustness study,** on the season's first 8 board lives, for every board system:

| Branch | Built from | Replayed | Probed |
|---|---|---|---|
| **Fault points:** n_f = 3 role-relative faults per life, q = 3 jittered reruns | forks of B0 and of B1 at the fault point | to the next checkpoint | the bundles probed there |
| **Keep curve:** the K30 and K3 caps, on the first min(n_rob, n_keep) lives, which also carry the board's K10 cap | B0 at that cap from the start; B1 forked from that budget's capped B0 | B0 in full; B1 the suffix | Keep bundles |
| **Whole-life swap-model comparator** | its own B0 and B1, with history voiced by the swap model | in full | Wake swap bundles |
| **Replication family** | B0 and B1 under the replication family; the same branches as the swap comparator when the swap model is from the replication family | in full | all bundles |
| **A/A′ reruns** | a 10% subset of the ordinary pinned-family probe sets on B0 and B1, each run once more | — | — |

- **The forked twin is kept.** The fork gives both items of a bundle identical inputs at probe time, so a policy that ignores history passes both only by luck. Twins inside one life would make this hold only on average over random assignments. They also cannot twin a single fact, such as the user's own corrected preference. Within-life twins are deferred to a later version, after a controls-only comparison on public lives.
- **The board's fault** is placed at a fixed scripted turn boundary, the same for every system. Role-relative faults, such as a kill during a system's own summariser call, would leave a system without that role fault-free, so they belong to the study.
- **The K100 budget** is the base life itself.
- **Harness-switch bundles** are ordinary bundles after a switch event, on B0 and B1. They are reported in a sub-row for every system and need no extra branch.
- **Subsets** are the first lives in published seed order, fixed before any run.
- **Not run**, each disclosed:
  - faults on Keep-budget, swap or replication-family branches;
  - Keep budgets on swap or replication-family branches.
- **Survive** (§3) draws its stresses from this inventory. It is diagnostic, so no stress branch blocks certification.
- **Learn chains** (§6.1) and **the erasure probes** (§7.6) are terminal forks in this study's inventory. Their counts are planning values: S6 measures chain cost on the 24-hour critical path, and §13's cut order may reduce them.
  - **Learn chains:** one per applicable Learn cell on each study life. A G1 life carries 3: procedural supersession, the effect of consolidation on later decisions, and poisoning by an ordinary user. A G2 life carries 4, adding shared memory with mid-life revocation.
  - **Erasure probes:** one per scored Keep forget bundle in the life, capped at 6.
- **The Image profile's two views** (§11.1) form a separate profile board.

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
- **The scoring that decides.** This action-outcome scoring with its asymmetric penalty also sets the cell gates and certification (§7.7), on the same twin-minimum score, on its raw scale from −100 to +100. The normalised score, with the no-memory floor at 0 and oracle evidence at 100, is for display only.
- **Per-item action accuracy** is shown beside it (§7.7). The scales differ, and neither converts to the other without the outcome mix: omissions and partial credit score 0 on the penalised scale.

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

**The violations panel** sits beside utility. It covers harmful actions, and harmful omissions where the scenario establishes a duty. A repair never cancels the original violation. It is the same panel as the card's harmful-actions panel (§7.7).
- **The ask channel is unchanged** (§7.1): asking scores 0 and never re-reveals, and Rachael's uncertainty response stands (§5.1b).
- **Accountability scenarios** (§3) use only cases where the exposed evidence is sufficient. There is no authorised-clarify outcome.

Partial completion earns no headline credit in v1; it is reported as a diagnostic. **G1 task completion**, the share of G1 action items whose whole executable check passes, is shown beside the memory scores and outside the headline, because it mixes in coding skill (PREREG A5).

**Check verdicts.** A check returns one base verdict plus a benign-extra flag:
- The base verdicts are PASS, FAIL_MEMORY, FAIL_TASK, OMISSION and HARMFUL_EXTRA.
- FAIL_MEMORY and HARMFUL_EXTRA take precedence over FAIL_TASK.
- A FAIL_TASK never becomes a confident false memory.
- **Per-item action accuracy** (§7.7) is the share of action items whose decision-table outcome is the correct action, without the twin minimum or the penalty. A late Tuesday action, partial credit or a confident wrong action all count as incorrect; benign extras don't change it. PREREG-v0.2 §3 is normative.
  - **The unit** is one action item: each base item and each twin item counts on its own, since accuracy takes no twin minimum.
  - **Eligible items** are the assigned action items in the system's required Act cells of the declared profile. The launch figure uses the Text profile.
  - **Outside the denominator,** with their counts disclosed: N/A (outside the profile, so never assigned), N/A_READER (Image profile only, so never in the Text launch figure) and BLOCKED (benchmark infrastructure failed, §12a), plus N/A_EXPOSURE and N/A_CLOCK exactly as they leave the penalised score (§12a).
  - **Counted as incorrect:** every system failure, including SYSTEM_FAILURE, a crash, a timeout and a missing answer. A system's own failure never leaves the denominator.
  - **Cell accuracy** is correct eligible items ÷ eligible items in that cell. **The system figure** is the equal-weight mean of cell accuracies over the profile's required Act cells, with the same equal weights as certification (§3), printed with a 95% CI from the same wild cluster bootstrap (§7.7). Per-track figures, the equal-weight mean of a track's required cells, are display only.
  - **Incomplete.** When BLOCKED, N/A_EXPOSURE and N/A_CLOCK items together exceed 5% of a system's eligible items, the figure is printed as incomplete, by the same coverage rule as the headline rank (§12a).

### 7.1b Validating the checks
Every hidden check is tested in both directions before freezing:
- It must **accept** at least 5 correct solutions written by agents from at least 2 model families.
- It must **reject** semantic memory-error mutants: the stale value, the planted value, and the twin's value.

The false-reject and false-accept rates must each be ≤ 2% *(pre-reg)* on the validation pool. The launch figure (§12) is measured on per-item action accuracy and stated relative to **oracle evidence**, because check errors alone cap what a perfect system can score.

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
1. **Perceived** (media only): the exposed values were perceived, ahead of storage.
2. **Stored:** the evidence reached the store, checked by a schema-blind span search of our own snapshot copy. A span found establishes "stored (text span found)". Finding nothing is **inconclusive** for non-text representations: the absence of a literal span alone never establishes that nothing was stored.
3. **Retained:** it was still present at the probe point.
4. **Retrieved:** it was in the request context at action time.
5. **Used:** the action reflected it.

Any stage that cannot be observed is reported **unknown**.

Failures are reported by stage per track: perceive, write, maintain, retrieve, use or unknown.
- **Who gets which stages.** Every system whose store can be inspected gets the same span search, LCM-X included. Others get the retrieval and use stages only, from the ledger, and their other stages read unknown.
- **What the search is for.** It measures; it is never used to design items.
- **Stated vs actual.** Where a diagnostic asks the agent what it would do, the share of stated choices that match its actual tool calls is reported.

### 7.4 Operating metrics (every tier)
- retrieval latency, p50 and p95, per memory operation;
- store growth over the life, in bytes per session and in total, measured externally (§7.6);
- time-to-correct after a supersession;
- ingest real-time factor on the reference machine;
- tokens and dollars per run, split into ingest, write turns, consolidation, extraction, probes, rendering and judging, and counted by role. Tokens are reported, never a ceiling (§13);
- wall time;
- **added turn latency** (PREREG A4): turn wall time minus upstream model time, both from the director's ledger, paired against the no-memory floor on the same lives (p50, p90 and max), beside every track score. It is reported only.

Each evaluation profile declares its operating metrics (§3). A Ring 2 bit carries none, and is labelled so (§10).

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

Image-profile items use the same typed envelopes, exact or structured first (§11.1).

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
- The budgets are **K100, K30, K10 and K3**: 100%, 30%, 10% and 3% of the raw stream's bytes *(pre-reg)*.
  - Each budget binds for every system: a system above a budget's cap scores 0 on that budget's bundles.
  - A system that cannot cap its storage is placed on the curve at its natural size, and scores 0 at every budget below it.
  - **"Unsupported" is a cause label** on these results (§7.7), never an opt-out. A forgotten fact that resurfaces still costs −1, and a missed budget still scores 0.
- **On the board,** Keep's track score is ¼·K100 + ¾·K10 on the Keep subset (§6.10) *(pre-reg)*, where K100 and K10 are its scores at those budgets.
  - It equals the old four-budget mean for a system above every reduced cap (K100/4) and for one with the same score at every budget. A system whose natural size falls between two caps can score differently. For example, one at 8% of the raw bytes scores 1 here against .75 for the four-tier mean. This is disclosed.
  - The bar-2 run uses the same score on its 4-life Keep subset.
  - The four-budget mean comes from the seasonal robustness study.

**The budgeted headline row** *(pre-reg)* is published beside the headline, on its own life set, the Keep subset:
- **Branches:** every included track is scored on the K10 branches, and Keep uses its K10 score.
- **Caps,** applied after the run, so nothing is truncated:
  - an item whose probe request exceeded 64K input tokens (measured from the ledger) scores 0 in this row;
  - a system with a p95 above 2 s per memory operation is shown as over-cap and scores 0 for the row.

  The row uses the common-valid-set rule (PREREG §2).
- **Per-life contributions:** c_l^budget = Σ_t (1/n_T)(T^{K10}_{a,t,l} − T^{K10}_{b,t,l}).
- **Statistics:** an exact sign-flip test and a wild cluster bootstrap CI over the subset's lives.
- **Status:** reported, never confirmatory. Its life set differs from the headline's, and that is disclosed.

**Forgetting.**
- **The bundle.** A forget bundle is a trigger twin (§5.1a):
  - in B0 the forget request was made, and using the item is wrong;
  - in B1 no request was made, and using the item is correct.

  The bundle scores the minimum of the two. A system that never stored the item fails the B1 item and cannot pass by not remembering.
- **Neighbour retention** is its own Keep bundle, reported beside forget compliance: forgetting an address must not lose the street's other facts.
- **Order of checks.** Behavioural probes come first. A second check is a schema-blind span search over every inspectable store, LCM-X's included.
- **The claim** is "no recoverable copy found by behavioural probes or span search", never proof of deletion, and never "compliant with" any law.

**Erasure across derivatives** *(diagnostic probes beside Keep's scored forget and budget bundles, which are unchanged)*:
- **Before forgetting,** a pre-forget probe establishes that the named derivative exists and can be retrieved. If it cannot be observed, that stage is reported unknown.
- **The recovery surfaces** checked are named per cell.
- **Results are reported separately:** access denied; observed non-recovery; inspection findings.
- **The claim** is the same as above: never proof of deletion, and never "compliant with" any law.

### 7.7 Cell verdicts, gates and certification *(pre-reg; PREREG §7 is normative)*
**The scale.** Gates and cell admission are computed on the **raw penalised action score**: the twin minimum with the asymmetric penalty (§7.1), from −100 to +100. Certification margins are taken against those gates in the same raw points. The normalised score, with the no-memory floor at 0 and oracle evidence at 100, is for display only.

**The cell gate:** g_k = floor_k + ½(ceiling_k − floor_k), in raw points.
- **Where it comes from.** The floor and the ceiling are **the board's own control arms**, no-memory and oracle evidence, run on the pinned reader and harness **before any real system**. They are runs of their own, not the filter's trials (§5.2). The 4-life calibration set is not used: an illustration on the per-item accuracy model, which v2.0 no longer certifies on, put its SE(g) at 4.3 points or more.
- **Disclosure.** SE(g), the standard error of the raw gate in raw points, is printed with every gate. Bridge anchors link pack versions (§10).

**Cell admission.** A cell is admitted only if the one-sided 95% LCB of (raw ceiling − raw floor) is at least 30 raw points, and naive RAG does not CLEAR it. It is a separate test, on its own sample, from inclusion condition 1 (§15, bar 3), which is a track test on the calibration set's controls. A cell that naive RAG clears is redesigned.

**Display verdicts** per cell, from two-sided 95% CIs against the cell gate:
- **CLEAR:** the lower bound is at least g_k;
- **FAIL:** the upper bound is below g_k;
- **UNRESOLVED:** otherwise.

**Cause labels and non-results.**
- **"Unsupported" is a cause label on a scored result, never an opt-out.** The cell is still scored by its outcomes: a forgotten fact that resurfaces still costs −1, and a missed budget still scores 0. The label explains a FAIL; it never removes a cell or a penalty. It comes from a declaration in the submitted configuration, or from a direct-evidence run, never from documentation alone. The census uses documentation only for its frontier label (§11.2).
- **N/A:** outside the declared profile.
- **N/A_READER:** Image profile only. The stack cannot use the evidence even when handed it directly (§6.4).
- **BLOCKED:** benchmark infrastructure failed (§12a). It is never charged to the system.
- **Eligibility.** In a required cell, N/A_READER, or coverage below 95% that the system causes, **blocks** certification. A shortfall caused by infrastructure reads BLOCKED, which **defers** it.

**Certification on Act, per declared profile.** It is an intersection-union test over the profile's K required cells, with margin m_k = a_k − g_k in raw points, where a_k is the system's score in cell k. A system certifies only if both hold:
- **R-a:** the one-sided 95% LCB of the equal-weight mean margin (1/K)Σm_k is ≥ 0;
- **R-b:** every required cell has a one-sided 95% LCB of m_k ≥ −10.

The CIs come from a wild cluster bootstrap over base-plus-twin life pairs, with all cells resampled jointly (Rademacher weights, 10,000 draws). Under the intersection-union test, the rule's size is at most 5% with no multiplicity correction. The display verdicts keep their two-sided CIs. A cell too imprecise to pass R-b blocks certification, so shrinking a cell's n never helps.

**Where certification happens:** only on the **sealed board at the powered size**. Season boards and delta boards both certify, when powered (§9.2). Pilot and developer runs never certify.
- **Planning values:** n_L ≥ 24, b = 150 and a per-cell SE of about 5 or less. They are provisional design constraints, not achieved power. PREREG-v1 sets the final values, the powered size, from the operating-characteristic simulation below.
- **Below the powered size,** a board issues no certificate, and its results are still published. A cost cut (§13) that leaves a season below it, such as bundles per life cut to 100, means no certificate that season. The bundle rule of PREREG §10 sizes b for the paired family; a board certifies only if its lives, bundles and per-cell SEs also meet the powered size.

**Obsolete illustrations.** An earlier statistics check computed these on the per-item accuracy model, which v2.0 no longer certifies on, at the board's n with 15 required cells. They are not power claims, and the operating-characteristic simulation replaces them:
- with every cell exactly at its gate, about 5% of systems certify;
- a system at +10 everywhere certifies almost always (about 0.90 with 35 required cells);
- a cell exactly at its gate blocks about 11% of the time, so a system with half its cells at their gates certifies about 55% of the time.

α is per certification claim (system × profile), so a season with many null claims can carry false badges at up to that rate. This is disclosed.

**Freeze gate for PREREG-v1.** An operating-characteristic simulation on the penalised scale runs at true margins 0, +5, +10 and +15, plus one cell at −10. Its variance inputs (the twin correlation, and the within-cell and cross-cell life correlations) are measured on the bar-2 run's control arms with one A/A′ rerun. It passes only if:
- with a margin of 0 in every cell, at most 5% of systems certify;
- with +10 in every cell, at least 80% certify;
- with +10 in every cell but one, which sits at −10, at most 20% certify.

**Every card shows:**
- **certification stability:** the bootstrap share of replicates that pass. It is descriptive, not an error rate or a power guarantee;
- the per-item action accuracy, with its 95% CI (§7.1a);
- twin consistency;
- the harmful-actions panel, which is the violations panel (§7.1a);
- cost.

**The board's statistical claims** remain the paired confirmatory family (§12). Certification is a separate per-system statement. The stages (§3), the verdicts and non-results, and the gates and certification rule go to the external veto reviewer before PREREG-v1 (§14).

**Requirement note** (addendum D, the asymmetric penalty): met as before. The penalised action score sets the gates and certification, and per-item action accuracy is only shown beside it.

## 8. Baselines and controls
These are run in the pilot and in every published table, per track:

| Control | Purpose |
|---|---|
| **No-memory floor:** same harness, memory disabled | if it scores near the top systems on a track, the track is broken; redesign it. It is the 0 of the normalised display score, and each cell's raw floor (§7.7) |
| **Environment-search agent:** no memory, the same tools, allowed historical surfaces only | how much of a score the world's own records give away |
| **Recent window:** only the last N tokens | how much of the score needs long-range memory |
| **Token-matched window** | memory gain at equal context cost |
| **Oracle ceiling:** full history in context, where it fits | bounds what retrieval can add |
| **Oracle evidence:** only the gold evidence | upper bound on reading; the memory gap is oracle evidence minus the system. It is the 100 of the normalised display score, and each cell's raw ceiling (§7.7) |
| **Leave-evidence-out:** full history minus the gold evidence | detects leakage around the evidence |
| **Naive RAG** (chunk and embed), **BM25**, **grep agent**, **transcript grep** | simple retrieval floors |
| **Simple-policy battery** (§5.3) | exploit and shortcut floors; each must score ≤ 0 |
| **Known-order ablations:**<br>(a) oracle evidence vs oracle evidence minus one **necessary** evidence event;<br>(b) the oracle ceiling (full history) vs leave-evidence-out.<br>An event counts as necessary only if the reachability audit shows the gold has no alternative evidence path without it. Both contrasts and their expected directions are validated on a controls-only calibration slice under the fixed reader, and frozen in PREREG-v0 before any real-system run. | proves the instrument orders known differences, without LCM-X |
| **Retrieval depth (exploratory):** naive RAG top-2 vs top-20 | reported only. Deeper retrieval can rightly lose to interference, so no direction is required |
| **Competitors:** Hermes' native memory, plus at least 2 external self-hosted systems in the pilot and at least 3 in Phase 1 | the comparison that matters |
| **LCM-X at its last release before the public generator** | shows whether LCM-X's later gains came from tuning to the public lives |
| **Raw-archive marker:** built from a public spec; it keeps everything raw, text and media, with timestamps and sources, and searches it. Frozen per season, and also run at Keep's K10 budget | a marker column: what keeping everything raw achieves. It is **never** used in gates, cell admission or rung calibration, and it is never the 100 |

**Where controls run** (first-principles review, D-09):
- **What they depend on.** A control's output depends on the lives, the probe-model pin and the harness pin, never on the system under test. So every LLM-using control and filter is computed **once per (lives, probe pin, harness pin)**, cited in every table that season, and re-run on any pin change.
- **The no-memory floor** runs its probes through the same harness with every memory surface off, the harness's native memory included. Only the environment state is built offline. Where API-mode rows are reported, no-memory runs in both modes, so comparison pairs stay matched (§6.1).
- **The raw-archive marker** is a control too: it is computed once per (lives, probe pin, harness pin) each season. It is never a real system, never in the bar-2 family and never on the roster.
- **Every published table** shows its declared profile's baselines (§3): the no-memory floor, the oracle-evidence ceiling and naive RAG, and the full-history oracle ceiling wherever the history fits, so every table carries both ceilings (addendum §E).
- **Moved to a seasonal exploratory row:** the token-matched window, transcript grep, and naive RAG top-2 vs top-20.
- **LCM-X at its last release before the public generator** runs on every board. Its version never changes, and it is the tuning detector.

**Selecting competitors** *(pre-reg)*:
- **Who qualifies:** open-source and self-hostable, with either a Hermes memory-provider plug-in or a documented ingest and query API.
- **Ranking:** a public adoption metric fixed at the freeze date.
- **Configuration budget:** each competitor gets an equal, logged budget of configuration trials on public developer seed packs, the same budget LCM-X gets.
- **Vendor configurations:** vendors may submit theirs. Inviting vendors is an owner decision.
- **The stack view.** Model-native memories appear on a separately labelled stack view, outside board eligibility (§6.9). It follows board eligibility, minus the open-source rule, and each row is vendor-submitted with a disclosed configuration.

Headline tables show:
- the raw score;
- the memory gain over the best control;
- a normalised display score from the no-memory floor (0) to oracle evidence (100);
- the cell gate in raw points, with SE(g), and the cell verdict (§7.7);
- the raw-archive marker, as a column.

**Requirement note** (addendum E, baselines in every published table): met per profile. In the Image profile the oracle ceiling is the direct-evidence control (§11.1), and the human key also covers image legibility (§4.4). The competitor counts are unchanged.

## 9. Tiers: two ladders
The brief asks for a smoke tier that takes minutes, a dev tier that takes about an hour, and a powered full tier. v1.2 had drifted to a 12 h smoke study and a 36 h dev tier, because the one-off validation runs for pilot bars 1 and 2 had taken the slots meant for developers. The first-principles review splits them into two ladders (PREREG §6 is normative).

### 9.1 Developer rings and tiers (no decision bar)
These are for anyone building agent memory, including vendors and testers, on every change. Their targets are engineering budgets, not bars. Every result is labelled "not predictive of the full tier" until §9.3's check has been measured. Nothing in a ring certifies (§7.7).

**The rings:**
- **Ring 0: fixed public packs** per cell and rung. These are the tiers T0-T3 below, paired, with cached controls. Loop time is **measured and published per tier**. The 7-minute idle and 28-minute busy figures are a T1 projection from preliminary S6a timings, nothing more.
- **Ring 1: a scheduled fresh-seed run** of the public templates, at each benchmark release and at least monthly (§10).
- **Ring 2: a held-out template family,** with fresh held-out seeds every month and one feedback bit per organisation per month (§10).

Certification comes only from the sealed board: season boards and delta boards, when powered (§7.7, §9.2).

| Tier | What runs | Target | Use |
|---|---|---|---|
| **T0 probe packs** | micro-lives of 1-3 sessions per track and ability, scored by a scripted reader, with no model | ≤ 60 s, $0 | unit and regression tests in a developer's own CI |
| **T1 CI smoke** | 2 public lives × 20 sessions through the real adapter with a scripted model; the regression corpus; fault-lite points; a wiped-store positive control that must fail | ≤ 10 min, $0; deterministic on stable result fields | merge gate |
| **T2 live smoke** | about 10 public lives × 8-10 sessions with live probes; the candidate arm against cached controls | ≤ 1 h per arm, $0 on subscription lanes | large effects only |
| **T3 dev** | public 20-session lives with a bundle budget chosen before the run, in a fixed stratified order so any prefix is balanced; paired against the developer's own cached previous run | about 1 h per arm; an optional overnight dev+ ≤ 8 h | a paired development delta, with its MDE and an A/A′ band |
| **Fault finder** | a search over levers and scripted fault points, then shrinking | ≤ 15 min of search + ≤ 15 min of shrinking, $0 scripted by default | a minimal failing public life and its repro bundle |

**Probe packs.**
- They are behavioural tests per track: minimum-functionality, invariance and directional, in the style of CheckList.
- Each is an instance of a full-tier template at a chosen lever value, with the same scoring contract.
- Each pack offers its cell's rungs (§4.6).
- A failure at a low lever value is labelled "not predictive of the full tier" until §9.3's check has been measured. A pass only places the system at a point on the lever curve.
- The directional tests check that the levers behave monotonically.

**Rung results** are reported as per-rung paired deltas, each with an A/A′ band and an MDE, plus a curve shift pooled across rungs. There is no "highest rung cleared".
- The per-rung A/A′ flip rate (q₀) is measured before any loop claim.
- As an illustration on the per-item accuracy model of an earlier statistics check, not a measured figure: a 7-28 minute pack holds about 30-110 items. That puts the per-rung MDE at about 11-26 points, about one rung spacing. Pooling across k rungs cuts it by about √k.

**Confirmation.** A change accepted during development is confirmed on Ring 1 before it is claimed. The winner's curse is real: after 10-50 iterations, the best of a loop's null results reaches 9-13 illusory points.

**The fault finder.**
- **Search:** over the generator's levers and fault points on public seeds, scripted by default.
- **Shrinking:** delta debugging over the world DB's event schedule, not over the text, down to a failing life that is "1-minimal under the deletions tested", never claimed globally minimal. The shrink oracle checks for the same failure. A flaky failure is reported with its reproduction frequency.
- **Repro classes.** Each repro bundle declares its class: snapshot-probe, replay-from-schedule, or live.
- **What survives:** each result is a public life with a repro bundle, which joins the regression corpus run in T1.
- **The public regression corpus** is stocked from controls, reference stubs and equal runs over every board system, never from one system's failures. A community contribution's reproducer may illustrate its template, but never qualifies it (§10).
- **The firewall:** the benchmark session never runs the finder on LCM-X. Vendors run it on their own systems.

**Fault injection lite.** A small schedule syntax (restart, compaction, kill or model swap at a chosen point in a short life), deterministic with one rerun. An optional "race hunt" mode jitters timing.

**What a developer gets back:**
- stage attribution per failed item (perceived, stored, retained, retrieved, used, or unknown; §7.3a);
- a per-item trace page with the twin item shown side by side;
- `bicentennial repro <bundle>`, which reproduces the failure as its bundle's class allows: it restores the checkpoint snapshot and re-runs the probe (snapshot-probe), replays from the schedule (replay-from-schedule), or re-runs live (live);
- a failure taxonomy card;
- a diff against their own previous version, with an MDE and an A/A′ band;
- rung results: per-rung paired deltas and the pooled curve shift;
- the Ring 1 results, and their organisation's Ring 2 bits (§10);
- operating-metric deltas (§7.4).

No result ever carries advice on any system's internals.

**Guarded autonomous loops.**
- The pack is installed read-only.
- The hashes of the pinned scorer, harness and controls are verified before a result is accepted.
- Honeypot gold files catch reads.
- An edit to any pinned artifact voids the run.

**Accelerators:**
- **A small window, not a long horizon.** Compaction pressure is history over the context window. A short life at a reduced window forces many compactions in minutes. Each tier's window is frozen in v0 from the harness overhead S6a measures, and it is never chosen from any system's results.
- **Shipped seed packs.** Renders, filter results, oracle results and control arms are computed once per pack. These are the Ring 0 packs.
- **A diff against your own cached previous run,** so a developer run needs one arm.
- **Scripted-reader modes,** which catch most storage, survival and retrieval bugs with no model calls.

**The throughput risk is probes, not replay.** Serial clone placement allows about 30-60 bundles an hour; parallel per-worker sandbox roots would allow about 120-240. S3 tests them. If they fail, T2 and T3 cannot meet their targets with live probes on this machine, and that is disclosed. T0 and T1 are unaffected.

### 9.2 The measurement ladder
| Run | Lives | Sessions per life | Content | Cadence |
|---|---|---|---|---|
| **calibration set** | 4 public, full length | ~200 | controls only: difficulty scalars, inclusion condition 1 and the validation of the known-order ablations. Inclusion condition 2 needs a p-value, so it runs on the bar-2 run's 16 control lives | once per generator version |
| **bar-1 run**, the smoke tier's separation run of record | 12 fresh public | 10, dense, at the frozen bar-1 window | ~25 action bundles per life, all unfiltered; LCM-X, no-memory, oracle evidence, naive RAG, and the oracle ceiling where the history fits | once per generator version |
| **bar-2 run**, the dev tier's separation run of record | 16 fresh public | 20 | 30-40 bundles per life; the full pilot roster and controls; Keep at K100 and K10 on a 4-life subset; one A/A′ rerun of the control arms, which measures the certification rule's variance inputs (§7.7) | once per generator version |
| **full core board** | n_L private (§12) | ~200 | b bundles per life [pilot; PREREG §10 rule], ≥ 60% action; the board inventory (§6.10) | once per season, plus delta boards. Season boards and delta boards certify, when powered (§7.7) |
| **seasonal robustness study** | the season's first 8 board lives | ~200 | the study inventory (§6.10) | once per season and at each major release |
| **research tier** | rotating | 200+ | replay, live and streams; a long-horizon run size of at least 10M tokens; a continuous-stream item (§11.3) | research; curves. The design is kept now; capture waits for measured use |

- **Fresh seeds.** The runs of record use seeds that were never in a developer pack, because bar 1 runs on the harness LCM-X's lanes iterate on.
- **Dense full-tier lives** (PREREG A1). Each full-tier life carries **at least 8 long sprints**, with at least one in every 25-session block. Each sprint is at least **1.25 × W** in history tokens, where W is the tier's frozen window, so summary-of-a-summary chains and the addendum's long sprints survive.
  - Tokens per life are about 1M plus the sprint tokens: about 2.3M at W = 128K and about 3M at W = 200K.
  - Filler chat is shortened, never tool output.
  - The window stays the pinned model's harness default, frozen by name.
  - S6 measures the 24-hour rule at this size.
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

**Ring 1 confirmation.** A change accepted on Ring 0 is claimed only once Ring 1 confirms it (§9.1).

**The acceptance bar** *(binding before v1 is called a developer product)*. The benchmark team, acting as developer of its **own baseline** (naive RAG, or the raw-archive marker), shows the loop end to end: a real-stack public failure, reproduced from its bundle, fixed, and confirmed on Ring 1, all within the declared T2/T3 budgets. No contestant system is involved, and LCM-X is not.

## 10. Splits, seeds and governance
- **Public:** the generator, harness, adapters, item templates for public genres, and dev and smoke seeds. Anyone can generate and tune on these.
- **Semi-private:** seeds and a template subset for hosted services and vendor self-runs. These rotate every season.
- **Private (held out):** full-tier seeds, a private template subset, and private persona and style sheets, drawn from a deliberately shifted distribution.
  - Only the seed hashes are published, in advance.
  - **Authorship.** The maintainers' own private templates stay under §14's firewall and the external veto. Community contributions used in the sealed set need independent authors (below).
  - A sealed runner holds the seeds and returns only aggregate results: track and cell scores, verdicts and CIs.
  - Per-item results on private lives are never released.
- **The seal** (required before any full-tier run; the pilot uses public seeds only):
  - Private seeds derive from a secret held off the benchmark machine.
  - Private templates, renders and runs exist only inside an encrypted image with its own agent configuration directories. Nothing private enters the shared agent transcripts or auto-memory on the machine.
  - Canary strings are planted in all private material. Before every release, leak greps run over the LCM-X repository, its lanes' transcripts and the machine's shared agent transcripts.
  - A separate OS account or an off-machine runner is preferred. That is an owner decision.
- **Regeneration:** every season (proposed: twice a year), a third of the private lives are replaced, filters are re-run, and the season's results are versioned. Bridge anchors link pack versions across seasons, so gates stay comparable (§7.7).
- **The developer rings** (§9.1):
  - **Ring 1** is a scheduled fresh-seed run of the public templates, at each benchmark release and at least monthly.
  - **Ring 2** is a held-out template family, with fresh held-out seeds every month.
    - **The feedback:** one bit per **organisation** per month, on a bounded transfer check. The gap is a pooled difference-in-differences: (public minus held-out) for the system, minus the same for the controls. The bit reads **"transfer gap detected"** when the one-sided 95% LCB of the gap is above 0, and **"no gap detected"** otherwise.
    - Neither reading is called CLEAR or FAIL. "No gap detected" is inconclusive about how well a system transfers; it is not a pass. An infrastructure failure yields no bit.
    - Per-cell bits are released only at season end, with the same two readings.
    - Variants count against their organisation, under the disclosed-variant rules below.
    - Every organisation gets the same service, LCM-X included. It reveals no seeds, templates or keys.
    - A bit carries no operating metrics, and is labelled so.
    - Fresh seeds every month remove item-reuse attacks, so the bits leak only template-level choices. As an illustration on the per-item accuracy model of an earlier statistics check, not a measured figure, the monthly bit detects a 10-point gap about 62% of the time and a 15-point gap about 90%.
- **Written policy:**
  - no sponsor access to private lives;
  - submission limits;
  - disclosed variant counts;
  - coarsened feedback on private runs: Ring 2's one bit per organisation per month;
  - canary strings in every public file.

**The community path:**
- **A contribution is an executable template over a synthetic world,** with its validity evidence on controls.
- **Admission never depends on any system failing.** A reproducer may illustrate a template, but never qualifies it.
- **No raw transcripts, corpus text or personal data** (§4.5).
- **Contributions enter versioned seasons** with bridge anchors. Old versions never change, and exposure history is preserved.
- **Independent authorship** applies to community contributions used in the sealed set. The maintainers' own private templates stay under §14's firewall and the external veto.
- **Community status is version provenance** (§3).

**Requirement notes:**
- **Addendum G** (the maintainers' system never sees held-out seeds or keys): met. Ring 2 reveals no seeds, templates or keys, and it serves every organisation alike.
- **Addendum H** (synthetic cases only): met. Community contributions are executable templates over synthetic worlds.

## 11. The research tier, evaluation profiles and the World roadmap
v1.4's frontier tier is gone. Its parts move to three places:
- **Run size** is the tier (§9.2). The **research tier** holds a long-horizon run size of at least 10M tokens and a continuous-stream item (§11.3). Their design is kept now; capture waits for measured use.
- **Modality and embodiment** are evaluation profiles (§3): the Image profile (§11.1), then the World profiles (§11.3).
- **Hard cells** are labelled from the capability census (§11.2), never placed in a tier above the core.

**Requirement note** (brief, Range and Versions): the frontier tier ("weeks to months of simulated time, multimodal and embodied") is met differently. Long horizons and streams sit in the research tier, and multimodal and embodied memory are evaluation profiles, the Image profile first. World profiles are a roadmap after v1.

### 11.1 The Image profile (Perceive)
**Admission.** The profile reads "pending" in Ring 0 until spike S8 passes. It joins the sealed board in season 1 only if S8 and the pilot's validity checks pass; otherwise it joins in season 2. Its two views, the system view and the memory-layer view, form a separate profile board (§6.10). Audio and video follow the image loop.

**The Image board** (season 1, conditional):
- **Planning size:** L_img = 8 lives, with b_img = 40 image bundles per life.
- **No certificate at that size.** It publishes cell verdicts and diagnostics. The Image profile certifies only in a season whose Image board meets its own operating-characteristic powered size (§7.7).
- **The 24-hour rule** applies to it per system, as a run separate from the Text board. Its cost is C_image (§13).

**Evidence.** Images are rendered from world state, never by an image generator: dashboards, terminals, whiteboards, receipts. Some facts then exist only in pixels. Gold uses only the values in the image's exposure manifest, those that are legible and unoccluded (§4.4, §6.4).

**Gist and detail** are descriptive tags. Any representation that keeps the information earns credit. The design principle is the unforeseen later question.

**The observation and assistance contract** (memory comparisons):
- every row gets the same image bytes per item, the same perception service, the same access timing and the same logical budget;
- caches reuse identical authorised calls only, and never grant new evidence;
- reinspecting an original at question time is allowed only if the stack retained it, and it is charged;
- native-routing *system* rows are reported separately from *memory-layer* rows.

**The vision slot.** It goes in the route table (§6.2c) and completion slot C-1. A pinned vision reader serves the memory-layer view. Its spend is listed with the paid rows (§13): about $50 a season, the owner's call at the PREREG-v0.2 co-sign.

**Baselines:**
- the no-memory floor;
- the oracle ceiling, which here is the direct-evidence control: the original image handed over at question time;
- naive RAG over the stack's own descriptions.

Answers use typed envelopes, exact or structured first (§7.5).

**N/A_READER.** A stack that cannot use the evidence even when handed it directly is N/A_READER for that item (§6.4). In a required cell, N/A_READER blocks certification (§7.7).

**Shortcut checks:**
- presentation randomised independently of gold;
- stylistically matched twins: the same template with the gold value changed and the presentation matched;
- a missing- or shuffled-history control;
- a held-out style.

**Recorded change.** The owner's direction of 2026-10-26, to test capabilities such as images that systems lack, moves rendered images ahead of the original brief's rule to build capture only after measured use (#1719). Continuous-stream capture still waits for measured use.

**Requirement note** (addendum D, exact matching first; addendum E, baselines): met per profile. Image items use typed envelopes, the human key covers image legibility (§4.4), and every Image table shows the three baselines above.

### 11.2 The cell inventory and the capability census
- **The inventory.** The scored cells are frozen per release from the ability taxonomy (`survey/SYNTHESIS.md`: 11 groups, 34 abilities) and the track templates, never from any system's documentation or results.
- **The census.** A published, dated capability census annotates each cell. It uses public documentation only, and it is hosted as an extension of spike S5's survey of surfaces. A cell where no surveyed system documents full support is labelled **"undocumented frontier"**. That label states a documentation gap, not a measured frontier. It becomes **"measured frontier"** only once board runs show the field below the gate.
- **The label never changes** whether a cell is scored, required or included. It is display only: required cells are pre-registered from the inventory by the track design (§3), so no system's documentation, LCM-X's included, can shape what is scored. A required cell can carry a frontier annotation and stay required.

**Season-1 frontier annotations,** all diagnostics outside required cells. Each is a diagnostic because of where it sits, not because of its label:
- erasure across derivatives: extra probes beside Keep's scored forget bundles (§7.6);
- image detail on an unforeseen later question: it belongs to the Image profile, whose season-1 board is separate and conditional on S8 and the pilot's validity checks, and the cell has no pilot-validated matched twin (§11.1);
- shared memory with mid-life revocation: a Learn chain, and Learn is a supporting diagnostic (§3);
- procedural supersession: a Learn chain (§3);
- poisoning by an ordinary user: a Learn chain (§3);
- attestation twins: a Rachael diagnostic (§5.1a);
- standing rules after compaction and a swap: the stress conditions place it in the Survive stage, which is diagnostic (§3). Tuesday's plain standing-rule bundles stay in Act.

Spatial memory waits for E1 (§11.3).

### 11.3 World profiles: the roadmap
**Admission rule.** A World profile is admitted only when it exposes a memory question that the Text and Image profiles cannot.

- **E1, robot vacuum.** A candidate chosen from the robotics survey, confirmed by an E1 spike before any commitment. It is an event-sourced 2D home with partial observation and high-level actions.
  - An event scheduler compresses idle time.
  - Programming the body is allowed, not required; agent-written routines count as memory.
  - It includes a two-vacuum fleet cell.
  - Body events join the Survive stage.
- **Hands** is scored inside admitted World profiles, after v1.
- **E2, desk arm:** a MuJoCo SO-101 candidate, also confirmed by a spike before any commitment.
- **Physical path, design only:** a small Hands subset on a low-cost desk arm (SO-100 class, via LeRobot) with a fixed tabletop scene. Objects are moved between sessions, and the arm must later retrieve or report them. No hardware is bought without the owner.
- **Board path:** Mac-feasible engines and commercially usable assets only, so NVIDIA-only simulators cannot be on it. Richer worlds draw on the survey's other candidates (Habitat, AI2-THOR/ProcTHOR, BEHAVIOR, ManiSkill, Genesis), with no commitment now.
- **The richer worlds:** procedurally generated homes and workspaces where residents follow schedules. They move objects, interrupt, and leave and return, over simulated weeks to months. Ground truth is the simulator's own state log.
- **Reporting:** simulated span, evidence volume, controller steps and real elapsed time are reported separately.

**Long horizons and streams** (the research tier, §9.2):
- a long-horizon run size of at least 10M tokens;
- a continuous-stream item. What streams add: real-time answering windows (TeleEgo-style), memory persistence over days, and accuracy against bytes stored per simulated day.

The design is kept now; capture waits for measured use.

**Research-tier extensions:** on-device budgets, and live segments that re-plan the rest of a life (§6.1). v1.4's multi-agent shared memory and adversarial writers are now Learn cells (§3): shared memory with mid-life revocation, and poisoning by an ordinary user.

**Requirement notes:**
- **Addendum B, Hands:** met later than v1.4 planned. Hands is scored inside admitted World profiles after v1, and spatial memory leaves season 1.
- **Addendum F:** met. E1 and E2 are candidates from the survey, and each is confirmed by its own spike before any commitment. Embodied work goes through simulation first, and the physical desk arm stays design only, beside E2. The board path's Mac-feasibility rule narrows the survey's candidates; it commits to none.
- **Original brief, horizon** ("from 100K tokens to beyond 10M"): met by the research tier's long-horizon run size.

## 12. Statistics and pre-registration
All frozen statistical quantities are in PREREG §2 and §7. This section explains them.

**Certification** (§7.7) is a separate per-system statement with its own frozen rules (PREREG §7). The board's paired statistics below are unchanged in v2.0, and they remain its statistical claims.

**The estimand.**
- **Headline:** H_s is the equal-weighted mean of the track scores T_{s,t} over the n_T included tracks.
- **Track score:** T_{s,t} is the mean, over the lives 𝓛_t where track t is measured, of each life's mean twin-min bundle score.
  - It covers the track's final scored distribution: memory-exclusive action bundles, five-class, in [−1, 1].
  - 𝓛_t is every life of the run, except Keep's. Keep's is the run's Keep subset: the board's n_keep lives, or the bar-2 run's four. There Keep scores ¼·K100 + ¾·K10. The c_l reweighting below covers it, and bar 2's sign rule counts every life's c_l. Bar 1 scores Keep at K100 on every life.
- **Per-life contributions** for a pair (a, b):
  c_l = Σ_t (1/n_T) × (|𝓛| / |𝓛_t^{ab}|) × 1[l ∈ 𝓛_t^{ab}] × (T_{a,t,l} − T_{b,t,l}).
  - Both systems' track scores are computed on the bundles valid for both, and 𝓛_t^{ab} is the set of lives with at least one such bundle.
  - The mean of c_l equals the pair's headline difference on that common set.
- **Keep's precision.** Keep enters at the same weight as every other track, from fewer lives. That puts a floor under the variance of the headline difference, which is why n_keep grows with n_L (§6.10) and is disclosed.

**The primary test.**
- **Test:** a two-sided sign-flip permutation test on the c_l (exact when n_L ≤ 20, otherwise 100,000 draws with a fixed seed), at α = .05.
- **CI:** a wild cluster bootstrap over lives (Rademacher weights, 10,000 resamples).
- **McNemar** is descriptive only.

**The confirmatory family on the board** *(pre-reg)*:
- **Membership:** each current real system against one pre-named neutral reference, Hermes native memory, under the pinned agent family. LCM-X at its last release before the public generator is **not** in the family; it is a secondary contrast. With the minimum Phase 1 roster (LCM-X, Hermes native and 3 external systems), M = 4.
  - All pairs would cost lives without giving a cleaner claim: going from M = 10 to M = 4 saves about 16% of the lives where the 24-48 clamp does not bind.
  - A fixed testing sequence would put the closest pair, LCM-X against its previous GA, first. That pair usually fails, and it would block the rest.
- **Correction:** Holm, with no fixed sequence and no sequential stopping. With shared lives the board waits for its slowest contrast, so the expected saving is small, and estimates from stopping early are biased upward.
- **Declared secondary contrasts,** each reported with its achieved MDE:
  - LCM-X vs LCM-X at its last release before the public generator, on every board (the tuning detector);
  - LCM-X vs its previous GA, on delta boards.
- **Every other pair** is exploratory, with a CI. Tracks are tested only for family contrasts whose headline separates (gatekeeping), with Holm within the contrast.
- **The bar-2 family** is the pairs excluding both LCM-X releases, M = 3. Under all-pairs Holm, a neutral pair's threshold loosened as LCM-X pairs rejected, which tied the neutral check to LCM-X's data.
- **Controls:** comparisons with controls are reported, not confirmatory. The exceptions are bar 1, its companion, and the inclusion and ablation tests.
- **Attainability:** exact two-sided sign-flip floors are 2/2^{n_L}: .0005 at n_L = 12, .002 at n_L = 10, and .00003 at n_L = 16.

**Power and life count.**
- **Units:** headline percentage points.
- **σ_d [pilot]:** the median, over the bar-2 family's pairs, of the SD of their c_l on the bar-2 run.
- **The rule:** n_L = clamp(⌈((z_{1−α/(2M)} + z_{0.8}) × σ_d / 8)²⌉, 24, 48), with M frozen in PREREG-v1.
  - It sizes the first, Bonferroni-strict Holm step for 80% power at 8 points.
  - It is a resource rule built on a normal approximation. Bar-2 lives are shorter than full lives, so σ_d may not transfer; the gap is disclosed.
  - **More bundles per life** lower only the sampling-noise part of σ_d. The variance between lives is bought with lives. Bundles per life are therefore a [pilot] value. PREREG §10 freezes the rule in v0: the smallest value in {100, …, 300} at which sampling noise is at most one third of the per-life variance, estimated from non-LCM-X pairs.
- **Always disclosed:** the achieved Holm-adjusted MDE, simulated on the full-tier c_l.
- **For scale:** the reviewers' estimate for 24 lives is an MDE of 8-13 points.
- **Certification's n.** Certification is issued only on the board, at the powered size that PREREG-v1 sets from the operating-characteristic simulation. n_L ≥ 24, b = 150 and a per-cell SE of about 5 or less are planning values (§7.7). The bundle rule above sizes b for the paired family; a board below certification's powered size issues no certificate, and its results are still published.
- **Requirement note** (brief, a full tier "statistically powered with paired tests"): met as before by the paired confirmatory family. Certification adds its own power condition on the board.

**The replication family** is a replication row (H^rep) from the seasonal robustness study: the study's 8 lives, the included tracks, and Keep at K100 only, for both families. It is never pooled, and a sign reversal against the matched pinned-family difference flags the pair (§6.2c).

**Reruns** belong to the seasonal robustness study. Every fault point there runs q = 3 times with jittered timing, and a 10% subset of the study's probes runs twice to give the A/A′ variance.

**Calibrating "hard for everyone"** *(pre-reg)*:
- **The shape** of the lever mix (which levers, in what proportions) is frozen in PREREG-v0.
- **The scalars.** The pilot sets one difficulty scalar per track, on **system-agnostic anchors** only: oracle evidence at least 75, and the best of naive RAG, BM25, grep and recent window at most 35, both in raw penalised points (PREREG §2). They are set from controls on the full-length calibration set and validated on controls over the bar-2 lives, so they are set at the full tier's scale.
- **No real system's score** enters calibration, both LCM-X releases included. Difficulty is frozen from controls only, and **no target or veto is set on any real system's results**.
- **Rungs** (§4.6) are calibrated on system-agnostic anchors too: the no-memory floor, oracle evidence and naive RAG.
- **Honest zeros.** Valid zeros are published, including all-zero rows.
- **The launch figure** is the highest system figure of **per-item action accuracy** (§7.1a) among real systems on the full-tier board, in the Text profile. It is published beside the penalised score, whatever its value (PREREG A3). Below about 60% for the best system is the disclosed expectation, never a release condition, and the test is not tuned toward it.
- **Requirement note** (addendum J, full-tier difficulty; brief, hard for everyone): met by measuring and publishing the launch figure on per-item action accuracy, beside the penalised score, whatever its value. It is never a release condition, so no real system's score can veto a release.

### 12a. Failures and missing data *(pre-reg)*
Every assigned bundle ends in exactly one class:

| Class | Treatment |
|---|---|
| scored | as scored |
| **FAIL_TASK** | 0 |
| **SYSTEM_FAILURE**: the system under test crashed, timed out inside the declared limits, made an out-of-contract request, violated a resource limit or refused, whichever component reports it | 0 |
| **INFRA_FAILURE**: a benchmark-owned component (director, runner or sandbox) failed, or a benchmark-owned precondition voided the item, as the ledger shows, with the system inside its contract | rerun at most twice; if it still fails, the bundle is **BLOCKED**: excluded for every system in that comparison, and never charged to the system |
| **N/A_EXPOSURE** (§6.4) | excluded for that system; cross-harness pairs use the common-exposure set |
| **N/A_CLOCK** (§6.6): a skew-audit failure or a wall-compressed row | excluded from time-dependent bundles for that system; pairs use the common set |
| **N/A_READER** (§6.4; Image profile only) | excluded for that system; in a required cell it blocks certification (§7.7) |

**Attribution follows cause, not reporter.** A failure the system causes is SYSTEM_FAILURE even when the director, runner or sandbox is the component that reports it: a crash, a timeout inside the declared limits, an out-of-contract request, a resource-limit violation or a refusal. INFRA_FAILURE needs the ledger to show a fault in a benchmark-owned component, or a failed precondition the benchmark owns, with the system inside its contract.

**Cell-level non-results** (§7.7): **N/A** for a cell outside the declared profile, and **BLOCKED** where infrastructure failed. "Unsupported" is a cause label on a scored result, never a non-result.

**Coverage.**
- Denominators are the assigned bundles.
- The card reports completion and eligibility per system, plus a **worst-case row** in which every SYSTEM_FAILURE scores −1. BLOCKED bundles are shown in it and never charged.
- A headline rank is valid only with at least 95% coverage and no more than 5% infrastructure exclusions.
- **For certification,** a required cell whose coverage falls below 95% through the system blocks it. A shortfall caused by infrastructure reads BLOCKED, and a BLOCKED required cell defers it (§7.7).

**Pre-registration.** PREREG-v0.2, then PREREG-v1, is the normative record. Both freezes are committed with a timestamp, and each hash is posted on #1964. Later changes are versioned and disclosed (§14).
- PREREG-v0.2 freezes the **rules**, not per-season contents such as the census (§11.2) and community templates (§10).
- **Requirement note** (addendum G, pre-registration): the rules are pre-registered as before. Per-season contents are met differently: they are versioned and disclosed each season, outside the pre-registration.

## 13. Cost model (formulas; spike S6 measures the inputs)
The formula, constants, ceilings and cut order are frozen in PREREG §11.

**Terms.** Per system and agent family, every cost term is a triple: requests, tokens and wall time. Each is counted by role: write turns, the system's own compaction and extraction, probes, and judging. Tokens are reported; they are never a ceiling.

| Term | Meaning |
|---|---|
| R | replay cost of one whole life |
| R_cap | replay cost of one whole life under a cap; the projection uses max(measured R_cap, R) |
| f | share of a life after the first flipped event (≤ 1) |
| P | probe cost of all bundles at the 4 checkpoints on one branch, including resume-only controls |
| r_c, p_c | replay from fault c to the next checkpoint, and the probes there, on one branch |
| P_K | probe cost of Keep bundles only, on one branch |
| P_W | probe cost of Wake swap bundles only, on one branch |
| R_B, P_B | replication-family replay and probe costs |
| C_learn | Learn chains on one study life, one per applicable Learn cell (3 in a G1 life, 4 in a G2 life), with their no-memory and frozen-skill arms |
| C_erase | the erasure probes on one study life, one per scored Keep forget bundle, capped at 6 |
| C_image | the Image profile board for one system, both views, including the vision reader: L_img × [R_img(1 + f) + 2P_img], plus vision-provider spend |
| R_img, P_img | replay cost of one Image-board life, and probe cost of its image bundles on one branch |
| C_cross | one crossover-panel row on the Ring 0 Act packs |
| C_marker | the raw-archive marker for one season, including its K10 run |
| C_aa | the bar-2 run's A/A′ rerun of the control arms |
| C_ring1, C_ring2 | one Ring 1 run, and one organisation's monthly Ring 2 check |

**The added workloads** have the C_ terms above. Each value is filled from S6, S8 or the pilot; until then it is a placeholder. They count as follows:
- **per system, in the robustness study:** C_learn and C_erase on each study life, since Learn chains and the erasure probes are terminal forks there (§6.10);
- **per system, on the Image profile board:** C_image, once the profile is on the board, as a run separate from the Text board (§11.1);
- **shared controls:** C_marker once per season (§8), C_aa once per generator version (§9.2), and C_cross for each crossover-panel row once per season, after the sealed board closes, plus once when a new PREREG version is frozen (§6.9). The panel runs in its own 24-hour window, never inside a system's board window;
- **recurring:** C_ring1 at each benchmark release and at least monthly, and C_ring2 once per organisation per month (§10).

From the inventory in §6.10, the costs per system are (PREREG §11 is normative):

  Cost_board = n_L × [ R(1 + f) + 2P ] + n_keep × [ R_cap(1 + f) + 2P ]

  Cost_rob = n_rob × [ Σ_{c=1..3} 2q(r_c + p_c) + R_B(1 + f) + 2P_B + δ_W(R(1 + f) + 2P_W) + 0.2P + C_learn + C_erase ] + n_curve × 2(R_cap(1 + f) + 2P_K)

  Cost_image = C_image = L_img × [ R_img(1 + f) + 2P_img ] + vision-provider spend, per system, when the Image profile is on the board

- R includes the board's inline fault and the swap. n_rob = 8 (4 after the cut), q = 3, n_curve = min(n_rob, n_keep), and δ_W = 0 when the swap model is from the replication family.
- L_img = 8 and b_img = 40 are planning values (§11.1). The vision-provider spend is within the owner's seasonal vision budget.
- **The 24-hour projection** counts every term that runs on the agent's model lane in the same window as a board: the board and study terms, plus the shared and recurring terms scheduled in that window, at the measured concurrency (C-11). The Image board is its own 24-hour run per system, and the crossover panel has its own window (§6.9), so neither is counted inside a system's board window.
- The runs of record (bar 1, bar 2) and the calibration set have formulas of their own in PREREG §11.

**Projection, mid band** (estimates from the first-principles review's assumption bands; S6a and S6 replace them):

| | v1.2 | Now |
|---|---|---|
| Per system on the board | about 4,600-6,700 sequential h | about 360-430 sequential h: ≤ 24 h at the concurrency S6a measures (C-11; v1.4 assumed about 16-20 concurrent jobs), with about 5 assistant turns per scripted session so each life's write-turn chain stays near 3 h |
| First board of a season, 5 real systems plus controls | about 171 machine-days | about 19 machine-days at 8 jobs |
| A delta board, with the previous version re-run alongside | — | about 3-4 machine-days |
| An extraction competitor on its vendor's models, per board | about $2-5K | about $0.1-0.3K |

**After these cuts probes dominate,** at about 2/3 of a system's hours. Further cuts therefore come from the probe side: bundles per life and cost per episode.

**Spikes:**
- **S6a** replays one 10-session micro-life on Hermes native, in hours. It measures replay time, write-turn and summariser calls, probe latency, lane concurrency, the harness overhead behind the developer windows, and whether parallel sandbox roots work.
- **S6** replays one full-scale life (about 200 sessions) on Hermes native and on one extraction competitor, once uncapped and once at the K10 cap. It runs at the PREREG A1 size (about 1M tokens plus at least 8 long sprints of at least 1.25 W), measures the 24-hour rule there, and measures every term by role, Learn chains and image cells included.
- **Replication-family terms** are measured on one life, or taken as the pinned family's costs × the price ratio.

**The 24-hour rule is sized by measured concurrency:** the sustained concurrency of the pinned agent family's model lane, as the spike on that lane measures it (S6a or S6b; completion slot C-11), with GLM-plan use paused while the busy marker's `glm` field is true. There is no credits slot.

**Ceilings and cuts** are in PREREG §11:
- the board and the robustness study: **≤ 24 h wall clock** (the 24-hour rule) and ≤ $300 per system each. Token counts (v1.4's ≤ 3B input and ≤ 100M output) are reported, never ceilings;
- the Image board: ≤ 24 h wall clock per system, as a run separate from the Text board;
- the bar-1 run: ≤ 8 h for all arms;
- the bar-2 run: ≤ 8 h per real system;
- the calibration set: ≤ 24 h.

**Go / no-go** is pilot bar 5: the projection "fits the 24-hour rule at measured concurrency", and the paid-lane spend and wall-time ceilings above hold. It is evaluated at the end of S6 with n_L = 48 for the board and re-checked once n_L is known. The cuts apply in this order:
1. bundles per board life, down to 100;
2. the robustness study, down to 4 lives;
3. n_L, down to 24.

A cut that leaves a season below certification's powered size (§7.7) means no certificate that season; its results are still published. If the projection still does not fit, the design returns to the owner.

**Generation** is a separate row: rendering cost per life × lives per season, run in a batch window off the build lanes.

**Machine envelope.**
- The ledger is content-addressed and zstd-compressed.
- Runs refuse to start below 150 GB of free disk.
- Heavy work gates on the gauntlet's timed-row marker, not on load average.
- CPU-bound jobs and model-wait jobs are counted separately.
- A failed session resumes from its last snapshot.

**Lanes.**
- Readers, summarisers and renderers run on subscription lanes first.
- Paid rows are labelled and capped: the third blind-panel family, extraction competitors' vendor models, the replication family, and the pinned vision reader (§11.1).
- **The vision slot's cost** is about $50 a season, the owner's call at the PREREG-v0.2 co-sign.
- Every run reports its spend, and its tokens by role.

## 14. Firewall and credibility
- **Separation.** This benchmark's design, data and runs are separate from LCM-X development. The benchmark session does not tune, patch or advise on LCM-X internals.
- **No shared code.** Bicentennial copies no LCM-X code. Instruments LCM-X built for its own testing are cited as prior art and reimplemented from specs.
- **Equal terms.** Every system, LCM-X included, is driven only through its public surfaces and documented configuration, pinned to a released artifact, within the same configuration budget.
- **Private data stays private.** LCM-X developers and lanes never see private seeds, private templates or per-item private results (§10).
- **Freeze before data.**
  - PREREG-v0.2 is frozen and hashed before the first real-system pilot run. It includes the code that computes every [pilot] value and the write-turn package.
  - PREREG-v1 is frozen before **any** system's first full-tier run.
- **Blinding.** Pilot analysis runs on blinded system codes until the [pilot] values are committed.
- **LCM-X never sets the test.**
  - Every [pilot] value is computed without either LCM-X release's data: lever scalars, track inclusion, life count and any later IRT selection.
  - Bar 1 has a neutral companion test (§15).
  - Calibration uses system-agnostic anchors only (§12), and so do the rungs (§4.6). The raw-archive marker is never an anchor (§8).
  - Cells come from the tasks. The capability census only annotates them, and it never changes whether a cell is scored, required or included (§11.2). No system's results select or remove cells.
  - No target or veto is set on any real system's results. LCM-X's zeros are reported, never targeted (§12).
  - If LCM-X alone fails bar 1, that is reported as a finding and never triggers a redesign keyed to LCM-X.
- **Purpose order.** "Help build LCM-X first" sets the first user and the problem classes. It does not set the measurement.
  - LCM-X improves only through outputs every registered system gets on equal terms: public packs, Ring 1 results, Ring 2 bits per organisation, and published cards (§9.1, §10).
  - The benchmark session runs nothing on LCM-X beyond the scheduled runs every system gets, and never advises on its internals.
  - The acceptance bar (§9.3) is shown on the benchmark team's own baseline, never on LCM-X.
- **Approval and veto.** The benchmark session approves the design and each PREREG freeze, and the owner co-signs each freeze hash (§16).
  - An external reviewer with a veto over scoring is recruited before PREREG-v1, and the owner decides who. Until one exists, every adversarial review of this design must test for self-serving construction.
  - The capability map's stages (DV1), the verdicts and non-results (DV4), and the gates and certification rule (DV5) go to that reviewer before PREREG-v1.
- **Production agents.** Bicentennial never runs against any live production agent. Any later test of one is an offline replay of a copy, with owner approval at that time.
- **Openness.** The harness, adapters and public lives are open. Competitors are run with their vendors' best documented configuration. Results are published where LCM-X loses.
- **Requirement note** (addendum G, the firewall): met as before. The owner's purpose order sets the first user, not the measurement.

## 15. Phase plan, done-when and exits

| Phase | Content | Done when |
|---|---|---|
| 0 (by about 2026-11-09) | survey, taxonomy, threat model, this design, three review rounds (Astra and an independent Opus red-team in round 1; targeted readbacks in rounds 2 and 3), a closure check, the first-principles cost review, and the v2.0 decisions with their reviews | design v2.0 and PREREG-v0.2 approved, with the owner's co-sign of the v0.2 hash; any overrun posted on #1964, with the cuts |
| Spikes | S1 role classification; S2 clocks; S3 clones, including parallel per-worker sandbox roots; S4 Claude Code against the director, which also names the swap model; S5 surfaces and entrypoints, extended by the capability census; **S6a one 10-session micro-life**; **S6 one full-scale life**, at the PREREG A1 size, uncapped and at K10; **S7 write turns**, plus the passive-pacing check; **S8 images**, an image rendered from world state routed through the director in both Hermes vision modes, with its direct-evidence control | S6a and S6 measurements in hand for bar 5; S7 shows agent-curated memory working in replay, with the write-turn boundary confirmed by readback; S8 passes, or the Image profile stays pending |
| Pilot (timebox re-planned after S6 and S8, from the first plan's 3 weeks from approval; posted on #1964) | Developer tiers T0 and T1 first, then T2, T3 and the fault finder, as the Ring 0 packs with their rungs. The Image profile in Ring 0 once S8 admits it; Learn chains as a diagnostic. The calibration set, then the bar-1 and bar-2 runs of record. G1 and G2, both evaluations. The roster: both LCM-X releases, Hermes native, ≥ 2 external self-hosted competitors, and every §8 control. Wake, Drift, Tuesday, Rachael and Keep. Flatten is not in the pilot; its map row reads "not yet built" | the bars below |
| Pre-registration | PREREG-v1 approved and committed | before any full-tier run |
| Phase 1 build (targeted alongside LCM-X v0.30.0, not gated by it) | the full core board for G1 and G2 in the Text profile, text and code; the Image profile's board in season 1 only if S8 and the pilot's validity checks pass, otherwise in season 2 (§11.1); the seasonal robustness study; the developer rings and tiers shipped with the harness, with Ring 1 and Ring 2; the capability census; one results table with full stack identity, the crossover panel and the stack view; director; Hermes and Claude Code adapters; ≥ 3 external competitors; the replication family; the seal | the launch figure, the highest real system's per-item action accuracy on the full-tier Text board (§7.1a), measured and published beside the penalised score whatever its value: below about 60% is the disclosed expectation, never a release condition, and the test is not tuned toward it (§12); the acceptance bar (§9.3) met before v1 is called a developer product; Codex adapter next |
| After v1 | World profiles from E1 (§11.3); the lab slice (§6.9); the research tier's long-horizon run size and continuous-stream item | E1 once its spike shows a memory question the Text and Image profiles cannot expose; continuous-stream capture after measured use (per #1719) |

**Pilot acceptance bars** *(the normative text is PREREG §8; all required)*. Bars 1-3 keep their own statistics, independent of the capability map and of certification:
1. **Smoke separation**, addendum bar 1, kept as written, on the bar-1 run (§9.2), the smoke tier's separation run of record. Every bundle there skips filters 2 and 4. LCM-X separates from the no-memory floor: life-level sign-flip, p < .05, on the per-life equal-weighted mean over the five candidate tracks, with Keep at K100 (PREREG §8).
   - **Neutral companion:** on the same lives and sample, oracle evidence and naive RAG must each separate from the no-memory floor.
2. **Dev separation**, addendum bar 2, on the bar-2 run (§9.2), the dev tier's separation run of record, over 16 lives:
   - **A pair excluding LCM-X:** at least one pair in the bar-2 family separates on the headline (Holm over that family only, M = 3; the same sign in at least 80% of lives).
   - **Known-order ablations:** both come out in their validated direction (§8; p < .05 each). They are validated before the PREREG-v0 freeze, on the calibration set, and contrast (b) uses only bundles whose history fits the reader's window. A contrast that fails validation is dropped.
3. **Inclusion.** At least 3 candidate tracks pass the inclusion rule:
   - not near-solved, on the calibration set's unfiltered sample: RAG_raw < floor_raw + 0.70 × (ceiling_raw − floor_raw), and floor_raw < 0.70 × ceiling_raw, on its controls in raw penalised points;
   - oracle evidence separates from no-memory, on the bar-2 run's control arms;
   - valid.

   These are computed from controls only, and a track that is hard for everyone stays in. Cell admission (§7.7) is a separate test, per cell and on its own sample.
4. **Validity**, on every included track's final scored distribution:
   - every §5.3 gate holds: the battery, the minimum shares, the Drift mix and the salience gate;
   - the template census passes, and the pilot instance audit (75 per track, clustered bound) is at most 10%;
   - check error rates are each ≤ 2%;
   - verifier recall is ≥ 0.90 per class, with a Wilson lower bound ≥ 0.80.
5. **Cost.** The S6a and S6 projection fits the 24-hour rule at measured concurrency, and the paid-lane spend and wall-time ceilings hold (§13). Token counts are reported, never a bar. The developer-tier targets are not bars; any that are missed are disclosed.
6. **Correlation.** API mode vs system is measured per comparable pair, with no bar. Proxy status needs the §6.1 criterion.

**Labelling.** If no human grader pool exists by pilot time, the pilot is labelled a **feasibility pilot**, and it cannot claim the binding gate.

**When bars fail:**
- **Ordinary inclusion vs the failed-pilot fallback.** "A track that is hard for everyone stays in" governs ordinary inclusion. The addendum's exit rule is a separate fallback, which fires when the bar 1 companion or bar 2 fails. Bicentennial then narrows before Phase 1 is built:
  - **The candidate.** It keeps the tracks where oracle evidence separates from the no-memory floor and at least one pair excluding both LCM-X releases separates. They are written down as PREREG-v0-narrowed, computed without LCM-X.
  - **Fresh evaluation.** The selecting pilot cannot also prove the narrowed design. PREREG-v0-narrowed needs a fresh, frozen acceptance run of bars 1-5 on new public seeds that played no part in the selection.
- **The claim contract** (PREREG A2):
  - with Wake on the board, the headline may be described as measuring whether the agent "wakes up as itself and acts on the right memories";
  - if the pilot exit drops Wake, the headline is labelled a **memory-action score**, and no text, page or paper may then claim it measures waking up as itself.
  - **Requirement note** (addendum B, Wake): a disclosed weakening only if the exit drops Wake; the claim contract keeps the words honest.
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
- the replication family;
- the seal;
- probe packs, the fault finder, the repro command and the developer report;
- the verdict and certification engine, and gate calibration on the board's control arms;
- the ring infrastructure: Ring 0 rungs, the Ring 1 schedule, the Ring 2 held-out family and its bit;
- repro classes and guarded autonomous loops;
- the Image profile's renderer, exposure manifests, vision slot and shortcut checks;
- Learn chains;
- the erasure probes;
- the capability census;
- the results table with stack identity, the crossover panel and the stack view;
- the raw-archive marker;
- community intake.

Pilot cut order if the timebox binds: the LLM renderer (template renders only), then the controls the addendum does not require.

## 16. Approval and channels
- **Ownership.** The benchmark session owns this design.
- **Approval.** The benchmark session approves the design and each PREREG freeze, under the owner's grant of 2026-10-26, which replaced the integration-owner approval in the original brief. The owner co-signs each freeze hash on #1964. PREREG-v0.1 was frozen on 2026-10-26. PREREG-v0.2 carries v2.0's rules; it was frozen on 2026-10-26, after the owner approved design v2.0, and the owner co-signs its hash; the completion record comes before the first real-system pilot run; PREREG-v1 comes before the full tier.
- **External veto.** An external reviewer with a veto over scoring is recruited before PREREG-v1, and the owner decides who. PREREG-v1 is not frozen without one unless the owner waives that in writing. DV1, DV4 and DV5 go to that reviewer first (§14).
- **Channel.** #1964 is the status channel, not an approval point.

**Owner-private decisions:**
- the public repository (approved and created: `bicentennial`);
- a public leaderboard;
- external partners: the external reviewer, vendor configuration windows and the human grader pool;
- sealing infrastructure (§10);
- spend above the standing limits (§13 paid rows);
- the vision budget, about $50 a season, at the PREREG-v0.2 co-sign (§11.1).

## 17. Open questions (for the spikes and the pilot)
1. **Hermes entrypoint:** can its documented production entrypoint be driven deterministically by the director, or does the pilot fall back to the CLI, with disclosure? (Spike S5.)
2. **Clocks:** if spike S2 fails for a C-level time source, the affected rows become N/A_CLOCK for time-dependent bundles. Is the remaining coverage enough for a headline rank, and for 95% coverage in every required cell (§7.7)?
3. **Third blind-panel family:** which family, at what single-call cost?
4. **Human grader pool,** an owner decision. It covers the template census, the pilot instance audit (75 bundles per track), the release audit (200 per track) and the 200-item image human-key sample (§4.4).
5. **Template counts:** can every track reach the minimum of 25 template versions for the pilot audit and 40 for release (PREREG §5), or do some tracks need more templates before the pilot?
6. **Variance inputs:** what are the twin correlation and the within-cell and cross-cell life correlations? They are measured on the bar-2 run's control arms with one A/A′ rerun, before the PREREG-v1 freeze gate, and the operating-characteristic simulation sets the final certification numbers from them (§7.7). The per-rung A/A′ flip rate (q₀) is measured before any loop claim (§9.1).
7. **Loop time:** what does each developer tier take, idle and busy? It is measured and published per tier (§9.1), replacing the T1 projection.
8. **Images:** does spike S8 route an image through the director in both Hermes vision modes, with its direct-evidence control clearing the no-memory floor, at a cost inside the vision budget (§11.1)?
9. **Learn chains:** what do they cost on the 24-hour critical path? (Spike S6.)
10. **E1, after v1:** does the E1 spike find a memory question the Text and Image profiles cannot expose (§11.3)?
