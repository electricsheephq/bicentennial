# Validity round 1 declaration: how the repaired templates' control trials are read

**Status:** written 13 November 2026, before any seed for these trials is drawn and before any trial runs. It is merged into the repository before the draw, and the results page names its commit. This is a developer-tier validity check on fresh lives that only control rows ever see: no bar, no certification, no real system, and not predictive of the full tier (PREREG-v0.5 §6). An adversarial review by a model family other than the author's is published beside it; that is the interim scrutiny, not the Scoring Veto Panel.

## 1. Why, and what is validated
Milestone 1's oracle row failed two kinds of task even with the needed evidence handed over ([results](../milestone-1/2026-11-11-separation-table/RESULT.md)). A control-only diagnostic run on the public lives then measured why ([#505](https://github.com/electricsheephq/bicentennial/issues/505), [#506](https://github.com/electricsheephq/bicentennial/issues/506)). Milestone 1's declaration (§6) says such a template gets a new version, and that the version needs three oracle trials on fresh control-only lives, with a frozen task list, before any system runs on it. This round does that for four templates. Each new version (v2) changes only its prompt and the id of its decision table. The instances, the options, the evidence, the checks and the scoring are unchanged:

| Template | What the diagnostic run measured | What v2 changes |
|---|---|---|
| `drift-chain-fault` | The reader wrote the right value under the entry name the prompt suggested ("<milestone> deadline"), not the bare name both checks read (10 of 10). | The prompt names the exact entry line to write. |
| `recall-count` | Right counts with citations that join lines, which the scorer cannot read (5 of 5). | The prompt asks for a one-line citation from one message. |
| `drift-config` | "Bring it up to date" led the reader to change a setting that was only raised as a possibility (2 of 5). | The prompt says when to change the value and when to leave it. |
| `drift-quote` | The rule that a value later reported or quoted does not replace the value that was set was never stated, and the reader took the quoted value on 6 of 6 with one wording. | The prompt states that rule. |

The v1 templates stay frozen and unchanged, and every existing pack keeps its pins. A pack holds one version of each template: the validation pack has the four v2s and the other templates' unchanged v1s. **The count question can be validated for its answer format only:** its answer is 2 on every T2 life, so a no-memory answer of 2 with no citation would get full marks ([#512](https://github.com/electricsheephq/bicentennial/issues/512)). This round can say whether a right count now scores; it cannot admit the count question as a memory task.

## 2. The lives
- **One validation pack**, built with the v2 templates (template edition 2) in T2's exact shape: ten lives of ten sessions (five software-partner lives and five personal-assistant lives), two twin branches each, a kill at session 6 and a model-label swap at session 8. Only the seeds differ from the public T2 spec.
- **Seeds.** Drawn once, after this declaration, the v2 templates and the roster script are merged: ten design seeds and sixteen ordered spares, each from `secrets.randbits(63)`, checked disjoint from every seed committed in the repository. Before the pack is built, the sha256 of the drawn list is posted on #505. A life whose seed fails the placement dry run takes the next spare, and the failure is recorded. If the dry run stops (a second design seed fails, or one life uses up its replacements), the draw is void. Its seed list, commitment and placement table up to the stop are kept and published with the results, and a new draw follows by the same rules, with its own commitment posted.
- **Hidden until the results.** The validation spec and its seeds stay out of the repository until the results are published; then the spec, the drawn list and the placement table are committed, and anyone can check them against the posted sha256.
- **Control-only for good.** Only the three control rows below ever run on this pack, before and after the results. The results page lists every run made on its pack hash, and the reading script refuses a run without its control record.

## 3. What runs
- **Reader:** the pinned reader model at its pinned effort, through the benchmark's own login, as in Milestone 1. Only the probe answer is live.
- **One commit for every arm:** a main commit that contains this declaration, the v2 templates, the roster script and the reading script. The results page names it. The v2 templates change none of the four code pins (controls, reader, scoring code, scorer); the page prints them beside Milestone 1's.
- **Rows:** F, no memory; R, the pinned naive-retrieval control (top five); O, the pinned oracle-evidence control. Each is defined, and its text placed, exactly as in Milestone 1 (its declaration §1).
- **Seven arms, in this order:** F, R, O, O, R, F, O. The first six are mirrored, so the means of F, R and the first two O arms sit at the same centre of the order. The seventh is O's third trial. Each arm runs alone over the whole pack from a clean state, never reads a cached result, and keeps the reader's diagnostics privately.
- **Target items:** every item of a v2 template: 30 action tasks (15 twin pairs: five each of `drift-chain-fault`, `drift-config` and `drift-quote`, one pair per software-partner life) and 5 count questions (one per personal-assistant life). The pack's other items run because the pack carries them; they are not read, published as results, or used to select anything.
- **Frozen task list:** before the first arm, `TASKS.json` (canonical JSON) lists the commit, the template edition, the spec's sha256, the draw's sha256, the pack hash, and one row per target item: life, branch, item id, template ref, bundle id (or none) and decision table. Its sha256 is posted on #505 with the pack hash. No item leaves the list after that.

