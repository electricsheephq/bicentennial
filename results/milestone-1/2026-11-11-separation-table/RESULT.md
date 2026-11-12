# Milestone 1, step 2: the first separation table (#497)

Claim class: nine live T2 arms at one commit on the public T2 pack: no memory (F, two repeats), naive retrieval (R, two), oracle evidence (O, three) and one real system, Hermes native (H, two), all through one live reader; read by the rules in [`DECLARATION.md`](../DECLARATION.md), written and merged before any of these arms ran. Two optional rows ran after the core arms, one attempt each, and are shown separately: Holographic's attempt stopped at the run's cap on live reader calls and has no score; OMEGA ran to the end with its reranker off, as registered. Five public lives carry scored actions. A developer-tier result: no bar, no certification, not predictive of the full tier. The screening flags are exploratory, and no significance is claimed.

This is the second step of [Milestone 1](https://github.com/electricsheephq/bicentennial/issues/494). Step 1 ([`2026-11-04-live-runs-by-kind`](../2026-11-04-live-runs-by-kind/RESULT.md)) read two earlier runs beside the pack's scripted controls. Step 2 runs every row live.

## The result in one paragraph

Of the three kinds of scored task, only Wake passes the declared screen: with the needed evidence handed to the reader it scores 5 of 5 pairs in every repeat, and with no memory or naive retrieval it scores 0. The two Drift kinds fail the oracle test. With the evidence handed over, the reader nets −3 on the 10 value-twin pairs (1 right, 4 confidently wrong, 5 no credit, in all three repeats) and 0 on the 5 correction pairs (−1 and +1 on the two repeats the flags use). By the declaration, those two kinds get new template versions, each validated with its own oracle trials on fresh lives before any system runs on it, and Wake goes on to fresh validation with every other kind. Hermes native reproduced its 4 November result exactly: the same score on each of the 20 pairs (from the outcome records; the output shows the same totals by kind and per life).

## The runs

- **Code commit** `42aea53d0e30ec124f8b7e3e4cbffad1b1cc5285` for all nine arms (the merge of #501, which added the live control arms). **Declaration:** sections 1-10 merged at `9087e35` (#499); section 11, readings fixed before the runs, merged at `ca3b379` (#502). **Table script:** [`table.py`](table.py), merged at `ca3b379` (#502), with one display-label fix (#504) merged at `e4e0f69` before the table was generated. `42aea53`, `ca3b379` and `e4e0f69` have the same code under `src/`.
- **T2 pack** hash `15141b194ab8abf389af2bfdbb4fd81e4d511fca14c54508d613fbe156628c04`, rebuilt at the run commit; it equals the pack of the 4 November runs.
- Hermes native at the registry's pinned Hermes (v0.22.2); the live reader `gpt-6.1-sol` at effort `medium`, served as identity `6e0b2b52fc6f` (a 12-character hash prefix) on every arm, with no change recorded during any arm. At T2 only the probe answers are live: write turns, compaction and extraction are scripted, and so is any embedding a system requests through a model route (no core row requests one; naive retrieval's hashed TF-IDF embedder runs inside the control).
- **Order:** F1 R1 O1 H1 H2 O2 R2 F2 O3, one arm at a time, each alone over the whole pack from a clean state, on one machine, on 11 November 2026 (times UTC):

  | Arm | F1 | R1 | O1 | H1 | H2 | O2 | R2 | F2 | O3 |
  |---|---|---|---|---|---|---|---|---|---|
  | Start | 16:39:52 | 17:00:59 | 17:21:34 | 17:37:52 | 19:03:27 | 20:06:41 | 20:20:01 | 20:36:57 | 20:50:02 |
  | End | 17:00:57 | 17:21:31 | 17:37:50 | 19:03:16 | 20:06:38 | 20:19:59 | 20:36:55 | 20:50:00 | 20:59:22 |

  No arm was rerun. The control arms never read a cached result. H1 ran with a fresh, empty cache and measured its own no-memory floor beside it, live on all 20 of its units; H2 took that floor from the cache on all 20 units, with the served identity matched. That extra floor is shown separately (section 3e of the output) and enters no mean, flag or comparison.
- **Run trees** in the private evidence store, tag `bicentennial/m1-step2-20261111`.

## The rows

- **No memory (F):** the live reader with memory off and no block.
- **Naive retrieval (R):** the pinned naive-retrieval control's top five chunks ([`specs/controls/naive_rag.md`](../../../specs/controls/naive_rag.md): hashed TF-IDF over 240-character chunks, query = the probe prompt), framed at the top of each probe turn, memory off.
- **Oracle evidence (O):** the pinned oracle-evidence control's gold evidence, framed the same way, memory off.
- **Hermes native (H):** Hermes's own memory.

R and O share one placement of text, chosen before the runs (DECLARATION §9); H has its own. H against the controls is therefore a comparison of whole paths.

## Deviations from the declaration

None. The run log has one start, end and exit 0 for each arm in the declared order; there is no rerun record; every check below passes. The table script and the declaration's readings were merged before the first arm started: §11 and the script at `ca3b379` (#502), one display-label fix at `e4e0f69` (#504). The optional rows ran as declared (§1): after the core arms, one at a time, one attempt each, with OMEGA's card pins equal to the core arms' except the two that name the system; Holographic's failed attempt is published as a failure (§11.12). One disclosure for the optional rows: the declaration and each card's T2 label describe T2's embeddings as scripted, which holds for any embedding requested through a model route, and no core row requests one; OMEGA computes its embeddings in its own process with its local model, so its embeddings are not scripted. This changes nothing in the core rows and needed no new run.

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

## The optional rows: Holographic and OMEGA

Both ran after the nine core arms, one attempt each, as DECLARATION §1 allows: at the run commit and pack, through the same live reader, one at a time, each with a fresh, empty cache, on 12 November 2026. Their install pins were measured equal to the registry's before the attempts. They are shown separately and never pooled, and nothing about them changes the core table, the flags or the comparisons above (§1, §11.12).

**Holographic (16:15:09 to 18:19:51 UTC): the attempt failed, refusal code `spend_stop`, so there is no score.** The table output prints only that refusal code; what follows is read from the attempt's receipt, the launch script and the core arms' records, all in the evidence. It reached the run's cap of 1,000 live reader calls (the launch script's `--max-sends`) near its end, about two hours in; the runner then refused the arm and discarded its partial results, as it does with every refusal (the receipt's status `INFRA_FAILURE` is that refusal's fixed label). The cap counts every live call of the attempt: the system's probes, every repeated attempt of a unit, and automatic re-sends after transient errors. It also counted the no-memory floor the runner measures beside a system: this row started with an empty cache, so its floor ran live, an estimated 410 calls (the no-memory arms alone used 408 and 413, as their records show) that enter no result. Three of the system's 20 units ran three attempts (the receipt's attempt count per unit), the most the runner allows, because each earlier attempt had at least one task scored as an infrastructure failure; the cause is not kept. Judging from the unit timings and the runner's stop logic (no send count is kept), the cap was reached in the attempt's last minutes, while the last of those repeats was running; which unit's call reached it is not recorded. For scale, Hermes native's first core run, which also measured its floor live, used 858 of its 1,000. By the declaration (§11.12) a failed attempt is published as a failure and is not rerun here. This failure says the attempt did not finish within the run's budget as I set it up; it says nothing about how well Holographic remembers. The cap and the fresh cache were choices in the launch script, which is in the evidence. [#507](https://github.com/electricsheephq/bicentennial/issues/507) tracks the fix and a later, separately labelled run.

**OMEGA (18:19:53 to 19:54:26 UTC) ran to the end.** It was served the same model identity as the core arms throughout, with no change recorded; every card pin except the two that name the system equals the core arms'; it scored all 40 of its scored action tasks, with none blocked. It ran as registered: through the benchmark's own Hermes provider over OMEGA's Python API, which OMEGA's maintainers have not yet reviewed, offline, with its cross-encoder reranker and its query expansion off ([#289](https://github.com/electricsheephq/bicentennial/issues/289) is open). So this row is not OMEGA as shipped, how much the reranker would change it is not measured, and it is not a comparison of OMEGA with any system. At T2 only the probe answers are live: the turns that decide what is stored are scripted and the same for every system, while OMEGA's own storing and search code runs as shipped. OMEGA computes its embeddings inside its own process with its local model, staged offline; no model route serves them, so none of its embeddings is scripted.

OMEGA scored no pair right and none confidently wrong: net 0 on every kind, as the no-memory row does. Against the control rows (points on each comparison's common pairs; O is the mean of O1 and O2; exact two-sided sign-flip p over the five lives, no significance claimed):

| Kind of task | OMEGA | OMEGA − F (p) | OMEGA − R (p) | OMEGA − O (p) |
|---|---|---|---|---|
| Drift, value twins | 0 | 0 (1) | +30 (3/8) | +30 (3/8) |
| Drift, correction twins | 0 | 0 (1) | 0 (1) | 0 (1) |
| Wake | 0 | 0 (1) | 0 (1) | −100 (1/16) |
| Pooled diagnostic | 0 | 0 (1; 1 on tasks) | +15 (3/8) | −10 (5/8) |

At task level it passed 5 of 40, as the no-memory row does. On the quiz it was right on 12 of 15 and wrong on 3, all "as of" Drift questions; its five count answers parsed and were right.

Read after the table from the run's records (counts only; outside the declared reading; from the `in_context` field of each task's outcome record and the `in_context_initial` field of each probe record): In none of OMEGA's 85 probe turns was the needed fact in the turn's first request (its registered adapter's prompt hook records the prompt and does not search), so a stored fact reached the reader only through a search during the turn. The needed fact reached the reader on all 15 quiz items but on only 11 of the 40 scored action tasks: all 10 of `drift-chain-fault`, which no row with evidence scores, and 1 of `drift-config`. With the evidence handed over, the oracle row had it in view on all 40 in every repeat, and naive retrieval on 20 in both. On `drift-config`, `drift-quote` and Wake its verdict counts are close to the no-memory row's: identical on `drift-config` (5 passed, 5 omitted) and Wake (10 omitted), and on `drift-quote` 5 failed tasks and 5 omissions against 4 and 6.

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
6. **Hermes native reproduces exactly.** Its two runs are identical pair for pair, and identical to the two 4 November runs at an older commit (the pair scores, from the outcome records, are equal on 20 of 20; the output shows the same totals by kind and per life; the older commit's scripted write-turn package differs, hash `753f83e1bd00` against `cf5d8ed51482` in the cards' pins, and whether that difference reaches these lives is not measured): value twins −1 (2 right, 3 wrong), correction twins 5 of 5, Wake 0. On correction twins it gets every pair, which the oracle row with the evidence handed over does not; on Wake it gets none, while the oracle row gets every pair. These are comparisons of whole paths, and no significance is claimed.
7. **My predictions missed where the reader works from handed-over evidence.** They were right for no memory and for Hermes (whose behaviour was already known from 4 November), and wrong for naive retrieval on value twins and for every oracle cell on its mean (one repeat, O3 on correction twins, landed inside its range). In this run the scripted controls did not predict the live oracle row, which is why the declaration has it run live.
8. **The two optional rows add little to this table.** Holographic has no score: its attempt stopped at the run's cap on live reader calls, a budget I set up, which says nothing about its memory. OMEGA nets 0 on every kind, as no memory does; read after the table, its search brought the needed fact to the reader on all 15 quiz items but on only 11 of the 40 scored action tasks. It ran with its reranker off, so the row is not OMEGA as shipped.

## After the table: where the failures sit

Read from the run's outcome records after the table (the `template_ref`, `base_verdict`, `competing_present` and `stage` fields of each task's record; the `drift-quote` wording split also reads each task's quoted statement in the public pack, as [#506](https://github.com/electricsheephq/bicentennial/issues/506) describes), as counts only, with one note from reading the code; none of it is part of the declared reading, and it moves no flag. Each kind of task here is made by one or two templates.

- **Value twins are two templates of five pairs each.** On `drift-chain-fault-v1`, every row that saw any evidence (R, O and H, every repeat) scored all 10 tasks as a failed task, no credit. Under this template's decision table, the scorer gives a failed task when the reader changed the repository but left it matching neither the current value nor a retracted one. The no-memory row did nothing (an omission). So five of the ten value pairs earn no credit in any row. The run keeps neither request bodies nor the edited files, so why the change never matches is not measured; the repair has to measure it first. Reading the code after the table suggests one cause, still unmeasured: in these lives the reader edits the file with shell commands it writes itself, and the check accepts only an entry keyed by the bare milestone name, in a strict format, while the prompt names the entry with the word "deadline" after the name. A reader that writes the key as the prompt phrases it would score exactly this. [#505](https://github.com/electricsheephq/bicentennial/issues/505) has the code references; one run that keeps the edited file settles it.
- On `drift-quote-v1`, a competing value was in view on every task in every row with evidence. The oracle row asserted the wrong value on 7, 8 and 7 of the 10 tasks; naive retrieval on 7 in both repeats; Hermes on 3 in both runs. The failures follow the wording of the later statement, a quoted value written as firmly as the decision: the oracle row failed all 18 of its trials where it reads "It was said that … must be …", and 4 of 12 where it reads as a quote from a note.
- **Correction twins** (`drift-config-v1`): the oracle row failed only on the hedged twins, where the right action is to leave the setting alone: 3, 2 and 1 of those five tasks in its three repeats. It applied every correction (15 of 15). The outcome records mark the hedged twins as having a competing value in view, because both of that twin's options carry the hedged value. Hermes passed all ten.
- **Quiz:** the oracle row answered every "as of" Drift question and every value-recall question right. None of its count answers (`recall-count-v1`, five in each repeat) could be parsed, which the scorer counts as −1000, the same as a confident wrong answer; naive retrieval's three misses there are unparsed too. Hermes's count answers all parsed and were right.

So, beside the `drift-chain-fault` tasks that every row with evidence fails, the oracle row's failures sit on the quoted values of `drift-quote`, the hedged twins of `drift-config` and count answers it did not format as the scorer requires; it was right on every Wake task, every correction, and every value-recall and "as of" question. For each, the repair has to find out whether the fault is in the template, in how the evidence is handed over, in the answer format, or in the reader; [#506](https://github.com/electricsheephq/bicentennial/issues/506) has the code reading, and this run cannot settle it.

## What happens next

By DECLARATION §6, decided before the runs:

- **Value twins and correction twins (low):** `drift-chain-fault`, `drift-quote` and `drift-config` get new versions, after the mechanism above is measured. Each new version needs three oracle trials on fresh control-only lives and a frozen task list before any system runs on it. The work is tracked in [#505](https://github.com/electricsheephq/bicentennial/issues/505) (`drift-chain-fault`) and [#506](https://github.com/electricsheephq/bicentennial/issues/506) (`drift-quote` and `drift-config`).
- **Wake (candidate):** goes into the fresh-seed follow-up ([#394](https://github.com/electricsheephq/bicentennial/issues/394)) with every other kind, repaired versions included.
- No kind is promoted or dropped because of how Hermes or OMEGA scored on it; the follow-up carries every kind.
- **Optional rows:** the send budget that stopped Holographic is fixed before Holographic's or OMEGA's next run ([#507](https://github.com/electricsheephq/bicentennial/issues/507)), and OMEGA's reranker is staged before any OMEGA result is compared with another system's ([#289](https://github.com/electricsheephq/bicentennial/issues/289)). Neither run belongs to Milestone 1.

## What this does not prove

- Public lives, not fresh ones. One reader model at one effort. Five lives with scored actions.
- A scripted life: no system's own judgment about what to store is tested.
- One real system in the core table. Of the two optional rows, Holographic has no score, and OMEGA ran with its reranker and query expansion off.
- Whole arms in a mirrored order, not arms interleaved within each life as the board will run them; and equal served-model names do not prove equal service behaviour across the run's hours, or across its two days (the optional rows ran on 12 November).
- Where the control text is placed is a declared choice that can move the oracle row.
- The table lacks two rows a published board table must carry, and says so: the agent-key validation row (no auditor panel exists yet) and the full-history ceiling (the history fits the window for none of the pack's items, each tested at its own time).
- The flags are exploratory screening from control rows; a kind's flag is a reason to repair or validate it, not a finding about any system. The section after the table is a post-hoc reading of counts; the one cause it mentions comes from reading code and is not measured.

## Reproduce

`table.py` reads the run trees, the T2 pack, the output of check 3's tests at the run commit, and (as earlier evidence) the two 4 November runs. It prints counts, labels, pass/fail and 12-character hash prefixes only (the served identity among them, as a prefix): never task text, answers, item or bundle ids, or paths. From a checkout of this repository at `e4e0f69`, with the run trees and the check-3 output from the evidence tag:

```
PYTHONPATH=<checkout>/src python3 -s -P <checkout>/results/milestone-1/2026-11-11-separation-table/table.py --packs <packs> --check3 <check3 output> --order F1,R1,O1,H1,H2,O2,R2,F2,O3 --after-reruns F1=<run> R1=<run> O1=<run> H1=<run> H2=<run> O2=<run> R2=<run> F2=<run> O3=<run> X-holographic=<run> X-omega=<run> E1=<4 Nov run 1> E2=<4 Nov run 2>
```

Check 3's output is the three tests named in `table.py` (`CHECK3_TESTS`, in `tests/runner/test_control_arms.py`), run with `pytest -v` in a clean checkout at the run commit, between a first line `commit <sha>` and a last line `exit <code>`.

Its output, verbatim:

```
== 1. Header and identity
run order F1,R1,O1,H1,H2,O2,R2,F2,O3 | equals the declared order True | reruns named none | --after-reruns given True
run order verified
F1: tier T2 control no_memory model gpt-6.1-sol effort medium pack_hash 15141b194ab8 start 2026-11-11T16:39:52+00:00 end 2026-11-11T17:00:57+00:00 served_identity 6e0b2b52fc6f matches_core True identity changed during the run no
  pins {"benchmark_commit": "42aea53d0e30", "director_commit": "42aea53d0e30", "generator_commit": "42aea53d0e30", "harness_hash": "dbf03edef301", "route_table_hash": "0490592ab5b0", "scorer_commit": "42aea53d0e30", "system_hash": "dbf03edef301", "write_turn_package_hash": "cf5d8ed51482"}
R1: tier T2 control naive_rag model gpt-6.1-sol effort medium pack_hash 15141b194ab8 start 2026-11-11T17:00:59+00:00 end 2026-11-11T17:21:31+00:00 served_identity 6e0b2b52fc6f matches_core True identity changed during the run no
  pins {"benchmark_commit": "42aea53d0e30", "director_commit": "42aea53d0e30", "generator_commit": "42aea53d0e30", "harness_hash": "dbf03edef301", "route_table_hash": "0490592ab5b0", "scorer_commit": "42aea53d0e30", "system_hash": "dbf03edef301", "write_turn_package_hash": "cf5d8ed51482"}
O1: tier T2 control oracle_evidence model gpt-6.1-sol effort medium pack_hash 15141b194ab8 start 2026-11-11T17:21:34+00:00 end 2026-11-11T17:37:50+00:00 served_identity 6e0b2b52fc6f matches_core True identity changed during the run no
  pins {"benchmark_commit": "42aea53d0e30", "director_commit": "42aea53d0e30", "generator_commit": "42aea53d0e30", "harness_hash": "dbf03edef301", "route_table_hash": "0490592ab5b0", "scorer_commit": "42aea53d0e30", "system_hash": "dbf03edef301", "write_turn_package_hash": "cf5d8ed51482"}
H1: tier T2 system model gpt-6.1-sol effort medium pack_hash 15141b194ab8 start 2026-11-11T17:37:52+00:00 end 2026-11-11T19:03:16+00:00 served_identity 6e0b2b52fc6f matches_core True identity changed during the run no
  pins {"benchmark_commit": "42aea53d0e30", "director_commit": "42aea53d0e30", "generator_commit": "42aea53d0e30", "harness_hash": "dbf03edef301", "route_table_hash": "0490592ab5b0", "scorer_commit": "42aea53d0e30", "system_hash": "dbf03edef301", "write_turn_package_hash": "cf5d8ed51482"}
H2: tier T2 system model gpt-6.1-sol effort medium pack_hash 15141b194ab8 start 2026-11-11T19:03:27+00:00 end 2026-11-11T20:06:38+00:00 served_identity 6e0b2b52fc6f matches_core True identity changed during the run no
  pins {"benchmark_commit": "42aea53d0e30", "director_commit": "42aea53d0e30", "generator_commit": "42aea53d0e30", "harness_hash": "dbf03edef301", "route_table_hash": "0490592ab5b0", "scorer_commit": "42aea53d0e30", "system_hash": "dbf03edef301", "write_turn_package_hash": "cf5d8ed51482"}
O2: tier T2 control oracle_evidence model gpt-6.1-sol effort medium pack_hash 15141b194ab8 start 2026-11-11T20:06:41+00:00 end 2026-11-11T20:19:59+00:00 served_identity 6e0b2b52fc6f matches_core True identity changed during the run no
  pins {"benchmark_commit": "42aea53d0e30", "director_commit": "42aea53d0e30", "generator_commit": "42aea53d0e30", "harness_hash": "dbf03edef301", "route_table_hash": "0490592ab5b0", "scorer_commit": "42aea53d0e30", "system_hash": "dbf03edef301", "write_turn_package_hash": "cf5d8ed51482"}
R2: tier T2 control naive_rag model gpt-6.1-sol effort medium pack_hash 15141b194ab8 start 2026-11-11T20:20:01+00:00 end 2026-11-11T20:36:55+00:00 served_identity 6e0b2b52fc6f matches_core True identity changed during the run no
  pins {"benchmark_commit": "42aea53d0e30", "director_commit": "42aea53d0e30", "generator_commit": "42aea53d0e30", "harness_hash": "dbf03edef301", "route_table_hash": "0490592ab5b0", "scorer_commit": "42aea53d0e30", "system_hash": "dbf03edef301", "write_turn_package_hash": "cf5d8ed51482"}
F2: tier T2 control no_memory model gpt-6.1-sol effort medium pack_hash 15141b194ab8 start 2026-11-11T20:36:57+00:00 end 2026-11-11T20:50:00+00:00 served_identity 6e0b2b52fc6f matches_core True identity changed during the run no
  pins {"benchmark_commit": "42aea53d0e30", "director_commit": "42aea53d0e30", "generator_commit": "42aea53d0e30", "harness_hash": "dbf03edef301", "route_table_hash": "0490592ab5b0", "scorer_commit": "42aea53d0e30", "system_hash": "dbf03edef301", "write_turn_package_hash": "cf5d8ed51482"}
O3: tier T2 control oracle_evidence model gpt-6.1-sol effort medium pack_hash 15141b194ab8 start 2026-11-11T20:50:02+00:00 end 2026-11-11T20:59:22+00:00 served_identity 6e0b2b52fc6f matches_core True identity changed during the run no
  pins {"benchmark_commit": "42aea53d0e30", "director_commit": "42aea53d0e30", "generator_commit": "42aea53d0e30", "harness_hash": "dbf03edef301", "route_table_hash": "0490592ab5b0", "scorer_commit": "42aea53d0e30", "system_hash": "dbf03edef301", "write_turn_package_hash": "cf5d8ed51482"}
X-omega: tier T2 system model gpt-6.1-sol effort medium pack_hash 15141b194ab8 start 2026-11-12T18:19:53+00:00 end 2026-11-12T19:54:26+00:00 served_identity 6e0b2b52fc6f matches_core True identity changed during the run no
  pins {"benchmark_commit": "42aea53d0e30", "director_commit": "42aea53d0e30", "generator_commit": "42aea53d0e30", "harness_hash": "dbf03edef301", "route_table_hash": "4a328cfa9525", "scorer_commit": "42aea53d0e30", "system_hash": "cee7131d9fb3", "write_turn_package_hash": "cf5d8ed51482"}
every arm's served identity equal True
one commit for every core arm (card pins equal) True

== 2. Checks before any score (§2)
check 1 F1: arm True no blocks True pass True
check 1 F2: arm True no blocks True pass True
check 1 R1: arm matches label True frame_sha256 True blocks matched 85 of 85 mismatched 0 recorded but not recomputed 0 pass True
check 1 R2: arm matches label True frame_sha256 True blocks matched 85 of 85 mismatched 0 recorded but not recomputed 0 pass True
check 1 O1: arm matches label True frame_sha256 True blocks matched 85 of 85 mismatched 0 recorded but not recomputed 0 pass True
check 1 O2: arm matches label True frame_sha256 True blocks matched 85 of 85 mismatched 0 recorded but not recomputed 0 pass True
check 1 O3: arm matches label True frame_sha256 True blocks matched 85 of 85 mismatched 0 recorded but not recomputed 0 pass True
check 2 R1: presence in the probe turn's first request equals the pack's scripted naive report on 85 of 85 tasks pass True
check 2 R2: presence in the probe turn's first request equals the pack's scripted naive report on 85 of 85 tasks pass True
check 2 O1: needed fact in the probe turn's first request on 40 of 40 scored action tasks pass True
check 2 O2: needed fact in the probe turn's first request on 40 of 40 scored action tasks pass True
check 2 O3: needed fact in the probe turn's first request on 40 of 40 scored action tasks pass True
check 3 (F, R, O): memory block, search tool, answer key and option order in the block are not visible in run outputs (request bodies are not kept); the runner's own tests at the run commit 42aea53d0e30 (§11.7): file names commit 42aea53d0e30, ends with exit 0 True; test_c_floor_bodies_and_memory_off {'PASSED': 1}; test_a_block_is_the_pinned_controls_text_in_the_probe_turn[naive_rag] {'PASSED': 1}; test_a_block_is_the_pinned_controls_text_in_the_probe_turn[oracle_evidence] {'PASSED': 1}; pass True
check 4: see header (served identity, and whether it changed during the run); mismatched arms are not pooled: 0
check 5 F1: scored action tasks assigned 40 scored 40 BLOCKED 0 missing 0 complete True (scored = integer score_milli; missing = no outcome row)
check 5 R1: scored action tasks assigned 40 scored 40 BLOCKED 0 missing 0 complete True (scored = integer score_milli; missing = no outcome row)
check 5 O1: scored action tasks assigned 40 scored 40 BLOCKED 0 missing 0 complete True (scored = integer score_milli; missing = no outcome row)
check 5 H1: scored action tasks assigned 40 scored 40 BLOCKED 0 missing 0 complete True (scored = integer score_milli; missing = no outcome row)
check 5 H2: scored action tasks assigned 40 scored 40 BLOCKED 0 missing 0 complete True (scored = integer score_milli; missing = no outcome row)
check 5 O2: scored action tasks assigned 40 scored 40 BLOCKED 0 missing 0 complete True (scored = integer score_milli; missing = no outcome row)
check 5 R2: scored action tasks assigned 40 scored 40 BLOCKED 0 missing 0 complete True (scored = integer score_milli; missing = no outcome row)
check 5 F2: scored action tasks assigned 40 scored 40 BLOCKED 0 missing 0 complete True (scored = integer score_milli; missing = no outcome row)
check 5 O3: scored action tasks assigned 40 scored 40 BLOCKED 0 missing 0 complete True (scored = integer score_milli; missing = no outcome row)
check 5 X-omega: scored action tasks assigned 40 scored 40 BLOCKED 0 missing 0 complete True (scored = integer score_milli; missing = no outcome row)
check 7 F1: expected units 20 units listed 20 (card) 20 (disclosures) cached or unconfirmed 0 probe files found 20 probed items covered 85 of 85 probe records 85 sent to the live reader 85 (answered probes are counted by check 5) stopped units 0 (a unit's stop record is not exactly its own entry with no stop) pass True
check 7 F2: expected units 20 units listed 20 (card) 20 (disclosures) cached or unconfirmed 0 probe files found 20 probed items covered 85 of 85 probe records 85 sent to the live reader 85 (answered probes are counted by check 5) stopped units 0 (a unit's stop record is not exactly its own entry with no stop) pass True
check 7 R1: expected units 20 units listed 20 (card) 20 (disclosures) cached or unconfirmed 0 probe files found 20 probed items covered 85 of 85 probe records 85 sent to the live reader 85 (answered probes are counted by check 5) stopped units 0 (a unit's stop record is not exactly its own entry with no stop) pass True
check 7 R2: expected units 20 units listed 20 (card) 20 (disclosures) cached or unconfirmed 0 probe files found 20 probed items covered 85 of 85 probe records 85 sent to the live reader 85 (answered probes are counted by check 5) stopped units 0 (a unit's stop record is not exactly its own entry with no stop) pass True
check 7 O1: expected units 20 units listed 20 (card) 20 (disclosures) cached or unconfirmed 0 probe files found 20 probed items covered 85 of 85 probe records 85 sent to the live reader 85 (answered probes are counted by check 5) stopped units 0 (a unit's stop record is not exactly its own entry with no stop) pass True
check 7 O2: expected units 20 units listed 20 (card) 20 (disclosures) cached or unconfirmed 0 probe files found 20 probed items covered 85 of 85 probe records 85 sent to the live reader 85 (answered probes are counted by check 5) stopped units 0 (a unit's stop record is not exactly its own entry with no stop) pass True
check 7 O3: expected units 20 units listed 20 (card) 20 (disclosures) cached or unconfirmed 0 probe files found 20 probed items covered 85 of 85 probe records 85 sent to the live reader 85 (answered probes are counted by check 5) stopped units 0 (a unit's stop record is not exactly its own entry with no stop) pass True
check 6: pairs scored in every repeat of F, R and O used (common support for the flags): {'Drift, value twins': 10, 'Drift, correction twins': 5, 'Wake': 5} total 20

== 3. Scored action pairs by kind and life (pairs, right, wrong, no credit, non-result, net, points)
-- F1
  Drift, value twins: pairs 10 right 0 wrong 0 no_credit 10 non_result 0 net 0 points 0.0
  Drift, correction twins: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  Wake: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  life 1: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  life 2: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  life 3: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  life 4: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  life 5: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  pooled diagnostic (all 20): pairs 20 right 0 wrong 0 no_credit 20 non_result 0 net 0 points 0.0
-- F2
  Drift, value twins: pairs 10 right 0 wrong 0 no_credit 10 non_result 0 net 0 points 0.0
  Drift, correction twins: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  Wake: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  life 1: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  life 2: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  life 3: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  life 4: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  life 5: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  pooled diagnostic (all 20): pairs 20 right 0 wrong 0 no_credit 20 non_result 0 net 0 points 0.0
-- F mean of ['F1', 'F2']
  Drift, value twins: common pairs 10 right 0 (0.0) wrong 0 (0.0) no_credit 10 (10.0) points 0 (0.0) (common pairs = scored in every repeat used; counts are means over repeats)
  Drift, correction twins: common pairs 5 right 0 (0.0) wrong 0 (0.0) no_credit 5 (5.0) points 0 (0.0) (common pairs = scored in every repeat used; counts are means over repeats)
  Wake: common pairs 5 right 0 (0.0) wrong 0 (0.0) no_credit 5 (5.0) points 0 (0.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 1: common pairs 4 right 0 (0.0) wrong 0 (0.0) no_credit 4 (4.0) points 0 (0.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 2: common pairs 4 right 0 (0.0) wrong 0 (0.0) no_credit 4 (4.0) points 0 (0.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 3: common pairs 4 right 0 (0.0) wrong 0 (0.0) no_credit 4 (4.0) points 0 (0.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 4: common pairs 4 right 0 (0.0) wrong 0 (0.0) no_credit 4 (4.0) points 0 (0.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 5: common pairs 4 right 0 (0.0) wrong 0 (0.0) no_credit 4 (4.0) points 0 (0.0) (common pairs = scored in every repeat used; counts are means over repeats)
  pooled diagnostic (all 20): common pairs 20 right 0 (0.0) wrong 0 (0.0) no_credit 20 (20.0) points 0 (0.0) (common pairs = scored in every repeat used; counts are means over repeats)
-- R1
  Drift, value twins: pairs 10 right 1 wrong 4 no_credit 5 non_result 0 net -3 points -30.0
  Drift, correction twins: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  Wake: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  life 1: pairs 4 right 0 wrong 1 no_credit 3 non_result 0 net -1 points -25.0
  life 2: pairs 4 right 0 wrong 1 no_credit 3 non_result 0 net -1 points -25.0
  life 3: pairs 4 right 0 wrong 1 no_credit 3 non_result 0 net -1 points -25.0
  life 4: pairs 4 right 0 wrong 1 no_credit 3 non_result 0 net -1 points -25.0
  life 5: pairs 4 right 1 wrong 0 no_credit 3 non_result 0 net 1 points 25.0
  pooled diagnostic (all 20): pairs 20 right 1 wrong 4 no_credit 15 non_result 0 net -3 points -15.0
-- R2
  Drift, value twins: pairs 10 right 1 wrong 4 no_credit 5 non_result 0 net -3 points -30.0
  Drift, correction twins: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  Wake: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  life 1: pairs 4 right 0 wrong 1 no_credit 3 non_result 0 net -1 points -25.0
  life 2: pairs 4 right 0 wrong 1 no_credit 3 non_result 0 net -1 points -25.0
  life 3: pairs 4 right 0 wrong 1 no_credit 3 non_result 0 net -1 points -25.0
  life 4: pairs 4 right 0 wrong 1 no_credit 3 non_result 0 net -1 points -25.0
  life 5: pairs 4 right 1 wrong 0 no_credit 3 non_result 0 net 1 points 25.0
  pooled diagnostic (all 20): pairs 20 right 1 wrong 4 no_credit 15 non_result 0 net -3 points -15.0
-- R mean of ['R1', 'R2']
  Drift, value twins: common pairs 10 right 1 (1.0) wrong 4 (4.0) no_credit 5 (5.0) points -30 (-30.0) (common pairs = scored in every repeat used; counts are means over repeats)
  Drift, correction twins: common pairs 5 right 0 (0.0) wrong 0 (0.0) no_credit 5 (5.0) points 0 (0.0) (common pairs = scored in every repeat used; counts are means over repeats)
  Wake: common pairs 5 right 0 (0.0) wrong 0 (0.0) no_credit 5 (5.0) points 0 (0.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 1: common pairs 4 right 0 (0.0) wrong 1 (1.0) no_credit 3 (3.0) points -25 (-25.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 2: common pairs 4 right 0 (0.0) wrong 1 (1.0) no_credit 3 (3.0) points -25 (-25.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 3: common pairs 4 right 0 (0.0) wrong 1 (1.0) no_credit 3 (3.0) points -25 (-25.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 4: common pairs 4 right 0 (0.0) wrong 1 (1.0) no_credit 3 (3.0) points -25 (-25.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 5: common pairs 4 right 1 (1.0) wrong 0 (0.0) no_credit 3 (3.0) points 25 (25.0) (common pairs = scored in every repeat used; counts are means over repeats)
  pooled diagnostic (all 20): common pairs 20 right 1 (1.0) wrong 4 (4.0) no_credit 15 (15.0) points -15 (-15.0) (common pairs = scored in every repeat used; counts are means over repeats)
-- O1
  Drift, value twins: pairs 10 right 1 wrong 4 no_credit 5 non_result 0 net -3 points -30.0
  Drift, correction twins: pairs 5 right 2 wrong 3 no_credit 0 non_result 0 net -1 points -20.0
  Wake: pairs 5 right 5 wrong 0 no_credit 0 non_result 0 net 5 points 100.0
  life 1: pairs 4 right 1 wrong 2 no_credit 1 non_result 0 net -1 points -25.0
  life 2: pairs 4 right 1 wrong 2 no_credit 1 non_result 0 net -1 points -25.0
  life 3: pairs 4 right 2 wrong 1 no_credit 1 non_result 0 net 1 points 25.0
  life 4: pairs 4 right 2 wrong 1 no_credit 1 non_result 0 net 1 points 25.0
  life 5: pairs 4 right 2 wrong 1 no_credit 1 non_result 0 net 1 points 25.0
  pooled diagnostic (all 20): pairs 20 right 8 wrong 7 no_credit 5 non_result 0 net 1 points 5.0
-- O2
  Drift, value twins: pairs 10 right 1 wrong 4 no_credit 5 non_result 0 net -3 points -30.0
  Drift, correction twins: pairs 5 right 3 wrong 2 no_credit 0 non_result 0 net 1 points 20.0
  Wake: pairs 5 right 5 wrong 0 no_credit 0 non_result 0 net 5 points 100.0
  life 1: pairs 4 right 2 wrong 1 no_credit 1 non_result 0 net 1 points 25.0
  life 2: pairs 4 right 1 wrong 2 no_credit 1 non_result 0 net -1 points -25.0
  life 3: pairs 4 right 2 wrong 1 no_credit 1 non_result 0 net 1 points 25.0
  life 4: pairs 4 right 2 wrong 1 no_credit 1 non_result 0 net 1 points 25.0
  life 5: pairs 4 right 2 wrong 1 no_credit 1 non_result 0 net 1 points 25.0
  pooled diagnostic (all 20): pairs 20 right 9 wrong 6 no_credit 5 non_result 0 net 3 points 15.0
-- O3
  Drift, value twins: pairs 10 right 1 wrong 4 no_credit 5 non_result 0 net -3 points -30.0
  Drift, correction twins: pairs 5 right 4 wrong 1 no_credit 0 non_result 0 net 3 points 60.0
  Wake: pairs 5 right 5 wrong 0 no_credit 0 non_result 0 net 5 points 100.0
  life 1: pairs 4 right 2 wrong 1 no_credit 1 non_result 0 net 1 points 25.0
  life 2: pairs 4 right 2 wrong 1 no_credit 1 non_result 0 net 1 points 25.0
  life 3: pairs 4 right 2 wrong 1 no_credit 1 non_result 0 net 1 points 25.0
  life 4: pairs 4 right 2 wrong 1 no_credit 1 non_result 0 net 1 points 25.0
  life 5: pairs 4 right 2 wrong 1 no_credit 1 non_result 0 net 1 points 25.0
  pooled diagnostic (all 20): pairs 20 right 10 wrong 5 no_credit 5 non_result 0 net 5 points 25.0
-- O mean of ['O1', 'O2', 'O3']
  Drift, value twins: common pairs 10 right 1 (1.0) wrong 4 (4.0) no_credit 5 (5.0) points -30 (-30.0) (common pairs = scored in every repeat used; counts are means over repeats)
  Drift, correction twins: common pairs 5 right 3 (3.0) wrong 2 (2.0) no_credit 0 (0.0) points 20 (20.0) (common pairs = scored in every repeat used; counts are means over repeats)
  Wake: common pairs 5 right 5 (5.0) wrong 0 (0.0) no_credit 0 (0.0) points 100 (100.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 1: common pairs 4 right 5/3 (1.7) wrong 4/3 (1.3) no_credit 1 (1.0) points 25/3 (8.3) (common pairs = scored in every repeat used; counts are means over repeats)
  life 2: common pairs 4 right 4/3 (1.3) wrong 5/3 (1.7) no_credit 1 (1.0) points -25/3 (-8.3) (common pairs = scored in every repeat used; counts are means over repeats)
  life 3: common pairs 4 right 2 (2.0) wrong 1 (1.0) no_credit 1 (1.0) points 25 (25.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 4: common pairs 4 right 2 (2.0) wrong 1 (1.0) no_credit 1 (1.0) points 25 (25.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 5: common pairs 4 right 2 (2.0) wrong 1 (1.0) no_credit 1 (1.0) points 25 (25.0) (common pairs = scored in every repeat used; counts are means over repeats)
  pooled diagnostic (all 20): common pairs 20 right 9 (9.0) wrong 6 (6.0) no_credit 5 (5.0) points 15 (15.0) (common pairs = scored in every repeat used; counts are means over repeats)
-- H1
  Drift, value twins: pairs 10 right 2 wrong 3 no_credit 5 non_result 0 net -1 points -10.0
  Drift, correction twins: pairs 5 right 5 wrong 0 no_credit 0 non_result 0 net 5 points 100.0
  Wake: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  life 1: pairs 4 right 1 wrong 1 no_credit 2 non_result 0 net 0 points 0.0
  life 2: pairs 4 right 2 wrong 0 no_credit 2 non_result 0 net 2 points 50.0
  life 3: pairs 4 right 1 wrong 1 no_credit 2 non_result 0 net 0 points 0.0
  life 4: pairs 4 right 1 wrong 1 no_credit 2 non_result 0 net 0 points 0.0
  life 5: pairs 4 right 2 wrong 0 no_credit 2 non_result 0 net 2 points 50.0
  pooled diagnostic (all 20): pairs 20 right 7 wrong 3 no_credit 10 non_result 0 net 4 points 20.0
-- H2
  Drift, value twins: pairs 10 right 2 wrong 3 no_credit 5 non_result 0 net -1 points -10.0
  Drift, correction twins: pairs 5 right 5 wrong 0 no_credit 0 non_result 0 net 5 points 100.0
  Wake: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  life 1: pairs 4 right 1 wrong 1 no_credit 2 non_result 0 net 0 points 0.0
  life 2: pairs 4 right 2 wrong 0 no_credit 2 non_result 0 net 2 points 50.0
  life 3: pairs 4 right 1 wrong 1 no_credit 2 non_result 0 net 0 points 0.0
  life 4: pairs 4 right 1 wrong 1 no_credit 2 non_result 0 net 0 points 0.0
  life 5: pairs 4 right 2 wrong 0 no_credit 2 non_result 0 net 2 points 50.0
  pooled diagnostic (all 20): pairs 20 right 7 wrong 3 no_credit 10 non_result 0 net 4 points 20.0
-- H mean of ['H1', 'H2']
  Drift, value twins: common pairs 10 right 2 (2.0) wrong 3 (3.0) no_credit 5 (5.0) points -10 (-10.0) (common pairs = scored in every repeat used; counts are means over repeats)
  Drift, correction twins: common pairs 5 right 5 (5.0) wrong 0 (0.0) no_credit 0 (0.0) points 100 (100.0) (common pairs = scored in every repeat used; counts are means over repeats)
  Wake: common pairs 5 right 0 (0.0) wrong 0 (0.0) no_credit 5 (5.0) points 0 (0.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 1: common pairs 4 right 1 (1.0) wrong 1 (1.0) no_credit 2 (2.0) points 0 (0.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 2: common pairs 4 right 2 (2.0) wrong 0 (0.0) no_credit 2 (2.0) points 50 (50.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 3: common pairs 4 right 1 (1.0) wrong 1 (1.0) no_credit 2 (2.0) points 0 (0.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 4: common pairs 4 right 1 (1.0) wrong 1 (1.0) no_credit 2 (2.0) points 0 (0.0) (common pairs = scored in every repeat used; counts are means over repeats)
  life 5: common pairs 4 right 2 (2.0) wrong 0 (0.0) no_credit 2 (2.0) points 50 (50.0) (common pairs = scored in every repeat used; counts are means over repeats)
  pooled diagnostic (all 20): common pairs 20 right 7 (7.0) wrong 3 (3.0) no_credit 10 (10.0) points 20 (20.0) (common pairs = scored in every repeat used; counts are means over repeats)

== 3x. Optional rows (one attempt each; shown separately, never pooled)
-- X-omega
  Drift, value twins: pairs 10 right 0 wrong 0 no_credit 10 non_result 0 net 0 points 0.0
  Drift, correction twins: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  Wake: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  life 1: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  life 2: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  life 3: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  life 4: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  life 5: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  pooled diagnostic (all 20): pairs 20 right 0 wrong 0 no_credit 20 non_result 0 net 0 points 0.0
X-holographic: attempt failed, refusal code spend_stop

== 3e. Extra floor
-- extra floor (H1's no-memory floor, measured live on 20 of 20 units, stopped or not recorded on 0, taken from a cache or unconfirmed on 0; enters no mean, flag or comparison)
  Drift, value twins: pairs 10 right 0 wrong 0 no_credit 10 non_result 0 net 0 points 0.0
  Drift, correction twins: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  Wake: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  life 1: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  life 2: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  life 3: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  life 4: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  life 5: pairs 4 right 0 wrong 0 no_credit 4 non_result 0 net 0 points 0.0
  pooled diagnostic (all 20): pairs 20 right 0 wrong 0 no_credit 20 non_result 0 net 0 points 0.0

== 4. Single tasks in scored action pairs, quiz items, agreement between repeats
-- F1
  Drift, value twins: tasks 20 right 0 wrong 0 no_credit 20 non_result 0 (no integer score_milli, or no row) base_verdict {'FAIL_TASK': 4, 'OMISSION': 16} failure_class {'FAIL_TASK': 4, 'None': 16}
  Drift, correction twins: tasks 10 right 5 wrong 0 no_credit 5 non_result 0 (no integer score_milli, or no row) base_verdict {'OMISSION': 5, 'PASS': 5} failure_class {'None': 10}
  Wake: tasks 10 right 0 wrong 0 no_credit 10 non_result 0 (no integer score_milli, or no row) base_verdict {'OMISSION': 10} failure_class {'None': 10}
  quiz items 15 by cell: +1000, 0, -1000, other, net
    DRIFT-ASOF: 0 5 0 0 net 0
    RECALL-AGG: 0 5 0 0 net 0
    RECALL-VERB: 0 5 0 0 net 0
-- R1
  Drift, value twins: tasks 20 right 3 wrong 7 no_credit 10 non_result 0 (no integer score_milli, or no row) base_verdict {'FAIL_MEMORY': 7, 'FAIL_TASK': 10, 'PASS': 3} failure_class {'FAIL_TASK': 10, 'None': 10}
  Drift, correction twins: tasks 10 right 5 wrong 0 no_credit 5 non_result 0 (no integer score_milli, or no row) base_verdict {'OMISSION': 5, 'PASS': 5} failure_class {'None': 10}
  Wake: tasks 10 right 0 wrong 0 no_credit 10 non_result 0 (no integer score_milli, or no row) base_verdict {'OMISSION': 10} failure_class {'None': 10}
  quiz items 15 by cell: +1000, 0, -1000, other, net
    DRIFT-ASOF: 1 0 4 0 net -3
    RECALL-AGG: 2 0 3 0 net -1
    RECALL-VERB: 5 0 0 0 net 5
-- O1
  Drift, value twins: tasks 20 right 3 wrong 7 no_credit 10 non_result 0 (no integer score_milli, or no row) base_verdict {'FAIL_MEMORY': 7, 'FAIL_TASK': 10, 'PASS': 3} failure_class {'FAIL_TASK': 10, 'None': 10}
  Drift, correction twins: tasks 10 right 7 wrong 3 no_credit 0 non_result 0 (no integer score_milli, or no row) base_verdict {'FAIL_MEMORY': 3, 'PASS': 7} failure_class {'None': 10}
  Wake: tasks 10 right 10 wrong 0 no_credit 0 non_result 0 (no integer score_milli, or no row) base_verdict {'PASS': 10} failure_class {'None': 10}
  quiz items 15 by cell: +1000, 0, -1000, other, net
    DRIFT-ASOF: 5 0 0 0 net 5
    RECALL-AGG: 0 0 5 0 net -5
    RECALL-VERB: 5 0 0 0 net 5
-- H1
  Drift, value twins: tasks 20 right 7 wrong 3 no_credit 10 non_result 0 (no integer score_milli, or no row) base_verdict {'FAIL_MEMORY': 3, 'FAIL_TASK': 10, 'PASS': 7} failure_class {'FAIL_TASK': 10, 'None': 10}
  Drift, correction twins: tasks 10 right 10 wrong 0 no_credit 0 non_result 0 (no integer score_milli, or no row) base_verdict {'PASS': 10} failure_class {'None': 10}
  Wake: tasks 10 right 1 wrong 0 no_credit 9 non_result 0 (no integer score_milli, or no row) base_verdict {'FAIL_TASK': 5, 'OMISSION': 4, 'PASS': 1} failure_class {'FAIL_TASK': 5, 'None': 5}
  quiz items 15 by cell: +1000, 0, -1000, other, net
    DRIFT-ASOF: 1 0 4 0 net -3
    RECALL-AGG: 5 0 0 0 net 5
    RECALL-VERB: 5 0 0 0 net 5
-- H2
  Drift, value twins: tasks 20 right 7 wrong 3 no_credit 10 non_result 0 (no integer score_milli, or no row) base_verdict {'FAIL_MEMORY': 3, 'FAIL_TASK': 10, 'PASS': 7} failure_class {'FAIL_TASK': 10, 'None': 10}
  Drift, correction twins: tasks 10 right 10 wrong 0 no_credit 0 non_result 0 (no integer score_milli, or no row) base_verdict {'PASS': 10} failure_class {'None': 10}
  Wake: tasks 10 right 0 wrong 0 no_credit 10 non_result 0 (no integer score_milli, or no row) base_verdict {'FAIL_TASK': 5, 'OMISSION': 5} failure_class {'FAIL_TASK': 5, 'None': 5}
  quiz items 15 by cell: +1000, 0, -1000, other, net
    DRIFT-ASOF: 2 0 3 0 net -1
    RECALL-AGG: 5 0 0 0 net 5
    RECALL-VERB: 5 0 0 0 net 5
-- O2
  Drift, value twins: tasks 20 right 2 wrong 8 no_credit 10 non_result 0 (no integer score_milli, or no row) base_verdict {'FAIL_MEMORY': 8, 'FAIL_TASK': 10, 'PASS': 2} failure_class {'FAIL_TASK': 10, 'None': 10}
  Drift, correction twins: tasks 10 right 8 wrong 2 no_credit 0 non_result 0 (no integer score_milli, or no row) base_verdict {'FAIL_MEMORY': 2, 'PASS': 8} failure_class {'None': 10}
  Wake: tasks 10 right 10 wrong 0 no_credit 0 non_result 0 (no integer score_milli, or no row) base_verdict {'PASS': 10} failure_class {'None': 10}
  quiz items 15 by cell: +1000, 0, -1000, other, net
    DRIFT-ASOF: 5 0 0 0 net 5
    RECALL-AGG: 0 0 5 0 net -5
    RECALL-VERB: 5 0 0 0 net 5
-- R2
  Drift, value twins: tasks 20 right 3 wrong 7 no_credit 10 non_result 0 (no integer score_milli, or no row) base_verdict {'FAIL_MEMORY': 7, 'FAIL_TASK': 10, 'PASS': 3} failure_class {'FAIL_TASK': 10, 'None': 10}
  Drift, correction twins: tasks 10 right 5 wrong 0 no_credit 5 non_result 0 (no integer score_milli, or no row) base_verdict {'OMISSION': 5, 'PASS': 5} failure_class {'None': 10}
  Wake: tasks 10 right 0 wrong 0 no_credit 10 non_result 0 (no integer score_milli, or no row) base_verdict {'OMISSION': 10} failure_class {'None': 10}
  quiz items 15 by cell: +1000, 0, -1000, other, net
    DRIFT-ASOF: 1 0 4 0 net -3
    RECALL-AGG: 2 0 3 0 net -1
    RECALL-VERB: 5 0 0 0 net 5
-- F2
  Drift, value twins: tasks 20 right 0 wrong 0 no_credit 20 non_result 0 (no integer score_milli, or no row) base_verdict {'FAIL_TASK': 4, 'OMISSION': 16} failure_class {'FAIL_TASK': 4, 'None': 16}
  Drift, correction twins: tasks 10 right 5 wrong 0 no_credit 5 non_result 0 (no integer score_milli, or no row) base_verdict {'OMISSION': 5, 'PASS': 5} failure_class {'None': 10}
  Wake: tasks 10 right 0 wrong 0 no_credit 10 non_result 0 (no integer score_milli, or no row) base_verdict {'OMISSION': 10} failure_class {'None': 10}
  quiz items 15 by cell: +1000, 0, -1000, other, net
    DRIFT-ASOF: 0 5 0 0 net 0
    RECALL-AGG: 0 5 0 0 net 0
    RECALL-VERB: 0 5 0 0 net 0
-- O3
  Drift, value twins: tasks 20 right 3 wrong 7 no_credit 10 non_result 0 (no integer score_milli, or no row) base_verdict {'FAIL_MEMORY': 7, 'FAIL_TASK': 10, 'PASS': 3} failure_class {'FAIL_TASK': 10, 'None': 10}
  Drift, correction twins: tasks 10 right 9 wrong 1 no_credit 0 non_result 0 (no integer score_milli, or no row) base_verdict {'FAIL_MEMORY': 1, 'PASS': 9} failure_class {'None': 10}
  Wake: tasks 10 right 10 wrong 0 no_credit 0 non_result 0 (no integer score_milli, or no row) base_verdict {'PASS': 10} failure_class {'None': 10}
  quiz items 15 by cell: +1000, 0, -1000, other, net
    DRIFT-ASOF: 5 0 0 0 net 5
    RECALL-AGG: 0 0 5 0 net -5
    RECALL-VERB: 5 0 0 0 net 5
-- X-omega
  Drift, value twins: tasks 20 right 0 wrong 0 no_credit 20 non_result 0 (no integer score_milli, or no row) base_verdict {'FAIL_TASK': 15, 'OMISSION': 5} failure_class {'FAIL_TASK': 15, 'None': 5}
  Drift, correction twins: tasks 10 right 5 wrong 0 no_credit 5 non_result 0 (no integer score_milli, or no row) base_verdict {'OMISSION': 5, 'PASS': 5} failure_class {'None': 10}
  Wake: tasks 10 right 0 wrong 0 no_credit 10 non_result 0 (no integer score_milli, or no row) base_verdict {'OMISSION': 10} failure_class {'None': 10}
  quiz items 15 by cell: +1000, 0, -1000, other, net
    DRIFT-ASOF: 2 0 3 0 net -1
    RECALL-AGG: 5 0 0 0 net 5
    RECALL-VERB: 5 0 0 0 net 5
-- extra floor (H1's no-memory floor, measured live on 20 of 20 units, stopped or not recorded on 0, taken from a cache or unconfirmed on 0; enters no mean, flag or comparison)
  Drift, value twins: tasks 20 right 0 wrong 0 no_credit 20 non_result 0 (no integer score_milli, or no row) base_verdict {'FAIL_TASK': 5, 'OMISSION': 15} failure_class {'FAIL_TASK': 5, 'None': 15}
  Drift, correction twins: tasks 10 right 5 wrong 0 no_credit 5 non_result 0 (no integer score_milli, or no row) base_verdict {'OMISSION': 5, 'PASS': 5} failure_class {'None': 10}
  Wake: tasks 10 right 0 wrong 0 no_credit 10 non_result 0 (no integer score_milli, or no row) base_verdict {'OMISSION': 10} failure_class {'None': 10}
  quiz items 15 by cell: +1000, 0, -1000, other, net
    DRIFT-ASOF: 0 5 0 0 net 0
    RECALL-AGG: 0 5 0 0 net 0
    RECALL-VERB: 0 5 0 0 net 0
-- F1 vs F2: scored pairs with equal score 20 of 20 scored in both; keys only in one 0
   task scores that differ (score_milli differs; tasks scored in either) 0 {}
   tasks whose score or failure class differs ((score_milli, failure_class) differs; tasks scored in either) 2 {'DRIFT-CUR': 2}
-- R1 vs R2: scored pairs with equal score 20 of 20 scored in both; keys only in one 0
   task scores that differ (score_milli differs; tasks scored in either) 2 {'DRIFT-CUR': 2}
   tasks whose score or failure class differs ((score_milli, failure_class) differs; tasks scored in either) 2 {'DRIFT-CUR': 2}
-- O1 vs O2: scored pairs with equal score 19 of 20 scored in both; keys only in one 0
   task scores that differ (score_milli differs; tasks scored in either) 2 {'DRIFT-CUR': 2}
   tasks whose score or failure class differs ((score_milli, failure_class) differs; tasks scored in either) 2 {'DRIFT-CUR': 2}
-- O1 vs O3: scored pairs with equal score 18 of 20 scored in both; keys only in one 0
   task scores that differ (score_milli differs; tasks scored in either) 4 {'DRIFT-CUR': 4}
   tasks whose score or failure class differs ((score_milli, failure_class) differs; tasks scored in either) 4 {'DRIFT-CUR': 4}
-- O2 vs O3: scored pairs with equal score 19 of 20 scored in both; keys only in one 0
   task scores that differ (score_milli differs; tasks scored in either) 2 {'DRIFT-CUR': 2}
   tasks whose score or failure class differs ((score_milli, failure_class) differs; tasks scored in either) 2 {'DRIFT-CUR': 2}
-- H1 vs H2: scored pairs with equal score 20 of 20 scored in both; keys only in one 0
   task scores that differ (score_milli differs; tasks scored in either) 2 {'DRIFT-ASOF': 1, 'WAKE-LOOP': 1}
   tasks whose score or failure class differs ((score_milli, failure_class) differs; tasks scored in either) 3 {'DRIFT-ASOF': 1, 'WAKE-LOOP': 2}

== 5. Screening flags from control rows (§4): f, r = means of F1,F2 and R1,R2; c = mean of O1,O2; exact points on each kind's common support
-- Drift, value twins: common pairs 10 f 0 (0.0) r -30 (-30.0) c -30 (-30.0) c over O1,O2,O3 -30 (-30.0)
  low: on means applies margin_pairs 21/2 (10.5) combinations 3 agreeing on whether it applies 3 status applies
  naive: on means not interpreted margin_pairs -9/10 (-0.9) combinations 12 agreeing on whether it applies 12 status does not apply
  floor: on means not interpreted margin_pairs 21/10 (2.1) combinations 6 agreeing on whether it applies 6 status does not apply
  classification: low
-- Drift, correction twins: common pairs 5 f 0 (0.0) r 0 (0.0) c 0 (0.0) c over O1,O2,O3 20 (20.0)
  low: on means applies margin_pairs 15/4 (3.8) combinations 3 agreeing on whether it applies 3 status applies
  naive: on means not interpreted margin_pairs 0 (0.0) combinations 12 agreeing on whether it applies 12 status does not apply
  floor: on means not interpreted margin_pairs 0 (0.0) combinations 6 agreeing on whether it applies 6 status does not apply
  classification: low
-- Wake: common pairs 5 f 0 (0.0) r 0 (0.0) c 100 (100.0) c over O1,O2,O3 100 (100.0)
  low: on means no margin_pairs -5/4 (-1.2) combinations 3 agreeing on whether it applies 3 status does not apply
  naive: on means no margin_pairs -7/2 (-3.5) combinations 12 agreeing on whether it applies 12 status does not apply
  floor: on means no margin_pairs -7/2 (-3.5) combinations 6 agreeing on whether it applies 6 status does not apply
  classification: candidate
flags: low c < 75; naive (near-solved by naive retrieval) r >= f + 0.7 (c - f); floor (near-solved without memory) f >= 0.7 c; near-solved flags not interpreted when c <= f or c <= 0. Margin in pairs = (left - right) x pairs / 100, low as 75 - c; it applies when the margin is > 0 (low) or >= 0. Combinations: one repeat per row used (naive F x R x O, floor F x O, low O); a flag is unstable when whether it applies differs between the means and any combination; not interpreted counts as not applying (disclosure only).

== 6. Prospective filter yield; validates nothing (each twin right with only its evidence in >= 2 of 3 O trials)
  Drift, value twins: pairs 10 pass 1 fail 9 unresolved 0 (twin: pass when right in >= 2 trials, fail when right + unknown < 2; pair: pass when both twins pass, fail when either fails) twins by (passes, unknown) {(0, 0): 16, (1, 0): 2, (3, 0): 2}
  Drift, correction twins: pairs 5 pass 3 fail 2 unresolved 0 (twin: pass when right in >= 2 trials, fail when right + unknown < 2; pair: pass when both twins pass, fail when either fails) twins by (passes, unknown) {(0, 0): 1, (1, 0): 1, (2, 0): 1, (3, 0): 7}
  Wake: pairs 5 pass 5 fail 0 unresolved 0 (twin: pass when right in >= 2 trials, fail when right + unknown < 2; pair: pass when both twins pass, fail when either fails) twins by (passes, unknown) {(3, 0): 10}

== 7. Real systems against the control rows (§5); no significance claimed
  H Drift, value twins: H points -10 (-10.0) on its own 10 scored pairs; against F 0 (0.0), H -10 (-10.0), H minus F -10 (-10.0) on 10 pairs; R -30 (-30.0), H -10 (-10.0), H minus R 20 (20.0) on 10 pairs; O -30 (-30.0), H -10 (-10.0), H minus O 20 (20.0) on 10 pairs (each comparison on the pairs scored in every repeat of both rows)
    H minus F, Drift, value twins, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['-500', '500', '-500', '-500', '500'] exact two-sided sign_flip_p 1 1.0000 no significance claimed
    H minus R, Drift, value twins, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['0', '1000', '0', '0', '0'] exact two-sided sign_flip_p 1 1.0000 no significance claimed
    H minus O, Drift, value twins, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['0', '1000', '0', '0', '0'] exact two-sided sign_flip_p 1 1.0000 no significance claimed
  H Drift, correction twins: H points 100 (100.0) on its own 5 scored pairs; against F 0 (0.0), H 100 (100.0), H minus F 100 (100.0) on 5 pairs; R 0 (0.0), H 100 (100.0), H minus R 100 (100.0) on 5 pairs; O 0 (0.0), H 100 (100.0), H minus O 100 (100.0) on 5 pairs (each comparison on the pairs scored in every repeat of both rows)
    H minus F, Drift, correction twins, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['1000', '1000', '1000', '1000', '1000'] exact two-sided sign_flip_p 1/16 0.0625 no significance claimed
    H minus R, Drift, correction twins, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['1000', '1000', '1000', '1000', '1000'] exact two-sided sign_flip_p 1/16 0.0625 no significance claimed
    H minus O, Drift, correction twins, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['1000', '2000', '0', '0', '2000'] exact two-sided sign_flip_p 1/4 0.2500 no significance claimed
  H Wake: H points 0 (0.0) on its own 5 scored pairs; against F 0 (0.0), H 0 (0.0), H minus F 0 (0.0) on 5 pairs; R 0 (0.0), H 0 (0.0), H minus R 0 (0.0) on 5 pairs; O 100 (100.0), H 0 (0.0), H minus O -100 (-100.0) on 5 pairs (each comparison on the pairs scored in every repeat of both rows)
    H minus F, Wake, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['0', '0', '0', '0', '0'] exact two-sided sign_flip_p 1 1.0000 no significance claimed
    H minus R, Wake, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['0', '0', '0', '0', '0'] exact two-sided sign_flip_p 1 1.0000 no significance claimed
    H minus O, Wake, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['-1000', '-1000', '-1000', '-1000', '-1000'] exact two-sided sign_flip_p 1/16 0.0625 no significance claimed
  H pooled diagnostic: H points 20 (20.0) on its own 20 scored pairs; against F 0 (0.0), H 20 (20.0), H minus F 20 (20.0) on 20 pairs; R -15 (-15.0), H 20 (20.0), H minus R 35 (35.0) on 20 pairs; O 10 (10.0), H 20 (20.0), H minus O 10 (10.0) on 20 pairs (each comparison on the pairs scored in every repeat of both rows)
    H minus F, pooled diagnostic, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['0', '500', '0', '0', '500'] exact two-sided sign_flip_p 1/2 0.5000 no significance claimed
    H minus R, pooled diagnostic, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['250', '750', '250', '250', '250'] exact two-sided sign_flip_p 1/16 0.0625 no significance claimed
    H minus O, pooled diagnostic, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['0', '750', '-250', '-250', '250'] exact two-sided sign_flip_p 7/8 0.8750 no significance claimed
    H minus F, pooled diagnostic, per life (tasks, milli; tasks scored in every repeat of both rows; 0 lives left out with none): ['125', '375', '375/2', '125', '375'] exact two-sided sign_flip_p 1/16 0.0625 no significance claimed
  X-omega Drift, value twins: X-omega points 0 (0.0) on its own 10 scored pairs; against F 0 (0.0), X-omega 0 (0.0), X-omega minus F 0 (0.0) on 10 pairs; R -30 (-30.0), X-omega 0 (0.0), X-omega minus R 30 (30.0) on 10 pairs; O -30 (-30.0), X-omega 0 (0.0), X-omega minus O 30 (30.0) on 10 pairs (each comparison on the pairs scored in every repeat of both rows)
    X-omega minus F, Drift, value twins, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['0', '0', '0', '0', '0'] exact two-sided sign_flip_p 1 1.0000 no significance claimed
    X-omega minus R, Drift, value twins, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['500', '500', '500', '500', '-500'] exact two-sided sign_flip_p 3/8 0.3750 no significance claimed
    X-omega minus O, Drift, value twins, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['500', '500', '500', '500', '-500'] exact two-sided sign_flip_p 3/8 0.3750 no significance claimed
  X-omega Drift, correction twins: X-omega points 0 (0.0) on its own 5 scored pairs; against F 0 (0.0), X-omega 0 (0.0), X-omega minus F 0 (0.0) on 5 pairs; R 0 (0.0), X-omega 0 (0.0), X-omega minus R 0 (0.0) on 5 pairs; O 0 (0.0), X-omega 0 (0.0), X-omega minus O 0 (0.0) on 5 pairs (each comparison on the pairs scored in every repeat of both rows)
    X-omega minus F, Drift, correction twins, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['0', '0', '0', '0', '0'] exact two-sided sign_flip_p 1 1.0000 no significance claimed
    X-omega minus R, Drift, correction twins, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['0', '0', '0', '0', '0'] exact two-sided sign_flip_p 1 1.0000 no significance claimed
    X-omega minus O, Drift, correction twins, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['0', '1000', '-1000', '-1000', '1000'] exact two-sided sign_flip_p 1 1.0000 no significance claimed
  X-omega Wake: X-omega points 0 (0.0) on its own 5 scored pairs; against F 0 (0.0), X-omega 0 (0.0), X-omega minus F 0 (0.0) on 5 pairs; R 0 (0.0), X-omega 0 (0.0), X-omega minus R 0 (0.0) on 5 pairs; O 100 (100.0), X-omega 0 (0.0), X-omega minus O -100 (-100.0) on 5 pairs (each comparison on the pairs scored in every repeat of both rows)
    X-omega minus F, Wake, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['0', '0', '0', '0', '0'] exact two-sided sign_flip_p 1 1.0000 no significance claimed
    X-omega minus R, Wake, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['0', '0', '0', '0', '0'] exact two-sided sign_flip_p 1 1.0000 no significance claimed
    X-omega minus O, Wake, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['-1000', '-1000', '-1000', '-1000', '-1000'] exact two-sided sign_flip_p 1/16 0.0625 no significance claimed
  X-omega pooled diagnostic: X-omega points 0 (0.0) on its own 20 scored pairs; against F 0 (0.0), X-omega 0 (0.0), X-omega minus F 0 (0.0) on 20 pairs; R -15 (-15.0), X-omega 0 (0.0), X-omega minus R 15 (15.0) on 20 pairs; O 10 (10.0), X-omega 0 (0.0), X-omega minus O -10 (-10.0) on 20 pairs (each comparison on the pairs scored in every repeat of both rows)
    X-omega minus F, pooled diagnostic, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['0', '0', '0', '0', '0'] exact two-sided sign_flip_p 1 1.0000 no significance claimed
    X-omega minus R, pooled diagnostic, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['250', '250', '250', '250', '-250'] exact two-sided sign_flip_p 3/8 0.3750 no significance claimed
    X-omega minus O, pooled diagnostic, per life (pairs, milli; pairs scored in every repeat of both rows; 0 lives left out with none): ['0', '250', '-250', '-250', '-250'] exact two-sided sign_flip_p 5/8 0.6250 no significance claimed
    X-omega minus F, pooled diagnostic, per life (tasks, milli; tasks scored in every repeat of both rows; 0 lives left out with none): ['0', '0', '0', '0', '0'] exact two-sided sign_flip_p 1 1.0000 no significance claimed

== 8. Full history
  fits the window on 0 of 85 items, summed over lives

== Earlier evidence: the 4 November runs at an older commit (step-1 by_kind.py); never pooled
== A. Header
run 1: tier T2 system hermes-native model gpt-6.1-sol effort medium pack_hash 15141b194ab8
  pins {"benchmark_commit": "ac81423de4bc", "director_commit": "ac81423de4bc", "generator_commit": "ac81423de4bc", "harness_hash": "dbf03edef301", "route_table_hash": "0490592ab5b0", "scorer_commit": "ac81423de4bc", "system_hash": "dbf03edef301", "write_turn_package_hash": "753f83e1bd00"}
run 2: tier T2 system hermes-native model gpt-6.1-sol effort medium pack_hash 15141b194ab8
  pins {"benchmark_commit": "ac81423de4bc", "director_commit": "ac81423de4bc", "generator_commit": "ac81423de4bc", "harness_hash": "dbf03edef301", "route_table_hash": "0490592ab5b0", "scorer_commit": "ac81423de4bc", "system_hash": "dbf03edef301", "write_turn_package_hash": "753f83e1bd00"}
same pack_hash in every run True
same scorer_commit in every run True
floor items in run 2 that differ from run 1's floor 0
scored pairs (by run 1) not scored in floor (live) 0
scored pairs (by run 1) not scored in system (live), run 1 0
scored pairs (by run 1) not scored in system (live), run 2 0

== B. Scored action pairs by kind (pairs, right, wrong, no credit, non-result, net, points)
scored action pairs 20 {'Drift, value twins': 10, 'Drift, correction twins': 5, 'Wake': 5}
-- floor (live)
  Drift, value twins: pairs 10 right 0 wrong 0 no_credit 10 non_result 0 net 0 points 0.0
  Drift, correction twins: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  Wake: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  total: pairs 20 right 0 wrong 0 no_credit 20 non_result 0 net 0 points 0.0
-- system (live), run 1
  Drift, value twins: pairs 10 right 2 wrong 3 no_credit 5 non_result 0 net -1 points -10.0
  Drift, correction twins: pairs 5 right 5 wrong 0 no_credit 0 non_result 0 net 5 points 100.0
  Wake: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  total: pairs 20 right 7 wrong 3 no_credit 10 non_result 0 net 4 points 20.0
-- system (live), run 2
  Drift, value twins: pairs 10 right 2 wrong 3 no_credit 5 non_result 0 net -1 points -10.0
  Drift, correction twins: pairs 5 right 5 wrong 0 no_credit 0 non_result 0 net 5 points 100.0
  Wake: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  total: pairs 20 right 7 wrong 3 no_credit 10 non_result 0 net 4 points 20.0
-- naive retrieval (scripted)
  Drift, value twins: pairs 10 right 10 wrong 0 no_credit 0 non_result 0 net 10 points 100.0
  Drift, correction twins: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  Wake: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  total: pairs 20 right 10 wrong 0 no_credit 10 non_result 0 net 10 points 50.0
-- oracle evidence (scripted)
  Drift, value twins: pairs 10 right 10 wrong 0 no_credit 0 non_result 0 net 10 points 100.0
  Drift, correction twins: pairs 5 right 5 wrong 0 no_credit 0 non_result 0 net 5 points 100.0
  Wake: pairs 5 right 5 wrong 0 no_credit 0 non_result 0 net 5 points 100.0
  total: pairs 20 right 20 wrong 0 no_credit 0 non_result 0 net 20 points 100.0
-- floor (scripted)
  Drift, value twins: pairs 10 right 0 wrong 0 no_credit 10 non_result 0 net 0 points 0.0
  Drift, correction twins: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  Wake: pairs 5 right 0 wrong 0 no_credit 5 non_result 0 net 0 points 0.0
  total: pairs 20 right 0 wrong 0 no_credit 20 non_result 0 net 0 points 0.0

== C. Naive-retrieval control flags on mean pair score in milli (f floor, r naive, c oracle, scripted)
  Drift, value twins: f 0.0 r 1000.0 c 1000.0 between False rag_near_solved True floor_near_solved False
  Drift, correction twins: f 0.0 r 0.0 c 1000.0 between False rag_near_solved False floor_near_solved False
  Wake: f 0.0 r 0.0 c 1000.0 between False rag_near_solved False floor_near_solved False
  total: f 0.0 r 500.0 c 1000.0 between True rag_near_solved False floor_near_solved False
pack rows as stored (stage, track, floor, naive_rag, ceiling, between, rag_near_solved, floor_near_solved): lives
   act Drift 0 0 1000 False False False 1
   act Drift 0 1000 1000 False True False 4
   act Drift 0 667 1000 True False False 5
   act Keep 0 1000 1000 False True False 5
   act Wake 0 0 1000 False False False 5
   survive Drift 0 1000 1000 False True False 5
   survive Recall 0 1000 1000 False True False 10

== D. Single tasks in scored action pairs, by kind
-- floor (live)
  Drift, value twins: tasks 20 base_verdict {'FAIL_TASK': 3, 'OMISSION': 17} in_context absent (field not in outcomes) competing_present 0
  Drift, correction twins: tasks 10 base_verdict {'OMISSION': 5, 'PASS': 5} in_context absent (field not in outcomes) competing_present 0
  Wake: tasks 10 base_verdict {'OMISSION': 10} in_context absent (field not in outcomes) competing_present 0
-- system (live), run 1
  Drift, value twins: tasks 20 base_verdict {'FAIL_MEMORY': 3, 'FAIL_TASK': 10, 'PASS': 7} in_context 20 (absent on 0) competing_present 20
  Drift, correction twins: tasks 10 base_verdict {'PASS': 10} in_context 10 (absent on 0) competing_present 5
  Wake: tasks 10 base_verdict {'FAIL_TASK': 3, 'OMISSION': 6, 'PASS': 1} in_context 7 (absent on 0) competing_present 0
-- system (live), run 2
  Drift, value twins: tasks 20 base_verdict {'FAIL_MEMORY': 3, 'FAIL_TASK': 10, 'PASS': 7} in_context 20 (absent on 0) competing_present 20
  Drift, correction twins: tasks 10 base_verdict {'PASS': 10} in_context 10 (absent on 0) competing_present 5
  Wake: tasks 10 base_verdict {'FAIL_TASK': 5, 'OMISSION': 5} in_context 8 (absent on 0) competing_present 0
-- naive retrieval (scripted)
  Drift, value twins: tasks 20 accuracy_correct 20 in_context 20
  Drift, correction twins: tasks 10 accuracy_correct 5 in_context 0
  Wake: tasks 10 accuracy_correct 0 in_context 0
-- oracle evidence (scripted)
  Drift, value twins: tasks 20 accuracy_correct 20 in_context 20
  Drift, correction twins: tasks 10 accuracy_correct 10 in_context 10
  Wake: tasks 10 accuracy_correct 10 in_context 10
-- floor (scripted)
  Drift, value twins: tasks 20 accuracy_correct 0 in_context 0
  Drift, correction twins: tasks 10 accuracy_correct 5 in_context 0
  Wake: tasks 10 accuracy_correct 0 in_context 0

== E. Per life (lives with scored action pairs)
lives 5
  net per life, floor (live): [0, 0, 0, 0, 0]
  net per life, system (live), run 1: [0, 2, 0, 0, 2]
  net per life, system (live), run 2: [0, 2, 0, 0, 2]
  net per life, naive retrieval (scripted): [2, 2, 2, 2, 2]
  net per life, oracle evidence (scripted): [4, 4, 4, 4, 4]
  net per life, floor (scripted): [0, 0, 0, 0, 0]
  run 1 pairs: per-life mean difference system minus floor (milli) ['0', '500', '0', '0', '500'] sign_flip_p 1/2 0.5000
  run 1 tasks: per-life mean difference system minus floor (milli) ['125', '375', '125', '125', '500'] sign_flip_p 1/16 0.0625
  run 2 pairs: per-life mean difference system minus floor (milli) ['0', '500', '0', '0', '500'] sign_flip_p 1/2 0.5000
  run 2 tasks: per-life mean difference system minus floor (milli) ['125', '375', '125', '125', '375'] sign_flip_p 1/16 0.0625

== F. Agreement between run 1 and run 2
  scored pairs with equal score 20 of 20
  keys only in one run 0
  scored tasks whose (score_milli, failure_class) differ 6 {'DRIFT-ASOF': 1, 'WAKE-LOOP': 5}
  action tasks whose pass or fail (base_verdict PASS) differs 1 {'WAKE-LOOP': 1}
  quiz items whose score_milli differs 1 {'DRIFT-ASOF': 1}

== G. Quiz items (stage survive) by cell: +1000, 0, -1000, other, net
-- floor (live): quiz items 15
  DRIFT-ASOF: +1000 0 0 5 -1000 0 other 0 net 0
  RECALL-AGG: +1000 0 0 5 -1000 0 other 0 net 0
  RECALL-VERB: +1000 0 0 5 -1000 0 other 0 net 0
-- system (live), run 1: quiz items 15
  DRIFT-ASOF: +1000 1 0 0 -1000 4 other 0 net -3
  RECALL-AGG: +1000 5 0 0 -1000 0 other 0 net 5
  RECALL-VERB: +1000 5 0 0 -1000 0 other 0 net 5
-- system (live), run 2: quiz items 15
  DRIFT-ASOF: +1000 2 0 0 -1000 3 other 0 net -1
  RECALL-AGG: +1000 5 0 0 -1000 0 other 0 net 5
  RECALL-VERB: +1000 5 0 0 -1000 0 other 0 net 5
-- naive retrieval (scripted): quiz items 15
  DRIFT-ASOF: +1000 5 0 0 -1000 0 other 0 net 5
  RECALL-AGG: +1000 5 0 0 -1000 0 other 0 net 5
  RECALL-VERB: +1000 5 0 0 -1000 0 other 0 net 5
-- oracle evidence (scripted): quiz items 15
  DRIFT-ASOF: +1000 5 0 0 -1000 0 other 0 net 5
  RECALL-AGG: +1000 5 0 0 -1000 0 other 0 net 5
  RECALL-VERB: +1000 5 0 0 -1000 0 other 0 net 5
-- floor (scripted): quiz items 15
  DRIFT-ASOF: +1000 0 0 5 -1000 0 other 0 net 0
  RECALL-AGG: +1000 0 0 5 -1000 0 other 0 net 0
  RECALL-VERB: +1000 0 0 5 -1000 0 other 0 net 0

== H. Pairs the live tier does not score (run 1), by kind: right, wrong, no credit
unscored pairs 15 stages {'act': 30}
  Drift, value twins, G2, not scored live: pairs 10
    naive retrieval (scripted): right 9 wrong 1 no_credit 0 non_result 0
    oracle evidence (scripted): right 10 wrong 0 no_credit 0 non_result 0
  KEEP-INC/fork, G2, not scored live: pairs 5
    naive retrieval (scripted): right 5 wrong 0 no_credit 0 non_result 0
    oracle evidence (scripted): right 5 wrong 0 no_credit 0 non_result 0

== I. Full history fits over lives
  run 0 of 85
-- E1 vs E2: scored pairs with equal score 20 of 20 scored in both; keys only in one 0
   task scores that differ (score_milli differs; tasks scored in either) 2 {'DRIFT-ASOF': 1, 'WAKE-LOOP': 1}
   tasks whose score or failure class differs ((score_milli, failure_class) differs; tasks scored in either) 6 {'DRIFT-ASOF': 1, 'WAKE-LOOP': 5}
exit 0
```
