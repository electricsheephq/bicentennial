# Adversarial review of the validity round 2 declaration, 2026-11-14

Reviewer: `gpt-6-astra` at high effort, a model family other than the author's (`claude-opus-5-5`), run read-only; in the third pass it could also run one unit test in a scratch folder. This is the interim scrutiny PREREG-v0.5 keeps until the Scoring Veto Panel is filled; it is not the panel. The first pass reviewed the whole declaration against the plan, the cards, round 1's declaration, the reading scripts and the run script; the second and third passes reviewed the fixes. A fresh-context Claude reviewer (`claude-opus-5-5`, high) reviewed the same text in two passes alongside it, and a second Claude agent checked its one blocking finding against the code. The run script is the maintainers' own operator script; a copy with local paths removed is published with the results.

How each finding was used:
- **First pass, seven findings.**
  1. **The send-cap path (blocking):** the declaration now states what the code does. A refused arm keeps no scores, so the reading script reads it as missing, and it is rerun once. If it is missing again, every template reads unresolved, as round 1's checks 5 and 6 say. The Claude reviewer found the same thing, and the second Claude agent confirmed it.
  2. **The pooled reading after an extension has no code (blocking):** accepted as a disclosed departure (§6), with its reason. Round 1 had the same arrangement. The rule is written out for all thirteen arms and leaves no choice open (the second pass agreed). It is unlikely to be needed. Its code is written to that rule, reviewed by another model family and merged before an extension's seeds are drawn; until then an unstable template is not a ranking candidate. A later Claude note added that, at that commit, the single-pack scripts stay the run commit's.
  3. **Check 8 (blocking):** fixed. The check reads nonzero summariser tokens, compaction is described as moving a score either way, and check 8 is listed as an addition.
  4. **A rerun without a qualifying failure (blocking):** fixed in the run script and stated in §3. A rerun needs the latest reading to name the arm as pending or invalid.
  5. **Wake's earlier exposure:** fixed in §1, §7 and §8.
  6. **The rehearsal is not live:** stated in §3 and listed as a departure; the cap is projected from measured counts.
  7. **The 78% figure:** reworded as a placement probability. The Claude reviewer then showed that the expected recent-window score on `drift-config` is 25 under the generator's placement, not the screening set's 35, and §7 now says so.
- **Second pass, one finding (blocking):** a rerun's recorded reason could go stale after another arm's rerun moved the reference identity. Fixed: the qualifying reading must be newer than every attempt so far, and the declaration says a new reading is made after each rerun. The guard's unit test covers that case, and a mutant of the old check fails it.
- **Third pass:** no new findings (SOUND). It ran the guard's unit test itself (14 passed) and noted a proof limit: it reviewed the scripts before the seed tool's round 2 was on `main`, and the pooled step is not yet written. Both are prerequisites the run script and §6 already state.
- **The Claude reviewer's other notes,** all applied: `unreadable_state` items count as scored (§4); §8 lists the cards, edition 1's anchor report and the screen's positive controls; §9 carries PLAN §9's claim language and `drift-config`'s placement dependence; the 90 probe turns are structural (nine items on every G1 life); and the extension's task list and scripts are fixed (§6).

## First pass, on the declaration

Read-only review completed. No tests, network access, credentials, home-directory dot-folders, or excluded run data were used. References to `DECLARATION.md` mean the supplied draft; `tasks.py` and `table.py` mean `results/validity-2/control-trials/`; `run-v2.sh` means the supplied operator script.

1. **MERGE_BLOCKING · Important — A cap stop does not take the declared check-7 path.**\
   **Declaration:** §3, `DECLARATION.md:35`. **Plan:** §10, `PLAN.md:203–206`.\
   **Claim:** a stopped unit fails check 7; a second stop ends the round before scores open.\
   **Evidence:** `src/bicentennial/runner/t2.py:345–373` removes scored output on `spend_stop`, leaving refusal evidence without `card.json` or `outcomes.json`. `table.py:258–260` therefore classifies that arm as **missing**, bypassing check 7. With `--after-reruns`, `table.py:302–310` can open scores and the oracle filter despite that missing arm.\
   **Scenario:** G1 and G1.rerun both exhaust their send budgets. The table publishes unresolved readings but also opens the other arms’ scores, instead of taking the declared round-ending path. Separately, exactly 1,000 completed sends need not stop an arm: the refusal occurs when another send is requested (`src/bicentennial/director/upstream/__init__.py:163–188`).\
   **Smallest fix:** “An arm that needs a send beyond the cap is refused with `spend_stop`. That refusal counts as a check-7 failure even when no card or outcomes remain. A second failure ends the round before any score is opened.” Make the reader implement that existing stop rule.

