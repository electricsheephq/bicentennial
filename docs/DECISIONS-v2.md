# Design v2.0: the decision record

**Status:** approved by the owner on 2026-10-26. This is the decision record of Bicentennial design v2.0, published after the owner's review. It states the final decisions only. [`docs/DESIGN.md`](DESIGN.md) carries them out, [`docs/REQUIREMENTS.md`](REQUIREMENTS.md) says how each changed requirement is met, and the pre-registration ([`prereg/PREREG-v0.2.md`](../prereg/PREREG-v0.2.md)) is the only normative source for frozen quantities. PREREG-v0.2 is frozen. Its hash is in [`prereg/FREEZE-v0.2.md`](../prereg/FREEZE-v0.2.md) and posted on [lcm-x #1964](https://github.com/electricsheephq/lcm-x/issues/1964) for the owner's co-sign.

The other documents cite these decisions as DV1-DV46. DV42 is reserved. Section references (DESIGN §, PREREG §) are to the v2.0 design and PREREG-v0.2.

**What does not change:**
- the north star and the firewall (DESIGN §1, §14);
- the seven tracks (DESIGN §3);
- the generator's ground truth before text (DESIGN §4.1);
- bundles and twins (DESIGN §5.1a);
- the director, write turns and route table (DESIGN §6.2);
- **action-outcome scoring with the asymmetric penalty (DESIGN §7.1), which stays the scoring that decides**;
- the paired confirmatory family (DESIGN §12, PREREG §7);
- the sealed board and the developer/measurement split (DESIGN §9-§10);
- the external scoring veto before PREREG-v1;
- the 24-hour rule.

Where v2.0 changes how a requirement is met, DESIGN says so and the pre-registration records it.

---

## A. Structure

**DV1. A capability map, with a diagnostic progression and certification on Act.** A result is a map of **track rows × evaluation profiles**, with cell verdicts (DV4) and rungs for developers (DV7). The map has three stages. They are reported **separately**; none gates another, and there is no cumulative "level reached":
- **Remember** (diagnostic): direct questions with citations across restarts and gaps. This is the addendum's diagnostic family; it is never part of the headline.
- **Survive** (diagnostic): the same evidence under stress (corrections, look-alike interference, compaction, crash, swap, harness switch), drawn from the existing robustness-study inventory (DESIGN §6.10). The whole-life swap-model comparator rule for swaps and the harness-switch-never-in-headline rule are unchanged (DV40).
- **Act** (headline): unprompted use judged on world-state outcomes. These are the action bundles of DESIGN §7.1, the headline per the addendum.

**Certification** (DV5) is issued **on Act, within a declared evaluation profile**. Remember and Survive locate a failure (alongside stage attribution, DESIGN §7.3a and DV30); they don't certify. There is no marginal-rate Guttman gate.

**DV2. Evaluation profiles are qualifiers.**
- **Text** is the core profile.
- **Image** is the Perceive profile (DV9).
- **World E1 onward** comes after v1 (DV15).

**Each profile declares, before submissions:**
- its required Act cells, pre-registered from the inventory by the track design (DV28) and pooled with **equal weights**;
- its baselines: the no-memory floor, the oracle-evidence ceiling and naive RAG, shown in every published table (requirement E), with the full-history oracle ceiling beside them where it fits (DV33);
- its operating metrics.

Run size is the tier. Model and harness are configuration metadata (DV14). Community status is version provenance (DV16).

**DV3. The cell inventory comes from the tasks; the census only annotates it.**
- **The inventory:** the scored cells are frozen per release from the ability taxonomy (11 groups, 34 abilities) and the track templates, never from any system's documentation or results.
- **The census:** a published, dated capability census annotates each cell. It is public docs only, an extension of spike S5. A cell where no surveyed system documents full support is labelled **"undocumented frontier"**. That label states a documentation gap, not a measured frontier. It becomes "measured frontier" only once board runs show the field below the gate.
- **The label is display only.** It never changes whether a cell is scored, required or included (DV28).

