# Milestone 1 declaration: how the first separation table is read

**Status:** written 11 November 2026, before any new arm runs. It is merged into the repository before the first new arm starts, and the results page names its commit. This is a developer-tier run on public lives: no bar, no certification, and not predictive of the full tier (PREREG-v0.5 §6). An adversarial review by a model family other than the author's is published beside it; that is the frozen interim scrutiny, not the Scoring Veto Panel.

## 1. What runs
- **Pack:** the public T2 pack, unchanged and unfiltered: 10 lives of 10 sessions, two twin branches each, a kill at session 6, a model-label swap at session 8.
- **Reader:** the pinned reader model at its pinned effort, through the benchmark's own login. Only the probe answer is live; write turns, compaction, extraction and embeddings are scripted.
- **One commit for every row:** the commit that lands the control-arm path. The four code pins (controls, reader, scoring code, scorer) equal main's before it; pinned control code and the scorer are not edited.
- **Rows:**
  - **F, no memory:** memory off, no search tool, no added text.
  - **R, naive retrieval:** the pinned naive-retrieval control (hashed TF-IDF, 240-character chunks, top five), queried with the task as the pack does at the probe's time, its five chunks handed to the live reader.
  - **O, oracle evidence:** the task's listed evidence events that exist at the probe's time, as the pinned oracle-evidence control returns them, handed to the live reader.
  - **H, Hermes native:** the registered system, as on 4 November.
- **Where control text goes:** at the top of the probe turn's user message, in one labelled block, the same for R and O. The arm otherwise equals F.
- **The nine core arms and their order:** F, R, O, H, H, O, R, F, O. The first eight are mirrored, which mitigates order effects without removing them; the ninth is oracle evidence's third repeat. Each arm runs alone over the whole pack, from a clean state, and never reads a cached result of its own kind. H's first run also produces a fresh no-memory floor beside it, and H's second run may take that floor from the cache. That extra floor is shown separately and enters no mean, flag or comparison: the two scheduled F arms are the floor. Each arm's start and end times and served model identity are recorded.
- **Earlier runs:** the Hermes native runs of 4 November and their one live floor are shown as earlier evidence at an older commit, never pooled with the new rows.
- **Optional rows:** Holographic and OMEGA, one attempt each, only after the nine core arms. They are shown separately; a failed attempt is published as a failure, and nothing about them changes the core table.

## 2. Checks before any score is read
1. **Payload:** for R and O, the block each task's reader received equals the pinned control's returned text byte for byte, in order and with its boundaries; a hash per task is recorded.
2. **Presence:** for O, the harness's own record shows the needed fact in what the reader received on all 40 scored action tasks; for R, that record equals the pack's scripted naive-retrieval report task by task.
3. **Memory off:** F, R and O requests carry no memory block and no search tool, and the block holds no answer key and no option order.
4. **Identity:** every arm was served the same model identity. An arm that differs is rerun once; a mismatched arm is shown separately and never pooled.
5. **Completeness:** a core arm with any scored action task left BLOCKED is rerun once, whole. If it is still incomplete it is published as incomplete, with its assigned, scored and excluded counts; its row uses the pairs it scored, and any flag that depends on it reads "unresolved". A system failure is a scored failure, as the scorer already treats it, never an exclusion.
6. **Repeats and common support:** a row's mean uses only its complete, identity-matched repeats. If a required repeat is still missing or mismatched after its one rerun, the row is published with the repeats it has, marked incomplete, and every flag that uses it reads "unresolved". Whenever rows are compared or a flag is computed, only the pairs scored in every repeat used on both sides count, and the page prints that number.
7. **Live units:** every unit of every F, R and O arm ran live in that arm, as the run's own records show; none came from a cache.
If check 1, 2, 3 or 7 fails, the arm is not a valid control row: the fault is fixed and the arm rerun before any score is opened.

## 3. What is scored
- **Primary display:** the 20 scored action pairs of the five software-partner lives, by kind: Drift value twins (10), Drift correction twins (5), Wake (5), and per life. A pair's score is the lower of its two twins' penalised scores (+1 right, 0 no credit, -1 a confident false memory), from the unchanged scorer. Right, confidently wrong and no-credit pairs are shown separately. A row's points are 100 times its mean pair score; a repeated row shows every repeat and their mean.
- **The all-20 figure** is a pooled scored-pair diagnostic. It weights Drift's 15 pairs three times Wake's five; the frozen headline averages within lives and then equally across tracks, so this figure is never carried into a pilot claim.
- **Beside it:** single-task counts with their failure classes, the 15 quiz questions, and the agreement between repeats.
- **Not scored:** the 30 personal-assistant actions, which the live tiers do not score yet.