2. **MERGE_BLOCKING · Important — The promised pooled extension has no implementation in the supplied reader.**\
   **Declaration:** §6, `DECLARATION.md:57`, together with §3’s frozen run commit at line 25. **Plan:** §6 and §10, `PLAN.md:135–138,204`; inherited pooling rule: `results/validity-1/DECLARATION.md:64`.\
   **Claim:** an unstable template gets one extension pack and a pooled reading.\
   **Evidence:** `table.py:205–218` accepts one pack and one task list; `tasks.py:73–79` requires exactly ten lives. `table.py:526–577` computes only that pack’s reading. There is no two-pack pooling path, extension identity comparison, or final “unstable counts as low” step. The inherited rule also names only F, R and O, leaving B, G and W’s pooling implicit.\
   **Scenario:** O1 scores 70, O2 80 and O3 80. The first pack reads unstable. Running the supplied table separately on an extension cannot produce the promised pooled decision; adding its reading machinery afterward conflicts with freezing the reader before the draw.\
   **Smallest fix:** “For an extension, pool each of the thirteen arm labels across the two packs; compute §5 on those pooled repeats, with unstable finally counting as low. Keep each pack’s own oracle filter. The extension reader is frozen at the run commit.” Supply that path before the draw.

3. **MERGE_BLOCKING · Important — Check 8’s stated predicate differs from its code; its directional rationale is false.**\
   **Declaration:** §4, `DECLARATION.md:40`. **Plan:** §6’s inherited checks, `PLAN.md:133–134`; departures, §11.\
   **Claim:** any `summariser` row triggers the rerun, and compaction can only understate an anchor or oracle.\
   **Evidence:** `table.py:98–101` requires **nonzero input or output tokens**, not merely a row. A pure-function check returned `False` for a zero/zero summariser row and `True` for a nonzero row. Receipt construction preserves supplied role rows (`src/bicentennial/report/receipt.py:80`); token extraction defaults absent usage to zero (`src/bicentennial/runner/life.py:242–254`).\
   **Scenario:** a zero-token row would exclude an arm under the declaration’s words but passes the code. Compaction can also remove misleading context: dropping a quoted competing value can turn a −1 answer into abstention at 0, **raising** an anchor’s score. Removing distractions can likewise improve an answer.\
   **Smallest fix:** “Compaction can change a row’s score in either direction. Check 8 rejects an arm whose receipt records nonzero summariser input or output tokens, across any unit attempt; a zero-token row alone does not trigger it.” List check 8 as an added procedural extension. Its whole-arm exclusion and oracle-filter treatment otherwise match the code.

4. **MERGE_BLOCKING · Important — The operator permits rerunning an arm without a qualifying failure.**\
   **Declaration:** §4, `DECLARATION.md:38–40`, incorporating round 1’s checks and single-rerun rule. **Plan:** §6, `PLAN.md:133–134`.\
   **Claim:** whole-arm reruns follow the specified failed checks.\
   **Evidence:** `run-v2.sh:280–289` checks that an initial attempt exists, no rerun exists, and scores have not opened or the round ended. It does **not** require a failed check.\
   **Scenario:** an otherwise valid F1 is rerun before the table opens scores. The operator automatically substitutes F1.rerun (`run-v2.sh:347–349`), and the table accepts its declared rerun position. That is an extra sampling opportunity outside the stated rule.\
   **Smallest fix:** “An arm is rerun only for a recorded failure requiring its rerun under §4; a passing arm is never rerun.” Require that reason in the operator before accepting the rerun.

5. **NON_BLOCKING · Pre-existing — Wake’s prior exposure is misstated.**\
   **Declaration:** §1, `DECLARATION.md:13`; predictions and disclosure, lines 69 and 78. **Plan:** §6, `PLAN.md:123–132`, contains the same stale statement.\
   **Claim:** Wake “never met the new anchors.”\
   **Evidence:** `cards/README.md:25–27` discloses public-life anchor results for Wake; lines 135–144 disclose its screening-set report, with all four anchors at 0/0/20.\
   **Scenario:** a reader treats Wake’s zero-anchor prediction as made without prior anchor observations, although those observations were available.\
   **Smallest fix:** “Wake’s four scripted anchors scored 0 on the twenty screening lives. It has not had live trials against the new anchors or oracle trials on fresh validation lives. It is read whatever the screen found and ranks only if it qualifies.” Its actual inclusion and qualification rules are consistent.

