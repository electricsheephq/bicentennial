# Milestone 1, step 2: the first separation table (#497)

Claim class: nine live T2 arms at one commit on the public T2 pack: no memory (F, two repeats), naive retrieval (R, two), oracle evidence (O, three) and one real system, Hermes native (H, two), all through one live reader; read by the rules in [`DECLARATION.md`](../DECLARATION.md), written and merged before any of these arms ran. ⟨Optional rows sentence.⟩ Five public lives carry scored actions. A developer-tier result: no bar, no certification, not predictive of the full tier. The screening flags are exploratory, and no significance is claimed.

This is the second step of [Milestone 1](https://github.com/electricsheephq/bicentennial/issues/494). Step 1 ([`2026-11-04-live-runs-by-kind`](../2026-11-04-live-runs-by-kind/RESULT.md)) read two earlier runs beside the pack's scripted controls. Step 2 runs every row live.

## The result in one paragraph

Of the three kinds of scored task, only Wake passes the declared screen: with the needed evidence handed to the reader it scores 5 of 5 pairs in every repeat, and with no memory or naive retrieval it scores 0. The two Drift kinds fail the oracle test. With the evidence handed over, the reader nets −3 on the 10 value-twin pairs (1 right, 4 confidently wrong, 5 no credit, in all three repeats) and 0 on the 5 correction pairs (−1 and +1 on the two repeats the flags use). By the declaration, those two kinds get new template versions, each validated with its own oracle trials on fresh lives before any system runs on it, and Wake goes on to fresh validation with every other kind. Hermes native reproduced its 4 November result exactly, pair for pair.

## The runs

- **Code commit** `42aea53d0e30ec124f8b7e3e4cbffad1b1cc5285` for all nine arms (the merge of #501, which added the live control arms). **Declaration:** sections 1-10 merged at `9087e35` (#499); section 11, readings fixed before the runs, merged at `ca3b379` (#502). **Table script:** [`table.py`](table.py), merged at `ca3b379` (#502), with one display-label fix (#504) merged at `e4e0f69` before the table was generated. `42aea53`, `ca3b379` and `e4e0f69` have the same code under `src/`.
- **T2 pack** hash `15141b194ab8abf389af2bfdbb4fd81e4d511fca14c54508d613fbe156628c04`, rebuilt at the run commit; it equals the pack of the 4 November runs.
- Hermes native at the registry's pinned Hermes (v0.22.2); the live reader `gpt-6.1-sol` at effort `medium`, served as identity `6e0b2b52fc6f` (a 12-character hash prefix) on every arm, with no change recorded during any arm. At T2 only the probe answers are live: write turns, compaction, extraction and embeddings are scripted.
- **Order:** F1 R1 O1 H1 H2 O2 R2 F2 O3, one arm at a time, each alone over the whole pack from a clean state, on one machine, on 11 November 2026 (times UTC):

  | Arm | F1 | R1 | O1 | H1 | H2 | O2 | R2 | F2 | O3 |
  |---|---|---|---|---|---|---|---|---|---|
  | Start | 16:39:52 | 17:00:59 | 17:21:34 | 17:37:52 | 19:03:27 | 20:06:41 | 20:20:01 | 20:36:57 | 20:50:02 |
  | End | 17:00:57 | 17:21:31 | 17:37:50 | 19:03:16 | 20:06:38 | 20:19:59 | 20:36:55 | 20:50:00 | 20:59:22 |

  No arm was rerun. The control arms never read a cached result. H1 ran with a fresh, empty cache and measured its own no-memory floor beside it, live on all 20 of its units; H2 took that floor from the cache on all 20 units, with the served identity matched. That extra floor is shown separately (section 3e of the output) and enters no mean, flag or comparison.
- **Run trees** in the private evidence store, tag ⟨tag⟩.

## The rows

- **No memory (F):** the live reader with memory off and no block.
- **Naive retrieval (R):** the pinned naive-retrieval control's top five chunks ([`specs/controls/naive_rag.md`](../../../specs/controls/naive_rag.md): hashed TF-IDF over 240-character chunks, query = the probe prompt), framed at the top of each probe turn, memory off.
- **Oracle evidence (O):** the pinned oracle-evidence control's gold evidence, framed the same way, memory off.
- **Hermes native (H):** Hermes's own memory.

R and O share one placement of text, chosen before the runs (DECLARATION §9); H has its own. H against the controls is therefore a comparison of whole paths.

## Deviations from the declaration

None. The run log has one start, end and exit 0 for each arm in the declared order; there is no rerun record; every check below passes. The table script and the declaration's readings were merged before the first arm started: §11 and the script at `ca3b379` (#502), one display-label fix at `e4e0f69` (#504). ⟨Optional-row deviations, if any.⟩

## Checks before any score

The table script prints its checks first and opens no score while one is open (DECLARATION §2 and §11). All pass:

- **Card pins and pack:** every arm's card pins are equal and name the run commit (`42aea53d0e30`), and every arm has the T2 pack above.
- **Run order:** the arms' recorded start and end times follow the declared order, with no overlap.
- **Check 1, block delivery:** F1 and F2 carry no block. R1, R2, O1, O2 and O3 each received the pinned control's text, byte for byte, on 85 of 85 tasks, with 0 mismatched and 0 recorded but not recomputed.
- **Check 2, presence:** in R1 and R2, whether the needed fact was in the probe turn's first request equals the pack's scripted naive-retrieval report on 85 of 85 tasks. In O1, O2 and O3, the needed fact was in the probe turn's first request on 40 of 40 scored action tasks.
- **Check 3, memory off:** request bodies are not kept, so this is the runner's own three tests at the run commit, named in `table.py` (`CHECK3_TESTS`, in `tests/runner/test_control_arms.py`): no control-arm request carries a memory block or a memory or search tool, and no block carries an answer key or option order. They passed in the table's own run at `42aea53` and in CI at that commit ([run 43024947257](https://github.com/electricsheephq/bicentennial/actions/runs/43024947257), the push to main; the file runs in its shard 3, which passed).
- **Check 4, identity:** every arm was served the same model identity, and none changed during its run; 0 arms mismatched.
- **Check 5, completeness:** every arm scored all 40 of its scored action tasks; 0 BLOCKED, 0 missing.
- **Check 6, common support:** the flags use the pairs scored in every repeat of F, R and O: 10 value twins, 5 correction twins and 5 Wake pairs, 20 in all.
- **Check 7, live units:** every unit of every F, R and O arm ran live: 20 of 20 units, 85 of 85 probes sent to the live reader, 0 cached, 0 stopped.

## The scale

The twin-pair scale of step 1: a pair scores the lower of its twins' scores, +1 when both twins are right, −1 when either asserts a false memory, otherwise 0. Points = 100 × net ÷ pairs. A row's mean uses its usable repeats on the pairs every one of them scored.

## The table: 20 scored action pairs on five lives

Net, with (pairs right, pairs wrong); every other pair is no credit. Each row is the mean of its repeats; F, R and H are identical in every repeat, and O's three repeats differ only on correction twins.

| Kind of task (pairs) | F, no memory (2) | R, naive retrieval (2) | O, oracle evidence (3) | H, Hermes native (2) |
| --- | --- | --- | --- | --- |
| Drift, value twins (10) | 0 (0, 0) | −3 (1, 4) | −3 (1, 4) | −1 (2, 3) |
| Drift, correction twins (5) | 0 (0, 0) | 0 (0, 0) | 1 (3, 2): by repeat −1 (2, 3), 1 (3, 2), 3 (4, 1) | 5 (5, 0) |
| Wake (5) | 0 (0, 0) | 0 (0, 0) | 5 (5, 0) | 0 (0, 0) |
| **All scored pairs (20)**, pooled diagnostic | **0** (0, 0) | **−3** (1, 4) | **3** (9, 6) | **4** (7, 3) |
| Points: value / correction / Wake / pooled | 0 / 0 / 0 / 0 | −30 / 0 / 0 / −15 | −30 / 20 / 100 / 15 | −10 / 100 / 0 / 20 |

The pooled figure weights Drift's 15 pairs three times Wake's five and is never carried into a pilot claim (DECLARATION §3).

**Per life** (net of each life's four scored pairs, lives 1 to 5; every repeat is in the output below): F 0, 0, 0, 0, 0; R −1, −1, −1, −1, +1; O 1/3, −1/3, 1, 1, 1 (mean of its three repeats); H 0, 2, 0, 0, 2.

At task level (40 tasks): F passes 5 in each repeat, R 8, O 20, 20 and 22, H 18 (H1) and 17 (H2). **Quiz items** (15 per arm; +1 right, −1 confident false memory): F answers none; R is right on 8 and wrong on 7; O is right on 10 and scored −1 on 5 in every repeat (its five count answers did not parse, which the scorer counts as a confident wrong answer); H is right on 11 (H1) and 12 (H2), wrong on 4 and 3.

**Agreement between repeats:** F1 and F2, R1 and R2, and H1 and H2 are equal on 20 of 20 pairs. O's repeats are equal on 19 (O1, O2), 18 (O1, O3) and 19 (O2, O3) of 20. Between H1 and H2 two task scores differ: one Wake task and one quiz item, as between the two 4 November runs.

## Screening flags, from the control rows only

f, r and c are the points of F, R and O on each kind's common pairs; f and r are the means of their two repeats, and c is the mean of O's first two repeats (DECLARATION §4). Margins are in pairs; "stable" means every combination of one repeat per row agrees with the means.

| Kind of task | f | r | c (O1, O2) | c (O1-O3) | low even with the evidence (c < 75) | near-solved by naive retrieval | near-solved without memory | Classification |
|---|---|---|---|---|---|---|---|---|
| Drift, value twins (10) | 0 | −30 | −30 | −30 | applies, margin 21/2 (10.5), stable (3 of 3) | not interpreted (c ≤ f) | not interpreted (c ≤ f) | **low** |
| Drift, correction twins (5) | 0 | 0 | 0 | 20 | applies, margin 15/4 (3.75), stable (3 of 3) | not interpreted (c ≤ f) | not interpreted (c ≤ f) | **low** |
| Wake (5) | 0 | 0 | 100 | 100 | does not apply, margin −5/4 (−1.25), stable (3 of 3) | does not apply, margin −7/2 (−3.5), stable (12 of 12) | does not apply, margin −7/2 (−3.5), stable (6 of 6) | **candidate** |

Flags: low even with the evidence handed over (c < 75); near-solved by naive retrieval (r ≥ f + 0.7 (c − f)); near-solved without memory (f ≥ 0.7 c); otherwise a candidate for fresh validation. A near-solved flag is not interpreted when c ≤ f or c ≤ 0; its arithmetic is printed in the output as a disclosure only. The output prints each margin as an exact fraction with one rounded decimal (3.8 for 15/4, −1.2 for −5/4). Real systems take no part in a flag. No flag is unstable.

## Hermes native against the control rows

Points on each comparison's common pairs; O is the mean of O1 and O2, as in the flags. Per life, the difference is in pairs; the exact two-sided sign-flip p is over the five lives. With five lives that p cannot go below 1/16, and no significance is claimed.

| Kind of task | H | H − F (p) | H − R (p) | H − O (p) |
|---|---|---|---|---|
| Drift, value twins | −10 | −10 (1) | +20 (1) | +20 (1) |
| Drift, correction twins | 100 | +100 (1/16) | +100 (1/16) | +100 (1/4) |
| Wake | 0 | 0 (1) | 0 (1) | −100 (1/16) |
| Pooled diagnostic | 20 | +20 (1/2; 1/16 on tasks) | +35 (1/16) | +10 (7/8) |

Hermes's net per life is 0, 2, 0, 0 and 2 in both runs, as on 4 November.

⟨Optional rows section.⟩

## Predictions against the result

The predictions in DECLARATION §7 were written before the runs, in pairs right; a result shows the confidently wrong pairs beside it.

| Row | Value twins (10), predicted | result | Correction twins (5), predicted | result | Wake (5), predicted | result |
|---|---|---|---|---|---|---|
| F | 0 | 0 | 0 | 0 | 0 | 0 |
| R | 2-5 | **1** (and 4 wrong) | 0 | 0 | 0 | 0 |
| O | 3-7 | **1** (and 4 wrong) in every repeat | 4-5 | **2, 3, 4** (and 3, 2, 1 wrong; mean 3) | 0-2 | **5** in every repeat |
| H | 2 (and 3 confidently wrong) | 2 (and 3 wrong) in both runs | 5 | 5 in both runs | 0 | 0 in both runs |

Expected flags: value twins and Wake low even with the evidence; correction twins a candidate. Observed: value twins low, as expected; **correction twins low and Wake a candidate, the reverse of the prediction.** Eight of the twelve cells fall inside their predicted range. Every miss is a live reader working from handed-over evidence: naive retrieval on value twins, and all three kinds of the oracle row, which on Drift did worse and on Wake far better than predicted.

## Prospective filter yield

Pairs whose twins each passed with only their evidence in at least two of the three O trials (DECLARATION §6). This validates nothing; it says how much of today's list the frozen oracle filter would keep.

| Kind of task | Pairs kept | Twins right in 0, 1, 2, 3 of the three O trials |
|---|---|---|
| Drift, value twins (10) | 1 | 16, 2, 0, 2 |
| Drift, correction twins (5) | 3 | 1, 1, 1, 7 |
| Wake (5) | 5 | 0, 0, 0, 10 |

Nine of the 20 pairs would be kept.

## What it says, in plain words

1. **The run is clean.** All nine arms ran live at one commit, in the declared order, with one served model identity throughout, and every check passed before any score was opened. No arm was rerun.
2. **Without memory, nothing.** The no-memory row scores 0 on every kind, in both repeats.
3. **Two of the three kinds fail the oracle test.** With the needed evidence handed straight to the reader, it nets −3 on the 10 value-twin pairs (1 right, 4 confidently wrong, 5 no credit) and 0 on the 5 correction pairs (−1 and +1 on the two repeats the flags use). As built today, a score on these kinds cannot be read as a memory result: a reader handed the needed evidence still fails them. That says direct evidence was not enough in this setup, not by itself that the reader is at fault (DECLARATION §4). The declaration's response is fixed: their templates get new versions, and each new version needs three oracle trials on fresh control-only lives and a frozen task list before any system runs on it (§6).
4. **Wake is the one candidate.** No memory and naive retrieval score 0; oracle evidence scores 5 of 5 in every repeat. It is the one kind here that separates having the evidence from not having it, and it goes into the fresh-seed follow-up with every other kind. A candidate is not yet a validated ranking task.
5. **Naive retrieval scores below no memory on value twins.** The pinned naive-retrieval row nets −3 (1 right, 4 confidently wrong) against no memory's 0, exactly as the oracle row does on that kind, and scores nothing on the other two kinds. This is a description, not a declared reading: on value twins the near-solved flags are not interpreted, because the oracle row is below the floor.
6. **Hermes native reproduces exactly.** Its two runs are identical pair for pair, and identical to the two 4 November runs at an older commit: value twins −1 (2 right, 3 wrong), correction twins 5 of 5, Wake 0. On correction twins it gets every pair, which the oracle row with the evidence handed over does not; on Wake it gets none, while the oracle row gets every pair. These are comparisons of whole paths, and no significance is claimed.
7. **My predictions missed where the reader works from handed-over evidence.** They were right for no memory and for Hermes (whose behaviour was already known from 4 November), and wrong for naive retrieval on value twins and for every oracle cell on its mean (one repeat, O3 on correction twins, landed inside its range). In this run the scripted controls did not predict the live oracle row, which is why the declaration has it run live.

## After the table: where the failures sit

Read from the run's outcome records after the table, as counts only, with one note from reading the code; none of it is part of the declared reading, and it moves no flag. Each kind of task here is made by one or two templates.

- **Value twins are two templates of five pairs each.** On `drift-chain-fault-v1`, every row that saw any evidence (R, O and H, every repeat) scored all 10 tasks as a failed task, no credit. Under this template's decision table, the scorer gives a failed task when the reader changed the repository but left it matching neither the current value nor a retracted one. The no-memory row did nothing (an omission). So five of the ten value pairs earn no credit in any row. The run keeps neither request bodies nor the edited files, so why the change never matches is not measured; the repair has to measure it first. Reading the code after the table suggests one cause, still unmeasured: in these lives the reader edits the file with shell commands it writes itself, and the check accepts only an entry keyed by the bare milestone name, in a strict format, while the prompt names the entry with the word "deadline" after the name. A reader that writes the key as the prompt phrases it would score exactly this. [#505](https://github.com/electricsheephq/bicentennial/issues/505) has the code references; one run that keeps the edited file settles it.
- On `drift-quote-v1`, a competing value was in view on every task in every row with evidence. The oracle row asserted the wrong value on 7, 8 and 7 of the 10 tasks; naive retrieval on 7 in both repeats; Hermes on 3 in both runs. The failures follow the wording of the later statement, a quoted value written as firmly as the decision: the oracle row failed all 18 of its trials where it reads "It was said that … must be …", and 4 of 12 where it reads as a quote from a note.
- **Correction twins** (`drift-config-v1`): the oracle row failed only on the hedged twins, where the right action is to leave the setting alone: 3, 2 and 1 of those five tasks in its three repeats. It applied every correction (15 of 15). The outcome records mark the hedged twins as having a competing value in view, because both of that twin's options carry the hedged value. Hermes passed all ten.
- **Quiz:** the oracle row answered every "as of" Drift question and every value-recall question right, None of its count answers (`recall-count-v1`, five in each repeat) could be parsed, which the scorer counts as −1000, the same as a confident wrong answer; naive retrieval's three misses there are unparsed too. Hermes's count answers all parsed and were right.

So the oracle row's failures sit on the quoted values of `drift-quote`, the hedged twins of `drift-config` and count answers it did not format as the scorer requires; it was right on every Wake task, every correction, and every value-recall and "as of" question. For each, the repair has to find out whether the fault is in the template, in how the evidence is handed over, in the answer format, or in the reader; [#506](https://github.com/electricsheephq/bicentennial/issues/506) has the code reading, and this run cannot settle it.

## What happens next

By DECLARATION §6, decided before the runs:

- **Value twins and correction twins (low):** `drift-chain-fault`, `drift-quote` and `drift-config` get new versions, after the mechanism above is measured. Each new version needs three oracle trials on fresh control-only lives and a frozen task list before any system runs on it. The work is tracked in [#505](https://github.com/electricsheephq/bicentennial/issues/505) (`drift-chain-fault`) and [#506](https://github.com/electricsheephq/bicentennial/issues/506) (`drift-quote` and `drift-config`).
- **Wake (candidate):** goes into the fresh-seed follow-up ([#394](https://github.com/electricsheephq/bicentennial/issues/394)) with every other kind, repaired versions included.
- No kind is promoted or dropped because of how Hermes scored on it; the follow-up carries every kind.

## What this does not prove

- Public lives, not fresh ones. One reader model at one effort. Five lives with scored actions.
- A scripted life: no system's own judgment about what to store is tested.
- One real system in the core table. ⟨Optional rows.⟩
- Whole arms in a mirrored order, not arms interleaved within each life as the board will run them; and equal served-model names do not prove equal service behaviour across the run's hours.
- Where the control text is placed is a declared choice that can move the oracle row.
- The table lacks two rows a published board table must carry, and says so: the agent-key validation row (no auditor panel exists yet) and the full-history ceiling (the history fits the window for none of the pack's items, each tested at its own time).
- The flags are exploratory screening from control rows; a kind's flag is a reason to repair or validate it, not a finding about any system. The section after the table is a post-hoc reading of counts; the one cause it mentions comes from reading code and is not measured.

## Reproduce

`table.py` reads the run trees, the T2 pack, the output of check 3's tests at the run commit, and (as earlier evidence) the two 4 November runs. It prints counts, labels, pass/fail and 12-character hash prefixes only (the served identity among them, as a prefix): never task text, answers, item or bundle ids, or paths. From a checkout of this repository at `e4e0f69`, with the run trees and the check-3 output from the evidence tag:

```
PYTHONPATH=<checkout>/src python3 -s -P table.py --packs <packs> --check3 <check3 output> --order F1,R1,O1,H1,H2,O2,R2,F2,O3 --after-reruns F1=<run> R1=<run> O1=<run> H1=<run> H2=<run> O2=<run> R2=<run> F2=<run> O3=<run> ⟨X rows⟩ E1=<4 Nov run 1> E2=<4 Nov run 2>
```

Check 3's output is the three tests named in `table.py` (`CHECK3_TESTS`, in `tests/runner/test_control_arms.py`), run with `pytest -v` in a clean checkout at the run commit, between a first line `commit <sha>` and a last line `exit <code>`.

Its output, verbatim:

```
⟨output⟩
```