## 4. Exploratory screening flags, from control rows only
Points are raw penalised points, from -100 to +100 (PREREG-v0.5 §7), the scale on which §9's 75 is set. Per kind, with f, r and c the points of F, R and O: f and r are the means of their two repeats, and c is the mean of O's first two repeats (arms 3 and 6), so each of the three means sits at the same centre of the mirrored order. O's third repeat (arm 9) enters the instability check below and the filter yield (§6), and the page also prints c over all three repeats.
- **low even with the evidence handed over** when c < 75;
- **near-solved by naive retrieval** when r >= f + 0.7 (c - f);
- **near-solved without memory** when f >= 0.7 c;
- **a candidate for fresh validation** when none of the three applies.

A kind can carry more than one flag, and every flag that applies is printed. When "low" applies together with a near-solved flag, the low row of §6 governs first: the template gets a new version, and the near-solved flags are computed again on that version's own control trials. Until then the kind is also excluded from any claim that memory beats retrieval.

What these are and are not:
- The 75 is the pilot's frozen calibration target for oracle evidence (PREREG-v0.5 §9), and the two 0.7 rules are the naive-retrieval control's frozen near-solved disclosures. There they apply to whole tracks on calibration lives. Applying them to kinds of five or ten pairs on public lives is new in this declaration. They screen; they are not gates, and a candidate is not a validated ranking task.
- A low c says that direct evidence was not enough in this setup. It does not by itself say the reader is at fault.
- Each flag is also computed for every combination of one repeat from each row it uses (the naive-retrieval flag, for example, has 2 x 2 x 3 = 12 combinations of F, R and O). If any combination disagrees with the flag computed on the means, the flag is **unstable** and the kind gets no classification.
- The page prints each flag's margin in pairs. With five pairs one pair is 20 points, and a pair that turns from right to confidently wrong moves 40.
- The near-solved flags are not interpreted when c <= f or c <= 0; the arithmetic is printed as a disclosure only.

## 5. Real systems
H (and any optional row) is reported per kind against F, R and O, with per-life differences. No test is claimed and nothing is triggered by a real system's result. H against the controls is a comparison of whole paths: R and O share one placement of text, and H has its own. The page prints the exact life-level sign-flip p for what it shows (five lives cannot go below .0625) and claims no significance.

## 6. What the result triggers
| Control rows say | Then |
|---|---|
| a kind is low even with the evidence | its template gets a new version; that version needs its own three oracle trials on fresh control-only lives and a frozen task list before any system runs on it |
| a kind is near-solved by naive retrieval | it is kept as a do-no-harm check and excluded from any claim that memory beats retrieval; calibration then uses all four frozen naive anchors (naive retrieval, BM25, grep, a recent window) |
| a kind is a candidate | it goes into the fresh-seed follow-up with every other kind |
| flags unstable, or no candidate | repair and calibration come before any further system run |

- Milestone 1 is published on the unchanged, unfiltered task list. O's three repeats are used only to report, separately, how many of today's pairs would pass the frozen oracle filter (each twin passes with only its evidence in at least 2 of 3 trials). They never validate a repaired template.
- No kind is promoted or dropped because of how a real system scored on it. The follow-up carries every kind, repaired where the control rows say so.

## 7. Predictions, written before the runs (pairs right)
| Row | Value twins (10) | Correction twins (5) | Wake (5) |
|---|---|---|---|
| F | 0 | 0 | 0 |
| R | 2-5 | 0 | 0 |
| O | 3-7 | 4-5 | 0-2 |
| H | 2 (and 3 confidently wrong) | 5 | 0 |

Expected flags: value twins and Wake low even with the evidence; correction twins a candidate.

## 8. What was already seen when this was written
- The 4 November results of F and H, kind by kind. In particular, the correction twins are already known to favour H.
- The pack's scripted control rows. They are evidence-availability diagnostics: their reader always picks the right value when a rival is in view, so they are not live retrieval results.
- The thresholds in section 4 predate both; their use here does not. The kinds in section 3 are the pack's own templates and twin types, not groups chosen from results.

