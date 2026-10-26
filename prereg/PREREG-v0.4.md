# Bicentennial pre-registration — PREREG-v0.4 (pilot)

**Status:** PREREG-v0.4, frozen FREEZE_DATE by the benchmark session, the product and release owner under the owner's grant of 2026-10-26. It supersedes PREREG-v0.3 by carrying design v2.2, which adds one decision: DV47, the run-time rule. At the owner's direction of 2026-10-26, a run of record no longer needs one contiguous 24-hour window: it runs in locked, resumable segments, with every life inside 24 h and each system's work inside a work bound (§11). DV47 also corrects DV42's fit, which left the mid-life swap's lane uncounted, and sets the paid-lane ceiling to the owner's $100 per run. No full-tier data has been collected. Every other rule, constant and threshold is PREREG-v0.3's, which carried design v2.1 (DV42, the pinned agent family) on top of PREREG-v0.2 and design v2.0. Its changelog is at the end. The decisions are recorded in `docs/DECISIONS-v2.md`. Its sha256 and time are in `prereg/FREEZE-v0.4.md`, and the commit and the tag `prereg-v0.4` are posted on lcm-x #1964.

**Precedence.** This document is the **only normative source** for every frozen quantity: constants, rules, thresholds, rosters, sample sizes, tests and ceilings. DESIGN-v2.2 (`docs/DESIGN.md`) explains and motivates. Where the two differ on a frozen quantity, this document governs, and the difference is logged as an erratum to DESIGN. "The addendum" means the binding requirements summarised in `docs/REQUIREMENTS.md`.

**Freezes:**
- **PREREG-v0.4, this text,** covers everything below except the values marked [pilot] and the completion slots. It freezes the **rules**, not per-season contents: the capability census and community templates change each season under the rules below.
- **The v0 completion record** (`prereg/PREREG-v0-completion.md`) fills the completion slots below, each by its stated rule.
  - **When:** it is committed, with the hash of every artifact it names, before any real memory system's first pilot run. The benchmark session approves it, and its hash is posted on #1964.
  - **What may come earlier:** spikes and control-only runs.
  - **The firewall:** no slot may be filled from any real system's scores. Spike measurements of cost, timing and harness overhead are allowed.

  | Slot | What | Rule |
  |---|---|---|
  | C-1 | the pinned agent family: the pinned model, and the route table (probe model, summariser, vision provider and alias per system); the pinned vision reader; S8's vision-capable main model for native mode | each system's vendor-documented defaults; the pinned model must be servable through the director on a subscription lane (S1, S4); the vision reader is pinned once for every row (S8); the vision-capable main model is chosen in S8 from the census and pinned here before any Image board |
  | C-2 | the swap model (§10), with its pinned reasoning effort | a model from a family other than the pinned family, servable through the director; named after S4. Its effort is pinned with it, and its cost and run-time terms are measured at that effort (S6) |
  | C-3 | the blind panel's paid third family (§4) | one family other than Anthropic, OpenAI and Zhipu; it runs on a plan lane, or as its own capped run with a projected filter spend of at most $100 per release (§11) |
  | C-4 | the full-tier window (§6) | the pinned model's harness default, by name |
  | C-5 | the developer-tier window and the bar-1 window (§6) | the smallest of 16K, 24K, 32K, 48K and 64K that is at least twice the harness's fixed overhead (system prompt plus tool schemas) on the pinned model, as measured in S6a |
  | C-6 | the write-turn prompt text, and each system's declared write-tool list (§10) | tool lists from each vendor's documentation |
  | C-7 | every template's decision table, the lever-mix shape and the direction labels (§3, §9); each cell's rung lever values (§6) | taken from the template build, before any real system runs on a template; rungs are calibrated on the no-memory floor, oracle evidence and naive RAG only, so that these anchors span about 20-80% across the ladder |
  | C-8 | the analysis code that computes every [pilot] value, the cell gates, the verdicts, certification and the Ring 2 bit; the operating-characteristic simulation, with its drift envelope and schedules (Freezes); and the scorer | hashed from the repository |
  | C-9 | competitor selection: the public adoption metric, its date, and the resulting ranked list (§10) | the metric is fixed on the completion date |
  | C-10 | the validation of the known-order ablations on the calibration set (§8) | controls only |
  | C-11 | the sustainable capacity (§11) | the sustainable capacity per account of the agent's model lane (its sustained concurrency, or its paced request rate R_s where a request rate binds), with the number of accounts a run uses; measured in S6a or S6b and confirmed by a paced soak, for every lane a run uses, with each lane's account pool; together with whether the run-time rule (§11) is met on it |
  | C-12 | each evaluation profile's declaration (§2): its required Act cells, its baselines and its operating metrics | from the frozen cell inventory by the track design, before any submission, independent of the census; never from any system's documentation or results. The Image profile's declaration is added when S8 admits it, before any submission to it |
  | C-13 | the crossover panel's models and harnesses (§10) | predeclared; never chosen from any system's results; no model from a blind-panel family (§4) |
  | C-14 | the raw-archive marker: its public spec and version (§6) | frozen per season |
  | C-15 | the Ring 2 held-out template family, by hash (§6) | authored and hashed before any Ring 2 bit is issued; its seeds are fresh every month |

  There is no credits slot (§11).

- **PREREG-v1** adds the [pilot] values, computed by the frozen code, plus the full-tier roster and the seed hashes. It is frozen before **any** system's first full-tier run.
  - **Freeze gate:** an operating-characteristic simulation of the certification rule (§7), on the penalised scale, at true margins 0, +5, +10 and +15, plus one cell at −10. Its variance inputs (twin correlation, within-cell and cross-cell life correlations) are measured on the bar-2 run's control arms with one A/A′ rerun (§6).
    - **Drift envelope:** the simulation also runs under a drift on the pinned reader, shared by every arm it serves. Swap-route drift is outside the envelope (§11). The simulation's code is part of C-8, so every choice below is hashed before any bar-2 input exists.
      - **The unit:** the simulation works on expected scores. Each (arm, life pair, cell, checkpoint) has an undrifted expected score a⁰ on the penalised scale, twin minimum included, from the variance model. The drift moves it to a⁰ + d(t) · (a⁰ − f⁰_k) / (c⁰_k − f⁰_k), clipped to [−100, +100], where f⁰_k and c⁰_k are the cell's undrifted floor and ceiling and t is the mean send time of that unit's B0 and B1 probes. The floor never moves, the ceiling moves by d(t), and the gate by d(t)/2. Sampling noise is added after the drift, from the same variance model.
      - **Time:** t is in hours since the first request of the run's first block, on each schedule; t₁ is that schedule's last probe.
      - **The cases:** a step, d = ±5 from the start of one block, drawn uniformly over the blocks in every replicate; a trend, d(t) = ±5 · min(1, t / t₁); and a daily cycle, d(t) = 3 · sin(2πt / 24 h + φ), at φ = 0, π/2, π and 3π/2. Each sign and each phase is its own case.
      - **The base schedule:** each arm's rate is its bar-2 seconds per input token, its total session time over its total input tokens across all its bar-2 sessions; a row with no bar-2 times takes the slowest measured arm's rate. Each full-tier session's time is that rate times the session's input tokens in the locked history set. This is a projection assumption, applied unchanged on both schedules. Blocks start in seed order as soon as the projected lane occupancy at C-11's capacity has room (§11). The replaying arms run under the life bound and the start window, where a breach is a pass-over for dispatch and BLOCKED for that row. Other pass-overs occur at bar-2's rate of failed or BLOCKED (arm, life)s, spread uniformly over sessions. The dispatch rule (§6) is applied to the result. Account moves are not modelled (§11).
      - **The stress schedule** is the same, with a keyed half of the rows 1.5 times slower than the rest.
      - **Per system:** certification is evaluated for one simulated system at a time, on the stress schedule once in the slow half and once in the fast half. A deferred certification counts as not certified.
      - **True margins** are undrifted: m⁰_k = a⁰_k − g⁰_k, with g⁰_k = f⁰_k + ½(c⁰_k − f⁰_k). The pass criteria must hold in every case, on both schedules. A pass bounds the certification claim to this envelope; it is not a bound on real provider drift.
    - **Pass criteria:** with margin 0 in every cell, the certification rate is ≤ 5%; with +10 in every cell, it is ≥ 80%; with +10 in every cell but one, which sits at −10, it is ≤ 20%.
    - The simulation sets the final n_L, b and per-cell SE bound for certification (§7). Until then those are planning values.
- **Approval.** The benchmark session approves each freeze, under the owner's grant of 2026-10-26, which replaced the integration-owner approval in the original brief. Each freeze hash is posted on #1964. There is no owner co-sign: the owner retired it on 2026-10-26.
- **External veto.** An external reviewer with a veto over scoring is recruited before PREREG-v1, and the owner decides who. PREREG-v1 is not frozen without one unless the owner waives that in writing on #1964. The stages (§2), the verdicts and non-results (§7) and the gates and certification rule (§7) go to that reviewer before PREREG-v1.

**Change control:**
- Every change makes a new version with a changelog, and every result discloses the version used.
- The pilot may set only the [pilot] values, and only through the frozen code.
- Pilot analysis runs on blinded system codes until the [pilot] values are committed.

**Requirements met differently.** Where design v2.0 changes how a binding requirement is met, DESIGN-v2.0 says so in a note, and this list records it:
- **The full tier is statistically powered with paired tests.** Unchanged: the paired confirmatory family (§7) stays the board's statistical claim. Certification is an additional per-system statement, issued only on the sealed board at the powered size that the operating-characteristic simulation sets before PREREG-v1 (Freezes).
- **No headline family is near-solved by the no-memory floor or by naive RAG.** Met per cell as well as per track: a cell that naive RAG clears is redesigned (§4).
- **At launch the best system, ours included, scores below about 60%, measured and not tuned toward.** The scale is now named: per-item action accuracy (§3), disclosed beside the penalised score (§9). It is measured and disclosed, never a release condition.
- **Horizon and streams (100K tokens to beyond 10M; continuous multimodal streams; weeks to months of simulated time at the frontier tier).** The frontier tier is replaced by run sizes and evaluation profiles. A long-horizon run size of at least 10M tokens and a continuous-stream item sit in the research tier on the roadmap; the design is kept now, and capture waits for measured use (§6).
- **Hands at the frontier tier.** Hands is scored inside admitted World profiles, after v1 (§2).
- **Modalities: build capture only after measured use.** The owner's direction of 2026-10-26 moves rendered images ahead of measured use, through spike S8 (§2). Continuous-stream capture still waits for measured use.
- **The simulator is chosen from the survey, without pre-commitment.** World profile candidates come from the robotics survey and are confirmed by a spike before any commitment (§2).
- **Wake, with a mid-life model swap; the north star.** Wake keeps its row. The claim contract (§2) governs when the headline may be described as waking up "as itself".
- **Baselines in every published table.** Each evaluation profile declares its baselines (§2), and every table carries both the oracle-evidence ceiling and the full-history oracle ceiling where the history fits; the Image profile has its own oracle ceiling and naive RAG (§4), and the human key covers image legibility (§5).
- **Operating metrics on every tier.** Each profile's tables carry them (§2). Ring 2 bits are labelled as carrying no metrics (§6).
- **Exact or structured matching first.** Image items use typed answer envelopes (§4).
- **Raw transcripts, corpus text and personal data are never used.** Community contributions are executable templates over synthetic worlds (§4).
- **The benchmark does not tune, patch or advise on the maintainers' own memory system.** LCM-X improves only through outputs every registered system gets on equal terms (§10).
- **Pre-registration and the external veto.** This version freezes the rules, not per-season contents, and the redesigned scoring goes to the veto reviewer before PREREG-v1 (Freezes, above).

**Notation:**

| Symbol | Meaning |
|---|---|
| n_T | number of included tracks |
| T_{s,t} | a track score |
| w | the Wake pickup window |
| n_f | faults per life: 1 inline on the board, 3 in the robustness study |
| q | reruns per fault point in the robustness study: q = 3. The metric is pass^q, τ-bench's metric with q reruns |
| n_L | lives in a tier; n_keep, n_rob and n_curve for the Keep subset, the robustness study and the Keep curve |
| M | number of contrasts in a confirmatory family |
| K | number of required Act cells in a declared profile |
| a_k, g_k, m_k | a system's penalised action score in cell k, the cell's gate, and the margin m_k = a_k − g_k, all in raw points (§7) |
| W | the context window frozen for a tier (C-4, C-5) |
| L_img, b_img | the Image profile board's lives and image bundles per life (§6) |

The subscript k always indexes a cell (a_k, g_k, m_k), and K counts the cells. Fault reruns are counted by q and contrasts by M, so neither shares a letter with a cell symbol.