**Season-1 frontier annotations,** all diagnostics outside required cells because of where they sit, not because of their label (DV28):
- erasure across derivatives, as extra probes beside Keep's scored forget bundles (DV12);
- image detail on an unforeseen later question (DV9): it belongs to the Image profile, whose season-1 board is separate and conditional, and the cell has no pilot-validated matched twin (DV36);
- shared memory with mid-life revocation (Learn, DV10);
- procedural supersession (Learn);
- poisoning by an ordinary user (Learn);
- attestation twins (DV13);
- standing rules after compaction and a swap (Tuesday): the stress conditions place it in the diagnostic Survive stage, and Tuesday's plain standing-rule bundles stay in Act (DV36).

Spatial memory waits for E1 (DV15).

## B. Scoring

**DV4. Verdicts, cause labels and non-results.**
- **Display verdicts** per cell, from two-sided 95% CIs against the cell gate: **CLEAR**, **UNRESOLVED** or **FAIL**.
- **"Unsupported" is a cause label on a scored result, never an opt-out.** The cell is still scored by its outcomes. A forgotten fact that resurfaces still costs −1, and a missed budget still scores 0. The label explains a FAIL; it never removes a cell or a penalty.
- **Non-results:**
  - **N/A:** outside the declared profile.
  - **N/A_READER:** Image profile only; the stack cannot use the evidence even when handed it directly.
  - **BLOCKED:** benchmark infrastructure failed. It is never charged to the system.
- **Eligibility:** in a required cell, N/A_READER or coverage below 95% **blocks** certification. BLOCKED **defers** it. A coverage shortfall caused by infrastructure reads BLOCKED and defers; a shortfall the system causes blocks (DV33).

**DV5. Gates and certification.** Both are on the **penalised action score**: the twin minimum with the asymmetric penalty. Gates and cell admission are computed on its **raw scale**, −100 to +100; the normalised 0-100 scale, with the no-memory floor at 0 and oracle evidence at 100, is for display only (DV25).
- **The cell gate:** g_k = floor_k + ½(ceiling_k − floor_k), in raw points.
  - It is computed from **the board's own control arms** (no-memory, oracle evidence), run on the pinned reader and harness **before any real system**. The 4-life calibration set is not used.
  - SE(g) is printed with every gate, in raw points. Bridge anchors link pack versions.
