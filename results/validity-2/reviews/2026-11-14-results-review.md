# Adversarial review of the validity round 2 results page, 2026-11-14

Reviewer: `gpt-6-astra` at high effort, a model family other than the author's (`claude-opus-5-5`), run read-only on the results commit with the run trees, the packs, the operator records and the reader's diagnostics. This is the interim scrutiny PREREG-v0.5 keeps until the Scoring Veto Panel is filled; it is not the panel. The text under each pass is the reviewer's own, unedited. The file names it cites outside this folder (such as `results-obligations.md`, `posts/draw-post.md`, `rehearse.log`, `resume.log`, `refused-1/`, `logs/chain.log` and `units.json`) are run trees and operator records in the private evidence store under this round's tag, `bicentennial/validity2-20261114`.

How each finding was used:
- **Finding 1 (an unsupported cause for `wake-loop`'s two misses):** fixed. The page no longer says the misses come from these lives rather than the live reader. It says the predictions came from the scripted anchor report on the screening set, that on this pack the scripted reports also fall above both ranges (grep 20, recent window 30), that live grep matched and the live recent window scored 5 points lower (W1 20, W2 30), and that check 2 measures presence, not why a pair was scored.
- **Finding 2 (the rehearsal was not reported):** fixed. "Before the run" reports the rehearsal: its time, commit and seeds, each step's outcome, and that its no-arm refusal was the only reading it made.
- **Finding 3 (the refused invocations were reported only together):** fixed. Each of the anchor check's three refused invocations has its own row (start, end, exit, refusal record, standard output, standard error, diagnostics), with a statement that the first script numbered no invocations and kept no sequence numbers, and where the records were moved.
- **Finding 4 (R1's wait):** fixed: 61 minutes.
- **Finding 5 (`drift-config`'s expected reading):** fixed: both tables keep "otherwise cleared".
- **Also changed by the author, unasked:** the result paragraph and "What follows" call the 75 points an oracle-to-best-anchor gap, "room a memory system could use, not a gain any system has shown". The second pass checked it.
- **A fresh-context Claude review** (two `claude-opus-5-5` reviewers at high effort, one on the numbers and one on claims and conformance) re-derived every number on the page from the run trees and found none wrong. It found four merge-blocking points, all fixed:
  - the page called this pack's reading the only run of the reading script, although the rehearsal ran it too. It now says "on this pack", and the rehearsal's output is published beside the page;
  - it gave a cause for R2's stall, load from unrelated work, that no record shows. It now gives the load averages each arm's receipt records, and no cause beyond the timeouts;
  - it lacked the promised sentence that the three refused records show the refusal's shape, not the race. Added;
  - the declaration says the oracle smoke's run record is published with these results, and it was only in the evidence store. `smoke/` now publishes both pre-draw checks' run records without the scores that were never read, and the smoke's reading of the finalists.

  Its other points were fixed as well:
  - the post times are marked as GitHub's, beside the machine's read-back times;
  - the wrapper that invoked the arms is disclosed, with its retry rule and its own call numbers;
  - the scripted anchors are given in points only;
  - the claim about later runs is limited to "so far";
  - `drift-config`'s risk is restated as the declaration gives it;
  - the run script's header names every kind of change made to it;
  - the admission sentence says what the gate checks;
  - the guard rule's Claude review is described as a review whose report was not kept.

  Separately, as [#536](https://github.com/electricsheephq/bicentennial/issues/536) requires, every arm's card is now published beside the page, cut to the target items (below).
- **The second pass** (below) checked the fixes of the first pass's findings: all five resolved, no new finding.
- **The third pass** (below) checked the fixes of the Claude review's findings, every new number, time and load figure against its source, the published records and the run script: no finding.
- **The Claude reviewers re-read the same fixes.** The numbers reviewer found every new figure matching its source, `records.json` equal to what `records.py` computes, and each card a byte copy of its run tree's. The claims reviewer found one merge-blocking point, fixed: each card also held the entries of the ten items outside the task list (one `recall-value` item per life), whose scores this round never read. Each card is now cut to the 80 target items by `cut_cards.py`, every other field unchanged, and `full-card-sha256.json` gives each full card's hash. It also found two nits, both fixed: the pull request's description still called the machine heavily loaded, and the guard rule's fresh Claude review was described as unkept. That review's two reports had not been saved as files; they were copied verbatim from the reviewer's transcript, with one header line naming the reviewer and the turn, into the evidence store, whose publish step had not copied that review folder at all. Its re-read of these fixes found no blocking point. One of its three nits was applied: the launch carried the guard rule's first *Codex*-reviewed version, because the Claude review of that version ended after the launch. The other two were answered: the copies were checked against the transcript by the author, and the evidence store was published before this page merged.
- **The fourth pass** (below) checked the card cut: no finding.

## First pass, on the results page

Reviewed clean commit `a9461a30281f`. No changes, tests, builds, network access, credentials, or home dot-folders used.

1. **Important · MERGE_BLOCKING — `RESULT.md:6,118`: unsupported causal attribution.**  
   Check 2 compares evidence-presence booleans, not causes of scored outcomes (`control-trials/table.py:412–427`). Scripted/live agreement does not establish that the live reader contributed nothing. The recent-window scores actually differ: scripted 30, live 25 (`table-output.txt:233`), contradicting “the same two scores” at line 6.  
   **Smallest fix:** state that both scripted scores also exceed the predicted ranges, with live grep matching and live window five points lower; remove “not from the live reader.”

2. **Important · MERGE_BLOCKING — `RESULT.md:47,51–55`: promised rehearsal disclosure missing.**  
   `results-obligations.md:12` requires the rehearsal line. `posts/draw-post.md:7` records it; `artifacts/rehearse.log:25` records successful placement, build, install, gate, task-list, reading-refusal and check-3 steps. The page describes the script’s rehearsal requirement but never reports this rehearsal.  
   **Smallest fix:** add the recorded rehearsal outcome, distinguishing its no-arm reading/refusal from the validation pack’s sole scored reading.

3. **Important · MERGE_BLOCKING — `RESULT.md:54`: refused-invocation disclosure is incomplete.**  
   The aggregate account is accurate, but `results-obligations.md:17–23` requires individual invocation records. `resume.log:1–6` supplies three separate intervals and exit 3 for each; `refused-1/` retains each refusal, stderr, empty stdout and empty diagnostics manifest. The page supplies only their combined interval and generic archive description.  
   **Smallest fix:** add three rows with each arm’s interval, exit and evidence-relative record locations. Explicitly distinguish the manual archive from later numbered guard archives; mark unrecorded invocation/sequence metadata as such.

4. **Nit · NON_BLOCKING — `RESULT.md:43`: elapsed wait is misstated.**  
   The printed endpoints span **61 minutes 8 seconds**, not 60 minutes (`logs/chain.log:8–11`). The operator’s `idle()` performs 61 sleep cycles (`run-v2.sh:50–52`).  
   **Smallest fix:** say “about 61 minutes,” retaining the exact timestamps. Its exclusion from attempts is correct: `idle` precedes invocation numbering (`run-v2.sh:334–338`).

5. **Nit · NON_BLOCKING — `RESULT.md:112`: expected reading is abbreviated.**  
   `DECLARATION.md:72` includes “otherwise cleared”; the copied prediction omits that branch. This does not change the observed held call.  
   **Smallest fix:** restore those words.

The remaining probe results:

- **Numbers:** Scores, per-arm pair counts, margins, stability counts, checks 1–8 and filter counts match `table-output.txt:39–274`. All thirteen reported arm times match `units.json`; sends match `logs/chain.log`. Dividing 418–546 by 90 gives 4.6–6.1; §3’s projections calculate to approximately 417 and 788, consistent with “about 420” and “about 790.”

- **R2 and anchors:** JSON inspection confirms 15 units with one attempt, four with two and one with three; 27 item reruns; eight slow units, including three completing on their first attempt. `grep -rc open_timeout` gives 24 matching lines for R2 and zero elsewhere. R1/R2’s 90 scored records match on the four claimed fields. Anchor times, sends and launches match `resume.log`, `resume-2.log`, `resume-3.log` and launch records; refusal contents support the stated classification.

- **Hashes and check 3:** `shasum -a 256` matches the page’s draw, spec, placement and task-list hashes; FILTER matches the reading output. Static hashing of Git objects reproduces all four code pins for both run commits. Check-3 copies differ only on lines 4–5; 71 tests are recorded passed, including the 15 required cases, ending in exit 0. **The linked CI run was not independently verified under the no-network constraint.**

- **Readings:** All four correctly read **ranking candidate**. Every repeat contributes; oracle trials all score 100, so neither unresolved, unstable nor low takes precedence. With floor 0, all near-solved thresholds are 70; every anchor stays below them in all 12 combinations, and the floor in all six. No flag is uninterpretable. Best-anchor means are 0, 10, 0 and 25.

- **Predictions and inference:** All 24 central values and ranges match §7; exactly 22 outcomes fall inside their ranges. All four observed readings satisfy their predictions. The 75-point “room” is supported as an **oracle-to-best-anchor gap**, not demonstrated achievable memory-system gain. The `drift-config` risk reproduces the declared placement-model threshold; §7’s qualification that live scores and stability still decide remains applicable.

- **Disclosures and follow-up:** Apart from findings 2–3, the required operational disclosures are present. The published table is byte-identical to the sole recorded scored reading; all thirteen unreadable-state counts are zero. Separate subsequent v3 admission is consistent with `DECLARATION.md:60` and `PLAN.md:135–140`. Wake needs no additional admission: `_check_c7` exempts edition-1 references (`t1.py:369–381`; `editions.py:19–22`).

- **Public text:** No unintended local paths, credential values, person/customer/machine names or private-store names found. Sanitizer reproduction exactly matches the committed script. Seeds and item/bundle identifiers occur in the intentionally published data artifacts required by the declaration; no task text or answers found there.

- **Test:** `test_t1.py:209–215` matches the accepted checklist requirement. Static evaluation of both listed page references confirms both exist and contain their own required hash line. It would pass at this commit; no test was run. Remote evidence-store publication remains unverified.

SOUND-WITH-FIXES
## Second pass, on the fix delta

No remaining findings in `a9461a3..7ae9c02`; all three blockers and both nits are closed.

- **Wake inference — `RESULT.md:6,127`:** scripted/live scores match `table-output.txt:167,172,232–233`. Check 2 measures presence agreement (`table.py:412–427`), as the revised text now states. The unsupported causal attribution is gone.
- **Rehearsal — `RESULT.md:52`:** start time, commit, placement counts, pack hash, task counts and refusal outcome match `rehearse.start` and `rehearse.log:5–25`; the recorded 71 passes match `rehearsal/check3.txt:81–82`. The rehearsal is clearly distinguished from this pack’s scored reading.
- **Refused invocations — `RESULT.md:55–65`:** all three intervals and exit codes match `resume.log:1–6`. The retained artifacts confirm the refusal codes, empty stdout, stderr, empty diagnostic file lists and marker value. The manual archive and absent sequence metadata are disclosed.
- **Nits — `RESULT.md:43,92,121`:** the wait spans 61 minutes 8 seconds; both prediction tables now preserve “otherwise cleared,” matching `DECLARATION.md:72`.
- **Additional wording — `RESULT.md:6,146`:** the 75-point gap is correctly framed as oracle-to-best-anchor separation, without claiming demonstrated memory-system gain.

The added rehearsal paragraph includes numeric screening seeds already disclosed in `posts/draw-post.md:7`; values match, and are not reproduced here. No new local absolute paths, person/customer/machine names, private repository/store names or item/bundle identifiers found.

Clean checkout at `7ae9c026a13e`. No changes, tests, builds or network access; remote evidence publication was not verified.

SOUND

## Third pass, on the fixes of the Claude review

No findings in `7ae9c02..d1f9bd0`. The delta resolves the Claude findings.

1. **Probe 1 — PASS.** New times, counts and load figures match the records. All thirteen cards match their run-tree copies byte for byte; the rehearsal excerpt matches log lines 9–23.
2. **Probe 2 — PASS.** `records.json` exactly matches `records.py`’s computed output and contains no scores. `oracle-reading.txt` matches the finalist-only computation; no anchor or non-finalist smoke scores are published.
3. **Probe 3 — PASS.** Revised claims agree with the declaration and cited evidence. The missing Claude guard-review reports are explicitly disclosed; their review coverage remains independently unverifiable.
4. **Probe 4 — PASS.** Applying the sanitizer’s declared substitutions reproduces the published script exactly, apart from its disclosure header. No other differences.
5. **Probe 5 — PASS.** No new private paths, personal/customer/machine names, repository/store names or undisclosed seeds found. All cards’ item identifiers belong to the already-public pack.

Worktree remains clean. No tests, builds, network, credentials or home-directory dot-folders accessed. Record computations used the host Python’s equivalent UTC alias; remote publication was not verified.

SOUND

## Fourth pass, on the card cut

- **Probe 1 — No finding; gate: none.** `cards/*.json`: all 13 contain exactly the 80 targets; canonical bytes equal the full cards with only excluded rows removed. All hashes match; other fields are unchanged and contain no excluded-item scores. Fix: none.
- **Probe 2 — No finding; gate: none.** `RESULT.md:46–47`: card claims match the checks; both recovered reports support the stated review coverage, and `publish-v2.sh:58` includes them in assembly. Transcript fidelity and remote publication were not independently verified. Fix: none.
- **Probe 3 — No finding; gate: none.** The public delta introduces no private paths, person/machine/store names, seeds or additional item identifiers. Cards introduce no new field values. Fix: none.

**SOUND** — for the inspected local delta `d1f9bd0..6121fc8`.