## 9. What this does not prove
- Public lives, not fresh ones. One reader model at one effort. Five lives with scored actions.
- A scripted life: no system's own judgment about what to store is tested.
- One real system (three with the optional rows).
- Whole arms in a mirrored order, not arms interleaved within each life as the board will run them; and equal served-model names do not prove equal service behaviour across two days.
- Where the control text is placed is a declared choice that can move the oracle row.
- The table lacks two rows a published board table must carry, and says so: the agent-key validation row (no auditor panel exists yet) and the full-history ceiling (the history fits the window for none of the pack's items, each tested at its own time).

## 10. Scope note
The Ring 0 documents describe controls as cached, scripted, API-mode rows, and put a Hermes-mode form of naive retrieval out of scope. The live control arms extend that. A dated, scoped extension note in the Ring 0 spec lands with the harness change. It changes no frozen scoring rule, calibration target or bar.

## 11. Readings fixed before the runs (added 11 November 2026, before any core arm runs)
The table script needs a reading wherever sections 1-10 leave a case open. These were settled while that script was reviewed, before any of the nine core arms ran. None of them changes a row, the order, a check, a threshold or a prediction.

1. **An incomplete repeat stays in its row.** An arm still incomplete after its one rerun keeps its place in its row's mean, on the pairs it scored. §2.5 says that its row "uses the pairs it scored", and §2.6's common support (only pairs scored in every repeat used) has work to do only in this case, because a complete arm scores every pair. "Complete" in §2.6's first sentence therefore means present and identity-matched. Keeping both repeats also keeps each mean at the centre of the mirrored order. Every flag that uses the row reads "unresolved".
2. **"Not interpreted" counts as not applying.** This holds both for instability and for the classification; the arithmetic is printed. A kind is a candidate when every flag is resolved and stable and none applies. A stable flag that applies is printed even when another flag of the same kind is unresolved.
3. **The flags' common support includes O's third repeat**, since that repeat enters each flag's instability check.
4. **Scores stay closed until the checks pass.** The table prints its checks first. It prints no score while any of these holds:
   - a control row fails check 1, 2 or 7;
   - the arms overlap in time, or ran out of the order listed;
   - the core arms' card pins (the commit and code hashes each card records) differ.

   Each such fault is fixed and the arm rerun before any score is opened. An identity mismatch or an incomplete arm (checks 4 and 5) also gets its one rerun before scores are opened; only after that is the arm published as mismatched or incomplete.
5. **Check 1** compares each item's recorded block hash with a fresh call of the pinned control, and the frame's hash with the runner's. That each request carries exactly that framed block, at the top of the probe turn, is the runner's own test at the run commit. Presence (check 2) is read from the request body the live model received.
6. **Check 2 for R** covers every task in the pack's scripted naive-retrieval report, not only the 40 scored action tasks, as "task by task" says.
7. **Check 3** cannot be read from the run outputs, which do not keep request bodies. It is the runner's own test at the run commit: no control-arm request carries a memory section, a memory fence, or a memory or search tool. The page names that test and the CI run that passed it.
8. **Check 7** reads each unit's own probe records. Every probe of every unit was served by the live reader, no unit stopped early, and the records cover all 40 scored action tasks. The cache provenance shows that no unit came from a cache.
9. **A rerun keeps its label.** A rerun of arm 6, for example, is still O2, and it runs after the arms already done. The page prints the order in which the arms actually ran, checks that order against their recorded start and end times, and says whether it equals the declared order.
10. **Filter yield (§6).** A trial with no score is unknown, not a failure. A twin passes with two passing trials. It fails when it could not reach two even if every unknown trial passed. Otherwise it is unresolved. The page prints pass, fail and unresolved counts.
11. **Real systems (§5).** Each system is compared per kind with each of F, R and O, on that comparison's common support, with per-life differences and the exact sign-flip p for each comparison. O means O1 and O2, as for c.
12. **A failed optional attempt** is printed as a failure, with its refusal code, and enters nothing else.
13. **The smoke runs.** Before the core arms, each control arm (O, R, F) runs once at the head of the pull request that adds it, to check delivery and output format. Only the table's checks are read; its scores are not opened, and these runs enter no row.
