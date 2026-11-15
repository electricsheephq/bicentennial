# Adversarial review of the fresh-seed follow-up's declaration, 14 November 2026

Reviewer: `gpt-6-astra` at high effort, a model family other than the author's (`claude-opus-5-5`), run read-only on the draft with the repository, round 2's results and Milestone 1's run records. This is the interim scrutiny PREREG-v0.5 keeps until the Scoring Veto Panel is filled; it is not the panel. A fresh-context Claude reviewer (`claude-opus-5-5` at high effort) reviewed each version too. The text under each pass is Astra's own, unedited; the Claude reviewer's findings are summarised in the dispositions. Line numbers in the passes refer to the draft each pass read.

How each finding was used:
- **First pass (both reviewers SOUND-WITH-FIXES):**
  - **Contrast inputs and missing data (Astra 1; Claude 3 and 4):** fixed. O's life score uses O1 and O2. A missing, mismatched or incomplete repeat, or a pair unscored after its rerun, makes the reading or comparison that needs it unresolved; nothing is dropped. Each comparison reads, in order, unresolved, inconclusive, holds or does not hold, and a contrast takes "does not hold" first. The Claude reviewer's other option, leaving a life out and printing the count, was not taken, because a contrast could then rest on fewer lives than declared.
  - **The whole-pack fallback (Astra 2; Claude 11):** removed. It allowed ten lives, below PLAN §1's twelve; §9 records that no pack, life or pair is dropped to rescue a reading.
  - **R's stability combinations (Astra 3; Claude 9):** fixed: twelve for R, six for B, G and W and for the floor, three for the low flag.
  - **The send bound (Astra 4; Claude 1 and 2):** fixed. The runner spends a system run's bound twice, so every arm runs with 1,000 and an H arm makes at most 2,000, within PLAN §7's cap. The rule cites figures from packs of T2's shape only.
  - **H's check 7 and floor cache (Astra 5; Claude 10):** fixed: check 7 is defined for a system arm, with its own rerun rule, and the floor cache follows Milestone 1's §11.16.
  - **The trigger (Astra 6; Claude 5):** fixed: each kind gets round 2's reading on the pooled repeats, and if Room does not hold, or reads inconclusive or unresolved, all four kinds leave the ranking set.
  - **Smaller points:** Milestone 1's send range and the anchor check's figures (Astra 7; Claude 8); the life names and the replacement limit per life (Claude 6 and 7); a §9 row for the absent do-no-harm kinds (Claude 11); the rehearsal's seeds (Claude 12); H's identity hashes, checked on every H arm (Claude 13); O as c and a prediction for the readings (Claude 14); a fix that would change the run commit ends the run (Claude 15). All fixed.
  - **Found by the author:** "every other kind is printed" contradicted `recall-count-v1` carried unread. It is now never printed, and each card is published cut to the items read. Reruns run after all 36 arms.
