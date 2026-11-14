# Validity round 2 declaration: how the finalists' and Wake's control trials are read

**Status:** written 14 November 2026, after the screen ([#534](https://github.com/electricsheephq/bicentennial/issues/534)) and the live oracle smoke ([#535](https://github.com/electricsheephq/bicentennial/issues/535)), before any seed for these trials is drawn and before any trial runs. It is merged before the draw, and the results page names its commit. This is a developer-tier validity check on fresh lives that only control rows ever see: no bar, no certification, no real system, and not predictive of the full tier (PREREG-v0.5 §6). An adversarial review by a model family other than the author's is published beside it ([review](reviews/2026-11-14-adversarial-review.md)).

## 1. Why, and what is validated
Round 1 cleared the repaired Drift templates: a reader handed the evidence does them. Naive retrieval also scored them near full, so they cannot show that memory beats retrieval ([round 1 results](../validity-1/2026-11-13-control-trials/RESULT.md)). This round asks which kinds are **ranking candidates**: the oracle row well above the best of four lexical and positional anchors, on fresh control-only lives ([PLAN](PLAN.md) §1). It reads four templates:

| Template | Version and lever | What the screen measured (scripted, 20 lives) |
|---|---|---|
| `drift-config` | v3 (card K3): no entry named in the prompt, and the decision rule restated in other words (levers 1 and 4) | oracle 100; naive RAG, BM25, grep 0; recent window 35 |
| `drift-quote` | v3 (card K3): every firmly decided entry, none named (lever 1) | oracle 100; three anchors 0; recent window −35 |
| `drift-chain-fault` | v3 (card K3): every milestone, none named (lever 1) | oracle 100; all four anchors 0 |
| `wake-loop` | v1, unchanged | not in the screen; edition 1's scripted anchor report on the screening set scored each of the four anchors 0 (no pair right or wrong, 20 without credit; cards README). It has never met the anchors live or had oracle trials on fresh lives |

Each v3 changes only its prompt and the id of its decision table; instances, options, evidence, checks and scoring are v1's. A finalist the smoke drops ([PLAN](PLAN.md) §5: a confidently wrong pair, or more than one pair without credit, on the public lives) leaves the target list before the draw (`TARGET_TEMPLATES` in the reading script's `tasks.py`), but stays in edition 3: the pack carries it and the reader answers it, and nothing reads it. Its id keeps its cleared v2 (§6). **The smoke kept all three finalists** (§8), so the target list holds all four templates.

## 2. The lives
- **One validation pack of ten G1 lives** (PLAN D6), in T2's G1 shape: ten sessions, two twin branches, a kill at session 6 and a model-label swap at session 8. Only the seeds differ from the public T2 spec. Template edition 3: the finalists, `wake-loop-v1`, edition 1 elsewhere. The run gate accepts this composition for control runs only ([#539](https://github.com/electricsheephq/bicentennial/issues/539)).
- **Seeds.** As round 1 (its §2): drawn once at the run commit, after this declaration merges; ten design seeds and sixteen ordered spares from `secrets.randbits(63)`, disjoint from every committed seed; the drawn list's sha256 and the run commit posted on #536 before the build; the placement dry run with T2's replacement limit; the same void-draw rule.
- **Hidden until the results;** then the spec, the drawn list and the placement table are committed.
- **Control-only for good.** Only the control rows below ever run on this pack. Its hash joins `specs/ring0/control-only-packs.json` ([#529](https://github.com/electricsheephq/bicentennial/issues/529)) before the results publish, so a non-control run on it is refused whatever any admission says.

## 3. What runs
- **Reader:** the pinned reader model at its pinned effort, through the benchmark's own login, as in round 1.
- **One commit for everything:** a main commit holding this declaration, edition 3, the #529 guard, the seed tool's round 2 and the reading script, merged before the draw; as round 1's §3. The four code pins are printed beside round 1's.
- **Rows:** F, no memory; R, naive retrieval (top five); B, BM25; G, scripted grep; W, recent window (W = 16,384 tokens); O, oracle evidence. B, G and W are the anchors at the spec and code hashes their cards' predictions were made against ([cards README](cards/README.md#anchor-identities)). G and W run the reader with compaction at twice W, and Hermes's configured context length follows at four times that window (the T2 guide); the other rows keep round 1's settings.
- **Thirteen arms, in this order:** F, R, B, G, W, O, O, W, G, B, R, F, O. The first twelve are mirrored; the thirteenth is O's third trial. Reruns run after the arms already done, as round 1.
- **Target items:** every action item of the four templates: 80 items (40 twin pairs, ten per template, one per life). The pack's other items are not read.
- **Frozen task list:** as round 1's §3, with the 80 target items.
- **Send cap** (#507; PLAN §10: from measured figures with stated headroom): every arm runs with a cap of 1,000 sends.
  - **Measured:** round 1's seven arms used 351 to 394 sends each for 85 probe turns on 20 units (45 turns on G1 units, 40 on G2 units), 4.1 to 4.6 sends a turn. The oracle smoke used 343 sends for the same 85 turns, 4.0 a turn.
  - **This pack:** ten G1 lives carry exactly 90 probe turns. Edition 3 places nine items on every G1 life: one twin pair from each of the four target templates and one `recall-value` item on B0 (five on B0, four on B1). The placement dry run replaces any seed whose life cannot host them all. Every G1 life in round 1 and in the smoke had nine.
  - **Projected:** about 420 sends an arm at the highest measured rate (394 sends for 85 turns). At most about 790 if every send of that arm had gone to its 45 G1 turns.
  - **Rule:** the cap is at least twice the first figure and 1.25 times the second. These are projections from measured counts, not a measured rate for this pack: the rehearsal is not live, so it measures no sends (a departure). The anchor arms B, G and W have no measured figures; each hands the reader a block, as R does, and R's two arms used 358 and 354 sends.
  - **Reaching the cap:** an arm that needs a send beyond the cap is refused (`spend_stop`) and keeps no card or outcomes, so the reading script reads it as missing. Like any missing or incomplete arm (round 1's check 5), it is rerun once, whole, with the same cap. If the rerun is refused too, the arm stays missing, and every template reads unresolved, because a missing repeat is left out of each (round 1's check 6); the other arms' scores are still printed. The cap does not change once an arm has run.
- **Reruns:** an arm is rerun only when the latest run of the reading script names it as pending or invalid under §4, and that run was made after every attempt so far. Another arm's rerun can change the reference identity (check 4), so after any rerun the reading is made again before the next one. A passing arm is never rerun, and the run script refuses such a rerun. Every attempt and every run of the reading script is published.

## 4. Checks before any score is read
Round 1's checks 1 to 7 (its §4) apply to the 80 target items, with checks 1 and 2 extended to B, G and W: each block equals its scripted anchor's text, byte for byte, and presence equals the pack's scripted anchor report, task by task. One check is added:

8. **No compaction.** A control arm's reader must see its whole block. Compaction changes what the reader sees, so it can move a row's score either way: it can drop evidence, and it can drop misleading context. Either way, a compacted arm is not the row this round tests. A reader that compacts records nonzero input or output tokens for the `summariser` role in its arm's receipt (`tokens_by_role`, [T2 guide](../../docs/developers/t2.md)), from any attempt of any unit; a summariser row with zero tokens does not count. The receipt names the arm, not the unit. An arm that compacted is rerun once, whole, after the arms already done, as check 4 reruns an arm served another identity. If its rerun compacts too, it is treated as an arm still mismatched after its rerun: never pooled, its trials unscored, in the oracle filter as well. None of round 1's seven arms compacted, and neither did the smoke's.

An item labelled `unreadable_state` counts as scored, as #524 and #537 define it (PLAN §5); each arm's count is published with the results.

Checks 1 and 2 for B, G and W also require each arm's control record to name its anchor with the spec and code hashes its card's predictions were made against ([cards README](cards/README.md#anchor-identities)), and G's and W's records to carry `reader_window` 32,768 ([#547](https://github.com/electricsheephq/bicentennial/issues/547)). Check 3's tests include the anchor arms' block and presence tests.

## 5. How each template is read
- **Scale and repeats:** round 1's §5 unchanged: an action pair scores its lower twin (+1, 0, −1); a template's points are 100 times its mean over its pairs on the common support. One pair is 10 points.
- **f, r, b, g, w, c:** the means of each row's two arms; c is the mean of the first two O arms; O's third trial enters the stability check and the filter.
- **Pairs:** every target is an action pair, Wake's included, so every template scores its pairs the same way; there is no count question this round.
- **One reading per template,** the first that applies: unresolved, unstable, low, as round 1; then **ranking candidate** (PLAN §1); otherwise **cleared** (a do-no-harm check). A template is a ranking candidate when all of these hold:
  - the best of r, b, g and w is at most 35, on the means;
  - each anchor's near-solved flag (x ≥ f + 0.7 (c − f), for x = r, b, g and w) and the floor's (f ≥ 0.7 c) does not apply on the means;
  - and each flag reads the same in every combination of one repeat per row, as round 1 computes it: F × that anchor × each O trial for an anchor's flag, F × each O trial for the floor's.
  A flag that is not interpreted (c ≤ f or c ≤ 0, Milestone 1's rule) does not count as "does not apply", so such a template is not a ranking candidate.
- **Scripted beside live:** the page prints each anchor's scripted score over every target pair (the pack's anchor report) beside its live score, on the same scale; printed, never used in a reading.
- **The oracle filter** over O's three trials, as round 1's §5.

## 6. What the result triggers
PLAN §6: a ranking candidate is admitted with that label, and a cleared template that is not one is admitted as a do-no-harm check, both only after #529 lands; a low v3 is not admitted and its cleared v2 stays; unstable gets one extension pack by round 1's pooled rule.

- **The pooled reading after an extension** (round 1's §6, for this round's thirteen arms). Only the templates read unstable are read again. The extension is one new control-only pack of ten G1 lives on a new draw, built, run and checked by these rules; its hash joins the control-only list too. The packs are pooled only when the extension's reference identity (check 4) is the first pack's and its arms carry the same four code pins; otherwise every pooled template reads unresolved. Pooled repeat k, for each of the thirteen labels F1 to O3, is that arm's items on both packs together. f, r, b, g, w, c, every flag and its stability are computed on the pooled repeats exactly as in §5, and §5's precedence gives the final reading, with "unstable" counting as low. A template whose items are unresolved on the extension pack reads unresolved. Each bundle keeps its own pack's three-trial filter. Templates that were not unstable keep their first reading, and their extension items are not read.
- **When the pooled reading's code is written** (a departure). The reading script at the run commit reads one pack. If a template reads unstable, the pooled step is written to the rule above, reviewed against this text by a model family other than its author's, and merged before the extension's seeds are drawn; the extension's page names that commit. At that commit, `tasks.py` and `table.py` are the run commit's except for the reviewed pooled step. The extension's task list holds all four templates, as `tasks.py` requires, and only the templates read unstable are read from it. Until the pooled step merges, an unstable template is not a ranking candidate.

**The follow-up ([#394](https://github.com/electricsheephq/bicentennial/issues/394)) starts only if this round establishes at least one ranking candidate;** that frozen set is its ranking set (Wake only if it qualifies), and every other kind is carried descriptively. If an id's v3 is not admitted, the follow-up's edition is registered separately; edition 3 stays what this round ran. The page prints each anchor's scripted score beside its live score.

## 7. Predictions, written before the draw (points; one pair = 10)
Central value, then the range expected to hold it. Live readers have missed predictions before when they work from handed-over evidence (Milestone 1: four of twelve cells), so the ranges are wide where the reader has a block to work from.

| Template | F | R | B | G | W | O (c) | Expected reading |
|---|---|---|---|---|---|---|---|
| `drift-config-v3` | 0 (−10 to 0) | 0 (−20 to 10) | 0 (−20 to 10) | 0 (−20 to 10) | 25 (0 to 60) | 95 (80 to 100) | ranking candidate if W stays at or below 35; otherwise cleared |
| `drift-quote-v3` | 0 (−10 to 0) | 0 (−20 to 10) | 0 (−20 to 10) | 0 (−20 to 10) | −35 (−70 to 0) | 95 (80 to 100) | ranking candidate |
| `drift-chain-fault-v3` | 0 (−10 to 0) | 0 (−20 to 10) | 0 (−20 to 10) | 0 (−20 to 10) | 0 (−20 to 20) | 95 (80 to 100) | ranking candidate |
| `wake-loop-v1` | 0 (−10 to 0) | 0 (−20 to 10) | 0 (−20 to 10) | 0 (−20 to 10) | 0 (−20 to 20) | 100 (80 to 100) | ranking candidate |

- **Where the numbers come from.** The finalists' anchor values are the screen's scripted scores on the screening set; Wake's are edition 1's scripted anchor report on the same set. The oracle values come from the smoke (100 on each finalist's five public pairs) and from Milestone 1's three oracle arms (5 of 5 Wake pairs in each).
- **The known risk, `drift-config`'s recent window.** W scores one pair (10 points) on each life whose first long sprint is in session 2, where its evidence falls inside the window (cards README ruling 10). The generator draws that sprint uniformly from sessions 2 to 5, so each fresh life has it in session 2 with probability 1/4. The expected W is therefore 25; the screening set's 35 came from 7 of its 20 lives. Four or more such lives (W above 35) would stop `drift-config` from ranking: under this placement model that has a probability of about 22%. That is not the probability of a ranking reading, because the live scores and every stability check still decide.
- **Checks:**
  - no arm compacts (check 8);
  - no arm reaches the send cap;
  - all thirteen arms are served one identity (check 4);
  - the oracle filter keeps at least 36 of the 40 target pairs.

## 8. What was already seen when this was written
- **Earlier results:** Milestone 1's results, round 1's results, the candidate cards and the rulings in the cards README, edition 1's scripted anchor report on the screening set (Wake's included), and the screen's reports (iteration 1 on the public lives, then the screening set, with their positive controls).
- **The oracle smoke** (14 November, at the commit that registered edition 3) ran on the public lives built with edition 3, with the send cap at 1,000 ([#535](https://github.com/electricsheephq/bicentennial/issues/535)):
  - each finalist scored 5 of 5 pairs right (100), with no wrong pair, no pair without credit and no rerun;
  - it used 343 sends for 85 probe turns, and its reader never compacted.
  - Only the finalists were read; Wake and the other templates in that pack were not. Its run record is published with this round's results.
- **What the smoke's reader saw:** the v3 prompts, on the public lives only.
- **What does not exist yet:** the validation seeds. The thresholds are PLAN's and PREREG-v0.5's; none was chosen after a report.

## 9. What this does not prove
- One reader at one effort, one pack, ten pairs per template: one pair is 10 points.
- Control rows only: nothing about any memory system.
- "Retrieval" means the four lexical and positional anchors; dense retrieval is untested (PLAN §9).
- On `drift-quote` and `drift-chain-fault` a pass shows that the scored entry is right, not that the sweep was complete (cards README ruling 5).
- Scripted lives; not a Ring 1 run.
- A ranking candidate is a ranking candidate on this pack with this reader: never cell admission (PREREG §4), a Stage A census, "calibrated", or a validated ranking task (PLAN §9).
- On `drift-config` the recent window scores every life whose first long sprint is in session 2, so its reading depends on this pack's placement (§7, cards README ruling 10).

**Departures:** PLAN §11's table, plus:
- the G and W rows' doubled compaction window and context length;
- edition 3 as a candidate edition;
- check 8 (no compaction), added beside round 1's checks 1 to 7, with check 4's single rerun and exclusion;
- the send cap projected from round 1's and the smoke's measured counts, because the rehearsal is not live (PLAN §10 expected the rehearsal to measure it);
- the pooled reading's code, written and reviewed before an extension's draw rather than at the run commit (§6).

Claim class: exploratory, developer-tier template validity.
