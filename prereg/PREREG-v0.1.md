# Bicentennial pre-registration — PREREG-v0.1 (pilot)

**Status:** PREREG-v0.1, frozen 2026-10-26 by the benchmark session. It supersedes PREREG-v0, which was frozen earlier the same day and never co-signed, by adding the **24-hour rule** (§11) at the owner's direction. It follows three adversarial review rounds, a closure check and a first-principles cost review, summarised in `docs/REVIEW-SUMMARY.md`. Its sha256, commit and time are posted on lcm-x #1964, where the owner co-signs them.

**Precedence.** This document is the **only normative source** for every frozen quantity: constants, rules, thresholds, rosters, sample sizes, tests and ceilings. DESIGN-v1.4 (`docs/DESIGN.md`) explains and motivates. Where the two differ on a frozen quantity, this document governs, and the difference is logged as an erratum to DESIGN. "The addendum" means the binding requirements summarised in `docs/REQUIREMENTS.md`.

**Freezes:**
- **PREREG-v0.1, this text,** covers everything below except the values marked [pilot] and the completion slots.
- **The v0 completion record** (`prereg/PREREG-v0-completion.md`) fills the completion slots below, each by its stated rule.
  - **When:** it is committed, with the hash of every artifact it names, before any real memory system's first pilot run. The owner co-signs its hash.
  - **What may come earlier:** spikes and control-only runs.
  - **The firewall:** no slot may be filled from any real system's scores. Spike measurements of cost, timing and harness overhead are allowed.

  | Slot | What | Rule |
  |---|---|---|
  | C-1 | agent family A: the pinned model, and the route table (probe model, summariser and alias per system) | each system's vendor-documented defaults; the pinned model must be servable through the director on a subscription lane (S1, S4) |
  | C-2 | model B for the swap (§10) | a model from a family other than A, servable through the director; named after S4 |
  | C-3 | the blind panel's paid third family (§4) | one family other than Anthropic, OpenAI and family A |
  | C-4 | the full-tier window (§6) | the pinned model's harness default, by name |
  | C-5 | the developer-tier window and the bar-1 window (§6) | the smallest of 16K, 24K, 32K, 48K and 64K that is at least twice the harness's fixed overhead (system prompt plus tool schemas) on the pinned model, as measured in S6a |
  | C-6 | the write-turn prompt text, and each system's declared write-tool list (§10) | tool lists from each vendor's documentation |
  | C-7 | every template's decision table, the lever-mix shape and the direction labels (§3, §9) | taken from the template build, before any real system runs on a template |
  | C-8 | the analysis code that computes every [pilot] value, and the scorer | hashed from the repository |
  | C-9 | competitor selection: the public adoption metric, its date, and the resulting ranked list (§10) | the metric is fixed on the completion date |
  | C-10 | the validation of the known-order ablations on the calibration set (§8) | controls only |
  | C-11 | the permitted concurrency (§11) | the sustained concurrency of the agent's model lane, measured in S6a, together with whether the 24-hour rule is met on it |

- **PREREG-v1** adds the [pilot] values, computed by the frozen code, plus the full-tier roster and seed hashes. It is frozen before **any** system's first full-tier run.
- **Approval.** The benchmark session approves each freeze, under the owner's grant of 2026-10-26, which replaced the integration-owner approval in the original brief. The owner co-signs each freeze hash on #1964.
- **External veto.** An external reviewer with a veto over scoring is recruited before PREREG-v1, and the owner decides who. PREREG-v1 is not frozen without one unless the owner waives that in writing on #1964.

**Change control:**
- Every change makes a new version with a changelog, and every result discloses the version used.
- The pilot may set only the [pilot] values, and only through the frozen code.
- Pilot analysis runs on blinded system codes until the [pilot] values are committed.

**Notation:**

| Symbol | Meaning |
|---|---|
| n_T | number of included tracks |
| T_{s,t} | a track score |
| w | the Wake pickup window |
| n_f | faults per life: 1 inline on the board, 3 in the robustness study |
| k | reruns per fault cell (robustness study) |
| L | lives in a tier |
| m | number of contrasts in a confirmatory family |