- **Cell admission:** a cell is admitted only if the one-sided 95% LCB of (raw ceiling − raw floor) is at least **30 raw points**, and **naive RAG does not CLEAR it** (requirement J's pilot-acceptance test, applied per cell). A cell that naive RAG clears is redesigned.
- **Certification on Act, per profile** (an intersection-union test with K required cells and margin m_k = a_k − g_k):
  - **R-a:** the one-sided 95% LCB of the equal-weight mean margin (1/K)Σm_k is ≥ 0;
  - **R-b:** every required cell has a one-sided 95% LCB of m_k ≥ −10.
  - CIs come from a wild cluster bootstrap over base-plus-twin life pairs, with all cells resampled jointly (Rademacher weights, 10,000 draws).
- **Where certification happens:** only on a **sealed board at the pre-registered size**: season boards, and delta boards when powered (DV33). Pilot and developer runs never certify. The planning values n_L ≥ 24, b = 150 and a per-cell SE of about 5 or less are provisional until PREREG-v1 (DV26).
- **Freeze gate for PREREG-v1:** an operating-characteristic simulation on the penalised scale, at true margins 0, +5, +10 and +15, plus one cell at −10, with the pass criteria of DV26. The variance inputs (twin correlation, within-cell and cross-cell life correlations) are measured on the bar-2 control arms with one A/A′ rerun.
- **Every card shows:**
  - **certification stability:** the bootstrap share of replicates that pass, a descriptive output and not an error-rate or power guarantee;
  - the per-item action accuracy (DV31, DV34);
  - twin consistency;
  - the harmful-actions panel, which is the violations panel (DV11, DV31);
  - cost.
- **The board's statistical claims** remain the paired confirmatory family (DESIGN §12, PREREG §7). Certification is a separate per-system statement.

**DV6. The raw-archive marker** is built from a public spec. It keeps everything raw, text and media, with timestamps and sources, and searches it.
- It is frozen per season.
- It is shown as a marker column.
- It is **never** used in gates, cell admission or rung calibration.
- It is also run at Keep's K10 budget.

**DV7. Rungs (developer packs only).**
- **What rungs are:** each cell's developer pack offers 3-5 lever values (DESIGN §4.6), calibrated only on **system-agnostic anchors**: the no-memory floor, oracle evidence and naive RAG. They are calibrated so those anchors span about 20-80% across the ladder (DV33).
- **The board is untouched:** board cells stay at the frozen board lever values, so rungs never move a board floor or erase a frontier zero.
- **Reporting:** per-rung paired deltas with an A/A′ band and an MDE, plus a curve shift pooled across rungs. No "highest rung cleared". The per-rung A/A′ flip rate (q0) is measured before any loop claim.
- **Confirmation:** a change accepted during development is confirmed on Ring 1 before it is claimed, because of the winner's curse (as an illustration on an assumed accuracy model, not a measured value: 9-13 illusory points after 10-50 iterations).

## C. The developer loop

**DV8. Dev rings.**
- **Ring 0: fixed public packs** per cell and rung. These are the T0-T3 tiers of DESIGN §9.1, paired, with cached controls. Loop time is **measured and published per tier**. The 7-minute idle and 28-minute busy figures are a T1 projection from preliminary S6a timings, nothing more.
- **Ring 1: a scheduled fresh-seed run** of the public templates, at each benchmark release and at least monthly.
- **Ring 2: a held-out template family** with fresh held-out seeds every month.
  - **The feedback:** one bit per **organisation** per month on a bounded transfer check (DV27). The gap is the pooled difference-in-differences: (public minus held-out) for the system, minus the same for the controls. The bit reads **"transfer gap detected"** when the one-sided 95% LCB of that gap is above 0, and **"no gap detected"** otherwise. Neither is called CLEAR or FAIL, and "no gap detected" is inconclusive about successful transfer.
  - An infrastructure failure yields no bit.
  - Per-cell bits, with the same meaning, are released only at season end.
  - Variants count against their organisation, under the existing disclosed-variant rules.
  - Every organisation gets the same service, LCM-X included. It reveals no seeds, templates or keys.
- **The sealed board** certifies on season boards and, when powered, delta boards (DV5, DV33).
- **Repro bundles** declare their class: snapshot-probe, replay-from-schedule, or live.
- **Guarded autonomous loops:** the pack is installed read-only, and the hashes of the pinned scorer, harness and controls are verified before a result is accepted. Honeypot gold files catch reads. An edit to any pinned artifact voids the run.
- **Acceptance bar, binding before v1 is called a developer product.** The benchmark team, acting as developer of its **own baseline** (naive RAG, or the raw-archive marker), shows the loop end to end: a real-stack public failure, reproduced from its bundle, fixed, and confirmed on Ring 1, all within the declared T2/T3 budgets. No contestant system is involved, and LCM-X is not.

## D. Profiles and tracks

**DV9. The Image profile, admitted through spike S8.**
- **Evidence** is rendered from world state, never by an image generator. Gold uses only values in the exposure manifest (legible and unoccluded). The image fidelity checks join DESIGN §4.4: the manifest verifier and a human-key sample covering legibility, with manifest-verifier recall ≥ 0.99 against a 200-item human-key sample and human legibility ≥ 95% (DV33).
- **Gist and detail are descriptive tags.** Any representation that keeps the information earns credit. The design principle is the unforeseen later question.
- **The observation and assistance contract** (memory comparisons):
  - every row gets the same image bytes per item, the same perception service, the same access timing and the same logical budget;
  - caches reuse identical authorised calls only and never grant new evidence;
  - reinspecting an original at question time is allowed only if the stack retained it, and it is charged;
  - native-routing *system* rows are reported separately from *memory-layer* rows.
- **The vision slot.** It goes in the route table and C-1. A pinned vision reader serves the memory-layer view; spend is listed with the paid rows (DESIGN §13). The vision provider is pinned separately, so a model swap does not move it (DV33). Cost is about $50 a season, the owner's call at the v0.2 co-sign.
- **Baselines:** the no-memory floor; the oracle ceiling (the direct-evidence control: the original image handed over at question time); and naive RAG over the stack's own descriptions. Answers use typed envelopes (exact or structured first).
- **Shortcut checks:**
  - presentation randomised independently of gold;
  - stylistically matched twins: the same template with the gold value changed and presentation matched (DV33);
  - a missing- or shuffled-history control;
  - a held-out style.
- **Admission:** "pending" in Ring 0 until S8 passes. The Image views form a separate profile board, which joins the season-1 sealed board only if S8 and the pilot's validity checks pass, and otherwise season 2 (DV33). At its season-1 planning size it issues no certificate (DV38). Audio and video follow the image loop.
- **Recorded change:** the owner's direction of 2026-10-26 (tests for capabilities like images that systems lack) moves rendered images ahead of the original brief's "build capture only after measured use". Continuous-stream capture still waits for measured use.

**DV10. Learn: bounded terminal chains, diagnostic in v1.**
- **The chain:** at a named fork point, a chain runs attempt → observed consequence → delayed retest. It **never rejoins** the scripted backbone, so the backbone's pairing and determinism are untouched (the terminal-fork rule of DESIGN §6.1). Learn chains are terminal forks in the robustness-study inventory (DV33). Each chain has a no-memory arm and a frozen-skill arm.
- **Status:** Learn is a **supporting diagnostic in v1**. It is outside the headline and outside required cells unless a later frozen inventory promotes it with its own controls and budget.
- **Cells:**
  - procedural supersession;
  - the effect of consolidation on later decisions;
  - shared memory between agents with mid-life revocation (revoking access is not deleting copies already made), in G2, the personal assistant: a household or office with two agents (DV33);
  - poisoning by an ordinary user.
- **What stays where it is:** Keep's salience and consolidation under budget (addendum B), Rachael's planted-memory refusal and Drift's time-to-correct. Learn chains add diagnostics beside them.
- **Cost:** S6 measures chain cost on the 24-hour critical path.
- **Ground truth** stays generator-compiled. Only the agent's own past actions come from the ledger (DESIGN §6.4).

**DV11. Accountability memory lives inside the existing tracks.**
- **Covered:** standing rules, consent and its revocation, promises, and the agent's own mistakes (disclosure, repair, non-recurrence), in Tuesday, Drift, Rachael and Keep, plus one Learn chain where the agent's own error has a later consequence.
- **The violations panel** sits beside utility; it is the same panel as the card's harmful-actions panel (DV31). It covers harmful actions, and harmful omissions where a duty is established. A repair never cancels the original violation.
- **PREREG §3 is unchanged:** asking scores 0, the ask channel never re-reveals, and Rachael's uncertainty response stands. Accountability scenarios use only cases where the exposed evidence is sufficient. There is **no** authorised-clarify outcome.
- **Excluded:** no moral judge, no laws-of-robotics scoring, no "Oath" track.

**DV12. Erasure across derivatives: extra probes beside Keep.** Keep's scored forget and budget bundles are unchanged (requirement B). The erasure probes are diagnostics, run as terminal forks in the robustness-study inventory (DV33):
- **Before forgetting:** a pre-forget probe establishes that the named derivative exists and can be retrieved. If it can't be observed, that stage is reported unknown.
- **The recovery surfaces** checked are named per cell.
- **Results are reported separately:** access denied; observed non-recovery; inspection findings. DESIGN §7.6's rule holds: this is never proof of deletion.
- **Never printed:** "compliant with" any law.

**DV13. Attestation is a Rachael diagnostic:** signed and unsigned twins under a declared trust policy, including attested-but-wrong cases. It stays outside the headline.

## E. Stacks, worlds and contributions

**DV14. One results table with full stack identity.**
- **Each row** declares memory × harness × model, plus the vision provider and spend.
- **The memory headline** holds the reader and harness fixed (the pinned reader).
- **A small predeclared crossover panel** runs on Ring-0 Act packs, with no full grid. Its rows render past turns in the pinned reader's voice, the same text for every model, and a model from the blind-filter panel's family is excluded from it (DV29).
- **Common item IDs and filters are frozen once.** Each reader's direct-evidence and blind performance is published, and nothing is refiltered per model.
- **Model-native memories** appear on a separately labelled stack view, outside board eligibility. The stack view follows board eligibility minus the open-source rule, and each row is vendor-submitted with a disclosed configuration (DV33). The board's open-source, self-hostable rule is unchanged.
- **The lab slice is v1.x,** under a seal-preserving design: the benchmark runs the lab's model inside the sealed runner, with no per-item private results and no traces of private items.
- **No targets are set on any system's scores.**

**DV15. World profiles are a roadmap.**
- **Admission rule:** a profile is admitted only when it exposes a memory question the Text and Image profiles cannot.
- **E1, robot vacuum:** a candidate chosen from the robotics survey, confirmed by an E1 spike before any commitment. It is an event-sourced 2D home with partial observation and high-level actions.
  - An event scheduler compresses idle time.
  - Programming the body is allowed, not required; agent-written routines count as memory.
  - It includes a two-vacuum fleet cell.
  - Body events join Survive.
- **Hands:** scored inside admitted World profiles after v1.
- **E2, desk arm:** MuJoCo SO-101, also confirmed by a spike before commitment (DV33), with the physical low-cost desk-arm design path kept as design only (requirement F, DESIGN §11.3).
- **Board path:** Mac-feasible engines and commercially usable assets only.
- **Reporting:** simulated span, evidence volume, controller steps and real elapsed time are reported separately.

**DV16. Community path.**
- **A contribution is an executable template over a synthetic world** (requirement H), with its validity evidence on controls.
- **Admission never depends on any system failing.** A reproducer may illustrate a template but never qualifies it.
- **No raw transcripts, corpus text or personal data.**
- **Contributions enter versioned seasons** with bridge anchors; old versions never change, and exposure history is preserved.
- **Independent authorship** applies to community contributions used in the sealed set. The maintainers' own private templates stay under DESIGN §14's firewall and the external veto.

## F. Product, rules and process

**DV17. Positioning against AML.**
- AML is a competitor. It runs Textual, Coding and Multimodal tracks through Add/Search.
- **Our claim to earn:** memory inside a real harness across a life, judged on actions, covering governance, with a fast diagnostic loop.
- **Never claimed:** firstness, multimodal novelty, or superiority before results.

**DV18. The 24-hour rule is sized by measured concurrency** of the pinned agent family's model lane (C-11, measured by S6a on the GLM lane or by S6b on a Sol lane; DV42 sets which lane is pinned), with the busy-marker `glm` pause for any GLM-plan use.
- The token ceilings of PREREG §11 are **report-only**.
- Bar 5 reads "fits the 24-hour rule at measured concurrency", and also checks the paid-lane spend and wall-time ceilings (DV32).
- There is no credits slot.

**DV19. PREREG-v0.2 carries five amendments:** long sprints by count (A1); the Wake claim contract (A2); per-item accuracy reported (A3); added turn latency (A4); G1 task completion (A5). A3 reads: the launch measurement "best below about 60%" is taken on per-item action accuracy and disclosed beside the penalised score; it is measured and published whatever its value, never a release condition, and it is not tuned toward (DV31, DV34).

**DV20. Names:**
- **Stages:** Remember, Survive, Act.
- **World profiles:** E1+.
- **Developer tiers:** T0-T3.
- **Keep budgets:** K100 and K10.
- **Board branches:** B0/B1.
- **Life count:** n_L.
- **Other names:**
  - "research tier", not "frontier tier";
  - the "undocumented frontier" label;
  - "raw-archive marker", "pinned reader" and "neutral reference"; earlier names for these are retired from public text;
  - "evaluation profile";
  - "fault point", not "fault cell";
  - "retained" for the attribution step after storage (DV30);
  - "swap model", "replication family", "comparison pair" and "own-behaviour baseline" (DV33);
  - "the pinned family" and "the whole-life swap-model comparator" (DV40).

**DV21. Difficulty and honest zeros.**
- Difficulty is frozen from controls only. **No target or veto is set on any real system's results.**
- Valid zeros are published, including all-zero rows.
- The launch figure of requirement J is measured and disclosed, never tuned toward, and never a release condition (DV31).
- Certification stability is printed on every card (DV5).

**DV22. Horizon, streams and the north star.**
- **A long-horizon run size** of at least 10M tokens and **a continuous-stream item** sit in the research tier on the roadmap (the brief's range, horizon and modality requirements). The design is kept now; capture waits for measured use.
- **Wake** keeps its row, and the A2 claim contract governs "as itself".
- **Flatten** stays deferred and is not in the pilot; its map row reads "not yet built" (DV33).

**DV23. Purpose order and the firewall.** "Help build LCM-X first" sets the first user and the problem classes. It does not set the measurement.
- LCM-X improves only through outputs every registered system gets on equal terms: public packs, Ring 1 results, Ring 2 bits per organisation, and published cards.
- The benchmark runs nothing on LCM-X beyond the scheduled runs every system gets, and never advises on its internals.

**DV24. Process.**
- PREREG-v0.2 freezes the **rules**, not per-season contents (the census, community templates).
- DV1, DV4 and DV5 go to the external veto reviewer before PREREG-v1.
- Each changed requirement gets its DESIGN note.

## G. Scales, attribution and settled details

**DV25. Scales.** Gates and admission are computed on the **raw penalised scale**, −100 to +100, with twin minimum and asymmetric penalty. The normalised 0-100 scale is for display only.
- A cell is admitted when the one-sided 95% LCB of (raw ceiling − raw floor) is at least **30 raw points**.
- g_k = floor_k + ½(ceiling_k − floor_k), in raw points.

**DV26. Certification numbers are provisional until PREREG-v1.**
- **Planning values:** n_L ≥ 24, b = 150 and the SE bound in DV5. The final values come from the operating-characteristic (OC) simulation **on the penalised scale**.
- **OC pass criteria:**
  - margin 0 in every cell: certification rate ≤ 5%;
  - +10 in every cell: certification rate ≥ 80%;
  - +10 in every cell but one, which sits at −10: certification rate ≤ 20%.
- **If a cut leaves a season below the powered size,** no certificate is issued that season, and results are still published.

**DV27. The Ring 2 bit.** It reads **"transfer gap detected"** when the one-sided 95% LCB of the difference-in-differences gap is above 0, and **"no gap detected"** otherwise. Neither is called CLEAR or FAIL.

**DV28. Required cells come from the design, independent of the census.**
- Each profile's required Act cells are pre-registered from the inventory by the track design.
- The census label is display only and never affects eligibility.
- The season-1 frontier annotations listed in DV3 are diagnostics because of where they sit (Learn, the erasure probes, attestation, the conditional Image board, and the Survive stage), not because of their label (DV36).

**DV29. Crossover rendering.**
- Crossover-panel rows render past turns in the pinned reader's voice, the same text for every model. The per-model voice option (DESIGN §6.2b) is off in the panel.
- A model from the blind-filter panel's family is excluded from the crossover panel.

**DV30. Stage attribution is honest about what it can observe.**
- DESIGN §7.3a has a **perceived** stage ahead of stored for media.
- A span search can establish "stored (text span found)"; finding nothing is **inconclusive** for non-text representations.
- Any stage that cannot be observed is **unknown**.
- The attribution step after storage is called **retained**, so it does not collide with the Survive stage.

**DV31. Release conditions and accuracy.**
- **No veto on scores.** The launch figure (best below about 60% per-item action accuracy) is measured and disclosed, never a release condition.
- **Per-item action accuracy:** the share of action items whose decision-table outcome is the correct action. A late Tuesday action, partial credit or a confident wrong action all count as incorrect. Benign extras don't change it. Its unit, denominator, exclusions and aggregation are defined in DV34.
- **One panel:** the harmful-actions panel and the violations panel are the same panel.

**DV32. Costs.** The added workloads are explicit cost terms in DESIGN §13 and PREREG §11. Each value is filled from S6, S8 or the pilot; until then it is a placeholder, and bar 5 checks the 24-hour rule plus the paid-lane spend and wall-time ceilings. The workloads:
- Learn chains;
- erasure probes;
- the Image profile's two views;
- the crossover panel;
- the raw-archive marker;
- the bar-2 A/A′ rerun;
- Rings 1 and 2.

**DV33. Settled details.**
- **Rungs:** calibrated so the system-agnostic anchors span about 20-80% across the ladder.
- **Learn's shared-memory chain** lives in G2, the personal assistant: a household or office with two agents.
- **Flatten** is not in the pilot; its map row reads "not yet built".
- **The Image profile on the sealed board:** in season 1 only if S8 and the pilot's validity checks pass; otherwise season 2.
- **Learn chains and erasure probes** are terminal forks in the robustness-study inventory. The Image views form a separate profile board.
- **Coverage:** a shortfall caused by infrastructure reads BLOCKED (defers). A shortfall the system causes blocks certification.
- **Certification** may be issued by season boards and by delta boards, when powered.
- **The stack view** follows board eligibility, minus the open-source rule. Each row is vendor-submitted with a disclosed configuration.
- **A model swap** does not move the vision provider: it is pinned separately.
- **Image fidelity:** manifest-verifier recall ≥ 0.99 against a 200-item human-key sample, and human legibility ≥ 95%.
- **Image twins:** the same template with the gold value changed and presentation matched.
- **Oracle ceilings:** every table carries both the oracle-evidence ceiling and the full-history oracle ceiling where it fits (requirement E).
- **E2** also needs a confirming spike before commitment.
- **Planning:** the v0.2 timebox is re-planned after S6 and S8. v1.0 is targeted alongside LCM-X v0.30.0 but not gated by it, since the benchmark's versions are independent.
- **S8's capped paid vision fallback** ($10) is an allowed exception to the spikes' $0 rule, reported per call.
- **Slot numbering** is the same across PREREG, DESIGN and the spikes index.
- **This record** is published as `docs/DECISIONS-v2.md`, and the public documents cite it.
- **Names:**
  - **swap model** (for the model a swap moves to);
  - **replication family** (the second agent family);
  - **comparison pair**;
  - **own-behaviour baseline**.

## H. Accuracy, sizes, placements and names

**DV34. Per-item action accuracy, fully defined.** PREREG §3 carries the normative definition.
- **The unit** is one action item: each base item and each twin item counts on its own, since accuracy takes no twin minimum.
- **Eligible items** are the assigned action items in the system's **required Act cells** of the declared profile. The launch figure uses the Text profile.
- **Excluded from the denominator,** with their counts disclosed:
  - N/A: outside the profile, so never assigned;
  - N/A_READER: Image profile only, so never in the Text launch figure;
  - BLOCKED: benchmark infrastructure failed;
  - N/A_EXPOSURE and N/A_CLOCK, exactly as they leave the penalised score (DV45).
- **Counted as incorrect:** every system failure, including SYSTEM_FAILURE, a crash, a timeout and a missing answer. A system's own failure never leaves the denominator.
- **Cell accuracy** is correct eligible items ÷ eligible items in that cell.
- **The system figure** is the **equal-weight mean of cell accuracies over the profile's required Act cells**, with the same equal weights as certification (DV2). It is printed with a 95% CI from the same wild cluster bootstrap (DV5).
  - Per-track figures (the equal-weight mean of a track's required cells) are display only.
  - When BLOCKED, N/A_EXPOSURE and N/A_CLOCK items together exceed 5% of a system's eligible items, the figure is printed as **incomplete**, by the same coverage rule as the headline rank.
- **The launch measurement** "best below about 60%" is the highest system figure among real systems on the full-tier board. It is measured, disclosed and never a release condition (DV31).

**DV35. Track inclusion on the raw scale.**
- PREREG §2's inclusion condition 1 reads: **RAG_raw < floor_raw + 0.70 × (ceiling_raw − floor_raw)**, and **floor_raw < 0.70 × ceiling_raw**. Both are on the calibration set's controls.
- It is a **track** test. Cell admission (DV5, PREREG §4) is a **separate** test on its own sample.
- **Every threshold in PREREG §2 and §9** is in raw penalised points unless it is labelled otherwise. This includes the difficulty targets: oracle evidence ≥ 75, and the best simple baseline ≤ 35.

**DV36. Placement reasons for the two remaining season-1 annotations** (DV3, DV28).
- **Image detail on an unforeseen later question** belongs to the Image profile. In season 1 that board is separate and conditional (S8 plus pilot validity), and the cell has no pilot-validated matched twin. So it is a diagnostic.
- **Tuesday standing rules after compaction and a swap:** the stress conditions place it in the **Survive** stage, which is diagnostic (DV1). Tuesday's plain standing-rule bundles stay in Act.
- DESIGN §11.2 lists all seven reasons.

**DV37. Robustness-study counts** (planning values; S6 measures the cost, and the cut order of PREREG §11 may reduce them).
- **Learn chains per study life:** one per applicable Learn cell.
  - In a G1 life that is 3: procedural supersession, the effect of consolidation on later decisions, and poisoning by an ordinary user.
  - In a G2 life it is 4, adding shared memory with mid-life revocation.
- **Erasure probes per study life:** one per scored Keep forget bundle in the life, capped at 6.
- The cost terms C_learn and C_erase are costed with these counts.

**DV38. The Image board** (season 1, conditional).
- **Planning size:** L_img = 8 lives, b_img = 40 image bundles per life.
  - At that size it issues **no certificate**. It publishes cell verdicts and diagnostics.
  - The Image profile certifies only in a season whose Image board meets its own OC-powered size (DV26).
- **Cost:** C_image = L_img × [R_img(1 + f) + 2P_img], plus vision-provider spend, which is within the owner's seasonal vision budget (DESIGN §13, PREREG §11).
- **The 24-hour rule applies** to the Image board per system, as a separate run from the Text board.

**DV39. The crossover panel's cadence.**
- It runs **once per season**, after the sealed board closes, in its own 24-hour window. It also runs once when a new PREREG version is frozen.
- C_cross is counted once per season and never inside a system's board window.

**DV40. Notation and names.**
- **Fault reruns:** the count is **q** (q = 3), and the metric is written **pass^q** (τ-bench's pass^k, with q reruns). The cell subscript keeps **k** (g_k, a_k, m_k, K).
- **The contrast count** is **M** (formerly m). The margin m_k is unchanged.
- **The pinned family** replaces the earlier "family A", so C-1 reads "the pinned agent family".
- **The whole-life swap-model comparator** replaces the earlier "B throughout" comparator.
- DESIGN §6.2 says a refused request "is refused: the director fails closed, and §12a decides what that does to the score" (formerly "fails the cell closed").
- "Two ladders" keeps its name.
- PREREG §10 reads "any live production agent".

**DV41. Placeholders that stay, by design.** None of these is an open decision. Each placeholder says who fills it:
- **S8's vision-capable main model:** chosen by the benchmark maintainers in S8 from the census, and pinned in C-1's route table before any Image board.
- **E1's done-when:** written by the benchmark maintainers after v1 (DV15).
- **README's freeze status, date and link:** filled by the benchmark maintainers at the v0.2 freeze.
- **This record:** published after the owner's review on 2026-10-26 (DV33).

**DV42.** Reserved for the pinned agent family's model lane, decided after a measurement spike of its sustained concurrency and latency.

**DV43. Failure attribution follows cause, not reporter.**
- A failure the contestant causes stays **SYSTEM_FAILURE** even when the director, runner or sandbox reports it: a crash, a timeout inside the declared limits, an out-of-contract request, a resource-limit violation or a refusal.
- **INFRA_FAILURE**, and so BLOCKED after reruns, needs the ledger to show a fault in a benchmark-owned component, or a failed precondition the benchmark owns, with the contestant inside its contract. The inline-fault rule follows the same precedence.
- So a system cannot shrink its own denominator: 50 correct of 100 never becomes 50 of 96 by relabelling its own limit violations as infrastructure.

**DV44. No conversion between the two scales.** An earlier illustration that converted per-item accuracy into the penalised score is withdrawn: it held only if every outcome were +1 or −1, and omissions and partial credit score 0. Both scales are always printed, and neither can be converted to the other without the outcome mix.

**DV45. Other exclusions from per-item accuracy.** N/A_EXPOSURE and N/A_CLOCK items leave the per-item accuracy denominator exactly as they leave the penalised score, with their counts disclosed. The incomplete label (DV34) applies when BLOCKED, N/A_EXPOSURE and N/A_CLOCK together exceed 5% of a system's eligible items.

**DV46. Who fills the remaining placeholders.** The benchmark maintainers name S8's vision-capable main model in S8, write E1's done-when after v1, and fill the README's freeze status, date and link at the v0.2 freeze. The owner's review releases this record for publication.

## Owner decisions still open
- The vision budget, about $50 a season (DV9), at the PREREG-v0.2 co-sign.
- The 24-hour decision of PREREG §11, once S6a's measurement is in.
