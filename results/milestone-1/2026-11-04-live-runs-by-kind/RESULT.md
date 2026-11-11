# Milestone 1, step 1: the 4 November live runs, read by kind of task (#495)

Claim class: two live T2 runs of one real system (Hermes native) and one live run of the no-memory floor, on the public T2 pack, beside the pack's scripted naive-retrieval and oracle-evidence controls; an exploratory reading by kind of task on the twin-pair scale. Five public lives carry scored actions. A developer-tier result: no bar, no certification, not predictive of the full tier, and no significance is claimed.

This is the first step of [Milestone 1](https://github.com/electricsheephq/bicentennial/issues/494). It re-reads runs already made, kind by kind, so the question "where do no memory, naive retrieval, Hermes's own memory and oracle evidence land?" has an answer before the live control arms of step 2 exist. Step 2 ([#497](https://github.com/electricsheephq/bicentennial/issues/497)) runs all four rows live at one commit under the published declaration.

## The runs

- Code commit `ac81423de4bceda65952cd44a3934e67105becd6` for both runs; T2 pack hash `15141b194ab8abf389af2bfdbb4fd81e4d511fca14c54508d613fbe156628c04`. Hermes native at the registry's pinned Hermes (v0.22.2); the live reader `gpt-6.1-sol` at effort `medium`. At T2 only the probe answers are live: write turns, compaction, extraction and embeddings are scripted.
- **Run 1:** 2026-11-04, 12:45:00Z to 14:35:14Z, 8 slots, exit 0, run status COMPLETE. The no-memory floor ran live beside the system arm. Its timing is published in [`results/v0.3-dev-tools/2026-11-04-t2-live-arm`](../../v0.3-dev-tools/2026-11-04-t2-live-arm/RESULT.md); full run tree in the private evidence store, tag `bicentennial/t2-live-arm-20261104`.
- **Run 2:** 2026-11-04, 22:09:16Z to 23:47:01Z, 4 slots, exit 0, run status COMPLETE. The floor came from run 1's cache, so the live floor ran once: its outcomes in run 2 equal run 1's on every item. Full run tree in the private evidence store, tag `bicentennial/t2-live-arm-20261104-live2`.
- Both runs have the same pack hash and scorer commit. Every action pair scored in run 1 is scored in every live arm.

## The rows

- **No memory, live (F):** the live reader with memory off.
- **Hermes native, live (H):** Hermes's own memory, two runs.
- **Naive retrieval, scripted (sR):** the pack's cached naive-RAG control ([`specs/controls/naive_rag.md`](../../../specs/controls/naive_rag.md): hashed TF-IDF over 240-character chunks, top five, query = the probe prompt).
- **Oracle evidence, scripted (sO):** the pack's cached oracle-evidence control, which hands over the gold evidence.

The two scripted rows use the pack's scripted reader, which picks the right value whenever it is in view. They show whether the evidence was available to each method, not what a live reader does with it. That is why step 2 runs them live.

## The scale

Every action task belongs to a pair of matched twins (DESIGN §5.1a). In value twins the decisive fact differs (here, the current value); in correction twins, a trigger twin type, one item carries a correction and the other only a hedge. A **pair** scores the lower of its twins' scores (`bicentennial.score.bundle.twin_min`): +1 when both twins are right, −1 when either asserts a false memory (a confident wrong value, score −1000), otherwise 0 ("no credit"). Net = pairs right minus pairs wrong; points = 100 × net ÷ pairs.

The pair scale removes credit that needs no memory: on correction twins the floor passes one twin of every pair (5 of 10 tasks) and none of the pairs.

## The table: 20 scored action pairs on five lives

Net, with (pairs right, pairs wrong); every other pair is no credit.

| Kind of task (pairs) | F, live | H, live, run 1 | H, live, run 2 | sR, scripted | sO, scripted |
| --- | --- | --- | --- | --- | --- |
| Drift, value twins (10) | 0 (0, 0) | −1 (2, 3) | −1 (2, 3) | 10 (10, 0) | 10 (10, 0) |
| Drift, correction twins (5) | 0 (0, 0) | 5 (5, 0) | 5 (5, 0) | 0 (0, 0) | 5 (5, 0) |
| Wake (5) | 0 (0, 0) | 0 (0, 0) | 0 (0, 0) | 0 (0, 0) | 5 (5, 0) |
| **All scored pairs (20)** | **0** (0, 0) | **4** (7, 3) | **4** (7, 3) | **10** (10, 0) | **20** (20, 0) |
| Points | 0 | 20 | 20 | 50 | 100 |

At task level (40 tasks): F passes 5, H passes 18 in run 1 and 17 in run 2.

## What it says, in plain words

1. **Without memory, nothing.** The live floor scores 0 on every kind of task. Whatever the other rows score is not available to the reader without memory on these lives.
2. **Hermes's memory carries corrections that naive retrieval misses.** H is right on all 5 correction pairs in both runs. Scripted naive retrieval gets none: the correction never reaches its top five chunks (in context on 0 of 10 tasks), while H had it in context on all 10.
3. **On value twins, Hermes has the evidence but picks the wrong value.** H had the current value in context on all 20 tasks, and the rival (old) value too. It answered 2 pairs right, 3 with the old value as a confident false memory, and 5 with no credit. Both scripted rows get all 10; their reader always picks the right value when it is in view, so this shows the evidence was retrievable, not that a live reader would use it.
4. **Wake tasks: only the scripted oracle scores.** H had the evidence in context on 7 (run 1) and 8 (run 2) of 10 tasks and scored no pair. Scripted naive retrieval never had it in context.
5. **The two runs agree pair for pair** (20 of 20 equal). Six task scores differ between them: five Wake tasks and one quiz item.
6. **Two lives carry all of H's net.** Per life, H's net is 0, 2, 0, 0, 2 in both runs. The exact two-sided sign-flip test over five lives, H minus F, gives p = 1/2 on pairs and 1/16 on tasks. These are descriptive; with five lives no significance is claimed.

**Quiz items** (the survive stage, 15 per arm; +1 right, −1 confident false memory): H answers all 10 recall items in both runs. On the five "as of" drift items it is right on 1 (run 1) and 2 (run 2), with 4 and 3 confident false memories. Both scripted rows answer all 15; the floor answers none.

## What the screening rule would say on the scripted rows

For reference only. The [declaration](https://github.com/electricsheephq/bicentennial/pull/499) applies its screening flags to step 2's live control rows; applied here to the scripted rows (f, r, c = points of the floor, naive retrieval and oracle evidence):

| Kind of task | f | r | c | Flag |
| --- | --- | --- | --- | --- |
| Drift, value twins | 0 | 100 | 100 | near-solved by naive retrieval |
| Drift, correction twins | 0 | 0 | 100 | candidate for fresh validation |
| Wake | 0 | 0 | 100 | candidate for fresh validation |

The pack's own stored rows (by track, not by twin kind) are printed in section C of the output below.

## What the live tier does not score here

- **G2's 30 action tasks (15 pairs)** are not scored live at T2 (the card labels them "G2 actions not scored live"). On them, scripted naive retrieval is right on 14 pairs and wrong on 1; scripted oracle evidence is right on all 15.
- **The full-history ceiling fits the window at 0 of 85 checkpoints,** so its column is empty. No value is invented.
- **The floor's outcomes record no in-context field,** so "in context" is reported only for H and the scripted rows.

## What this does not prove

- Public lives, not fresh ones; five lives with scored actions; one reader model at one effort.
- One real system. The two scripted rows are not live retrieval results.
- A scripted life: no system's own judgment about what to store is tested.
- The live floor ran once; run 2 reused it.
- Kinds of task are the pack's own templates and twin types, read after the runs: this is exploratory.

## Reproduce

`by_kind.py` (beside this file) reads the two run trees and the pack's sealed controls. It prints counts, labels and 12-character hash prefixes only: never task text, answers, item or bundle ids, or paths. From a checkout of this repository at the commit that adds this file, with the run trees from the two evidence tags and the T2 pack (in run 2's bundle):

```
PYTHONPATH=<checkout>/src python3 -s -P by_kind.py --packs <packs> <run 1> <run 2>
```

Its output, verbatim:

```
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
  Drift, value twins: pairs 10
    naive retrieval (scripted): right 9 wrong 1 no_credit 0 non_result 0
    oracle evidence (scripted): right 10 wrong 0 no_credit 0 non_result 0
  KEEP-INC/fork: pairs 5
    naive retrieval (scripted): right 5 wrong 0 no_credit 0 non_result 0
    oracle evidence (scripted): right 5 wrong 0 no_credit 0 non_result 0

== I. Full history fits over lives
  run 0 of 85
```