## 1. Identity
- **Design:** DESIGN-v1.4. Its hash is recorded at freeze.
- **Generator:** the version is recorded at freeze.
- **Genres:** G1 software partner and G2 personal assistant, in text and code.
- **Agent families:** the primary agent family (A) is pinned in the route table. A second family (B) runs in the seasonal robustness study (§6).

## 2. Tracks, estimand and headline
- **Candidate headline tracks:** Wake, Rachael, Tuesday, Drift and Keep.
  - Flatten is a diagnostic until a live establishment segment exists for each tested agent.
  - Hands joins at the frontier tier.
- **Inclusion** (ordinary, when the pilot passes). It is computed from controls only, on the **unfiltered sample** (§4), so it never uses any real system's data. A candidate track is included only if all three hold:
  1. **Not near-solved,** on the calibration set (full-length lives, §6): naive RAG's normalised score is below 70, and the no-memory floor is below 0.7 × oracle evidence.
  2. **Measures memory,** on the bar-2 run's control arms (16 lives, §6): oracle evidence separates from the no-memory floor (life-level sign-flip, p < .05). Four calibration lives cannot reach p < .05: the floor is 2/2⁴ = .125.
  3. **Valid:** it passes the validity bar (§8, bar 4) on its final scored distribution.
  - **Redesign path.** A track failing condition 3 may be redesigned and re-validated on fresh calibration seeds, without LCM-X data, before the PREREG-v1 freeze. Otherwise it is excluded.
  - **Power is never a criterion.** A track that is hard for every real system stays in.
  - **Reporting.** An excluded track is reported as a diagnostic, with the reason.
- **Estimand:**
  - **Bundle:** the score of a bundle is the minimum of its two items' scores.
  - **Final scored distribution:** the post-filter, memory-exclusive action bundles of a track. The unfiltered sample never enters it.
  - **Track:** T_{s,t} is the mean, over the lives 𝓛_t where the track is measured, of each life's mean bundle score. 𝓛_t is every life of the run, except Keep's. Keep's score exists only on that run's Keep subset (§6): the board's, or the bar-2 run's four lives. There it is ¼·T100 + ¾·T10 (§3).
  - In c_l, Keep's contribution is reweighted by |𝓛| / |𝓛_Keep^{ab}|, as the formula below does for every track.
  - The sign rule of bar 2 counts the c_l of all of the run's lives.
  - Bar 1 is the exception: it scores Keep at 100% on every life (§8).
  - **Headline:** H_s is the equal-weighted mean of T_{s,t} over the included tracks, reported from −100 to 100. Weights are fixed and equal.
- **Per-life contributions** for a pair (a, b):
  c_l = Σ_t (1/n_T) × (|𝓛| / |𝓛_t^{ab}|) × 1[l ∈ 𝓛_t^{ab}] × (T_{a,t,l} − T_{b,t,l}).
  - T_{a,t,l} and T_{b,t,l} are computed on the bundles valid for **both** systems.
  - 𝓛_t^{ab} is the set of lives with at least one such bundle.
  - The mean of c_l over the lives equals the pair's headline difference on that common set.
- **The budgeted headline row** (reported, never confirmatory). It is computed on the Keep subset only:
  - every included track uses the 10%-cap branches, and Keep uses its 10%-tier score;
  - c_l^budget = Σ_t (1/n_T)(T^{10%}_{a,t,l} − T^{10%}_{b,t,l});
  - an exact sign-flip test and a wild cluster bootstrap CI over the subset's lives;
  - **Caps,** applied after the run (nothing is truncated, so execution is unchanged):
    - an item whose probe request exceeded 64K input tokens, measured from the ledger, scores 0 in this row;
    - a system whose p95 latency per memory operation on the reference machine exceeds 2 s over the subset is shown as over-cap and scores 0 for the whole row;
  - **Validity and weighting:** c_l^budget uses the §2 common-valid-set rule, with 𝓛 = the Keep subset.
- **Also reported:**
  - the normalised score, from the no-memory floor (0) to oracle evidence (100);
  - environment-recoverable bundles, as a diagnostic;
  - the family-B replication row (H^rep, §7), from the seasonal robustness study;
  - the Wake wake-crossing contrast (§3).