6. **NON_BLOCKING · Important — Historical projection replaces the plan’s measured rehearsal without an explicit departure.**\
   **Declaration:** §3, `DECLARATION.md:31–34`; departures, line 93. **Plan:** §10, `PLAN.md:198`.\
   **Claim:** the cap follows measured figures; the plan additionally says the G1-only cost is measured at rehearsal.\
   **Evidence:** `run-v2.sh:107–111` explicitly makes rehearsal non-live. It measures no reader sends. The declaration instead projects from round 1 and the smoke.\
   **Scenario:** a reader assumes the ten-G1 configuration’s send rate was measured, when B, G and W remain unmeasured and the rate is extrapolated. The arithmetic itself is sound:\
   `394 × 90 / 85 = 417.176`; twice that is `834.353`.\
   `394 × 90 / 45 = 788`; 1.25 times that is `985`.\
   Thus 1,000 satisfies both bounds.\
   **Smallest fix:** “Departure from PLAN §10: the rehearsal is non-live. The cap uses the measured round-1 and smoke counts projected to ninety turns, with the stated headroom; it is not a measured ten-G1 send rate.”

7. **NON_BLOCKING · Important — The 78% figure is a placement probability, not a validated probability of ranking.**\
   **Declaration:** §7, `DECLARATION.md:64,70`. **Plan:** §4, `PLAN.md:103–106`, explicitly calls scripted scores a proxy, not a bound.\
   **Claim:** config is a ranking candidate if W stays at or below 35, “about 78%”; four suitable placements stop it ranking.\
   **Evidence:** `cards/README.md:108–114` derives this from `Bin(10,¼)`. The arithmetic is correct: `P(k≥4)=0.2241249`. But `table.py:542–573` additionally requires live scores and stable flags.\
   **Scenario:** four placements yield scripted W=40, but live abstentions lower W to 30; alternatively, three placements satisfy the proxy while an oracle trial makes the reading unstable.\
   **Smallest fix:** “The scripted placement model puts W at or below 35 with probability about 78%. This is not the probability of a ranking-candidate reading; live scores and all stability checks still decide.”

**Probe 1:** Not fully matched. Targets, frozen-list validation, scale, row means, precedence, flag combinations and oracle filter match (`tasks.py:49–104`; `table.py:486–500,526–643`). Findings 1–4 identify the substantive execution mismatches. Payload and live-unit checks cover the whole pack; score readings use the targets.

**Probe 2:** The numerical reading and smoke gates agree with PLAN §§1, 5 and 6. Existing listed departures are substantively explained by the plan/cards; candidate-edition immutability and enlarged G/W windows are reasonable. Check 8 and the non-live rehearsal need explicit departure accounting; the extension remains unimplemented.

**Probe 3:** No numerical gate retuning was found: 75, 35 and 0.7 are inherited. Writing predictions after the screen and smoke is expressly allowed by PLAN §5. Their provenance is mostly candid; Wake’s disclosure and the placement probability need findings 5 and 7. Publication chronology was not independently verified.

**Probe 4:** The published round-1 send counts and smoke summary support the stated inputs; 1,000 meets both headroom calculations. B/G/W remain extrapolations. Cap-stop handling does not match the declaration: finding 1.

**Probe 5:** Dropping is explicitly smoke-only and before the draw (`DECLARATION.md:15`; `tasks.py:20–21`); the committed target list and frozen task hash prevent an ordinary later drop. Wake always runs and ranks only if qualified. Its prior-exposure description needs correction.

**Probe 6:** The one-direction compaction argument is false. The code correctly distinguishes zero-token from nonzero-token rows, while the prose does not. All-attempt aggregation is explicitly declared, so compaction in a discarded unit attempt intentionally excludes the arm.

**Probe 7:** §9 covers one reader/effort, ten pairs per template, control-only evidence, lexical/positional anchors, dense retrieval untested, incomplete-sweep interpretation and scripted lives. The exploratory developer-tier claim class is appropriate; “ranking candidate” remains a pack-and-reader-specific routing label under PLAN §9.

**Probe 8:** The main threats are undeclared rerun opportunities, the cap-stop mismatch and the missing frozen extension path. No broader controls are needed for this review; reconcile those paths before the draw. Raw run evidence and the declaration’s historical timing claims were outside this review’s proof boundary.

SOUND-WITH-FIXES

