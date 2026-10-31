# Binding requirements

These are the requirements Bicentennial's design answers to. They summarise the original brief and its binding addendum, and the pre-registration calls this document "the addendum". Where the design changes how a requirement is met, `docs/DESIGN.md` says so and the pre-registration records it.

**Precedence (from the addendum).** When the brief and the addendum conflict, the addendum wins on what the benchmark measures, how it is scored and what counts as done. The brief still governs authority, spend, machine sharing, public text and prohibitions.

**In v2.0.** This version adds the passages of the brief and the addendum that the earlier summary omitted, quoted from the originals. Under each requirement whose means design v2.0 changes, a *How v2.0 meets it* note says how, citing the v2.0 decision (DV1-DV41, recorded in [`docs/DECISIONS-v2.md`](DECISIONS-v2.md)). The notes explain; they never relax the requirement above them, and the requirement text stays binding as written.

## Mission (from the brief)
- **The reference.** Design and build the benchmark that defines memory for long-running agents, the one others measure against.
- **Range.** It should cover today's coding and assistant agents and reach future androids and robots that live for months on continuous multimodal streams.
  - *How v2.0 meets it:* results are a capability map of track rows × evaluation profiles (DV1, DV2). Text is the core profile; Image is the Perceive profile, admitted through spike S8 (DV9); World profiles from E1 onward follow v1 as a roadmap (DV15). A long-horizon run size and a continuous-stream item sit in the research tier on the roadmap, with the design kept now and capture after measured use (DV22).