## 1. Identity
- **This document:** PREREG-v0.4, frozen FREEZE_DATE. Its sha256 and time are in `prereg/FREEZE-v0.4.md`; the commit and the tag `prereg-v0.4` are posted on lcm-x #1964.
- **Design:** DESIGN-v2.2. Its hash is recorded at freeze.
- **Generator:** the version is recorded at freeze.
- **Genres:** G1 software partner and G2 personal assistant, in text and code.
- **Evaluation profiles:** Text, the core profile. Image, **pending** until spike S8 admits it (§2). World profiles, E1 onward, after v1.
- **Agent families:** the primary agent family, **the pinned family**, is fixed in the route table (C-1). A second family, the **replication family**, runs in the seasonal robustness study (§6).

## 2. The capability map, tracks, estimand and headline
- **The capability map.** A result is a map of **track rows × evaluation profiles**, with a display verdict per cell (§7). The map has three stages. They are reported **separately**; none gates another, and there is no cumulative "level reached":
  - **Remember** (diagnostic): direct questions with citations across restarts and gaps. This is the Recall diagnostic family; it is never part of the headline.
  - **Survive** (diagnostic): the same evidence under stress (corrections, look-alike interference, compaction, crash, swap, harness switch), drawn from the existing board and robustness-study inventories (§6). Swap bundles keep the whole-life swap-model comparator rule (§3), and harness-switch bundles never enter the headline (§6).
  - **Act** (headline): unprompted use judged on world-state outcomes. These are the action bundles scored in §3.
  - **Certification** (§7) is issued **on Act, within a declared evaluation profile**. Remember and Survive locate a failure, beside stage attribution; they never certify.
- **Evaluation profiles** are qualifiers on the map:
  - **Text** is the core profile.
  - **Image** is the Perceive profile (§4). It reads "pending" in Ring 0 until spike S8 passes. It joins the sealed board in season 1 only if S8 and the pilot's validity checks pass; otherwise in season 2. Its two views form a separate profile board (§6). Audio and video follow the image loop.
  - **World profiles, E1 onward,** come after v1. A World profile is admitted only when it exposes a memory question the Text and Image profiles cannot. E1, a robot vacuum in an event-sourced 2D home, is a candidate from the robotics survey, confirmed by an E1 spike before any commitment. E2 is a desk arm in MuJoCo, also confirmed by a spike before any commitment; the physical low-cost desk-arm path stays design only. The board path uses Mac-feasible engines and commercially usable assets only.
  - **Each profile declares, before any submission** (C-12):
    - its required Act cells, pooled with **equal weights**;
    - its baselines: the no-memory floor, the oracle-evidence ceiling and naive RAG, shown in every published table, beside the full-history oracle ceiling where the history fits (addendum §E). The oracle-evidence ceiling stays the one that sets gates (§7);
    - its operating metrics.
  - Run size is the tier. Model and harness are configuration metadata (§10). Community status is version provenance (§4).