## Second pass, on the fixes

Read-only delta review completed. No tests, network, credentials, dot-foldolders or excluded run data were accessed. The supplied test receipts were inspected; `/bin/bash` 3.2.57 syntax checking passed.

1. **MERGE_BLOCKING · Important — Another arm’s rerun can invalidate the guard’s recorded reason.**\
   **Where:** `run-v2.sh:72–78,298`; `table.py:167–173,378`; declaration §3, “Reruns.”\
   **Claim:** a passing arm is never rerun.\
   **Evidence:** `rerun_named` requires the latest table output to postdate only the requested arm’s original attempt. It remains usable after another arm reruns. However, the table recomputes the reference identity from the current attempts; the operator itself acknowledges this at `run-v2.sh:375–376`.\
   **Scenario:** seven arms have identity A and six have B. F1 is an A arm that compacted; R1 is an otherwise valid B arm. The table names F1 and all six B arms pending. F1 reruns without compaction and receives B, making B the majority, seven to six. R1 now satisfies the identity check, but the unchanged table log still names it pending and postdates its original attempt. `rerun R1` therefore succeeds without a currently qualifying failure, giving it an unnecessary extra sample. The supplied tests exercise label matching and per-arm freshness, not freshness after another arm changes the reference.\
   **Smallest fix:** require the qualifying table output to cover the **current complete set of attempts**, including other arms’ reruns. After any new attempt, require a fresh checks-only reading before another rerun; accept both pending and invalid labels from that reading. Preserve the existing one-rerun limit.

**Probe 1:** Round-1 finding 1 is accepted by the owner’s stated completeness interpretation and now matches the missing-arm path; finding 2 is accepted as an explicitly disclosed delayed-implementation departure, with the supplied precedent and fixed-rule rationale; findings 3, 5, 6 and 7 are resolved. Finding 4 is partially resolved but remains open through the stale-authorization scenario above. The Claude reviewer’s listed textual corrections are present, including scored `unreadable_state`, expected W=25, exposure disclosures, check-8 departure and bounded claim language.

**Probe 2:** No discretionary statistical choice remains apparent in §6: extension size and count, eligible templates, thirteen-label pooling, identity/pin requirements, flags, precedence, unresolved treatment and per-pack filters are specified. The later implementation is not yet proven, but its timing is candidly disclosed and independent review is required before the extension draw.

**Probe 3:** Yes, a currently passing arm can still rerun through finding 1. Otherwise, the guard recognizes pre-check logs, missing-output arms with recorded attempts, and multiple pending labels; one rerun does not itself erase another label’s authorization. A never-attempted arm correctly uses `run`, not `rerun`. The syntax is compatible with bash 3.2; the supplied receipts report 11 passing cases and one failure for each named mutant, without proving the cross-arm freshness condition.

**Probe 4:** The stale rerun authorization is the remaining mismatch with the declaration’s passing-arm prohibition and `table.py`’s changing reference identity. No additional substantive mismatch was found in the changed passages against `tasks.py`, `table.py` or PLAN; the delayed pooling code, added compaction check and projected cap are disclosed departures.

SOUND-WITH-FIXES

## Third pass, on the second pass's fix

No new findings in the fix delta.

P1: **Resolved.** `rerun_named` checks the newest table or pre-check output against every attempt, including other arms’ reruns; the caller passes `"$S/runs"`. This closes the round-2 stale-reference scenario. Exact-label matching excludes passing arms; a fresh reading restores authorization for an arm still pending. Timestamp equality causes a retryable refusal, not permanent exclusion. The permitted `/bin/bash` test returned `rerun_named: 14 passed, 0 failed`; the supplied old-guard mutant fails case 4a.

P2: **The sentences close their intended specification gaps.** The rerun sentence matches the guard; T2’s selection and edition-3 templates support four twin pairs plus one recall item per G1 life, with placement failures replaced within the declared limits. `tasks.py` requires all four target templates, and §6 now separates that complete task list from unstable-only pooled reading while freezing unrelated script changes. **Pre-existing proof limit:** the supplied worktree at `4caf0feb` still lacks roster `--round 2` support; `prep` rejects that state. The merged round-2 roster and future pooling implementation remain prerequisites, not proven implementations.

P3: **No additional delta defect found that would void the round or enlarge its claims.** The other script change is commentary above the unchanged `CAP=1000`. This verdict covers the inspected delta and guard unit test; it does not establish rehearsal, live-run, send-cap sufficiency, or pooled-extension execution.

SOUND