- **Second pass (both SOUND-WITH-FIXES):** a kind's reading and Room no longer depend on H's arms (both reviewers); H's live-reader exception is per item, not per unit (Astra 2); a control arm's rerun failing any of checks 1, 2, 3 or 7 ends the run, with one rerun per arm whatever check it failed (Astra 3); and six wording and build points (Astra 4; the Claude reviewer's other five). All fixed.
- **Third pass:** Astra SOUND, no finding. The Claude reviewer SOUND, with one nit: H's arms counted toward the reference identity. That was fixed: the reference is taken over the 30 control arms and every arm must match it.
- **Fourth pass, on that change:** both SOUND. The Claude reviewer's optional wording ("a control arm's rerun") was applied after it; so was the date, now given in UTC.

## First pass, on the draft

- **Important — MERGE_BLOCKING — §5, lines 43–49: contrast inputs and missing-data outcomes are incomplete.** Check 6 makes template readings unresolved, but the new contrasts have no corresponding rule for a missing repeat or unscored pair. “Mean over its repeats” also needs to explicitly preserve O1/O2, excluding O3. **Fix:** specify required repeats and exact per-life arithmetic; retain four-kind support; make an affected contrast unresolved/inconclusive after exhausted reruns rather than silently dropping repeats, pairs or lives. Define comparison precedence explicitly: unavailable → unresolved; fewer than six nonzero differences → inconclusive; otherwise positive mean and p < .05 → holds; otherwise fails.

- **Important — MERGE_BLOCKING — §4, line 37; §9, lines 81–87: dropping a whole mismatched pack silently changes the planned reading.** The exclusion itself is deterministic, but permits a held contrast on ten lives, below PLAN §1’s “at least 12” and §7’s fifteen. It also conflicts with the inherited rule that missing required repeats make readings unresolved. **Fix:** explicitly declare this departure and its precedence over check 6, including reduced denominators and support counts; alternatively publish reduced-pack scores descriptively and leave the planned contrasts unresolved.

- **Important — MERGE_BLOCKING — §5, lines 43–44; §9, line 85: R’s repeats are miscounted.** R is one of the four contrast anchors and has two arms per pack. Its near-solved stability therefore has **2 × 2 × 3 = 12** combinations, not six. B/G/W have six each; the floor flag has six; low has three oracle trials. **Fix:** name these counts separately and replace “Each anchor has one repeat” with “B, G and W each have one repeat.”

- **Important — MERGE_BLOCKING — §3, line 29; §9: the send-budget statement does not match the runner.** `t2.py:239–247` resets `max_sends` between floor and system; `docs/developers/t2.md:38` explicitly allows **2 × N** sends per H invocation. Passing 2,000 permits 4,000 total, not the stated 2,000. Also, 1,000 is less than twice 546. **Fix:** freeze the actual CLI value and separate floor/system/total limits, correct the headroom claim, and flag departure from PLAN §7’s 1,000-send wording. A shared 2,000-send total needs additional enforcement.

- **Important — MERGE_BLOCKING — §4, lines 36–39: H’s check 7 needs a system-specific definition and failure disposition.** The inherited control check requires every probe live and no stopped unit (`table.py:458–470`), whereas `hermes_score.py:74–75` scores `SYSTEM_FAILURE` without requiring a reader result. Applying that control predicate to H can reject legitimate scored failures; line 39 only specifies control-arm repairs. **Fix:** require uncached execution/provenance for H while accepting documented scored system failures, and state the bounded rerun/terminal rule for an actual H provenance failure.

- **Important — MERGE_BLOCKING — §6, line 57: “each such kind” is undefined when only the pooled Room contrast fails.** A positive difference can fail significance without any individual kind being low, near-solved or nonpositive. The text does not determine which kinds leave the ranking set. **Fix:** explicitly choose all four, or a fixed per-kind predicate; also state what inconclusive/unresolved Room permits.

- **Nit — NON_BLOCKING — §3, line 28: Milestone 1’s control-send range omits O3.** The supplied run disclosures show O3 = 358, so the nine-core-arm control range is **358–413**, not 361–413. **Fix:** correct the minimum or explicitly restrict the range to the first eight arms. H1 = 858 and H2 = 486 are verified.

Probe 1 — Pack order, anchor rotation and void-draw conditions are fixed; missing-data handling, pack exclusion precedence and cap semantics need the fixes above. Rerun authorization inherits round 2’s bounded rule.

Probe 2 — The main design conforms to §7: thirty lives, three T2-shaped packs, four frozen kinds and twelve arms per pack. Reduced-pack inference and revised H budgets need explicit departure entries.

Probe 3 — The exact two-sided test and six-*nonzero*-life rationale are correct: five cannot beat .0625; zero differences add no information. The contrast decision table and score-support rules remain incomplete.

Probe 4 — Edition 3, admissions and five-G1/five-G2 system composition agree with source. The replacement rule allows eight replacements for the sole failing design life per pack; a second failing design life voids it. H floor/cache counts are verified; budget facts need correction.

Probe 5 — H is adequately frozen for this exploratory declaration by the run commit, registry-entry digest, install pins, reader and committed run script, provided these are fixed before drawing and enforced on every attempt.

Probe 6 — All 28 kind/row predictions, both contrasts and four operational predictions have measurable outputs. Final checkability depends on fixing repeat arithmetic, missing-data outcomes and cap semantics.

Probe 7 — The build must supply three-pack drawing/placement, five-G1 task lists, a pooled H-aware reader and the enforcing run script before the draw. Current `validity_roster.py` supports only 10+16 draws; `tasks.py` requires ten G1 lives; `table.py` is control-only. Also, `t2_dry_run` eagerly consumes its supplied pool: merely passing one iterator to three calls will exhaust it on A. These are declared implementation prerequisites, not reasons to expand the research scope.

Verdict: **SOUND-WITH-FIXES**.

## Second pass, on the revision

- **Important — MERGE_BLOCKING — §5, lines 63–65, versus §4 line 54 and §6 lines 94–96:** the missing-data rule makes a kind unresolved when **any row**, including H, loses a target pair or repeat. That conflicts with the control-only per-kind readings and could remove a kind because H failed. **Smallest fix:** specify dependencies: per-kind readings and flags require controls only; comparisons require their participating rows and declared repeats. Explicitly keep O3 out of Room’s required repeats.

- **Important — MERGE_BLOCKING — §4, line 51:** the live-reader exception refers to a **unit’s** scored system failure, but scoring is per item. `runner/units.py:301–334` assigns individual outcomes; `runner/life.py:731–738` can preserve earlier results while classifying later items after a stop. A mixed unit therefore has no single scored outcome that safely exempts every probe. **Smallest fix:** require each probe to be live unless **that item’s final outcome** is `SYSTEM_FAILURE`; check the unit’s stop separately. The complete probe-record requirement itself matches `probe_live.py:161–198`.

- **Important — MERGE_BLOCKING — §4, line 57:** “the **same check** fails again” weakens the inherited terminal rule. Round 1 §4 line 41 ends the run if the rerun fails **any** of checks 1, 2, 3 or 7. A first-attempt check-1 failure followed by a check-7 failure now lacks an explicit terminal disposition. **Smallest fix:** replace “the same check” with “any of checks 1, 2, 3 or 7”; preserve one rerun total.

- **Nit — NON_BLOCKING — §9, lines 129 and 131:** two summary statements remain overbroad. “Each anchor has one repeat” still includes R, despite the correct twelve-combination rule. “Every Drift id in edition 3” overlooks the G2 v1 kinds, including descriptive `drift-asof-v1`. **Smallest fix:** say “B, G and W” and “the three ranking Drift kinds.” The substantive counts and no-do-no-harm decision are otherwise clear.

Probe 1 — Most findings close. A1/C3, A5/C10 and C15 need the fixes above; A3/C9 retain only summary wording. The remaining listed findings close at declaration level. Implementation prerequisites remain prerequisites, not demonstrated capabilities.

Probe 2 — The comparison/contrast decision table is complete once dependencies are fixed: comparison precedence is unresolved → inconclusive → holds → does not hold; contrast precedence is does not hold → unresolved → inconclusive → holds. Zero differences, tied sums and exactly .05 are handled correctly by the cited exact test.

Probe 3 — Verified the send semantics and corrected figures, cache rule, lock-hash construction, scored-kind selection, life mapping/replacement limit and rehearsal sequence rule. The placement-model probability is approximately 14.84%. H’s item-versus-unit exception needs correction. Future prerequisite changes were not verified.

Probe 4 — §9 records the relevant PLAN §7 decisions. The narrowed rerun-stop rule contradicts its cited source; the other overstatements are identified above. No tests, builds, network or mutations were performed.

Verdict: **SOUND-WITH-FIXES**.

## Third pass, on the second revision

Findings: None in the r2→r3 delta; no new verified blocker or required fix.

Probe 1 — Each listed change closes its finding. §4 makes the live-reader exception item-specific, checks early stops separately, and identifies the probe provenance field; inspected source supports floor-only caching. The terminal rule now covers any listed control-check failure on rerun, caps each arm at one rerun, and excludes H after any failed rerun. The repeat/Drift wording, rehearsal-range extension, preparation-only hash capture, committed card cutter, and explicit 35-rule departure close their respective points. No new post-draw choice was identified.

Probe 2 — §5 now states the dependencies correctly: kind readings/flags require F, R, B, G, W and all three O trials; each Room comparison requires O1/O2 and its anchor’s repeats; each Use comparison requires H1/H2 and its anchor’s repeats. O3 remains required for stability and the filter, but not Room. Missing H observations no longer directly invalidate control readings or Room.

Scope: declaration delta and targeted source inspection only. The supplied diff matches both revisions. Implementation prerequisites and runtime enforcement remain unproven; no tests, builds, network access or changes performed.

Verdict: **SOUND**.

## Fourth pass, on the reference identity

SOUND

The change closes the nit: H cannot influence the reference identity or which control arms are mismatched, but every H arm must still match that reference.

The added decision row explicitly records the control-only interpretation of round 1’s check 4. The visible §4 H rules remain consistent, and the shared one-rerun-per-arm limit is unchanged; this grants no extra retry.

No new hole or contradiction is apparent in the diff. Review limited to `decl-r3-r4.diff`, as requested.