- **Supporting families:** Recall and Procedural are reported, never in the headline in v1.

## 3. Scoring

**Action items.** The class comes from the action trace and the end state; text never sets it. Each template's decision table is frozen in the v0 completion record (C-7). Evaluation runs in this order:
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

**Checks** return a base verdict plus a benign-extra flag:
- The base verdicts are PASS, FAIL_MEMORY, FAIL_TASK, OMISSION and HARMFUL_EXTRA.
- Order of precedence: FAIL_MEMORY and HARMFUL_EXTRA, then FAIL_TASK, then the rest.
- **Ask channel:** one fixed, non-revealing reply to every question about past statements.

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
  - **Model swaps:** the swap is an event in every full-tier life. Swap bundles are confirmatory only in the seasonal robustness study, where the "B throughout" comparator exists. On the board and in dev they are diagnostic.
- **Flatten** (diagnostic): the paired violation-rate difference, pressure minus calm.
- **Keep budgets:**
  - Tiers are 100%, 30%, 10% and 3% of the raw stream's bytes. Store size is measured externally over every recoverable surface, **above the system's own empty-store baseline**, which is measured before any ingest.
  - A system above a tier's cap scores 0 on that tier's bundles. A system that cannot cap is placed at its natural size and scores 0 at every tier below it.
  - **On the board and in the bar-2 run,** Keep's track score is **T_Keep = ¼·T100 + ¾·T10** on the Keep subset.
    - **Where it matches the old four-tier mean:** a system above every reduced cap scores T100/4 under both rules, and a system with the same score at every tier scores the same under both.
    - **Where it does not:** a system whose natural size falls between two caps can score differently. For example, one at 8% of the raw bytes scores (1, 1, 1, 0) across the tiers: 1 here, against .75 for the four-tier mean. This is disclosed.
  - **The budgeted row** is unchanged: T10 on every track (§2).
  - The four-tier mean is reported from the seasonal robustness study.
- **Keep forgetting:**
  - A forget bundle is a **trigger twin**:
    - B0: the forget request was made, and using the item is wrong;
    - B1: no request was made, and using the item is correct.
  - The bundle scores the minimum of the two. A system that never stored the item fails the B1 item, so it cannot pass by never remembering.
  - Neighbour retention is a separate Keep bundle, reported alongside.