## 4. Checks before any score is read
Milestone 1's checks (its §2) and its readings 4-9 (§11) apply, with the 35 target items in place of its 40 action tasks:
1. **Payload:** each R and O block equals the pinned control's text, byte for byte.
2. **Presence:** for O, the needed facts are in what the reader received, on all 35 target items. For R, presence equals the pack's scripted naive-retrieval report, task by task.
3. **Memory off:** the runner's own tests at the run commit, as in Milestone 1.
4. **Identity:** every arm was served one model identity, the most common among the seven arms (on a tie, that of the arm that ran first). An arm served another identity, or whose run discloses a change of identity during the arm or records none (Milestone 1's §11.15), is rerun once. If it is still mismatched, it is never pooled and its trials count as unscored.
5. **Completeness:** an arm with a target item BLOCKED, or with no score, is rerun once, whole. A system failure is a scored failure, never an exclusion.
6. **Repeats and common support:** a template's reading uses only complete, identity-matched repeats, and only the items scored in every repeat used. After the one rerun, a target item that is still unscored, or a required repeat that is still missing or mismatched, makes that template's reading **unresolved**.
7. **Live units:** every unit of every arm ran live in that arm.

If check 1, 2, 3 or 7 fails, the fault is fixed and the arm rerun before any score is opened. If the rerun fails one of these checks again, the round ends: no score is opened, the checks and the missing observations are published, and every template reads unresolved. A rerun keeps its label and runs after the arms already done; the page prints the order in which the arms actually ran.

## 5. How each template is read
- **Scores** come from the unchanged scorer. An action pair scores the lower of its two twins' scores (+1 right, 0 no credit, −1 a confident false memory). A count question is its own bundle and scores `score_milli / 1000`, so the half points the scorer gives below asserted confidence are kept (+0.5 or −0.5). A template's points are 100 times its mean over its items on the common support; one pair or question is 20 points.
- **f, r, c:** f and r are the means of the two F and the two R arms; c is the mean of the first two O arms. O's third trial enters the stability check and the filter, and the page also prints c over all three.
- **The low flag** applies when c < 75 (PREREG-v0.5 §9's oracle target, applied per template as in Milestone 1's §4). It is computed on the means and with each O trial alone.
- **One reading per template,** the first of these that applies:
  1. **unresolved:** §4's completeness rule;
  2. **unstable:** the low flag with any one O trial alone disagrees with the flag on the means;
  3. **low:** the low flag applies;
  4. **admitted**, or for the count question **format validated** (§1). An admitted action template may enter the fresh-seed follow-up ([#394](https://github.com/electricsheephq/bicentennial/issues/394)) with every other kind.
- **Near-solved flags,** as in Milestone 1's §4 (naive retrieval r ≥ f + 0.7 (c − f); no memory f ≥ 0.7 c; not interpreted when c ≤ f or c ≤ 0), are computed and printed for every template, with their stability over every combination of repeats as in Milestone 1. Unlike Milestone 1, only the low flag's stability enters the reading; the near-solved flags never do. A template they apply to is labelled as such, and Milestone 1's §6 governs its use: kept as a do-no-harm check and excluded from any claim that memory beats retrieval.
- **The oracle filter** (PREREG-v0.5 §4, filter 3), over O's three trials: an item passes a trial when it scores 1000. A trial from an excluded arm (invalid, or identity-mismatched after its rerun) counts as unscored. An item passes the filter with two passing trials, fails when it could not reach two even if every unscored trial passed, and is unresolved otherwise. A bundle (a twin pair, or one count question) passes when every item passes, fails when any item fails, and is unresolved otherwise; only passing bundles are kept. `FILTER.json` is written after the trials and published with them.
- **Disclosure counters,** read from the diagnostics after the scores are opened and never used as gates: chain entries written under the exact name; count answers the scorer could not read; on `drift-config`, changes on hedged twins and corrections left unapplied; on `drift-quote`, results by the wording of the later statement.

## 6. What the result triggers
| The reading says | Then |
|---|---|
| admitted | the template may enter the fresh-seed follow-up with every other kind; its kept bundles are published with the result |
| low | its mechanism is measured again from this round's diagnostics before a v3, and the v3 is validated by these rules on a new draw |
| unstable | one extension pack on a new draw, built, run and checked by these rules, then the pooled reading below |
| unresolved | the missing observations are the result; the template is not admitted, and the cause is fixed before any new round |

- **The pooled reading after an extension.** Only the templates read unstable are read again. Pooled repeat k (F1, F2, R1, R2, O1, O2, O3) is that arm's items on both packs together. f, r, c, the low flag and its stability are computed on the pooled repeats exactly as in §5, and §5's precedence gives the final reading, with "unstable" counting as low. A template whose items are unresolved on the extension pack reads unresolved. Each bundle keeps its own pack's three-trial filter. Templates that were not unstable keep their first reading, and their extension items are not read.

No real system runs on these lives, and nothing here rescores Milestone 1.

## 7. Predictions, written before the draw (points; one pair or question = 20)
| Template | F | R | O (c) | Expected reading |
|---|---|---|---|---|
| `drift-chain-fault` v2 | −20 to 0 | −60 to 20 | 60 to 100 | admitted |
| `drift-config` v2 | −20 to 0 | −40 to 20 | 60 to 100 | admitted |
| `drift-quote` v2 | −20 to 0 | −60 to 20 | 40 to 100 | unsure: low is as likely as admitted |
| `recall-count` v2 | 0 | 0 to 60 | 80 to 100 | format validated |

## 8. What was already seen when this was written
- Milestone 1's results and the diagnostic run of 13 November, both on the public lives with the v1 prompts. The v2 prompts were written afterwards from that run's measured mechanisms, and reviewed by a model family other than the author's before this declaration.
- No reader has seen a v2 prompt. The validation seeds do not exist yet.
- The thresholds are Milestone 1's and PREREG-v0.5's; none was chosen for this round.

## 9. What this does not prove
- One reader at one effort, one pack, five pairs or questions per template: one pair is 20 points.
- Control rows only: nothing about any memory system, and no claim that memory beats retrieval.
- The count question: its answer format only (#512).
- Scripted lives: no system's own judgment about what to store is tested.
- The seed rules borrow Ring 1's, but this is not a Ring 1 run.

Claim class: exploratory, developer-tier template validity.