- **The cell inventory.** The scored cells are frozen per release from the ability taxonomy (11 groups, 34 abilities) and the track templates, never from any system's documentation or results.
  - **The census.** A published, dated capability census, built from public documentation only, annotates each cell. A cell where no surveyed system documents full support is labelled **"undocumented frontier"**: a documentation gap, not a measured frontier. It becomes "measured frontier" only once board runs show the field below the gate.
  - **The label never changes** whether a cell is scored, required or included. Each profile's required Act cells are pre-registered from the inventory by the track design (C-12), independent of the census; the label is display only and never affects eligibility.
  - **Season-1 frontier annotations,** all diagnostics outside required cells because of where they sit in the design, not because of their label: erasure across derivatives, as extra probes beside Keep's scored forget bundles (§3); image detail on an unforeseen later question, which belongs to the Image profile: its season-1 board is separate and conditional, and the cell has no pilot-validated matched twin (§4); shared memory with mid-life revocation, procedural supersession and poisoning by an ordinary user (Learn, below); attestation twins (§4); Tuesday's standing rules after compaction and a swap, which the stress conditions place in the Survive stage (Tuesday's plain standing-rule bundles stay in Act). Spatial memory waits for E1.
- **Candidate headline tracks** (the Text profile's Act rows): Wake, Rachael, Tuesday, Drift and Keep.
  - Flatten stays deferred and is not in the pilot. Its map row is shown as "not yet built".
  - Hands joins with a World profile (E1 onward), after v1.
  - **Learn** is a supporting diagnostic in v1: outside the headline and outside required cells, unless a later frozen inventory promotes it with its own controls and budget. Its items are bounded terminal chains: at a named fork point, attempt → observed consequence → delayed retest. A chain **never rejoins** the scripted backbone, so the backbone's pairing and determinism are untouched. Each chain has a no-memory arm and a frozen-skill arm. Its cells are procedural supersession; the effect of consolidation on later decisions; shared memory between agents with mid-life revocation (revoking access is not deleting copies already made), which lives in G2, the personal assistant, as a household or office with two agents; and poisoning by an ordinary user. Keep's salience and consolidation under budget, Rachael's planted-memory refusal and Drift's time-to-correct stay where they are. Ground truth stays generator-compiled; only the agent's own past actions come from the ledger. Learn chains are terminal forks in the seasonal robustness study's inventory (§6).
- **Inclusion** (ordinary, when the pilot passes). It is computed from controls only, on the **unfiltered sample** (§4), so it never uses any real system's data. A candidate track is included only if all three hold:
  1. **Not near-solved,** on the calibration set (full-length lives, §6): **RAG_raw < floor_raw + 0.70 × (ceiling_raw − floor_raw)**, and **floor_raw < 0.70 × ceiling_raw**, where RAG_raw, floor_raw and ceiling_raw are the raw penalised scores of naive RAG, the no-memory floor and oracle evidence on the calibration set's controls. This is a track test. Cell admission (§4) is a separate test, on its own sample.
  2. **Measures memory,** on the bar-2 run's control arms (16 lives, §6): oracle evidence separates from the no-memory floor (life-level sign-flip, p < .05). Four calibration lives cannot reach p < .05: the floor is 2/2⁴ = .125.
  3. **Valid:** it passes the validity bar (§8, bar 4) on its final scored distribution.
  - **Units.** Every threshold in §2 and §9 is in raw penalised points (§7) unless it is labelled otherwise.
  - **Redesign path.** A track failing condition 3 may be redesigned and re-validated on fresh calibration seeds, without LCM-X data, before the PREREG-v1 freeze. Otherwise it is excluded.
  - **Power is never a criterion.** A track that is hard for every real system stays in.
  - **Reporting.** An excluded track is reported as a diagnostic, with the reason. If Wake is excluded, the claim contract below applies.
- **Estimand:**
  - **Bundle:** the score of a bundle is the minimum of its two items' scores.
  - **Final scored distribution:** the post-filter, memory-exclusive action bundles of a track. The unfiltered sample never enters it.
  - **Track:** T_{s,t} is the mean, over the lives 𝓛_t where the track is measured, of each life's mean bundle score. 𝓛_t is every life of the run, except Keep's. Keep's score exists only on that run's Keep subset (§6): the board's, or the bar-2 run's four lives. There it is ¼·T_K100 + ¾·T_K10 (§3).
  - In c_l, Keep's contribution is reweighted by |𝓛| / |𝓛_Keep^{ab}|, as the formula below does for every track.
  - The sign rule of bar 2 counts the c_l of all of the run's lives.
  - Bar 1 is the exception: it scores Keep at K100 on every life (§8).
  - **Headline:** H_s is the equal-weighted mean of T_{s,t} over the included tracks, reported from −100 to 100. Weights are fixed and equal. H_s is the statistic of the paired confirmatory family (§7). It is not a certification; certification is per cell and per profile (§7).
- **Per-life contributions** for a pair (a, b):
  c_l = Σ_t (1/n_T) × (|𝓛| / |𝓛_t^{ab}|) × 1[l ∈ 𝓛_t^{ab}] × (T_{a,t,l} − T_{b,t,l}).
  - T_{a,t,l} and T_{b,t,l} are computed on the bundles valid for **both** systems.
  - 𝓛_t^{ab} is the set of lives with at least one such bundle.
  - The mean of c_l over the lives equals the pair's headline difference on that common set.
- **The budgeted headline row** (reported, never confirmatory). It is computed on the Keep subset only:
  - every included track uses the K10 branches, and Keep uses its K10 score;
  - c_l^budget = Σ_t (1/n_T)(T^{K10}_{a,t,l} − T^{K10}_{b,t,l});
  - an exact sign-flip test and a wild cluster bootstrap CI over the subset's lives;
  - **Caps,** applied after the run (nothing is truncated, so execution is unchanged):
    - an item whose probe request exceeded 64K input tokens, measured from the ledger, scores 0 in this row;
    - a system whose p95 latency per memory operation on the reference machine exceeds 2 s over the subset is shown as over-cap and scores 0 for the whole row;
  - **Validity and weighting:** c_l^budget uses the §2 common-valid-set rule, with 𝓛 = the Keep subset.
- **The claim contract.**
  - **With Wake on the board,** the headline may be described as measuring whether the agent "wakes up as itself and acts on the right memories".
  - **If the pilot exit drops Wake,** the headline is labelled a **memory-action score**. No text, page or paper may then claim it measures waking up as itself.
- **Also reported:**
  - the capability map, with each cell's display verdict and cause label (§3, §7), and each profile's baselines;
  - the Remember and Survive stages, each reported separately;
  - the normalised score, from the no-memory floor (0) to oracle evidence (100), for display only (§7);
  - beside every gate (§7): the penalised action score, the per-item action accuracy (§3), twin consistency, the harmful-actions panel (the violations panel, §3) and cost. Per-item accuracy and the penalised score are different scales: both are always printed, and neither converts to the other without the outcome mix, because omissions and partial credit score 0 on the penalised scale;
  - certification stability (§7);
  - environment-recoverable bundles, as a diagnostic;
  - the replication-family row (H^rep, §7), from the seasonal robustness study;
  - the Wake wake-crossing contrast (§3);
  - the attestation diagnostic (§4) and the erasure probes (§3);
  - **G1 task completion:** the share of G1 action items whose whole executable check passes, beside the memory scores and outside the headline, since it mixes in coding skill;
  - the raw-archive marker, as a column (§6).
- **Operating metrics,** in every profile's tables beside the scores, as declared in C-12. They include **added turn latency**:
  - **Definition:** for every turn, turn wall time minus upstream model time, both taken from the director's ledger.
  - **Reported per track, beside every track score:** p50, p90 and max, paired against the no-memory floor on the same lives.
  - **Report only.** A cap waits for measurements.
- **Supporting families:** Recall (the Remember stage) and Learn are reported, never in the headline in v1.

## 3. Scoring

**Action items.** The class comes from the action trace and the end state; text never sets it. Each template's decision table is frozen in the v0 completion record (C-7). This action-outcome scoring with its asymmetric penalty is the scoring that decides: the headline, the cell gates and certification (§7) all use it. Evaluation runs in this order:
1. **Disqualifier.** Any wrong state change driven by a false, stale or planted memory, or any harmful extra action, scores **−1**, and scoring stops. Tuesday false alarms and Tuesday wrong actions are included.
2. **Base score**, from the first match:
   - a question to the user, with no other state change → **0**, whatever the gold. Asking never counts as refraining;
   - a correct rejection (refraining when the gold is to refrain, rejecting a false premise, or "never observed" when that is the gold) → **+1**;
   - the admissible state is reached → **+1**. For Tuesday, the timing score of the first execution is used instead;
   - omission or unresolved abstention → **0**;
   - any other trace, such as partial completion or FAIL_TASK → **0**.
3. **Cap.** Any benign duplicate or extra caps the score at **min(base, 0)**.
   - A correct reminder sent twice scores 0.
   - An early execution followed by a duplicate scores −0.25.

The table of outcomes this produces:

| Outcome | Score |
|---|---|
| correct, with no harmful or benign extra, by any retrieval route | +1 |
| correct with a benign duplicate or extra | 0 |
| omission, abstention, a question to the user, partial completion, FAIL_TASK | 0 |
| a memory-driven wrong state change, or a harmful extra | −1 |

**Per-item action accuracy** is reported beside the penalised score; it is never a gate or a release condition (§7, §9). It is the share of action items whose decision-table outcome is the correct action, without the twin minimum or the penalty: no disqualifier applies and the base score is +1.
- A late Tuesday action, partial credit or a confident wrong action counts as incorrect.
- A benign duplicate or extra does not change it: the cap applies to the penalised score only.
- **The unit** is one action item. Each base item and each twin item counts on its own, since accuracy takes no twin minimum.
- **Eligible items** are the assigned action items in the system's required Act cells of the declared profile (C-12). The launch figure uses the Text profile.
- **Excluded from the denominator,** with their counts disclosed:
  - N/A: outside the profile, so never assigned;
  - N/A_READER: Image profile only, so never in the Text launch figure;
  - BLOCKED: benchmark infrastructure failed;
  - N/A_EXPOSURE and N/A_CLOCK (§7), exactly as they leave the penalised score.
- **Counted as incorrect:** every system failure, including SYSTEM_FAILURE, a crash, a timeout and a missing answer. A system's own failure never leaves the denominator.
- **Cell accuracy** is correct eligible items ÷ eligible items in that cell.
- **The system figure** is the **equal-weight mean of cell accuracies over the profile's required Act cells**, with the same equal weights as certification (§7). It is printed with a 95% CI from the same wild cluster bootstrap (§7).
  - Per-track figures, the equal-weight mean of a track's required cells, are display only.
  - When BLOCKED, N/A_EXPOSURE and N/A_CLOCK items together exceed 5% of a system's eligible items, the figure is printed as **incomplete**, by the same coverage rule as the headline rank (§7).

**Checks** return a base verdict plus a benign-extra flag:
- The base verdicts are PASS, FAIL_MEMORY, FAIL_TASK, OMISSION and HARMFUL_EXTRA.
- Order of precedence: FAIL_MEMORY and HARMFUL_EXTRA, then FAIL_TASK, then the rest.
- **Ask channel:** one fixed, non-revealing reply to every question about past statements.

**Accountability.** Standing rules, consent and its revocation, promises, and the agent's own mistakes (disclosure, repair, non-recurrence) are scored inside Tuesday, Drift, Rachael and Keep, plus one Learn chain where the agent's own error has a later consequence. Accountability scenarios use only cases where the exposed evidence is sufficient. There is **no** authorised-clarify outcome: asking scores 0 as above, and the ask channel never re-reveals.

**The violations panel** sits beside utility. It covers harmful actions, and harmful omissions where the scenario establishes a duty. A repair never cancels the original violation. It is the same panel as the harmful-actions panel on every card (§7).

**Cause labels.** "Unsupported" is a **cause label on a scored result, never an opt-out**. The cell is still scored by its outcomes: a forgotten fact that resurfaces still costs −1, and a missed budget still scores 0. The label explains a FAIL; it never removes a cell or a penalty. It is assigned only from a declaration in the system's submitted configuration or from a direct-evidence run, never from documentation alone; the census uses documentation only for the frontier label (§2).

**QA and diagnostic items:**

| Outcome | Score |
|---|---|
| correct, asserted (stated confidence ≥ 0.5) | +1 |
| correct, hedged (< 0.5) | +0.5 |
| UNKNOWN when the gold is known | 0 |
| wrong, hedged | −0.5 |
| wrong, asserted; or a missing or unparseable envelope | −1 |

UNKNOWN when the gold is "never observed" scores +1.

**Tuesday** (the first execution decides the class):

| Outcome | Score |
|---|---|
| on time, inside the window | +1 |
| late | linear decay from +1 to 0 at the end of the late horizon (2 × the window) |
| early | −0.25 |
| never | 0 |
| false alarm on a lure or decoy | −1 |
| wrong action | −1 |

**Sensitivity rows**, always published: the −1 outcomes rescored at 0 and at −2.

**Calibration:**
- Brier score and ECE (10 equal-width bins) on QA confidence;
- assertion precision on action items;
- selective accuracy at the observed coverage.

**Track-specific measures:**
- **Wake:**
  - **Pickup window:** w = 5 agent turns.
  - **Wake-crossing contrast** (diagnostic): within the same life and template, bundles whose evidence crosses a wake event are compared with lever-matched bundles whose evidence does not. No extra branch is needed.
  - **Model swaps:** the swap is an event in every full-tier life. Swap bundles are confirmatory only in the seasonal robustness study, where the whole-life swap-model comparator exists. On the board and in dev they are diagnostic.
- **Flatten** (deferred and not in the pilot; its map row reads "not yet built"): when built, its diagnostic is the paired violation-rate difference, pressure minus calm.
- **Keep budgets:**
  - The tiers K100, K30, K10 and K3 are 100%, 30%, 10% and 3% of the raw stream's bytes. Store size is measured externally over every recoverable surface, **above the system's own empty-store baseline**, which is measured before any ingest.
  - A system above a tier's cap scores 0 on that tier's bundles. A system that cannot cap is placed at its natural size and scores 0 at every tier below it. "Unsupported" capping is a cause label on those zeros, never an opt-out.
  - **On the board and in the bar-2 run,** Keep's track score is **T_Keep = ¼·T_K100 + ¾·T_K10** on the Keep subset.
    - **Where it matches the old four-tier mean:** a system above every reduced cap scores T_K100/4 under both rules, and a system with the same score at every tier scores the same under both.
    - **Where it does not:** a system whose natural size falls between two caps can score differently. For example, one at 8% of the raw bytes scores (1, 1, 1, 0) across the tiers: 1 here, against .75 for the four-tier mean. This is disclosed.
  - **The budgeted row** is unchanged: K10 on every track (§2).
  - The four-tier mean is reported from the seasonal robustness study.
- **Keep forgetting:**
  - A forget bundle is a **trigger twin**:
    - B0: the forget request was made, and using the item is wrong;
    - B1: no request was made, and using the item is correct.
  - The bundle scores the minimum of the two. A system that never stored the item fails the B1 item, so it cannot pass by never remembering. A system that declares erasure unsupported is still scored on these bundles.
  - Neighbour retention is a separate Keep bundle, reported alongside.
  - **Erasure across derivatives** (diagnostic probes beside the scored forget bundles, which are unchanged; the probes are terminal forks in the seasonal robustness study's inventory, §6):
    - **Before forgetting,** a pre-forget probe establishes that the named derivative exists and can be retrieved. If it cannot be observed, that stage is reported unknown.
    - **The recovery surfaces** checked are named per cell.
    - **Results are reported separately:** access denied; observed non-recovery; inspection findings. They are never proof of deletion, and a card never prints "compliant with" any law.
- **Faults:**
  - **On the board:** one system-neutral scripted fault per life, inline at a fixed turn boundary (§6). It is never tied to a system's own background calls. Fault-crossing bundles (evidence before the fault, probe after it) are also reported separately, as a diagnostic.
  - **In the seasonal robustness study:**
    - role-relative faults (for example, during a system's own summariser call);
    - robustness is the paired delta against the fault-free twin;
    - a rerun passes if its bundle score is at least the twin's;
    - pass^q with q = 3 reruns, with fault timing jittered by a seed per rerun.

## 4. Bundles, tagging, balance and filters
- **Bundle types:**
  - value twins;
  - trigger twins, covering restraint, forgetting, correction vs hedge, and commitment made vs cancelled;
  - source twins: a plant vs a genuine message on the same channel and in the same wording. Where an authority rule decides, the genuine twin comes from the authorised source, so the two golds differ.
    - **Attestation twins** (a Rachael diagnostic, outside the headline) are a source-twin subtype: signed and unsigned twins under a declared trust policy, including attested-but-wrong cases. A declared trust policy is an authority rule.
- **One twin life per base life.** All decisive facts are flipped at once, with independence checked by the generator.
- **Tag verification**, run on every bundle before any filter:
  - A memory-exclusive bundle that the environment-search agent or always-verify passes on both items, in at least 2 of 3 trials, is retagged `env_recoverable`.
  - Retagging never deletes a bundle.
- **The unfiltered sample.** A fixed 20% of each track's bundles, drawn by seed before filtering, skips filters 2 and 4. In the bar-1 run (§6) it is 100%.
  - It is used only for inclusion conditions 1 and 2, bar 1 and its companion, and filter-yield reporting.
  - It never enters the headline.
- **Filters**, run on every other bundle every release, with drop logs published:
  1. **Literal copy:** a rare 3-gram (top 1% by IDF over the life's stream) shared between task and evidence. Overlap is otherwise stratified by tertile. Retrieval rank is never a filter.
  2. **Blind panel:** three families: Anthropic, Zhipu and one paid third family, named in the v0 completion record (C-3). The pinned agent family is never on the panel.
     - A family *passes the bundle* if it passes both items without evidence, in a single-call form; abstention counts as a fail.
     - The bundle is dropped if at least 2 families pass it.
     - Pre-filter blind-pass rates are reported.
     - A model from a panel family is excluded from the crossover panel (§10).
  3. **Oracle evidence:** the bundle is kept only if each item passes with only its evidence in at least 2 of 3 trials.
  4. **Evidence-free shortcuts:** the bundle is dropped if any of these passes both items:
     - do-nothing
     - always-abstain
     - always-"never observed"
     - always-"forgotten"
     - always-ask
     - generic default and its reverse
     - fire on every cue
     - channel distrust
     - comply always or resist always

     **Memory-using heuristics never delete a bundle:** latest mention, most frequent, first mention, the reverse of each, recent window, dump-store and recite-everything.
- **Common item IDs and filters are frozen once.** Nothing is refiltered per model. Each reader's direct-evidence and blind performance is published.
- **Gates on the final scored distribution of each track,** checked before each freeze:
  - **The battery.** All of these must score ≤ 0 on every track:
    - every policy in filter 4;
    - every memory-using heuristic;
    - the environment-search agent;
    - always-verify.
  - **Minimum shares:**
    - restraint bundles ≥ 25% of action bundles in Rachael, Tuesday and Keep;
    - single-update value twins ≥ 30% of Drift (trigger twins never count toward this share);
    - no direction label above 40% of any track.
  - **Drift mix.** At least as many bundles where a later mention must be ignored (hedged, quoted, or made by a non-authoritative source) as single-update value twins.
  - **Salience gate:** a surface-feature classifier must fail to pick gold-critical events (AUC ≤ 0.6).
  - **Remedy.** A failed gate is fixed by redesigning or regenerating the template under the same pre-registered mix. Results are never re-filtered.
- **Cell admission.** A cell is admitted only if both hold, computed from controls on the board's own control arms (§7):
  - the one-sided 95% lower confidence bound of (raw ceiling − raw floor) is at least **30 raw points**, on the raw penalised scale (§7);
  - **naive RAG does not CLEAR the cell.** This is a separate test from track inclusion condition 1 (§2), on its own sample. A cell that naive RAG clears is redesigned. The test needs evidence: when naive RAG's CLEAR test is BLOCKED or undefined, or its support after the probe-only exclusions (§11) is below ¾ of the cell's pairs, the cell gets no admission verdict for that run, and a required cell defers certification.
  - **On a full-tier run,** admission is computed after the last block (§6). A required cell that is not admitted reads NOT ADMITTED, and that profile's certification is deferred for that run. A redesign goes to the next generator version, validated on fresh control-only calibration seeds. Its disclosure says the redesigner had seen the unsealed results.
- **Filter yield.** A template that loses more than 50% of its bundles to filters is redesigned.
- **Image profile items** (pending S8):
  - **Evidence** is rendered from world state, never by an image generator. Gold uses only values in the exposure manifest: legible and unoccluded.
  - **Gist and detail are descriptive tags.** Any representation that keeps the information earns credit. Items ask an unforeseen later question.
  - **The observation and assistance contract** (memory comparisons):
    - every row gets the same image bytes per item, the same perception service, the same access timing and the same logical budget;
    - caches reuse identical authorised calls only and never grant new evidence;
    - reinspecting an original at question time is allowed only if the stack retained it, and it is charged;
    - native-routing *system* rows are reported separately from *memory-layer* rows.
  - **Baselines:** the no-memory floor; the oracle ceiling, which is the direct-evidence control (the original image handed over at question time); and naive RAG over the stack's own descriptions.
  - **N/A_READER** (§7) applies when the stack cannot use the evidence even when handed it directly.
  - **Answers** use typed envelopes, exact or structured first.
  - **Shortcut checks:** presentation randomised independently of gold; stylistically matched twins (an image twin is the same template with the gold value changed and presentation matched); a missing- or shuffled-history control; a held-out style.
- **Community templates.**
  - **A contribution is an executable template over a synthetic world,** with its validity evidence on controls. It passes every gate in this section.
  - **Admission never depends on any system failing.** A reproducer may illustrate a template but never qualifies it.
  - **No raw transcripts, corpus text or personal data.**
  - **Contributions enter versioned seasons** with bridge anchors. Old versions never change, and exposure history is preserved.
  - **Independent authorship** applies to community contributions used in the sealed set. The maintainers' own private templates stay under DESIGN's firewall and the external veto.

## 5. Ground-truth fidelity budgets
- **Verifier suite:** at least 50 cases per error class (value edit, omission, added fact, anachronism, speaker swap, modality shift, implicature). Each class needs recall ≥ 0.90, with a two-sided 95% Wilson lower bound ≥ 0.80.
- **Image fidelity checks** (Image profile): the exposure-manifest verifier, and a human-key sample covering legibility. The verifier's recall is ≥ 0.99 against a 200-item human-key sample, and human legibility is ≥ 95%.
- **Check validation:** each check must accept at least 5 correct solutions from at least 2 families, and must reject the stale, planted and twin-value mutants. False-reject and false-accept rates are each ≤ 2%.
- **Stage A, the template census.** Every template version:
  - two annotators, with kappa reported;
  - seeded known-bad items, with annotator recall ≥ 90%;
  - a global contradiction search;
  - zero unresolved template-level errors.
- **Stage B, the instance audit,** in confirm-or-dispute format:

  | Audit | Pool | Bundles per track | Max per template version | Needs at least | Gate on the upper bound |
  |---|---|---|---|---|---|
  | pilot | the final scored distribution of the bundles generated for the calibration set and the bar-2 seeds, probed or not | 75 | 3 | 25 template versions per track | ≤ 10% |
  | release | the full tier's final scored distribution, audited outside the LCM-X lanes | 200 | 5 | 40 template versions per track | ≤ 5% |

  - **Sampling:** stratified by template version, with a fixed seed. The sample is drawn before inspection and never topped up.
  - **Bound:** a two-sided 95% Wilson upper bound with p̂ = errors / n, at n_eff = n / (1 + (m̄ − 1)ρ), where ρ = max(0.1, ρ̂ between versions, ANOVA estimator).
  - **The gate:** the computed bound is the **only** gate. An error count never establishes passage by itself.
  - **Orientation only:** at ρ = 0.1, with every sampled version contributing the maximum, the pilot passes with ≤ 1 error and the release with ≤ 2. Errors concentrated in one version raise ρ̂, and the gate can then fail with fewer errors.
  - **Also reported:** the fully conservative cluster-level bound.
  - **Unmet gates.** A gate the rule cannot establish is unmet, including a track with too few template versions.
- **Fixed mechanics:**
  - phrase-bank rendering for gold-critical events;
  - locked tokens;
  - deterministic relative dates;
  - scoped closed-world checks.

## 6. Tiers, rings, subsets and branches
There are two ladders. **Developer tiers** carry no decision bar. **The measurement ladder** carries every bar and every board claim.

**Ring 0: the developer tiers.** Ring 0 is the fixed public packs per cell and rung: the tiers below, paired, with cached controls. Their targets are engineering budgets, not bars. Every developer-tier result is labelled "not predictive of the full tier" until dev-predicts-full has been measured (DESIGN §9). Ring 0 results are developer signals and never certify (§7).

| Tier | What runs | Target | Use |
|---|---|---|---|
| T0 probe packs | micro-lives of 1-3 sessions per track and ability, scored by a scripted reader, with no model | ≤ 60 s, $0 | unit and regression tests |
| T1 CI smoke | 2 public lives × 20 sessions through the real adapter with a scripted model; the regression corpus; fault-lite points; a wiped-store positive control that must fail | ≤ 10 min, $0; deterministic on stable result fields | merge gate |
| T2 live smoke | about 10 public lives × 8-10 sessions with live probes; the candidate arm against cached controls | ≤ 1 h per arm, $0 on subscription lanes | large effects only |
| T3 dev | public 20-session lives with a bundle budget chosen before the run, run in a fixed stratified order; paired against the developer's own cached previous run, with its MDE and an A/A′ band | about 1 h per arm; an optional overnight dev+ ≤ 8 h | a paired development delta |
| Fault finder | search over levers and scripted fault points on public seeds, then shrinking over the event schedule | ≤ 15 min of search + ≤ 15 min of shrinking, $0 scripted by default | a minimal failing public life and its repro bundle |

- **Loop time** is measured and published per tier. The 7-minute idle and 28-minute busy figures are a T1 projection from preliminary S6a timings, nothing more.
- **Windows.** Each developer tier's context window is frozen in the v0 completion record (C-5), from the harness overhead S6a measures. It is never chosen from any real system's results.
- **Rungs.** Each cell's developer pack offers 3-5 lever values (rungs), frozen in C-7 and calibrated only on system-agnostic anchors: the no-memory floor, oracle evidence and naive RAG, so that these anchors span about 20-80% across the ladder. Board cells stay at the frozen board lever values, so rungs never move a board floor or erase a frontier zero.
  - **Reporting:** per-rung paired deltas with an A/A′ band and an MDE, plus a curve shift pooled across rungs. No "highest rung cleared" is reported.
  - The per-rung A/A′ flip rate (q₀) is measured before any loop claim.
  - **Confirmation:** a change accepted during development is confirmed on Ring 1 before it is claimed. After 10-50 iterations, the best of the null iterations shows 9-13 illusory points.
- **Repro bundles** declare their class: snapshot-probe, replay-from-schedule, or live.
- **Guarded autonomous loops:** the pack is installed read-only, and the hashes of the pinned scorer, harness and controls are verified before a result is accepted. Honeypot gold files catch reads. An edit to any pinned artifact voids the run.
- **Seeds.** Developer seed packs are public. The runs of record below use fresh seeds that were never published in a pack.
- **Ring 1:** a scheduled fresh-seed run of the public templates, at each benchmark release and at least monthly. Its results are published.
- **Ring 2:** a held-out template family (C-15), with fresh held-out seeds every month.
  - **The feedback:** one bit per **organisation** per month on a bounded transfer check. It reads **"transfer gap detected"** when the one-sided 95% lower confidence bound of the pooled difference-in-differences gap is above 0: (public minus held-out) for the system, minus the same for the controls, equally weighted over the required cells. Otherwise it reads **"no gap detected"**.
  - Neither reading is called CLEAR or FAIL. "No gap detected" is inconclusive about successful transfer; it is not a pass. An infrastructure failure yields no bit. The bits carry no operating metrics, and are labelled so.
  - Per-cell bits, with the same two readings and the same meaning, are released only at season end.
  - Variants count against their organisation, under the existing disclosed-variant rules.
  - Every organisation gets the same service, LCM-X included. It reveals no seeds, templates or keys.
- **The public regression corpus** is stocked from controls, reference stubs and equal runs over every board system, never from one system's failures. The benchmark session never runs the fault finder on LCM-X.

**The measurement ladder:**

| Run | Lives | Sessions per life | Content | Cadence |
|---|---|---|---|---|
| calibration set | 4 public, full length | ~200 | controls only; no real system runs on it | once per generator version |
| **bar-1 run**: the smoke tier's separation run of record | 12 fresh public | 10, dense, at the frozen bar-1 window | ~25 action bundles per life, all unfiltered; arms: LCM-X, no-memory, oracle evidence, naive RAG, and the oracle ceiling where the history fits (addendum §E) | once per generator version |
| **bar-2 run**: the dev tier's separation run of record | 16 fresh public | 20 | 30-40 bundles per life, stratified; the full pilot roster and controls; Keep at K100 and at K10 on a 4-life Keep subset; no robustness branches; one A/A′ rerun of the control arms, which measures the certification rule's variance inputs (Freezes) | once per generator version |
| **full core board** | n_L private (§7) | ~200 | b bundles per life [pilot, by the §10 rule; certification's planning value is 150, §7], ≥ 60% action; checkpoints at 20, 60, 120 and 200; the board inventory below | once per season, plus delta boards |
| **seasonal robustness study** | the season's first 8 board lives | ~200 | the study inventory below | once per season and at each major release, inside its board's run (§11) |

**Full-tier lives** are dense:
- about 1M tokens plus the long-sprint tokens over about 200 sessions: about 2.3M at W = 128K and about 3M at W = 200K. S6 measures the run-time rule at this size;
- **at least 8 long sprints** per life, with at least one in every 25-session block. Each sprint is at least **1.25 × W** in history tokens, where W is the window frozen for the tier, so compaction fires inside sessions at a known rate;
- filler chat is shortened, never tool output;
- about 5 assistant turns per scripted session, so the write-turn chain, the critical path of a life, stays short;
- the window is the pinned model's harness default, named in the v0 completion record (C-4), which keeps the harness realistic.

**The long horizon.** A long-horizon run size of at least 10M tokens and a continuous-stream item sit in the research tier on the roadmap. Their design is kept now; capture waits for measured use. This is disclosed.

**Board inventory** (DESIGN §6.10):
- **B0 and B1:** each probed at every checkpoint. B1 forks from B0 at the first flipped event.
- **One scripted fault per life:** a SIGKILL of the harness process at the first turn boundary of session ⌈0.55 × S⌉, where S is the life's session count (session 110 of 200), followed by a cold restart. It is inline on B0 and B1, at the same boundary. It is system-neutral, and it adds no extra branch and no reruns.
- **The mid-life model swap:** an event in every life.
- **Keep subset:** n_keep = max(6, ⌈n_L/4⌉) lives. Each has a B0 at the K10 cap, replayed in full under the cap, and a B1 forked from that capped B0. All bundles are probed there; these give the budgeted row.
- **Roster:** every real system in the frozen roster, including LCM-X at its last release before the public generator.
- **Controls:** in a full-tier run, the control arms (no-memory floor, oracle evidence) are arms of every life's block, like any real system (§11). They run on the pinned reader and harness and **never swap**: their probes at post-swap points are answered on the pinned reader too, so every gate stays the pinned-reader gate (§7).
  - **Naive RAG** runs with them in every block, as a baseline arm for admission (§4) and the tables. It is never a real system.
  - **Checkpoint-dispatched probes.** The control arms and naive RAG replay nothing: they are the block's **probe-only arms**. Every probe-only arm's probes for checkpoint c of branch b follow the same real arm of its block, chosen by this frozen rule, so a gate's floor and ceiling, and naive RAG, are probed together:
    - **Eligible arms:** the block's real-system arms whose schedule includes checkpoint c of branch b.
    - **Order:** the eligible arms sorted by their keyed draw (§11), with the unit id (life, branch, checkpoint, arm id) and the attempt index 0, so a resume, an attempt or a retry reuses the order.
    - **Dispatch:** the probes go out when the first arm in that order that has not been passed over reaches c on its own chain of branch b (not a fault fork, an A/A′ rerun or a comparator chain). An arm is **passed over** at c of b only when it can no longer reach it there: its replay of branch b has stopped before c (completed, failed or BLOCKED), it broke its life bound before c, or it made no first request within its block's start window. A quota wait, a hold or a pending INFRA attempt is not a pass-over; the probe-only arm waits with it.
    - **Already arrived:** if the next arm in order reached c before the arm ahead of it was passed over, the probes go out at once.
    - **Exhausted:** if every eligible arm is passed over, the probes go out at the last pass-over, flagged unmatched. Unmatched probes are used like any other, and their lag is measured from that pass-over.
    - **Recorded:** for every dispatch, the followed arm, its arrival time, the probes' send times and the lag between them.
    - **Timing bounds:** the life bound and the start window (§11) bind the arms that replay. A probe-only arm has neither of its own: its times are set by this rule and are checked through the arms it follows. Every dispatch therefore falls within 48 h of the block's first request, apart from its recorded lag and retries.
    - **What it gives:** each dispatch follows a keyed-random eligible arm and goes out at that arm's arrival, or at the pass-over that releases it if that is later. The probe-only arms' probe times are therefore a keyed-random sample of the eligible arms' checkpoint times, delayed where a pass-over releases them, with the lag recorded. That removes a probe-only arm's lead over the systems. It does not match a gate's times to any one row: a row that runs systematically faster or slower than the roster meets a time-varying reader effect that its gate's probes do not (§11).
  - **Computed after the last block.** The frozen code (C-8) computes the cell gates (§7) and cell admission (§4) from the control arms alone. Control results stay sealed with the systems' results until the run completes.
  - **A mechanics check first.** Before the first block, the control arms run once on one public life, on every route they use. Every probe must return a parsed, scored outcome, and the oracle arm must hand over its evidence; otherwise the run does not start.
  - **Gates are per run.** A table prints each row's run gate. A delta board's in-block controls re-measure the season board's on the same lives, and the change is reported.
  - In the pilot's runs of record, the controls run first. Controls are re-run on any pin change (DESIGN §8).
- **Scheduling** (§11): every arm, the control arms included, runs interleaved in life-major blocks. Each block is one life, run by every arm on the roster, so each life's contrasts and its control results are within one block.
- **The raw-archive marker** (C-14) is built from a public spec. It keeps everything raw, text and media, with timestamps and sources, and searches it. It is frozen per season, runs once per season in the season board's blocks as a replaying arm, under the life bound and the start window like a system (§11), on the pinned reader, is shown as a marker column, and also run at K10. It is **never** used in gates, cell admission or rung calibration, and it is never a real system (§8, §10).
- **The full-history oracle ceiling,** which every table shows where the history fits (the baselines rule), is a labelled diagnostic. It is a probe-only arm in the season board's blocks, on the pinned reader, under the dispatch rule, run once per season at the checkpoints whose history fits the window. It is never used in gates, cell admission or rung calibration, and its cost is counted with the marker's (C_marker). A delta board's tables cite the season board's values for both, labelled as such.

**The Image profile board.** Once the Image profile is admitted to the sealed board (§2), its two views, memory-layer rows and native-routing system rows (§4), form a separate profile board beside the full core board.
- **Planning size:** L_img = 8 lives, with b_img = 40 image bundles per life.
- **At that size it issues no certificate.** It publishes cell verdicts and diagnostics. The Image profile certifies only in a season whose Image board meets its own powered size, set by the operating-characteristic simulation (Freezes, §7).
- **The run-time rule** applies to it per system, as a separate run from the Text board (§11).

**Seasonal robustness study inventory**, on its 8 lives, for every board system:
- **Faults:** n_f = 3 role-relative faults per life, q = 3 reruns each, on B0 and B1, each running from the fault point to the next checkpoint.
- **The Keep curve:** the K30 and K3 tiers, each a capped B0 replayed in full and a B1 forked from it, probed on Keep bundles.
  - It runs on the intersection of the study's lives with the board's Keep subset: the first n_curve = min(n_rob, n_keep) lives in seed order, so that each has its board T_K10. n_rob is the study's life count: 8, or 4 after the §11 cut.
  - The four-tier mean is computed on those lives, and their count is disclosed.
- **The whole-life swap-model comparator:** a B0 and a B1, run with the swap model throughout and probed on Wake swap bundles.
- **The replication family:** a B0 and a B1 with all-bundle probes. If the swap model is from the replication family (§10), these are the same branches as the whole-life swap-model comparator.
- **A/A′ reruns:** a 10% subset of the ordinary pinned-family probe sets on B0 and B1 on the study's lives, each run once more, in the same block as its original (§11).
- **Learn chains** (§2): terminal forks at named fork points, each with its no-memory and frozen-skill arms. They never rejoin the backbone. Each study life carries one chain per applicable Learn cell: 3 in a G1 life (procedural supersession, the effect of consolidation on later decisions, and poisoning by an ordinary user) and 4 in a G2 life, which adds shared memory with mid-life revocation.
- **Erasure probes** (§3): terminal forks beside the Keep forget bundles, one per scored Keep forget bundle in the life, capped at 6.
- **These counts are planning values.** S6 measures their cost, and the §11 cut order may reduce them.
- **Blocks:** the fault reruns, the A/A′ reruns and the whole-life swap-model comparator run in the same block as the branches they are compared with (§11).

**Not run:**
- faults on Keep-tier, swap or replication-family branches;
- Keep tiers on swap or replication-family branches.

**Harness-switch bundles** are ordinary bundles after a switch event on B0 and B1. They are reported in a sub-row for every system and need no extra branch.

**Subset selection.** Every subset is the first lives in published seed order, fixed before any run.

**Delta boards and run selection:**
- **When a delta board runs:** only for a new GA of a system already on the board. At most 2 per system per season, run in order, with the system's previous version re-run alongside on the season's lives, interleaved with it in the same blocks (§11).
- **When a fresh board is forced:** any change of harness pin or model alias, or a change of served identity (§11). Only the stopped run restarts (§11).
- **Publication:** every scheduled run is published in order. The board shows each system's latest version, never its best.
- **No dual use:** sealed runs never serve as a phase of any release gauntlet.
- **Certification:** the sealed board certifies per release: each season board and each delta board may issue certificates, when it is at the powered size (§7). "Release" means such a board, not every contestant release. The cadence above is unchanged.

## 7. Statistics
- **Primary test:** for a pair, a two-sided sign-flip permutation test on the per-life contributions c_l (§2), at α = .05. Each c_l is computed within its life's block (§11), and the estimates over the first and the second half of the blocks, in start order, are reported beside the test as a sensitivity. It is exact when n_L ≤ 20, and otherwise uses 100,000 draws with a fixed seed. CIs come from a wild cluster bootstrap over lives (Rademacher weights, 10,000 resamples, fixed seed). McNemar is descriptive only.
- **Confirmatory family on the board** (unchanged in v0.2; it remains the board's statistical claim, and certification below is a separate per-system statement):
  - **Membership:** each real system in the frozen roster against one pre-named neutral reference, **Hermes native memory**, on the pinned family only. With the minimum Phase 1 roster (LCM-X, Hermes native and 3 external systems), M = 4. LCM-X at its last release before the public generator is not in the family.
  - **Correction:** Holm within the family. There is no fixed testing sequence and no sequential stopping. n_L is fixed by the rule below before any full-tier run.
  - **Declared secondary contrasts:** each is tested and reported with its achieved MDE, outside the family's correction:
    - LCM-X vs LCM-X at its last release before the public generator, on every board (the tuning detector);
    - LCM-X vs its previous GA, on delta boards, where that version is re-run alongside.
  - **Every other pair** of real systems is exploratory. Its CI is reported; no test is claimed.
  - **Tracks** are tested only for family contrasts whose headline separates, with Holm within the contrast.
- **The bar-2 family** (§8) is the pairs of real systems excluding both LCM-X releases. LCM-X's results never enter it or its correction.
  - **Comparisons with controls** are reported, not confirmatory, except for bar 1, its companion, and the inclusion and ablation tests.
- **Life count:**
  - Units are headline percentage points.
  - σ_d [pilot] is the median, over the bar-2 family's pairs, of the SD of their per-life contributions c_l on the bar-2 run. The scale difference from the full tier is disclosed.
  - n_L = clamp(⌈((z_{1−α/(2M)} + z_{0.8}) × σ_d / 8)²⌉, 24, 48), with α = .05 and M frozen in v1. This sizes the first, Bonferroni-strict Holm step. It is a resource rule built on a normal approximation.
  - The achieved Holm-adjusted MDE is always simulated and disclosed.
- **The replication family and its estimand.** H^rep is the equal-weighted mean of the included tracks on the robustness study's 8 lives, with Keep scored at its K100 tier only, because the replication family has no capped branches.
  - **The two rows:** H^rep is computed for both families on those same 8 lives, tracks and tier. Each confirmatory pair's replication-family difference on H^rep is compared with its pinned-family difference on H^rep: the matched comparator.
  - **The flag:** a pair is flagged **family-dependent** when its replication-family CI (wild cluster bootstrap over the 8 lives) excludes 0 with the opposite sign to the matched pinned-family difference.
  - **Disclosure:** H^rep does not replicate Keep's board score (§3).
  - **Never pooled** into H_s.
- **Reported for every run of the measurement ladder:** the MDE simulated on the estimand and the life-level ICC. A/A′ variance comes from the seasonal robustness study, and the developer tiers report their own A/A′ band.
- **Every pair tested is reported,** not only the significant ones.

**Cell gates, verdicts and certification.**
- **The scale.** Gates, cell admission (§4) and certification use the **penalised action score** (§3) on its **raw scale**, from −100 to +100: the twin minimum with the asymmetric penalty. a_k is a system's score in cell k in raw points. The normalised score, with the no-memory floor at 0 and oracle evidence at 100 per cell, is for display only.
- **The cell gate:** g_k = floor_k + ½(ceiling_k − floor_k), in raw points.
  - It is computed by the frozen code (C-8) from **the board's own control arms** (no-memory, oracle evidence), run on the pinned reader and harness **in the same blocks as the real systems** and computed after the last block from the control arms alone (§6, §11), on the final scored distribution, from those runs and never from the filter trials (§4). The gap against the unfiltered sample is disclosed. The 4-life calibration set is not used. The statistics check put SE(g) there at ≥ 4.3 points; that figure comes from its per-item accuracy model, which no longer applies, and is an illustration, not a penalised-scale estimate.
  - SE(g), the standard error of the raw gate, is printed with every gate, in raw points, with the gate computed over the first and over the second half of the blocks, in start order, beside it as a drift sensitivity (§11). Bridge anchors link pack versions.
  - Every model row, including the crossover panel's (§10), is judged against the pinned-reader gate. A row's own direct-evidence ceiling is shown but not used.
- **Display verdicts** per cell, from two-sided 95% CIs against the cell gate: **CLEAR** when the lower bound is at least g_k, **FAIL** when the upper bound is below g_k, and **UNRESOLVED** otherwise. A cause label (§3) may explain a FAIL.
- **Certification on Act, per declared profile:** an intersection-union test over the profile's K required cells, with margin m_k = a_k − g_k. A system certifies only if both hold:
  - **R-a:** the one-sided 95% lower confidence bound of the equal-weight mean margin (1/K)Σm_k is ≥ 0;
  - **R-b:** every required cell has a one-sided 95% lower confidence bound of m_k ≥ −10 raw points.
  - **CIs** come from a wild cluster bootstrap over base-plus-twin life pairs, with all cells resampled jointly (Rademacher weights, 10,000 draws, fixed seed).
  - **Per-life margins:** each life pair's margin is m_k,l = a_k,l − g_k,l, on the pair's common valid bundles, with g_k,l from that pair's own control arms. A pair's controls are resampled with its systems: each replicate multiplies the pair's deviation of its system score from the cell mean, and of its control gate from the mean over the cell's pairs with valid controls, by the pair's weight w_l, and adds the means back. A sensitivity bootstrap, clustered by groups of blocks that overlap in time, is reported beside the CIs.
  - **The pooled gate.** A pair whose control (arm, life) failed (§11) keeps every system result, and its gate is the cell's pooled gate: the equal-weight mean of g_k,l over the cell's surviving pairs with valid controls, each g_k,l on that pair's valid control bundles, one value per cell. Every replicate recomputes it from that replicate's perturbed surviving gates, so the pairs that share it share its error.
    - **Support:** a cell's control support is its number of surviving pairs with valid controls. The per-cell SE bound counts the pooled gate's uncertainty. A cell whose control support is below ¾ of its pairs reads BLOCKED for every system, as an infrastructure cause, and defers certification; it is never read as a pass. This BLOCKED applies to the cell's margins, verdict and certification only: the systems' bundles stay in the headline, coverage and every denominator. Admission (§4) uses the surviving pairs only, and a cell below the floor gets no admission verdict for that run.
    - **Disclosure:** the card lists the pooled pairs, which lose their own controls' in-block timing, and reports R-a and R-b without them as a sensitivity.
- **Eligibility.** In a required cell, N/A_READER or coverage below 95% **blocks** certification. BLOCKED **defers** it, and so does NOT ADMITTED (§4).
  - A coverage shortfall caused by infrastructure reads BLOCKED, and defers.
  - A coverage shortfall the system causes blocks.
- **Where certification happens:** only on the **sealed board at the pre-registered powered size**: a season board, or a delta board (§6).
  - **Planning values:** n_L ≥ 24, b = 150, per-cell SE ≤ about 5. They are provisional design constraints, not achieved power. The final values are frozen in PREREG-v1 from the operating-characteristic simulation on the penalised scale (Freezes).
  - **Below the powered size,** a board issues no certificate. This covers a b set by the §10 rule below the powered value, a cell whose SE exceeds the frozen bound, the Image board at its planning size (§6), and a §11 cut: if a cut leaves a season below the powered size, no certificate is issued that season. Its results are still published.
  - Pilot and developer runs never certify. The statistics check put their power at a true margin of +10 near 0.18; that figure comes from the same per-item accuracy model and is an illustration, not a penalised-scale estimate.
- **Every card shows:**
  - **certification stability:** the bootstrap share of replicates that pass;
  - the per-item action accuracy;
  - twin consistency;
  - the harmful-actions panel, which is the violations panel (§3);
  - cost.
- **Certification stability** is descriptive. It is not an error rate or a power guarantee.

**Failure classes:**

| Class | Treatment |
|---|---|
| FAIL_TASK | 0 |
| SYSTEM_FAILURE: the system crashed, timed out inside the declared limits, made an out-of-contract request, violated a resource limit or refused, whichever component reports it | 0 |
| INFRA_FAILURE: a fault in a benchmark-owned component (director, runner or sandbox), or a failed benchmark-owned precondition, shown in the ledger with the system inside its contract | at most 2 reruns, then **BLOCKED**: excluded for every system in the comparison, and never charged to the system |
| N/A_EXPOSURE: the decisive span was never exposed in that harness | excluded for that system; cross-harness pairs use the common-exposure set |
| N/A_CLOCK: a row failed the skew audit, or is wall-compressed | excluded from time-dependent bundles for that system; pairs use the common set |

**Attribution follows cause, not reporter.** A failure the system causes is SYSTEM_FAILURE even when the director, runner or sandbox is the component that reports it: a crash, a timeout inside the declared limits, an out-of-contract request, a resource-limit violation or a refusal. INFRA_FAILURE needs the ledger to show a fault in a benchmark-owned component, or a failed precondition the benchmark owns, with the system inside its contract.

**Non-results** in the map (none is a score):
- **N/A:** the cell is outside the declared profile.
- **N/A_READER:** Image profile only; the stack cannot use the evidence even when handed it directly.
- **BLOCKED:** benchmark infrastructure failed. It is never charged to the system.

- **Denominators** are the assigned bundles. Per-item action accuracy has its own item denominator (§3).
- **The card reports** completion per system, and a worst-case row in which every system failure scores −1. BLOCKED results are shown in that row and never charged.
- **A headline rank** needs at least 95% coverage and no more than 5% infrastructure exclusion. Per cell, the eligibility rule above applies.
- **Inline faults are classified mechanically.** A failure inside a scripted fault's recovery window is SYSTEM_FAILURE unless the ledger records a fault in a benchmark-owned component with the system inside its contract, in which case it is INFRA_FAILURE. Real 429s and quota pauses are absorbed by the director, and they are never faults.

## 8. Pilot acceptance bars (all required)
The bars keep their own statistics, defined below, independent of the capability map and of certification. The raw-archive marker is a control: it is never a real system, never in the bar-2 family (§7) and never on the roster (§10).

1. **Smoke separation**, addendum bar 1, on the bar-1 run (§6), the smoke tier's separation run of record.
   - **Sample:** in the bar-1 run **every** bundle is in the unfiltered sample, so filters 2 and 4 never apply there.
   - **The per-life statistic:** the equal-weighted mean, over the five candidate tracks, of each track's mean bundle score on that life, with Keep at its K100 tier. A track with no bundle valid for both systems on a life is dropped from that life's mean for both. The companion uses the same statistic.
   - **Test:** LCM-X vs the no-memory floor, life-level sign-flip on that statistic, p < .05.
   - **Companion,** required for validity: on the same lives and sample, oracle evidence vs no-memory and naive RAG vs no-memory, each p < .05.
2. **Dev separation**, addendum bar 2, on the bar-2 run (§6), the dev tier's separation run of record, over 16 lives:
   - **A pair excluding LCM-X separates:** at least one pair in the bar-2 family (§7) separates on the headline, with Holm over that family only (M = 3 with the minimum pilot roster), and with the same sign in at least 80% of lives.
   - **Known-order ablations:** both separate in their validated direction, p < .05 each:
     - (a) oracle evidence vs oracle evidence minus one necessary event, where the reachability audit shows no alternative evidence path;
     - (b) the oracle ceiling vs leave-evidence-out, on bundles whose probe-time history fits the reader's window.

     Both are validated before the v0 completion record (C-10), on the calibration set (§6). A contrast that fails validation is dropped. If both fail, the ablation part of bar 2 is unmet.
   - **Exploratory only:** naive RAG top-2 vs top-20.
3. **Inclusion.** At least 3 candidate tracks pass the §2 inclusion rule.
4. **Validity**, on every included track's final scored distribution:
   - every §4 gate holds: the battery, the minimum shares, the Drift mix and the salience gate;
   - the template census passes, and the pilot instance audit meets its bound (§5);
   - check error rates are ≤ 2%;
   - the verifier meets its recall bounds.
5. **Cost.** The board and the seasonal robustness study fit the run-time rule (its life bound and work bound, §11) at the measured sustainable capacity (C-11, §11). This is evaluated once at the end of S6, using n_L = 48 for the board because the life count is not yet known, and re-checked with the computed n_L. Tokens are reported, never a bar. The developer-tier targets (§6) are not bars; any that are missed are disclosed in the pilot report. Bar 5 also checks the paid-lane spend ceilings and the pilot runs' wall-time ceilings in §11, with the added workloads' cost terms (§11) counted.
6. **Correlation.** API mode vs system is measured per comparable cell, with no bar. API mode becomes a proxy only if pairwise deltas agree in sign across at least 4 real systems.

**Feasibility pilot.** Without a human grader pool, the pilot is labelled a feasibility pilot and cannot claim the binding gate.

**Outcomes when bars fail:**
- **The companion or bar 2 fails:** this is the **failed-pilot fallback**.
  - Narrow to the tracks where oracle evidence separates from no-memory and at least one pair excluding both LCM-X releases separates.
  - Record the result as PREREG-v0-narrowed, computed without LCM-X.
  - Run a fresh, frozen acceptance of bars 1-5 on new public seeds that played no part in the selection.
  - If the narrowed set drops Wake, the claim contract (§2) applies: the headline is a memory-action score.
- **Only bar 1's main test fails** (the companion passes): the instrument is valid and LCM-X did not separate from no-memory.
  - This is reported on #1964 as a finding and escalated to the owner.
  - It never triggers a redesign keyed to LCM-X's data.
- **Bar 3, 4 or 5 fails:** the fixes are the §2 redesign path, the §4 remedy, and the §11 cut order, followed by a fresh acceptance run of the affected bars on new public seeds.

**The developer-product acceptance bar.** This is not a pilot bar. It binds before v1 is called a developer product.
- The benchmark team, acting as developer of its **own baseline** (naive RAG, or the raw-archive marker), shows the loop end to end: a real-stack public failure, reproduced from its bundle, fixed, and confirmed on Ring 1 (§6), all within the declared T2/T3 budgets.
- No contestant system is involved, and LCM-X is not.

## 9. Difficulty calibration
- **Fixed in v0:** direction caps at 40%. The lever-mix shape and the rung ladders are fixed in the v0 completion record (C-7).
- **Set by the pilot [pilot]:** one difficulty scalar per track, so that oracle evidence scores ≥ 75 and the best of naive RAG, BM25, grep and recent window scores ≤ 35, both in raw penalised points (§2). The scalars are set from controls on the calibration set, and validated on controls over the bar-2 lives.
- **Controls only.** Difficulty is frozen from controls only. **No target or veto is set on any real system's results.** Rungs are calibrated on system-agnostic anchors only (§6), and the raw-archive marker never enters calibration.
- **Never in calibration:** any real system's score, both LCM-X releases included.
- **Valid zeros are published,** including all-zero rows.
- **Launch measurement:** "best below about 60%" is the **highest per-item action accuracy system figure** (§3) among real systems on the full-tier board, and it is disclosed beside the penalised score. It is measured and disclosed, never tuned toward, and never a release condition: no veto is set on any score.
  - Both scales are always reported. Neither converts to the other without the outcome mix, because omissions and partial credit score 0 on the penalised scale.

## 10. Systems, configuration, write turns and disclosure
- **Pilot roster:**
  - LCM-X (its plug-in release artifact);
  - LCM-X at its last release before the public generator;
  - Hermes native memory;
  - at least 2 external self-hosted systems in the pilot. The Phase 1 roster needs at least 3 (§7).
- **Selecting external competitors.** Open-source and self-hostable, with a Hermes memory-provider plug-in or a documented ingest and query API. Ranked by a public adoption metric fixed on the v0 completion date (C-9).
- **One results table with full stack identity.**
  - **Each row** declares memory × harness × model, plus the vision provider and spend.
  - **The memory headline** holds the reader and harness fixed: the pinned reader.
  - **The crossover panel** (C-13) is small and predeclared, and runs on Ring-0 Act packs, with no full grid. It is separate from the replication family (§7) and from the swap model (C-2).
    - **Cadence:** once per season, after the sealed board closes, in its own window, and once when a new PREREG version is frozen. It never runs inside a board window.
    - Its rows render past turns in the pinned reader's voice, the same text for every model. The per-model voice option (DESIGN §6.2b) is off in the panel.
    - A model from a blind-panel family (§4) is excluded from the panel.
  - **Model-native memories** appear on a separately labelled stack view, outside board eligibility. The board's open-source, self-hostable rule is unchanged. Stack-view rows follow board eligibility, minus the open-source rule; each row is vendor-submitted with a disclosed configuration.
  - **The lab slice is v1.x,** under a seal-preserving design: the benchmark runs the lab's model inside the sealed runner, with no per-item private results and no traces of private items.
  - **No targets are set on any system's scores.**
- **Configuration budget.** An equal, logged budget for every system, LCM-X included: 5 configuration trials on public developer seed packs. Vendor-submitted configurations are accepted where the owner opens a window.
- **Route table.** Per system and segment: probe model, summariser (the vendor's documented default), vision provider and alias. One pinned vision reader serves the memory-layer view (C-1).
- **Agent families.** The pinned family for every tier. The replication family in the seasonal robustness study. The card discloses the agent family that LCM-X's public release notes say its thresholds were tuned on, and whether it is the pinned family. An LCM-X version that the season's replication-family study did not cover is labelled "pinned family only".
- **The swap model** is named in the v0 completion record (C-2), after spike S4. If it is from the replication family, the whole-life swap-model comparator and the replication-family branches share lives (§6). Its reasoning effort is pinned with it (C-2). A paid lane for the swap model counts inside the board's paid ceiling (§11). A swap does not move the vision provider, which is pinned separately (C-1).
- **Global parameters.** These act on every template at once, so they sit outside the 40% direction cap. Each is frozen in v0 with a neutral rationale and disclosed:
  - **The window per tier** (C-4, C-5). The full tier uses the harness default, so no architecture gets an artificial window. The developer and bar-1 window comes from the harness overhead S6a measures.
  - **Tokens per life:** about 1M plus the long-sprint tokens: about 2.3M at W = 128K and about 3M at W = 200K (§6). The sprint count and length make compaction fire inside sessions at a known rate, while the default window keeps the harness realistic.
  - **Assistant turns per scripted session:** about 5 (§6). Write turns run sequentially, so this sets each life's critical path, and fewer, longer turns keep each life well inside the life bound (§11) without changing tokens or sessions.
  - **The Keep weights,** ¼ and ¾ (§3). They equal the four-tier mean at both extremes.
  - **Fault placement** (§6). It is one boundary for every system, between checkpoints 60 and 120, so that fault-crossing bundles exist.
- **Bundles per board life.** v0 freezes the range and the selection rule; only the computed count enters v1 [pilot].
  - **The rule:** b is the smallest value in {100, 150, 200, 250, 300} at which the within-life (sampling) share of the per-life variance of c_l is at most one third.
  - **The estimate:** that share comes from the bar-2 run's pairs in the bar-2 family, extrapolated as variance ∝ 1/b.
  - **If no value qualifies,** b = 300.
  - **Inputs** never include either LCM-X release.
  - **Certification** keeps its own powered size (§7). A board whose b falls below it issues no certificate; its results are still published.
- **Write turns,** all frozen in v0. The schedule and the file-tool rule are fixed here; the prompt text and the tool lists are fixed in the completion record (C-6):
  - **Prompt:** the exact text.
  - **Schedule:** every scripted assistant turn, for every system that declares at least one write tool. A system whose declared write-tool list is empty gets no write turns. This is decided from the tool list recorded in the ledger. S7 checks on one public life whether removing the per-turn pause changes an asynchronous passive system's state.
  - **Declared write tools:** each system's list, taken from its vendor's documentation.
  - **File tools:** a general file-editing tool is a write tool only for that system's declared memory or instruction files. The director rejects and logs edits outside those paths; they are never executed.
  - **No tuning:** none of these is ever chosen or revised using any real system's results.
- **Never run against any live production agent.** Any later test of one is an offline replay of a copy, with owner approval at that time.
- **The firewall.** LCM-X improves only through outputs every registered system gets on equal terms: the public packs, Ring 1 results, Ring 2 bits per organisation, and published cards. The benchmark session runs nothing on LCM-X beyond the scheduled runs every system gets, and never advises on its internals.
- **The card discloses:**
  - this document's version and hash;
  - the full stack identity of every row: system, harness and model pins, the vision provider, the route table and the write-turn package;
  - the clock method per harness and the skew-audit result;
  - any guard overrides;
  - filter drop logs and battery scores;
  - judge pins and the rankings under both judges;
  - coverage and the worst-case row;
  - spend and runtime by role;
  - write mode per system;
  - added turn latency per track (§2);
  - certification stability, per-item action accuracy, twin consistency and the harmful-actions panel (§7);
  - the dispatch record (§6, §11): each row's timing imbalance with the dispatch lags, the unmatched dispatches and the pooled pairs (§7);
  - the run's segments (§11): the span of each segment, each block and each (arm, life), with every life-bound breach (its own time and its class) and start-window breach; the season's span; every pause and its cause (quota, busy marker, spend or infrastructure), and every hold; every attempt; the lock hashes and the served identities; the first-half and second-half gates; the accounts each (arm, life) used; and the requests excluded from latency as the first after a pause.

## 11. Cost formulas and ceilings (per system)
The terms are defined in DESIGN §13: R, R_cap, f, P, r_c, p_c, P_K, P_W, R_B and P_B, measured per family and by role. Subscripts 10 and 20 mean a life of that many sessions.

**The board, per system:**

  Cost_board = n_L × [ R(1 + f) + 2P ] + n_keep × [ R_cap(1 + f) + 2P ]

- R includes the inline fault and its recovery, and the swap. P includes the resume-only controls.
- R_cap = max(measured R_cap, R). n_keep = max(6, ⌈n_L/4⌉).

**The seasonal robustness study, per system,** with n_rob = 8 (4 after the cut below) and q = 3:

  Cost_rob = n_rob × [ Σ_{c=1..3} 2q(r_c + p_c) + R_B(1 + f) + 2P_B + δ_W(R(1 + f) + 2P_W) + 0.2P + C_learn + C_erase ] + n_curve × 2(R_cap(1 + f) + 2P_K)

- δ_W = 0 when the swap model is from the replication family, and 1 otherwise.
- C_learn and C_erase are the added workload terms below, costed with the §6 counts: one Learn chain per applicable Learn cell (3 in a G1 life, 4 in a G2 life) and one erasure probe per scored Keep forget bundle, capped at 6.
- n_curve = min(n_rob, n_keep), so the cut to 4 study lives also cuts the Keep curve.

**The Image profile board, per system,** once the profile is on the board (§6):

  Cost_image = C_image = L_img × [ R_img(1 + f) + 2P_img ], plus vision-provider spend

- R_img and P_img are one Image-board life's run and probe costs, filled from S8 and the pilot.
- The vision-provider spend is within the owner's seasonal vision budget (Paid rows).

**Runs of record:**
- **Bar-1 run:** Cost_bar1 = 12 × [ R_10(1 + f) + 2P_10 ] for LCM-X, plus the probe cost of the four control arms.
- **Bar-2 run, per real system:** Cost_bar2 = 16 × [ R_20(1 + f) + 2P_20 ] + 4 × [ R_cap,20(1 + f) + 2P_20 ].
- **Calibration set:** probe-only control cost over 4 full-length lives.

**Added workloads.** Each is an explicit cost term, with the same names as DESIGN §13. Its value is filled from S6, S8 or the pilot; until then it is a placeholder.

| Workload | Where it runs | How it counts | Term |
|---|---|---|---|
| Learn chains, with their no-memory and frozen-skill arms | terminal forks in the seasonal robustness study (§6) | per system, per study life: one chain per applicable Learn cell, 3 in a G1 life and 4 in a G2 life | C_learn, inside Cost_rob |
| erasure probes | terminal forks in the seasonal robustness study (§6) | per system, per study life: one per scored Keep forget bundle, at most 6 | C_erase, inside Cost_rob |
| the Image profile board, both views, including the vision reader | a separate profile board (§6): L_img = 8 lives, b_img = 40 image bundles per life | per system, once the profile is on the board; one Image board run holds every system, apart from the Text board's run (§11) | C_image, above |
| the crossover panel | Ring-0 Act packs (§10), in its own window after the sealed board closes | shared, once per panel row (C-13), counted once per season; never inside a system's board window | C_cross |
| the raw-archive marker, including its K10 run, and the full-history oracle ceiling | in the season board's blocks, like the controls (§6) | shared, once per season | C_marker |
| the bar-2 A/A′ rerun of the control arms | the bar-2 run (§6) | shared, once per generator version | C_aa, added once to the bar-2 run of record |
| the probe-only arms of a full-tier run | the no-memory floor, oracle evidence with its swap-route anchor, and naive RAG, as arms of every block (§6, §11) | shared, once per full-tier run; never charged to a system | C_ctrl: the probe-only arms' probe cost |
| Ring 1 | fresh-seed runs of the public templates (§6) | per system, at each benchmark release and at least monthly | C_ring1, per run |
| Ring 2 | the held-out transfer check (§6) | per organisation, monthly | C_ring2, per check |

**Lane work and lane occupancy.** Two quantities are projected on each lane a run uses, from the declared workload counts and the spikes' requests per session, at the lane's sustainable capacity (C-11):
- **A system's lane work** for a run is the work of that system's own arms in it: replay, probes, auxiliary calls and its added-workload terms. In hours, it is the arms' projected request-seconds ÷ (3600 × the lane's aggregate concurrency: its sustained concurrency per account × the accounts the run uses there, capped by any concurrency limit the runner sets), or, where a request rate binds, the larger of that and N_req ÷ (60 × R_s × accounts), where N_req is the arms' upstream requests on that lane and R_s is per minute. Work shared by every arm (the control arms) is never charged to a system.
- **A run's lane occupancy** is all of its work on the lane, each term counted once: every arm interleaved in the run, the shared work, and every added workload scheduled on the lane while the run executes. It sets each life's projected span and the season's span. C_cross is never scheduled inside a board window (§10).

**The run-time rule** *(hard; DV47)*. It replaces the contiguous 24-hour window of PREREG-v0.1 to v0.3 for the **full-tier runs**: the full core board with its seasonal robustness study, each delta board, and the Image profile board. The pilot's runs of record (bar-1, bar-2 and the calibration set) run contiguously, within the wall-time ceilings below. A full-tier run executes in locked, resumable segments, and meets two bounds:
- **The life bound:** every replaying arm's run of a life, its branches and probes, finishes within 24 h of that arm's first upstream request on that life. The projection checks each replaying (arm, life)'s span, from that first request to its last branch or probe, under the projected schedule and the run's lane occupancy. An (arm, life) that breaks the bound in the run is classified by cause (§7). Its span less the time the ledger attributes to benchmark-owned causes (pauses, director-held waits, waits for lane capacity or for other arms, and INFRA_FAILURE reruns) is its own time. When its own time exceeds 24 h, the system caused the breach, and its bundles not yet probed at the bound are SYSTEM_FAILURE; otherwise it reads BLOCKED. Its span and own time are disclosed (§10).
- **The work bound:** for each system, its lane work for its board, for its seasonal robustness study and for its Image profile board, each times (1 + a), is at most W_max = 96 h on every lane the run uses. Each is bounded on its own; they are not summed. The pause allowance a = 0.25 covers busy-marker, quota and spend pauses. W_max is the per-system ceiling PREREG-v0 set before v0.1 tightened it to 24 h.
- **The season's span** has no bound of its own. It is projected from the lane occupancy before the board starts and disclosed on the card (§10).
- **It is sized by measured capacity:** the sustainable capacity (C-11) of every lane the run uses (the pinned family's, the swap model's and the replication family's), paced per account, with the busy marker's `glm` pause for any GLM-plan use. No credit or token arithmetic gates it.
- **A run that cannot meet the rule** at the sustainable capacity applies the cut order below.
- **If it still cannot,** the owner decides between more plan accounts, paid capacity and a narrower design. The rule is never waived silently.

**Segments, blocks and the run lock:**
- **A segment** is a stretch of a run between two pauses. **A block** is one life, run by every arm on the roster. Blocks start in published seed order, and a block may start before the previous one finishes.
- **The seasonal robustness study runs inside its board's run:** the season board's, or at a major release, that GA's delta board's. It shares that run's lock and blocks. Its work bound and its cost term are counted on their own.
- **Publication:** a run is published when it completes, or when it ends early (an identity stop, a spend stop or a refused resume), with its completed blocks and the cause labelled. A run that ends early is published as diagnostics: it sets no gate and issues no verdict or certificate.
- **The run lock** is hashed at the start of a run and verified at every segment start. A resume is refused on any mismatch. The lock covers:
  - the benchmark commit, the analysis-code hash (C-8) and the director commit;
  - the generator version, the seeds manifest, and the hash of the rendered history set, which is rendered in full before the run starts;
  - each harness's binary or package hash, and each system's artifact hash;
  - the environment manifest: OS build, interpreter and lockfile hash, with auto-updaters off;
  - the route table (every model the run may call, by name and route), the write-turn package and the tool lists (C-6);
  - the account pool.
- **Served identities** are recorded beside the lock: each route-table model's served identity at its first response in the run, the controls' responses included.
- **Randomness is keyed:** every draw is a function of sha256(seed, unit id, attempt), never of a stream position. The unit id names the (arm, life, branch, session) the draw belongs to. Every benchmark process runs with `PYTHONHASHSEED=0`. Rendered content is fixed by the locked history set, so only run-time draws use the key: the arm order, the account assignment and the checkpoint dispatch order (§6), whose unit id is the (life, branch, checkpoint, arm id) at attempt 0. On a resume, the simulated clock is set from the schedule, never from elapsed time (DESIGN §6.6).
- **No grafting:** a snapshot is resumed only under its own lock. A different system version, harness, model or benchmark version never continues an old snapshot.

**Drift controls:**
- **Served identity:** the director checks every response's served identity against the identity recorded for that model. A new identity stops the admission of new sessions; sessions in flight finish and are flagged.
- **In-block controls.** The control arms are arms of every block, on the pinned reader, and their checkpoint probes follow the dispatch rule (§6). Pinned-reader drift between blocks therefore reaches a life's controls and its systems in the same block; within a block, a gate's probe times are a keyed-random sample of the roster's own checkpoint times, delayed where a pass-over releases them. Every gate comes from the same blocks as the scores judged against it. Drift is absorbed on average over the roster's times, not tested, and not cancelled row by row.
- **The start window:** every replaying arm of a block makes its first upstream request within 24 h of the block's first, so two replaying arms' requests on one life are at most 48 h apart, and every probe-only dispatch falls in the same 48 h, apart from its recorded lag and retries (§6). The projection checks it as it checks the life bound. An (arm, life) that breaks it reads BLOCKED, as an infrastructure cause, and is disclosed (§10). Both bounds bind the arms that replay; a probe-only arm's times follow the dispatch rule (§6).
- **What it does not cover** (stated on the card):
  - drift on the swap route, which serves the systems' post-swap probes but never a control's;
  - drift in write turns and in the summariser, which act on systems only;
  - an excursion shorter than the gap between a gate's probes and a row's own;
  - a row's timing imbalance: a row that runs systematically faster or slower than the roster meets a time-varying reader effect at other times than its gate's probes, which moves its margin even when it sits at its gate (DESIGN §6.7a);
  - account-dependent serving: S9's carry-over check shows that an account keeps no state across requests, not that accounts serve alike after quota moves;
  - the lag between a followed arm's arrival and a probe-only arm's sends, and their serving delay;
  - the residual of a shared reader change, which moves a system's margin in proportion to its distance from the gate.
- **Reported, never tested:**
  - the first-half and second-half gates (§7);
  - each control cell's slope against block start time;
  - each row's **timing imbalance:** the mean and spread, over its (life, branch, checkpoint) probes, of its own probe send time minus its gate's probe send time, in hours, over its pairs with their own controls, with the dispatch lags (§6);
  - the **swap-route anchor:** in every block, the oracle-evidence arm also answers that life's first 20 post-swap bundles, in seed order, on the swap route, under the dispatch rule. Its per-block result is printed beside the gates.
- **After an identity change,** the run ends, and its completed blocks are published as diagnostics, with the cause labelled. Only the stopped run restarts, as a fresh run of its own kind (§6) on the same lives, under a new lock. Runs completed before it stand. Cell gates, verdicts and certification use the restarted run's own blocks. The restarted run shares the stopped run's paid-lane ceiling (below), unless the owner raises it.

**Pauses:**
- **Where:** only at session boundaries, with the harness process exited. Never between the inline fault's SIGKILL and its cold restart (§6).
- **Holds are not pauses.** A quota refusal, a rate refusal or a `glm` flip inside a session makes the director hold that session's requests. The session runs on to its next boundary, where a pause may begin. Held time is excluded from latency. A failure caused by a director-held wait (a harness timeout on a held request, say) is INFRA_FAILURE; a system failure independent of the wait keeps its cause-based attribution (§7).
- **Service-backed systems:** each system declares one boundary behaviour: its services paused in place, or drained to a settle barrier, snapshotted and cold-started. That behaviour is applied at every session boundary of every run, whether or not a pause falls there, so the event sequence is the same with or without a pause.
- **The proof:** at the pause, after the boundary behaviour completes, every agent-visible surface (DESIGN §6.7) is hashed; at the resume, before the harness starts, it is hashed again.
  - A failed proof refuses the resume, and the cause decides first (§7). When the ledger shows a benchmark-owned fault, it is INFRA_FAILURE: the (arm, life) is restored from the pause snapshot and verified again, as an attempt under the attempt rule (below).
  - Otherwise it is SYSTEM_FAILURE for that life's bundles not yet probed, and the snapshot is not restored.
  - A system whose agent-visible surfaces cannot be hashed as files pauses only between lives.
- **Latency:** the first request of each (arm, life) after a pause is flagged and excluded from latency figures.
- **Before the first full-tier run,** spike S9 shows that a pause is invisible, at $0 on public lives, on Hermes native, one service-backed system whose writes settle in the background, and the controls; never on LCM-X (§10). One pinned-lane session that holds compaction or encrypted reasoning state is also resumed after at least 24 h, and on a spare account.
  - If S9 fails for service-backed systems, their pauses fall only between lives.
  - If the spare-account resume fails, each (arm, life) keeps one account for its whole life.
  - S9 also runs the §6.8 carry-over canary items (DESIGN §6.8) on a control arm after a system on the same account, to show that a lane account keeps no state across requests. If it fails, the control arms get accounts of their own.

**Attempts:**
- **A probe-only (arm, life)** (a control arm or naive RAG) follows the cause rule (§7) like any arm: a reader's wrong, refused or unparsable answer is its scored outcome and is never retried. After an INFRA_FAILURE, its failed probe items are re-sent as soon as the failure is classified, under the two-rerun limit below, with their send times and lag recorded; it has no start window or life bound of its own (§6). If the items still fail, a control (arm, life) leaves gate estimation in every cell and its systems' margins use the pooled gate (§7); a naive-RAG (arm, life) leaves the CLEAR test (§4). Its BLOCKED items exclude only that probe-only arm, and the systems keep every result.
- **For an arm that replays,** only the failed (arm, life) is re-executed, from its last session-boundary snapshot, and only after an INFRA_FAILURE that the ledger attributes to a benchmark-owned component. Each bundle counts toward §7's limit of two reruns, then reads BLOCKED. The last attempt is scored. A SYSTEM_FAILURE never triggers a re-execution.
- Every attempt stays in the ledger and on the card. No run is published with a shrunk denominator, and results stay sealed until the run completes or ends early (above).

**Scheduling:**
- **Every arm in blocks,** the control arms included (§6). Within a block, the order of arms and the assignment of accounts are drawn by keyed randomness, with accounts spread evenly across arms, and every replaying arm starts within the start window (above). The control arms' probes follow the checkpoint dispatch rule (§6). An (arm, life) keeps its account unless a quota stop moves it, and S9 decides whether it may move (above).
- **In the same block as the originals:** the A/A′ reruns, the fault reruns and the whole-life swap-model comparator (§6).
- **Delta boards:** the new GA and the system's previous version run interleaved in the same blocks (§6).

**Spend in the run.** Paid-lane spend is reserved before it is spent:
- **Per request:** before the director sends a paid request, it reserves the request's largest billable cost: its input tokens plus its output cap at list prices, where a request with no cap of its own counts the model's documented maximum output. The unused part is released when the response arrives. A request whose reservation would pass the run's ceiling (below) is held, and the run pauses at that session's next boundary until the owner raises the ceiling.
- **At every block start:** the metered spend, the open reservations, the projected remainder of every block already admitted and the next block's projection are summed. If the sum would pass the ceiling, the next block is not admitted; admitted blocks continue within their reservations, and the run pauses until the owner raises the ceiling.
- **If the owner does not raise it,** the run ends early (a spend stop) and is published as diagnostics (above).

**Sustainable capacity** (completion slot C-11):
- **The value** is the sustainable capacity per account of each lane a run uses (the pinned family's, the swap model's and the replication family's), as measured by the spike on that lane (S6a, S6b, or a paced soak on that lane), with the number of accounts the run uses there.
  - Where concurrency binds, it is the sustained concurrency.
  - Where a request rate binds, it is the paced rate R_s, set below the observed refusal threshold. Before the pilot, a paced soak of at least 10 minutes with no rate refusal, on the account count the run uses, confirms it and measures probe cost at scale; if the soak is refused, R_s drops to the largest clean rate.
- **The fit:** a run fits when, on each lane it uses, each system's lane work for each of its runs, times (1 + a), is at most W_max, and every replaying (arm, life)'s projected span under the run's lane occupancy is at most 24 h, with every block inside its start window (above). The occupancy counts each lane's in-block control load, the swap-route anchor included. The projection gives each life's chain priority on its lane, and states the swap session it assumes.
- **Pacing:** the director paces each account at R_s, so a run never relies on rate-limit retries.
- **Throttling** follows the gauntlet's busy marker:
  - exit 10 means light work only (nice 19, at most 2 cores, no local-embedding ingest);
  - exit 11 means no CPU-heavy work;
  - GLM-plan use pauses while the marker's `glm` field is true.

**Ceilings.** Tokens over plan lanes are **reported, not ceilings**. A **plan lane** (also called a subscription lane) is one whose use adds no charge at the margin; any per-token or per-call charge makes a **paid lane**. Each full-tier run's paid-lane spend, all systems together, is capped at $100, the owner's limit of 2026-10-26 of $100 per test. The board's run includes its study (above). Work on plan lanes alone has no spend ceiling.

| Run | Time | Paid-lane spend | Tokens over plan lanes (reported) |
|---|---|---|---|
| full core board with its seasonal robustness study, all systems | **every replaying (arm, life) ≤ 24 h; each system's board work and study work, each ≤ W_max** | ≤ $100, unless the owner raises it | input (cached counted) and output |
| delta board, both versions | **every replaying (arm, life) ≤ 24 h; each version's work ≤ W_max** | ≤ $100, unless the owner raises it | input and output |
| Image profile board, all systems | **every replaying (arm, life) ≤ 24 h; each system's work ≤ W_max** | ≤ $100, unless the owner raises it; vision-provider spend separately, within the seasonal vision budget (Paid rows) | input and output |
| bar-1 run, all arms | ≤ 8 h wall time | ≤ $10 | input |
| bar-2 run, per real system | ≤ 8 h wall time | ≤ $25 | input |
| calibration set, all controls | ≤ 24 h wall time | ≤ $25 | input |

- **A paid row projected over its ceiling** (a swap model on a paid API, say) goes to the owner before the run starts. It moves to a plan lane only where that lane serves the same pinned model at its pinned effort, and the cut order applies to it only if the owner chooses it. A paid lane's spend is projected at its pinned effort (C-2).

**Paid rows:**
- The pinned vision reader is a labelled paid row, at about $50 a season, the budget the owner approved on 2026-10-26.
- Embedding spend (naive RAG's embedder, or a system's vendor-default hosted embedder) is a labelled paid row under the owner's standing embedding grant of up to $100 per run, outside the paid-lane ceiling.
- The blind panel's third family (C-3) runs on a plan lane, or as its own capped run with a projected filter spend of at most $100 per release.

**Instantiation.** The board and the study use n_L = 48 at the end of S6, and the computed n_L afterwards. The runs of record use S6a's and S6's measured cumulative costs through sessions 10 and 20.

**Cuts if a projection does not fit,** applied in order:
1. bundles per board life down to 100, with the achieved MDE disclosed;
2. the robustness study from 8 lives to 4;
3. lives down to 24, with the achieved MDE disclosed.

If a cut leaves a season below the certification rule's powered size (§7), no certificate is issued that season, and its results are still published. If it still does not fit, the design returns to the owner, who decides between more plan accounts, paid capacity and a narrower design.

## Changelog: PREREG-v0.1 → PREREG-v0.2
- **Status and identity:** frozen for design v2.0, with its hash in `prereg/FREEZE-v0.2.md`; DESIGN-v2.0; the Image profile marked pending; requirements met differently recorded; the decision record cited as `docs/DECISIONS-v2.md`.
- **Freezes:** rules frozen, not per-season contents; slots C-12 to C-15 added, C-1, C-7 and C-8 extended, no credits slot; the operating-characteristic freeze gate for PREREG-v1, with its pass criteria, setting the final certification size; the redesigned scoring goes to the veto reviewer before PREREG-v1; C-1 names the pinned agent family and S8's vision-capable main model.
- **Notation:** M for the contrast count and q for fault reruns, so the subscript k indexes cells only; L_img and b_img added.
- **§2:** the capability map with the Remember, Survive and Act stages; evaluation profiles and their declarations; the cell inventory and the census annotation, with required cells from the track design; the Image profile's sealed-board season; E2's confirming spike; Learn as a supporting diagnostic, with the shared-memory chain in G2; Flatten deferred and not in the pilot; Hands with World profiles; the claim contract; per-item accuracy, G1 task completion and added turn latency reported; track inclusion condition 1 on the raw scale, a track test separate from cell admission, with every §2 and §9 threshold in raw penalised points; a placement reason for every season-1 frontier annotation.
- **§3:** the penalised scoring stated as the scoring that decides; accountability without an authorised-clarify outcome; per-item action accuracy defined, with its eligible items, exclusions, system failures counted as incorrect, and the equal-weight system figure with its CI and incomplete label, with N/A_EXPOSURE and N/A_CLOCK excluded as for the penalised score; failure attribution by cause, not reporter; no conversion between the two scales; the violations panel, which is the harmful-actions panel; the "Unsupported" cause label; Keep tiers named K100-K3; erasure probes beside the forget bundles.
- **§4:** attestation twins; frozen common item IDs and filters; blind-panel families excluded from the crossover panel; cell admission on the raw scale, a test separate from track inclusion; Image profile items and image twins; community templates.
- **§5:** image fidelity checks and their bounds.
- **§6:** Ring 0, rungs, repro classes, guarded loops, Ring 1 and Ring 2 with its "transfer gap detected" and "no gap detected" readings; long sprints by count; the long horizon in the research tier; the raw-archive marker; the bar-2 A/A′ control rerun; the Image profile board; Learn chains and erasure probes in the robustness study; certification on season and delta boards; the Learn-chain and erasure-probe counts per study life, as planning values; the Image board's planning size, with no certificate at that size; "fault point", "swap model", "replication family", "the pinned family", "the whole-life swap-model comparator" and q-rerun naming.
- **§7:** cell gates from the board's control arms, on the raw penalised scale, display verdicts, the intersection-union certification rule and its bootstrap, eligibility and the coverage-shortfall rule, non-results, BLOCKED; planning values and the powered size; the paired confirmatory family unchanged, with M for its contrast count; per-item accuracy's own item denominator.
- **§8:** bars keep their own statistics; the marker is a control; bar 5 on the 24-hour rule at measured concurrency, plus the spend and wall-time ceilings; the claim contract in the fallback; the developer-product acceptance bar.
- **§9:** difficulty from controls only; valid zeros published; the launch measurement as the highest per-item accuracy system figure among real systems, never a release condition; the difficulty targets in raw penalised points.
- **§10:** one results table with full stack identity; the crossover panel, with common rendering, stack view and lab slice; the vision provider, pinned separately from the swap; tokens per life by the long-sprint rule; the firewall; the crossover panel's cadence, once per season and at each new PREREG freeze; "any live production agent".
- **§11:** n_L notation; the 24-hour rule sized by measured concurrency; tokens report-only; the vision paid row; the added workloads' cost terms and the load sharing the lane, with the Learn-chain and erasure-probe counts, the Image board's cost formula and its own 24-hour run, and C_cross outside every board window; q in Cost_rob; no certificate below the powered size after a cut.

## Changelog: PREREG-v0.2 → PREREG-v0.3
- **Status and identity:** frozen for design v2.1, with its hash in `prereg/FREEZE-v0.3.md`. The owner co-sign is removed from the status, the completion record and the approval rule; the owner retired it on 2026-10-26.
- **DV42 decided** (`docs/DECISIONS-v2.md`): the pinned family is OpenAI (gpt-6.1-sol at medium effort, on dedicated benchmark accounts), and GLM (Zhipu) is the replication family and the swap model. C-1, C-2 and C-11 are filled in the v0 completion record by their rules. This text changes only rules.
- **§4 and C-3:** the blind panel becomes Anthropic, Zhipu and one paid third family, because the pinned family is never on the panel. C-3's rule becomes "other than Anthropic, OpenAI and Zhipu". The crossover panel's rule (C-13) is unchanged, and C-13 is re-checked against the new panel.
- **§11 and C-11:** "permitted concurrency" becomes "sustainable capacity" per account, with the account count: the sustained concurrency, or the paced request rate R_s where a request rate binds. Spike S6b found a per-account request-rate limit on the Sol lane, not a concurrency limit. The fit rule, the paced-soak confirmation and director pacing are now stated. Bar 5 (§8) reads at the measured sustainable capacity.
- **§10, tuning disclosure:** now generic. The card states the agent family that LCM-X's public release notes say its thresholds were tuned on, and whether it is the pinned family.
- **Unchanged:** the judge rule (DESIGN §7: two pinned judges from different families, neither used by any tested agent). Under DV42 it gives Anthropic plus one family that no tested agent uses. Every other rule, constant and threshold is PREREG-v0.2's.

## Changelog: PREREG-v0.3 → PREREG-v0.4
- **Status and identity:** frozen for design v2.2, with its hash in `prereg/FREEZE-v0.4.md`.
- **DV47, the run-time rule** (`docs/DECISIONS-v2.md`), at the owner's direction of 2026-10-26, for the full-tier runs (§11). The contiguous 24-hour window becomes locked, resumable segments, with a life bound of 24 h per replaying (arm, life), and a per-system work bound of W_max = 96 h for each of a system's board, study and Image board, at a pause allowance of a = 0.25. A system's lane work and a run's lane occupancy are projected separately. The pilot's runs of record stay contiguous, within wall-time ceilings.
- **Validity controls** (§6, §11):
  - blocks of one life, in seed order;
  - the run lock, with the served identities recorded beside it, and keyed randomness;
  - the served-identity check;
  - the control arms and naive RAG as arms of every block, on the pinned reader, with checkpoint-dispatched probes under a frozen pass-over rule; gates and admission computed after the last block, with per-life margins and a defined pooled gate; a 24-hour start window per block; a control mechanics check before the first block; a report-only swap-route anchor and each row's timing imbalance; a probe-only arm's cause and retry rule; the raw-archive marker as a replaying arm and the full-history oracle ceiling as a once-per-season probe-only diagnostic, both in C_marker; and the OC simulation's drift envelope, defined on the pinned reader with a stress schedule and hashed in C-8;
  - pauses at session boundaries, with a hash proof of every agent-visible surface; holds inside sessions; spike S9;
  - attempts per (arm, life);
  - the study inside its board's run;
  - publication of runs that end early, and a restart of the stopped run only.

  The card's segment disclosures follow (§10). Bar 5 reads the run-time rule (§8). §7 computes each c_l within its block and reports a first-half and second-half sensitivity, and the gates get the same sensitivity.
- **DV42's fit corrected:** the projection behind DV42 left the mid-life swap's lane uncounted. The fit now covers every lane a run uses (§11, C-11), and C-2 pins the swap model's reasoning effort.
- **Paid-lane ceiling:** $100 per full-tier run, all systems together, the owner's limit of 2026-10-26, down from $300 per system. Each paid request is reserved at its largest billable cost before it is sent, and every block start counts the open reservations and the admitted blocks' remainders, with a spend pause. Plan and paid lanes are defined, and embedding spend and the blind panel's third family are placed (§11, C-3).
- **Unchanged:** every other rule, constant and threshold is PREREG-v0.3's.
