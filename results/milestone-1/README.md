# Milestone 1: the first separation table

One question: through one fixed live reader, on action-scored tasks, where do no memory, naive retrieval, Hermes's own memory and oracle evidence land, and which kinds of task can rank a memory system at all? The plan is in `ROADMAP.md` ("Now") and in [#494](https://github.com/electricsheephq/bicentennial/issues/494).

These are developer-tier results on public lives: no bar, no certification, and not predictive of the full tier.

## The result (step 2, 11 November 2026)

Nine live arms at one commit, through one live reader, on the 20 scored action pairs of five public lives ([the step-2 page](2026-11-11-separation-table/RESULT.md)). Net pairs, with (pairs right, pairs wrong), each row the mean of its repeats; the screen uses the control rows only.

| Kind of task (pairs) | No memory | Naive retrieval | Oracle evidence | Hermes native | Screen |
| --- | --- | --- | --- | --- | --- |
| Drift, value twins (10) | 0 (0, 0) | −3 (1, 4) | −3 (1, 4) | −1 (2, 3) | low even with the evidence |
| Drift, correction twins (5) | 0 (0, 0) | 0 (0, 0) | 1 (3, 2)\* | 5 (5, 0) | low even with the evidence |
| Wake (5) | 0 (0, 0) | 0 (0, 0) | 5 (5, 0) | 0 (0, 0) | candidate |

\* Over its three repeats; the screen uses the first two, where it nets 0.

Two of the three kinds fail the oracle test: a reader handed the needed evidence still fails them, so a score on them cannot be read as a memory result yet. By the declaration, their templates get new versions, each validated with its own oracle trials on fresh lives before any system runs on it. Wake is the one candidate and goes on to fresh validation with every other kind. Hermes native reproduced its 4 November result pair for pair. The screen is exploratory, and no significance is claimed. Two optional rows ran after the core arms, one attempt each, and are shown separately on the page: Holographic's attempt stopped at the run's cap on live reader calls and has no score; OMEGA, run with its reranker off as registered, nets 0 on every kind.

| File | What it is |
|---|---|
| [`DECLARATION.md`](DECLARATION.md) | How the table is read, written and merged before any new arm runs: what runs, the checks before any score is read, the scale, the exploratory screening flags from control rows only, the predictions, and what the result does not prove. |
| [`reviews/2026-11-11-adversarial-review.md`](reviews/2026-11-11-adversarial-review.md) | The adversarial review of the plan and the declaration by a model family other than the author's, with its check of the fixes. |
| [`2026-11-04-live-runs-by-kind/`](2026-11-04-live-runs-by-kind/RESULT.md) | Step 1: the two live T2 runs of 4 November, read by kind of task beside the pack's scripted controls. Descriptive; the reading rule is not applied to it. |
| [`2026-11-11-separation-table/`](2026-11-11-separation-table/RESULT.md) | Step 2: nine live arms at one commit, read by the declaration through the table script (merged before any arm ran, with its fixture tests): the table, the screening flags, Hermes native against the control rows, the two optional rows, the predictions against the result, and the table script's output verbatim. |
