# Milestone 1: the first separation table

One question: through one fixed live reader, on action-scored tasks, where do no memory, naive retrieval, Hermes's own memory and oracle evidence land, and which kinds of task can rank a memory system at all? The plan is in [#494](https://github.com/electricsheephq/bicentennial/issues/494) and the declaration below; what comes next is in `ROADMAP.md` ("Now").

These are developer-tier results on public lives: no bar, no certification, and not predictive of the full tier.

| File | What it is |
|---|---|
| [`DECLARATION.md`](DECLARATION.md) | How the table is read, written and merged before any new arm runs: what runs, the checks before any score is read, the scale, the exploratory screening flags from control rows only, the predictions, and what the result does not prove. |
| [`reviews/2026-11-11-adversarial-review.md`](reviews/2026-11-11-adversarial-review.md) | The adversarial review of the plan and the declaration by a model family other than the author's, with its check of the fixes. |
| [`2026-11-04-live-runs-by-kind/`](2026-11-04-live-runs-by-kind/RESULT.md) | Step 1: the two live T2 runs of 4 November, read by kind of task beside the pack's scripted controls. Descriptive; the reading rule is not applied to it. |
| [`2026-11-11-separation-table/`](2026-11-11-separation-table/table.py) | Step 2's table script, written to the declaration and merged before any new arm runs, with its fixture tests. The results page lands with the runs. |