- **Versions.** There should be a version for fast testing, one for design iteration, and one for full measurement:
  - **smoke:** minutes, runs in CI, deterministic;
  - **dev:** about an hour, paired against a baseline;
  - **full:** release and board grade, statistically powered with paired tests;
  - **frontier:** weeks to months of simulated time, multimodal and embodied.

  Every tier reports cost per run and runtime.
  - *How v2.0 meets it:*
    - **smoke and dev** are the developer tiers T0-T3, served as Ring 0's fixed public packs. Loop time is measured and published per tier (DV8).
    - **full:** the paired confirmatory family is unchanged and remains the board's statistical claim. Certification is a separate per-system statement on Act, issued only on a sealed board (a season board, or a delta board when powered) at the pre-registered size, and its pass share under the bootstrap (certification stability) is printed on every card (DV5, DV33). n_L ≥ 24, b = 150 and the per-cell SE bound are planning values until PREREG-v1, whose operating-characteristic simulation on the penalised scale sets the final ones. A season cut below the powered size issues no certificate, and its results are still published (DV26). In season 1 the Image profile's separate board runs at a planning size of 8 lives × 40 image bundles; at that size it publishes cell verdicts and diagnostics and issues no certificate (DV38).
    - **frontier** is named the **research tier** (DV20). It holds the ≥ 10M-token run size and the continuous-stream item (DV22). Run size is the tier; modality and embodiment are evaluation profiles that qualify it (DV2).
    - **cost and runtime:** every profile declares its operating metrics (DV2), and the run-time rule for the full-tier runs (every replaying arm's run of a life within 24 h, and each system's work within a work bound in each of its board, study and Image board runs, in locked, resumable segments) is sized by the measured capacity of every lane a run uses (concurrency or a paced request rate per account), with token ceilings report-only (DV18, DV42, DV47). The added workloads (Learn chains, erasure probes, the Image profile's two views, the crossover panel, the raw-archive marker, the bar-2 A/A′ rerun, and Rings 1 and 2) are explicit cost terms, each filled from S6, S8 or the pilot; pilot bar 5 checks the run-time rule plus the paid-lane spend ceilings and the pilot runs' wall-time ceilings (DV32, DV47).
- **Real harnesses.** Runs go through actual agent harnesses, with tool calls, retries, crashes, restarts, compaction under pressure, and fault injection.
- **Losslessness and provenance** (from the brief's design requirements). "Questions require citing the exact original turn or event, surviving restarts and rollbacks, and handling superseded facts."
  - *How v2.0 meets it:* the **Remember** stage asks direct questions with citations across restarts and gaps, and the **Survive** stage asks them again under corrections, compaction, crashes and swaps (DV1). Under the precedence rule, addendum C decides what is measured: these stages stay diagnostic, and the headline and certification are on **Act** (DV1).
- **Horizon headroom** (from the brief's design requirements). "From 100K tokens to beyond 10M, and from days to months of simulated time."
  - *How v2.0 meets it:* a full-tier life is about 200 sessions over simulated weeks to months, sized by a count of long sprints (at least 8 per life, at least one per 25-session block, each at least 1.25 W), so tokens per life are about 1M plus the sprint tokens (DV19 A1). A long-horizon run size of at least 10M tokens sits in the research tier on the roadmap; its design is kept now, and it is built after measured use (DV22).
- **Modalities** (from the brief's design requirements). "Designed now and built in stages: time-indexed events with provenance for text, code execution, screenshots, images, audio, video, sensor and pose streams. Build capture only after measured use (#1719)."
  - *How v2.0 meets it:* text and code execution are the Text profile. Screenshots and images rendered from world state are the Image profile, admitted through spike S8; audio and video follow the image loop (DV9). Continuous-stream capture still waits for measured use (DV9, DV22).
  - **Recorded change:** the owner's direction of 2026-10-26, to test capabilities such as images that systems lack, moves rendered images ahead of "build capture only after measured use" (DV9). The images are rendered from world state, never by an image generator.
- **Hard for everyone.** Frontier systems, including the benchmark maintainers' own, should score well below ceiling at the full and frontier tiers.
  - *How v2.0 meets it:* difficulty is frozen from controls only, and no target or veto is set on any real system's results. Valid zeros are published, including all-zero rows (DV21).
- **Credibility** (from the brief's design requirements):
  - "frozen, held-out test seeds";
  - "an open harness and adapters";
  - "baselines for at least 3 competing memory systems, run by us and reproducible by them";
  - "results published where we lose too";
  - "an external co-maintainer if possible".
  - *How v2.0 meets it:* the seeds, the seal and the open harness are unchanged. Every scheduled run is published, and so is every valid zero (DV21). The external reviewer with a veto over scoring (G below) stands in until a co-maintainer exists. Developers of every registered system, LCM-X included, get the same outputs on the same terms (DV8, DV23).

## The addendum (binding on what is measured, how it is scored, and what counts as done)

**A. Shape and north star.**
- A full run is a generated *life* of about 200 sessions, not one long transcript.
- Restarts, compaction, model swaps, corrections and gaps of days or weeks are first-class events in that life.
- The north star is whether a long-lived agent **wakes up as itself and acts on the right memories**. Recall of trivia is not the goal.
  - *How v2.0 meets it:* the headline and certification are on Act, judged on the world's state; direct questions are the diagnostic Remember stage (DV1). The words "wakes up as itself" describe the headline only while Wake is included. Without Wake, the headline is labelled a memory-action score (DV19 A2, DV22).

**B. Tracks.**
- **Wake:** pickup after a restart, compaction, model swap or gap. A mid-life model swap is required in generated lives.
  - *How v2.0 meets it:* Wake keeps its row (DV22). Wake events under stress are reported in the diagnostic Survive stage, drawn from the existing robustness-study inventory; the whole-life swap-model comparator rule for swaps, and the rule that harness switches never enter the headline, are unchanged (DV1).
- **Rachael:** memory provenance, including detecting and refusing planted memories.
  - *How v2.0 meets it:* the planted-memory refusal stays in Rachael, and its uncertainty response stands (DV10, DV11). Attestation twins (signed and unsigned, under a declared trust policy) are a Rachael diagnostic outside the headline (DV13). Poisoning by an ordinary user is a Learn diagnostic beside it (DV10).
- **Tuesday:** prospective memory. The agent acts on commitments unprompted and on time, and timing is scored.
- **Drift:** supersession. The latest correction wins, stale facts are not resurrected, and time-to-correct is measured.
  - *How v2.0 meets it:* Drift's time-to-correct stays where it is. Procedural supersession is added as a Learn diagnostic beside it (DV10).
- **Hands:** embodied and spatial memory, at the frontier tier.
  - *How v2.0 meets it:* Hands is scored inside admitted World profiles, after v1 (DV15). Spatial memory waits for E1, so it is not in season 1 (DV3).
- **Flatten:** identity and behaviour stability, measured against the agent's own earlier behaviour.
  - *How v2.0 meets it:* Flatten stays deferred. Its row is shown on the map as "not yet built" (DV22).
- **Keep:** salience and consolidation (the addendum's wording): choosing what to retain under a storage budget, and forgetting on request.
  - *How v2.0 meets it:* Keep's salience and consolidation under budget stay in Keep (DV10), and its scored forget and budget bundles are unchanged (DV12). "Unsupported" is a cause label on a scored result, never an opt-out: a forgotten fact that resurfaces still costs −1, and a missed budget still scores 0 (DV4). Erasure across derived copies adds diagnostic probes beside Keep, never in place of its bundles (DV12).

**C. Grade actions, not quizzes.**
- Most of the full-tier score comes from task outcomes in which the memory is never named.
- Direct questions with citations are a diagnostic family.
  - *How v2.0 meets it:* certification is issued on Act only. Remember (direct questions with citations) and Survive are diagnostics that locate a failure; they never certify and are never part of the headline (DV1).
- Ground truth comes from the generator's world state.
  - *How v2.0 meets it:* Learn's chains keep generator-compiled ground truth; only the agent's own past actions come from the ledger (DV10). Image gold uses only values in the render's exposure manifest (DV9).

**D. Scoring.**
- An asymmetric penalty: a confident false memory costs more than an honest abstention, with pre-registered weights.
  - *How v2.0 meets it:* cell gates and certification are both computed on the **penalised action score** (the twin minimum with the asymmetric penalty). Gates and cell admission use its raw scale, −100 to +100, and so do track inclusion and every threshold of PREREG §2 and §9 unless labelled otherwise (DV35); the 0-100 scale, with the no-memory floor at 0 and oracle evidence at 100, is for display only (DV5, DV25). Per-item action accuracy is shown beside it, never in its place (DV5, DV31).
- Calibration is reported.
- Operating metrics on every tier: retrieval latency, store growth, time-to-correct and cost per run.
  - *How v2.0 meets it:* every evaluation profile declares its operating metrics, and every profile table carries them (DV2). Added turn latency joins them (DV19 A4). Ring 2's monthly bits are labelled as carrying no operating metrics.
- Exact or structured matching comes first. Pinned LLM judges with a placebo check are used only where needed.
  - *How v2.0 meets it:* Image-profile answers use typed envelopes, exact or structured first (DV9).

**E. Baselines in the pilot and in every published table:**
- the no-memory floor (same harness, memory disabled);
- the oracle ceiling (full history in context where it fits);
- naive RAG;
- a human key on a sample;
- at least 3 competitor systems.
- *How v2.0 meets it:* each evaluation profile declares its baselines before submissions, and every published table shows them: the no-memory floor, the oracle-evidence ceiling and naive RAG (DV2). In the Image profile the ceiling is the direct-evidence control (the original image handed over at question time), and naive RAG runs over the stack's own descriptions; legibility is checked by the agent reader ensemble (DV9, DV48). Learn chains add a frozen-skill arm beside the no-memory arm (DV10). The raw-archive marker is a display column, never a baseline used in gates (DV6). Every table also keeps E's full-history oracle ceiling where it fits, beside the oracle-evidence ceiling (DV33).
- **Recorded change** (owner, 2026-10-31): "a human key on a sample" is replaced by an **agent-key row** in every published table (DV48). The row is the auditor families' evidence-only answers, scored on the pre-quarantine distribution; a cell below 0.90 is flagged as a gold or render problem. Beside it go validation columns: the audit bound and procedure recall, the quarantine rate, the judge false-accept bound, the judged share, and the phrase-bank and legibility receipt hashes.

**F. Frontier, grounded.** Embodied work goes through simulation first. A path to a low-cost physical desk arm is documented, as a design only.
- From the addendum: "Choose the simulator from the survey; do not pre-commit." The physical path is a small Hands subset later, and there is "no hardware purchase without the owner".
- *How v2.0 meets it:* World profiles are a roadmap, and a profile is admitted only when it exposes a memory question the Text and Image profiles cannot (DV15). E1, a robot vacuum in an event-sourced 2D home, is a candidate chosen from the robotics survey and confirmed by an E1 spike before any commitment. E2 is a desk arm in MuJoCo (SO-101), and the physical low-cost desk-arm path stays design only. The board path admits Mac-feasible engines and commercially usable assets only (DV15). E2 also needs a confirming spike before commitment (DV33).

**G. Firewall.**
- The benchmark does not tune, patch or advise on the maintainers' own memory system.
- That system's developers do not see held-out full-tier seeds or answer keys.
  - *How v2.0 meets it:* "help build LCM-X first" sets the first user and the problem classes, not the measurement. LCM-X improves only through outputs every registered system gets on equal terms: public packs, Ring 1 results, Ring 2 bits per organisation, and published cards. The benchmark session runs nothing on LCM-X beyond the scheduled runs every system gets (DV23). Ring 2 reveals no seeds, templates or keys (DV8). Rungs are calibrated only on system-agnostic anchors, and the raw-archive marker is never used in gates, cell admission or rung calibration (DV6, DV7). The cell inventory comes from the tasks; the capability census only annotates it and never changes whether a cell is scored, required or included (DV3). Each profile's required Act cells are pre-registered from that inventory by the track design; the census label is display only (DV28). The developer-loop acceptance bar is shown on the benchmark team's own baseline, with no contestant system and not LCM-X (DV8).
- Metrics, weights, families and the seed policy are pre-registered with a timestamp before that system's first full-tier run. Later changes are versioned and disclosed.
  - *How v2.0 meets it:* PREREG, from v0.2 on, freezes the rules, not the per-season contents (the census, community templates) (DV24).
- An external reviewer has veto power over scoring.
  - *How v2.0 meets it:* the map, the verdicts and the gates (DV1, DV4, DV5) go to the external reviewer before PREREG-v1 (DV24).
  - **Recorded change** (owner, 2026-10-31): a Scoring Veto Panel of agents (C-18) reviews the map, the verdicts and the gates before each freeze, and a blocking finding from any one of its families blocks the freeze (DV48). Whether the owner's direction waives the external human reviewer was asked on 2026-10-31 and is pending. With the owner's written waiver on lcm-x #1964, the panel holds the veto alone; without it, the panel runs in addition to the reviewer.

**H. Real failures as seeds.** Real failure classes are rebuilt as **synthetic** generator cases. Raw transcripts, corpus text and personal data are never used.
- *How v2.0 meets it:* a community contribution is an executable template over a synthetic world, with its validity evidence on controls. It never carries raw transcripts, corpus text or personal data, and its admission never depends on any system failing (DV16).

**I. Production agents.** Bicentennial is never run against a live production agent. Testing one means an offline replay against a copy, with explicit approval.

**J. Done when.** All of these are required:
- **Phase 0 timebox** (from the addendum): "survey, taxonomy and design doc v1 within about 2 weeks of start. If it overruns, post why on #1964 and cut scope rather than extend silently."
- **Pilot acceptance:**
  - the smoke tier separates the no-memory floor from LCM-X, paired, p < .05;
  - the dev tier separates at least two real memory systems;
  - no headline family is near-solved by the no-memory floor or by naive RAG.
    - *How v2.0 meets it:* the test is also applied per cell. A cell is admitted only if the one-sided 95% lower bound of (raw ceiling − raw floor) is at least 30 points on the raw penalised scale (−100 to +100) and naive RAG does not CLEAR it; a cell that naive RAG clears is redesigned (DV5, DV25).
- **Full-tier difficulty:** at launch the best system, ours included, scores below about 60%. That is measured, and the test is not tuned toward it.
  - *How v2.0 meets it:* the launch measurement is taken on per-item action accuracy and disclosed beside the penalised score (DV19 A3). It is met by measuring and publishing that figure, whatever its value: below about 60% is the disclosed expectation, never a release condition, and the test is not tuned toward it (DV31). Per-item action accuracy is the share of action items whose decision-table outcome is the correct action; a late Tuesday action, partial credit or a confident wrong action counts as incorrect, and benign extras don't change it (DV31). Each base and twin item counts on its own. The items counted are the assigned action items in the Text profile's required Act cells: N/A, N/A_READER and BLOCKED items leave the denominator with their counts disclosed, as do N/A_EXPOSURE and N/A_CLOCK items, exactly as they leave the penalised score (DV45); a system failure (a crash, a timeout or a missing answer) counts as incorrect, whichever component reports it (DV43). A system's figure is the equal-weight mean of its cell accuracies, with a 95% CI, printed as incomplete when BLOCKED, N/A_EXPOSURE and N/A_CLOCK items together exceed 5% of its eligible items; the launch measurement is the highest figure among real systems on the full-tier board (DV34, defined normatively in PREREG §3). No target or veto is set on any system's scores (DV21).
- **Exit:** if the pilot does not discriminate, narrow to the families that do. In the addendum's words: "Do not build Phase 1 on a test that cannot tell systems apart."
- *Added by v2.0, not replacing any of the above:* before v1 is called a developer product, the benchmark team, acting as developer of its own baseline, shows the developer loop end to end within the declared T2/T3 budgets (DV8).

**K. Handback and approval** (from the addendum):
- "The benchmark session owns the design under [the brief's authority section]."
- "Design doc v1 and the pre-registration (§G) are approved by [the integration owner] before the Phase 1 build. [The integration owner] escalates to the owner only for owner-private calls (public repo, public leaderboard, external partners, spend beyond limits)."
- "#1964 remains the durable status channel. It is not an approval point."
- "Public text rules still apply."
- **Recorded change:** the owner's grant of 2026-10-26 replaced K's approval route. The benchmark session owns approval of the design and of each PREREG freeze, and each freeze hash is posted on lcm-x #1964. The owner retired the co-sign on 2026-10-26. PREREG-v1 is not frozen without the external reviewer unless the owner waives that in writing. The owner-private calls are unchanged (`docs/DESIGN.md` §16).
- **Recorded change** (owner, 2026-10-31): every freeze also goes to the Scoring Veto Panel (G above, DV48). The owner's waiver of the external reviewer was asked on 2026-10-31 and is pending, and each freeze record states which applies. The human grader pool is no longer an owner-private call, because no person grades (DV48).
