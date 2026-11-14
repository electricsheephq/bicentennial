# Validity round 2: kinds of task that separate evidence from retrieval

Round 1 cleared the three Drift templates: with the needed evidence handed over, the reader did all of them. But naive retrieval also scored 100 on each, so none can show that memory beats retrieval ([round 1](../validity-1/README.md)). Round 2 looks for kinds of task on which a reader handed the evidence does well and every naive anchor does badly: naive retrieval, BM25, a scripted grep and a recent window. Every reading comes from control rows only; no kind is promoted or dropped on a real system's score.

| File | What it is |
|---|---|
| [`PLAN.md`](PLAN.md) | The adopted plan: the three new anchors, the candidate cards and their predictions, the scripted screen, the oracle smoke, round 2's thirteen control arms on ten fresh lives, the fresh-seed follow-up that runs only if round 2 finds a ranking candidate, the order of work, the claim discipline, the costs and the stop rules. |
| [`reviews/2026-11-13-plan-review.md`](reviews/2026-11-13-plan-review.md) | The adversarial review of the draft plan by a model family other than the author's, with how each finding was applied. |
| [`cards/`](cards/README.md) | The candidate cards and the rulings on them, published before any screen report. |
| [`screening/`](screening/README.md) | The 20-life G1 screening set, committed before any candidate report was read. |
| [`DECLARATION.md`](DECLARATION.md) | Round 2's declaration: how the finalists' and Wake's control trials are run and read, its predictions, and what was already seen; merged before the seed draw. |
| [`reviews/2026-11-14-adversarial-review.md`](reviews/2026-11-14-adversarial-review.md) | The adversarial review of the declaration and of the run script's rerun rule by a model family other than the author's, with how each finding was used. |
| [`control-trials/`](control-trials/) | The task-list and reading scripts for round 2's thirteen control arms, with their tests. |

Round 2's declaration, the candidate cards, the screen reports and the results land here as each step is done. The work is tracked in the issues listed in the [roadmap](../../ROADMAP.md).