- **Faults:**
  - **On the board:** one system-neutral scripted fault per life, inline at a fixed turn boundary (§6). It is never tied to a system's own background calls. Fault-crossing bundles (evidence before the fault, probe after it) are also reported separately, as a diagnostic.
  - **In the seasonal robustness study:**
    - role-relative faults (for example, during a system's own summariser call);
    - robustness is the paired delta against the fault-free twin;
    - a rerun passes if its bundle score is at least the twin's;
    - pass^k with k = 3, with fault timing jittered by a seed per rerun.

## 4. Bundles, tagging, balance and filters
- **Bundle types:**
  - value twins;
  - trigger twins, covering restraint, forgetting, correction vs hedge, and commitment made vs cancelled;
  - source twins: a plant vs a genuine message on the same channel and in the same wording. Where an authority rule decides, the genuine twin comes from the authorised source, so the two golds differ.
- **One twin life per base life.** All decisive facts are flipped at once, with independence checked by the generator.
- **Tag verification**, run on every bundle before any filter:
  - A memory-exclusive bundle that the environment-search agent or always-verify passes on both items, in at least 2 of 3 trials, is retagged `env_recoverable`.
  - Retagging never deletes a bundle.
- **The unfiltered sample.** A fixed 20% of each track's bundles, drawn by seed before filtering, skips filters 2 and 4. In the bar-1 run (§6) it is 100%.
  - It is used only for inclusion conditions 1 and 2, bar 1 and its companion, and filter-yield reporting.
  - It never enters the headline.
- **Filters**, run on every other bundle every release, with drop logs published:
  1. **Literal copy:** a rare 3-gram (top 1% by IDF over the life's stream) shared between task and evidence. Overlap is otherwise stratified by tertile. Retrieval rank is never a filter.
  2. **Blind panel:** three families: Anthropic, OpenAI and one paid third family, named in the v0 completion record (C-3). The pinned agent family is never on the panel.
     - A family *passes the bundle* if it passes both items without evidence, in a single-call form; abstention counts as a fail.
     - The bundle is dropped if at least 2 families pass it.
     - Pre-filter blind-pass rates are reported.
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
- **Filter yield.** A template that loses more than 50% of its bundles to filters is redesigned.

## 5. Ground-truth fidelity budgets
- **Verifier suite:** at least 50 cases per error class (value edit, omission, added fact, anachronism, speaker swap, modality shift, implicature). Each class needs recall ≥ 0.90, with a two-sided 95% Wilson lower bound ≥ 0.80.
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

## 6. Tiers, subsets and branches
There are two ladders. **Developer tiers** carry no decision bar. **The measurement ladder** carries every bar and every board claim.

**Developer tiers.** Their targets are engineering budgets, not bars. Every developer-tier result is labelled "not predictive of the full tier" until dev-predicts-full has been measured (DESIGN §9).

| Tier | What runs | Target | Use |
|---|---|---|---|
| T0 probe packs | micro-lives of 1-3 sessions per track and ability, scored by a scripted reader, with no model | ≤ 60 s, $0 | unit and regression tests |
| T1 CI smoke | 2 public lives × 20 sessions through the real adapter with a scripted model; the regression corpus; fault-lite cells; a wiped-store positive control that must fail | ≤ 10 min, $0; deterministic on stable result fields | merge gate |
| T2 live smoke | about 10 public lives × 8-10 sessions with live probes; the candidate arm against cached controls | ≤ 1 h per arm, $0 on subscription lanes | large effects only |
| T3 dev | public 20-session lives with a bundle budget chosen before the run, run in a fixed stratified order; paired against the developer's own cached previous run, with its MDE and an A/A′ band | about 1 h per arm; an optional overnight dev+ ≤ 8 h | a paired development delta |
| Fault finder | search over levers and scripted fault points on public seeds, then shrinking over the event schedule | ≤ 15 min of search + ≤ 15 min of shrinking, $0 scripted by default | a minimal failing public life and its repro bundle |

- **Windows.** Each developer tier's context window is frozen in the v0 completion record (C-5), from the harness overhead S6a measures. It is never chosen from any real system's results.
- **Seeds.** Developer seed packs are public. The runs of record below use fresh seeds that were never published in a pack.
- **The public regression corpus** is stocked from controls, reference stubs and equal runs over every board system, never from one system's failures. The benchmark session never runs the fault finder on LCM-X.

**The measurement ladder:**

| Run | Lives | Sessions per life | Content | Cadence |
|---|---|---|---|---|
| calibration set | 4 public, full length | ~200 | controls only; no real system runs on it | once per generator version |
| **bar-1 run**: the smoke tier's separation run of record | 12 fresh public | 10, dense, at the frozen bar-1 window | ~25 action bundles per life, all unfiltered; arms: LCM-X, no-memory, oracle evidence, naive RAG, and the oracle ceiling where the history fits (addendum §E) | once per generator version |
| **bar-2 run**: the dev tier's separation run of record | 16 fresh public | 20 | 30-40 bundles per life, stratified; the full pilot roster and controls; Keep at 100% and at 10% on a 4-life Keep subset; no robustness branches | once per generator version |
| **full core board** | L private (§7) | ~200 | b bundles per life [pilot, by the §10 rule; 150 is the planning value], ≥ 60% action; checkpoints at 20, 60, 120 and 200; the board inventory below | once per season, plus delta boards |
| **seasonal robustness study** | the season's first 8 board lives | ~200 | the study inventory below | once per season and at each major release |

**Full-tier lives** are dense:
- about 2M tokens over about 200 sessions (planning value; S6 compares 2M with 5M on the same seed);
- at least 20% of sessions are long sprints exceeding the context window, so compaction still fires inside a session;
- filler chat is shortened, never tool output;
- about 5 assistant turns per scripted session, so the write-turn chain, the critical path of a life, stays short;
- the window is the pinned model's harness default, named in the v0 completion record (C-4).

The ≥ 10M-token horizon is a frontier-tier property, and this is disclosed.

**Board inventory** (DESIGN §6.10):
- **B0 and B1:** each probed at every checkpoint. B1 forks from B0 at the first flipped event.
- **One scripted fault per life:** a SIGKILL of the harness process at the first turn boundary of session ⌈0.55 × S⌉, where S is the life's session count (session 110 of 200), followed by a cold restart. It is inline on B0 and B1, at the same boundary. It is system-neutral, and it adds no extra branch and no reruns.
- **The mid-life model swap:** an event in every life.
- **Keep subset:** L_keep = max(6, ⌈L/4⌉) lives. Each has a B0 at the 10% cap, replayed in full under the cap, and a B1 forked from that capped B0. All bundles are probed there; these give the budgeted row.
- **Roster:** every real system in the frozen roster, including LCM-X at its last release before the public generator.
- **Controls:** computed once per (lives, probe pin, harness pin), cited in every table that season, and re-run on any pin change (DESIGN §8).

**Seasonal robustness study inventory**, on its 8 lives, for every board system:
- **Faults:** n_f = 3 role-relative faults per life, k = 3 reruns each, on B0 and B1, each running from the fault to the next checkpoint.
- **The Keep curve:** the 30% and 3% tiers, each a capped B0 replayed in full and a B1 forked from it, probed on Keep bundles.
  - It runs on the intersection of the study's lives with the board's Keep subset: the first L_curve = min(L_rob, L_keep) lives in seed order, so that each has its board T10. L_rob is the study's life count: 8, or 4 after the §11 cut.
  - The four-tier mean is computed on those lives, and their count is disclosed.
- **The "B throughout" swap comparator:** a B0 and a B1, probed on Wake swap bundles.
- **Family B:** a B0 and a B1 with all-bundle probes. If model B is from family B (§10), these are the same branches as the swap comparator.
- **A/A′ reruns:** a 10% subset of the ordinary family-A probe sets on B0 and B1 on the study's lives, each run once more.

**Not run:**
- faults on Keep-tier, swap or family-B branches;
- Keep tiers on swap or family-B branches.

**Harness-switch bundles** are ordinary bundles after a switch event on B0 and B1. They are reported in a sub-row for every system and need no extra branch.

**Subset selection.** Every subset is the first lives in published seed order, fixed before any run.

**Delta boards and run selection:**
- **When a delta board runs:** only for a new GA of a system already on the board. At most 2 per system per season, run in order, with the system's previous version re-run alongside on the season's lives.
- **When a fresh board is forced:** any change of harness pin or model alias.
- **Publication:** every scheduled run is published in order. The board shows each system's latest version, never its best.
- **No dual use:** sealed runs never serve as a phase of any release gauntlet.

## 7. Statistics
- **Primary test:** for a pair, a two-sided sign-flip permutation test on the per-life contributions c_l (§2), at α = .05. It is exact when L ≤ 20, and otherwise uses 100,000 draws with a fixed seed. CIs come from a wild cluster bootstrap over lives (Rademacher weights, 10,000 resamples, fixed seed). McNemar is descriptive only.
- **Confirmatory family on the board:**
  - **Membership:** each real system in the frozen roster against one pre-named neutral reference, **Hermes native memory**, on family A only. With the minimum Phase 1 roster (LCM-X, Hermes native and 3 external systems), m = 4. LCM-X at its last release before the public generator is not in the family.
  - **Correction:** Holm within the family. There is no fixed testing sequence and no sequential stopping. L is fixed by the rule below before any full-tier run.
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
  - L = clamp(⌈((z_{1−α/(2m)} + z_{0.8}) × σ_d / 8)²⌉, 24, 48), with α = .05 and m frozen in v1. This sizes the first, Bonferroni-strict Holm step. It is a resource rule built on a normal approximation.
  - The achieved Holm-adjusted MDE is always simulated and disclosed.
- **Family B, the replication estimand.** H^rep is the equal-weighted mean of the included tracks on the robustness study's 8 lives, with Keep scored at its 100% tier only, because family B has no capped branches.
  - **The two rows:** H^rep is computed for both families on those same 8 lives, tracks and tier. Each confirmatory pair's family-B difference on H^rep is compared with its family-A difference on H^rep: the matched comparator.
  - **The flag:** a pair is flagged **family-dependent** when its family-B CI (wild cluster bootstrap over the 8 lives) excludes 0 with the opposite sign to the matched family-A difference.
  - **Disclosure:** H^rep does not replicate Keep's board score (§3).
  - **Never pooled** into H_s.
- **Reported for every run of the measurement ladder:** the MDE simulated on the estimand and the life-level ICC. A/A′ variance comes from the seasonal robustness study, and the developer tiers report their own A/A′ band.
- **Every pair tested is reported,** not only the significant ones.

**Failure classes:**

| Class | Treatment |
|---|---|
| FAIL_TASK | 0 |
| SYSTEM_FAILURE: the system crashed, timed out or refused | 0 |
| INFRA_FAILURE: director, runner or sandbox failure, or a failed precondition | at most 2 reruns, then excluded for every system in the comparison |
| N/A_EXPOSURE: the decisive span was never exposed in that harness | excluded for that system; cross-harness pairs use the common-exposure set |
| N/A_CLOCK: a row failed the skew audit, or is wall-compressed | excluded from time-dependent bundles for that system; pairs use the common set |

- **Denominators** are the assigned bundles.
- **The card reports** completion per system, and a worst-case row in which every system and infrastructure failure scores −1.
- **A headline rank** needs at least 95% coverage and no more than 5% infrastructure exclusion.
- **Inline faults are classified mechanically.** A failure inside a scripted fault's recovery window is SYSTEM_FAILURE unless the ledger records a director, runner or sandbox fault, in which case it is INFRA_FAILURE. Real 429s and quota pauses are absorbed by the director, and they are never faults.

## 8. Pilot acceptance bars (all required)
1. **Smoke separation**, addendum bar 1, on the bar-1 run (§6), the smoke tier's separation run of record.
   - **Sample:** in the bar-1 run **every** bundle is in the unfiltered sample, so filters 2 and 4 never apply there.
   - **The per-life statistic:** the equal-weighted mean, over the five candidate tracks, of each track's mean bundle score on that life, with Keep at its 100% tier. A track with no bundle valid for both systems on a life is dropped from that life's mean for both. The companion uses the same statistic.
   - **Test:** LCM-X vs the no-memory floor, life-level sign-flip on that statistic, p < .05.
   - **Companion,** required for validity: on the same lives and sample, oracle evidence vs no-memory and naive RAG vs no-memory, each p < .05.
2. **Dev separation**, addendum bar 2, on the bar-2 run (§6), the dev tier's separation run of record, over 16 lives:
   - **A pair excluding LCM-X separates:** at least one pair in the bar-2 family (§7) separates on the headline, with Holm over that family only (m = 3 with the minimum pilot roster), and with the same sign in at least 80% of lives.
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
5. **Cost.** The S6a and S6 measurements, put through the §11 formulas, fit every §11 ceiling of the measurement ladder. This is evaluated once at the end of S6, using L = 48 for the board because the life count is not yet known, and re-checked with the computed L. The developer-tier targets (§6) are not bars; any that are missed are disclosed in the pilot report.
6. **Correlation.** API mode vs system is measured per comparable cell, with no bar. API mode becomes a proxy only if pairwise deltas agree in sign across at least 4 real systems.

**Feasibility pilot.** Without a human grader pool, the pilot is labelled a feasibility pilot and cannot claim the binding gate.

**Outcomes when bars fail:**
- **The companion or bar 2 fails:** this is the **failed-pilot fallback**.
  - Narrow to the tracks where oracle evidence separates from no-memory and at least one pair excluding both LCM-X releases separates.
  - Record the result as PREREG-v0-narrowed, computed without LCM-X.
  - Run a fresh, frozen acceptance of bars 1-5 on new public seeds that played no part in the selection.
- **Only bar 1's main test fails** (the companion passes): the instrument is valid and LCM-X did not separate from no-memory.
  - This is reported on #1964 as a finding and escalated to the owner.
  - It never triggers a redesign keyed to LCM-X's data.
- **Bar 3, 4 or 5 fails:** the fixes are the §2 redesign path, the §4 remedy, and the §11 cut order, followed by a fresh acceptance run of the affected bars on new public seeds.

## 9. Difficulty calibration
- **Fixed in v0:** direction caps at 40%. The lever-mix shape is fixed in the v0 completion record (C-7).
- **Set by the pilot [pilot]:** one difficulty scalar per track, so that oracle evidence scores ≥ 75 and the best of naive RAG, BM25, grep and recent window scores ≤ 35. The scalars are set from controls on the calibration set, and validated on controls over the bar-2 lives.
- **Never in calibration:** any real system's score, both LCM-X releases included.
- **Launch target:** best system below about 60 on the full tier. Measured, not tuned toward.

## 10. Systems, configuration, write turns and disclosure
- **Pilot roster:**
  - LCM-X (its plug-in release artifact);
  - LCM-X at its last release before the public generator;
  - Hermes native memory;
  - at least 2 external self-hosted systems.
- **Selecting external competitors.** Open-source and self-hostable, with a Hermes memory-provider plug-in or a documented ingest and query API. Ranked by a public adoption metric fixed on the v0 completion date (C-9).
- **Configuration budget.** An equal, logged budget for every system, LCM-X included: 5 configuration trials on public developer seed packs. Vendor-submitted configurations are accepted where the owner opens a window.
- **Route table.** Per system and segment: probe model, summariser (the vendor's documented default) and alias.
- **Agent families.** Family A for every tier. Family B in the seasonal robustness study. LCM-X's thresholds were tuned on family A, and that is disclosed. An LCM-X version that the season's family-B study did not cover is labelled "family A only".
- **Model B for the swap** is named in the v0 completion record (C-2), after spike S4. If it is from family B, the swap comparator and the family-B branches share lives (§6). A paid lane for model B counts inside the board's paid ceiling.
- **Global parameters.** These act on every template at once, so they sit outside the 40% direction cap. Each is frozen in v0 with a neutral rationale and disclosed:
  - **The window per tier** (C-4, C-5). The full tier uses the harness default, so no architecture gets an artificial window. The developer and bar-1 window comes from the harness overhead S6a measures.
  - **Tokens per life:** about 2M (§6). This is the cost floor at which long sprints still force compaction inside a session.
  - **Assistant turns per scripted session:** about 5 (§6). Write turns run sequentially, so this sets each life's critical path, and fewer, longer turns keep the 24-hour rule reachable without changing tokens or sessions.
  - **The Keep weights,** ¼ and ¾ (§3). They equal the four-tier mean at both extremes.
  - **Fault placement** (§6). It is one boundary for every system, between checkpoints 60 and 120, so that fault-crossing bundles exist.
- **Bundles per board life.** v0 freezes the range and the selection rule; only the computed count enters v1 [pilot].
  - **The rule:** b is the smallest value in {100, 150, 200, 250, 300} at which the within-life (sampling) share of the per-life variance of c_l is at most one third.
  - **The estimate:** that share comes from the bar-2 run's pairs in the bar-2 family, extrapolated as variance ∝ 1/b.
  - **If no value qualifies,** b = 300.
  - **Inputs** never include either LCM-X release.
- **Write turns,** all frozen in v0. The schedule and the file-tool rule are fixed here; the prompt text and the tool lists are fixed in the completion record (C-6):
  - **Prompt:** the exact text.
  - **Schedule:** every scripted assistant turn, for every system that declares at least one write tool. A system whose declared write-tool list is empty gets no write turns. This is decided from the tool list recorded in the ledger. S7 checks on one public life whether removing the per-turn pause changes an asynchronous passive system's state.
  - **Declared write tools:** each system's list, taken from its vendor's documentation.
  - **File tools:** a general file-editing tool is a write tool only for that system's declared memory or instruction files. The director rejects and logs edits outside those paths; they are never executed.
  - **No tuning:** none of these is ever chosen or revised using any real system's results.
- **Never run against the live reference agent.** Any later test of it is an offline replay of a copy, with owner approval at that time.
- **The card discloses:**
  - this document's version and hash;
  - system, harness and model pins, the route table and the write-turn package;
  - the clock method per harness and the skew-audit result;
  - any guard overrides;
  - filter drop logs and battery scores;
  - judge pins and the rankings under both judges;
  - coverage and the worst-case row;
  - spend and runtime by role;
  - write mode per system.

## 11. Cost formulas and ceilings (per system)
The terms are defined in DESIGN §13: R, R_cap, f, P, r_c, p_c, P_K, P_W, R_B and P_B, measured per family and by role. Subscripts 10 and 20 mean a life of that many sessions.

**The board, per system:**

  Cost_board = L × [ R(1 + f) + 2P ] + L_keep × [ R_cap(1 + f) + 2P ]

- R includes the inline fault and its recovery, and the swap. P includes the resume-only controls.
- R_cap = max(measured R_cap, R). L_keep = max(6, ⌈L/4⌉).

**The seasonal robustness study, per system,** with L_rob = 8 (4 after the cut below) and k = 3:

  Cost_rob = L_rob × [ Σ_{c=1..3} 2k(r_c + p_c) + R_B(1 + f) + 2P_B + δ_W(R(1 + f) + 2P_W) + 0.2P ] + L_curve × 2(R_cap(1 + f) + 2P_K)

- δ_W = 0 when model B is from family B, and 1 otherwise.
- L_curve = min(L_rob, L_keep), so the cut to 4 study lives also cuts the Keep curve.

**Runs of record:**
- **Bar-1 run:** Cost_bar1 = 12 × [ R_10(1 + f) + 2P_10 ] for LCM-X, plus the probe cost of the four control arms.
- **Bar-2 run, per real system:** Cost_bar2 = 16 × [ R_20(1 + f) + 2P_20 ] + 4 × [ R_cap,20(1 + f) + 2P_20 ].
- **Calibration set:** probe-only control cost over 4 full-length lives.

**The 24-hour rule** *(hard)*. The hardest run is the full core board for one system. It must finish within **24 h of wall-clock time**, and so must the seasonal robustness study for one system.
- **The board** is a set of per-system runs. They execute in parallel or on consecutive days.
- **A run that cannot meet the rule** at the permitted concurrency applies the cut order below.
- **If it still cannot,** the owner decides between paid model capacity and a narrower design. The rule is never waived silently.

**Permitted concurrency** (completion slot C-11):
- **The value** is the sustained concurrency of the agent's model lane, as measured in S6a. Wall-time projections use it.
- **Throttling** follows the gauntlet's busy marker:
  - exit 10 means light work only (nice 19, at most 2 cores, no local-embedding ingest);
  - exit 11 means no CPU-heavy work;
  - GLM-plan use pauses while the marker's `glm` field is true.

**Ceilings:**

| Run | Wall time | Paid-lane spend | Tokens over subscription lanes |
|---|---|---|---|
| full core board, per system | **≤ 24 h** | ≤ $300, unless the owner raises it | ≤ 3B input (cached counted), ≤ 100M output |
| seasonal robustness study, per system | **≤ 24 h** | ≤ $300 | ≤ 3B input, ≤ 100M output |
| bar-1 run, all arms | ≤ 8 h | ≤ $10 | ≤ 300M input |
| bar-2 run, per real system | ≤ 8 h | ≤ $25 | ≤ 300M input |
| calibration set, all controls | ≤ 24 h | ≤ $25 | ≤ 500M input |

**Instantiation.** The board and the study use L = 48 at the end of S6, and the computed L afterwards. The runs of record use S6a's and S6's measured cumulative costs through sessions 10 and 20.

**Cuts if a projection does not fit,** applied in order:
1. bundles per board life down to 100, with the achieved MDE disclosed;
2. the robustness study from 8 lives to 4;
3. lives down to 24, with the achieved MDE disclosed.

If it still does not fit, the design returns to the owner.
