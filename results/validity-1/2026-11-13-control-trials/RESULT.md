# Validity round 1: the v2 templates' control trials (#505, #506)

Claim class: exploratory, developer-tier template validity. Seven live control arms (F no memory x2, R pinned naive retrieval x2, O oracle evidence x3) at one commit on one fresh, control-only validation pack, read by the rules in [`DECLARATION.md`](../DECLARATION.md), which was merged before the draw. No bar, no certification, no real system, and not predictive of the full tier.

## The result in one paragraph
All seven arms ran once each, in the declared order, at one commit; every check passed and no arm was rerun (one unit of the third oracle arm ran a second attempt; see the deviations). On each of the four v2 templates, the no-memory row scored 0, the oracle-evidence row scored 100 in each of its three trials, and the naive-retrieval row also scored 100. By the declared rule, `drift-chain-fault` v2, `drift-config` v2 and `drift-quote` v2 read **cleared**, and `recall-count` v2 reads **format validated**. So, on this pack and with this reader, the repairs work: with the needed evidence in view, the reader does each task the way the scorer reads it. But the flag "near-solved by naive retrieval" applies to all four, stable in all 12 combinations of repeats: on this pack, naive retrieval put the needed fact in front of the reader on 34 of the 35 target items. So on this pack none of the four can show that memory beats retrieval. The three cleared templates go to the fresh-seed follow-up as do-no-harm checks (Milestone 1 §6); the count question's answer format is validated only ([#512](https://github.com/electricsheephq/bicentennial/issues/512)). The no-memory row, the oracle row and the readings came out as predicted (`drift-quote`, predicted "unsure", cleared). Every naive-retrieval prediction missed: each range topped out at 20 or 60 points, and the row scored 100 on all four. For `drift-config`, the rewritten prompt is part of why: naive retrieval searches with the task's prompt, and on the same public lives the v1 prompt led it to the needed fact on none of the ten tasks, the v2 prompt on seven.

## The runs
- **Run commit** `0dfff9c91099262ef7631d87b6932bddc91c8da5`, the merge of [#517](https://github.com/electricsheephq/bicentennial/pull/517). It contains the declaration ([#513](https://github.com/electricsheephq/bicentennial/pull/513)), the send budget ([#515](https://github.com/electricsheephq/bicentennial/pull/515)), the reading script ([#516](https://github.com/electricsheephq/bicentennial/pull/516)), the v2 templates and template edition 2 ([#519](https://github.com/electricsheephq/bicentennial/pull/519)) and the roster script (#517).
- **Draw:** drawn at 16:07:05Z at the run commit. Its sha256 `c88cdf35f2a597290baffe85da356cb661943bc577a5f061bbfeff0ab8f42abb` and the run commit were posted on #505 ([16:07:32Z](https://github.com/electricsheephq/bicentennial/issues/505#issuecomment-6858319989)) before the pack was built. The drawn list ([`draw.json`](draw.json)), the validation spec ([`t2-validity.toml`](t2-validity.toml)) and the placement table ([`placement.json`](placement.json)) are published beside this page; `sha256sum draw.json` gives the posted hash.
- **Placement:** all ten design seeds placed on the first try, so no spare was used and nothing failed. Validation spec sha256 `e9e3768c684710fb711d7f16621ccb1d600c2b99ecd67afc84d1643a9e08fa25`, placement table sha256 `b65611ae748d8c8bc2bb65d8f58c347a365495f6642f034e19d542c9f7487b40`. With the seeds masked, the validation spec equals the public T2 spec.
- **Validation pack** hash `172b87bf9c60ed79c1b56fbccb0f8caba64f931124581c6d46f6838e55fc59b5` (template edition 2: version 2 of the four templates, version 1 of the other six). **[`TASKS.json`](TASKS.json)** sha256 `202c24ae6df54a1f0f94f4b16a83b0d5425c0fa338d051081c64855714d4f54c`, posted on #505 with the pack hash ([16:14:35Z](https://github.com/electricsheephq/bicentennial/issues/505#issuecomment-6858481556)) before the first arm started (16:14:40Z).
- **Code pins,** the same as Milestone 1's (measured on whole-tree checkouts of both run commits):

  | Pin | Milestone 1 (`42aea53`) | This round (`0dfff9c`) |
  |---|---|---|
  | controls | `848935cdb04f` | `848935cdb04f` |
  | reader | `90ed83e9bed4` | `90ed83e9bed4` |
  | scoring code | `925f3fc812fd` | `925f3fc812fd` |
  | scorer (every `score/*.py`) | `0e5979ff5aff` | `0e5979ff5aff` |

  Every arm's card names the run commit and carries Milestone 1's harness (`dbf03edef301`), route table (`0490592ab5b0`) and write-turn package (`cf5d8ed51482`) hashes.
- **Reader:** `gpt-6.1-sol` at `medium` effort, served as identity `6e0b2b52fc6f` (a sha256 prefix) on every arm, the same identity as in Milestone 1.
- **Order and times (UTC, 13 November 2026, from each arm's run record, as the reading script prints them):**

  | Position | Arm | Row | Start | End | Live sends (cap 1,000) |
  |---|---|---|---|---|---|
  | 1 | F1 | no memory | 16:14:40 | 16:29:34 | 394 |
  | 2 | R1 | naive retrieval | 16:29:49 | 16:59:48 | 358 |
  | 3 | O1 | oracle evidence | 17:00:00 | 17:22:22 | 353 |
  | 4 | O2 | oracle evidence | 17:22:33 | 17:41:30 | 351 |
  | 5 | R2 | naive retrieval | 17:41:39 | 18:02:26 | 354 |
  | 6 | F2 | no memory | 18:02:37 | 18:18:26 | 378 |
  | 7 | O3 | oracle evidence | 18:18:35 | 18:34:39 | 379 |

  The actual order is the declared one, so each row's centre is 3.5 as declared (O3 at 7). No arm was rerun.
- **Every invocation:** each label was invoked once, and each invocation was an attempt (it created its output). No invocation was refused.
- **Every run on this pack hash:** the seven arms above, and no other (§2: control rows only, before and after the results).
- **Run trees** are in the private evidence store under tag `bicentennial/validity1-20261113`, with the reader's diagnostics, the check-3 output, every operator log and the operator script.
- **How the run was held to the declaration** (the operator script's checks, as promised on #517): every step refuses unless the worktree is clean at the run commit; the draw needs a passed rehearsal at that commit; placement and the build refuse until the draw's #505 post is read back with its sha256 and the run commit; the task list is written whole, checked against the commit, edition, pack, draw and spec, and frozen by its sha256, and no arm runs until that post is read back; each label has one attempt and one rerun, numbered in run order, and no arm starts while another arm process runs or holds the reader login's lock; an invocation the runner refuses before creating output is not an attempt and would be listed here; the reruns used are the ones on disk, and no rerun is allowed once a table run has opened the scores or ended the round; check 3 has at most two attempts, and none after a pass; each #505 post is read back once, and refused if GitHub shows it edited (to the second) or if it is already the other post; the checked body is kept with its creation time; a void draw keeps its draw, hash, post, placement receipt and work directory together. The script was reviewed in four rounds by two reviewers from different model families before the draw, and every finding has a recorded disposition.
- **Run gate disclosure:** at the run commit, the T1/T2 run gate accepts edition-2 packs for any system. Control-only use rested on the run script (every arm passes `--control`) and on the reading script (it refuses a card without its control record). The gate rule is [#520](https://github.com/electricsheephq/bicentennial/issues/520).

## Deviations from the declaration
- **None in the arms:** each ran once, in the declared order, at the run commit, on the declared pack.
- **Before the run commit existed,** the rehearsal steps ran once on a local merge of main with #516, #519 and #517's head (`1fe59f1`), whose tree is identical to the run commit's: pack hash `3e58b801…`, equal to #519's evidence build. That merge also ran one live oracle arm on the public edition-1 T2 pack (Milestone 1's, `15141b19…`), to test the live arm path after the send-budget change (#515): 370 sends of the 1,000 allowed, 85 of 85 items scored, no infrastructure rerun, no change of served identity, and scores by template equal to the 13 November oracle arm's except for one item. Both were disclosed in the draw post, which went up under half a minute after the draw (27 seconds between the draw file's timestamp and the post's) and before the pack was built. No reader saw a v2 prompt before arm 1.
- **The official rehearsal** ran at the run commit before the draw, on the public T2 seeds: place, build (pack hash `3e58b801…`), install, the run gate, the task list, the reading's refusal path, and check 3 (18 tests passed).
- **The operator script** ran in its sixth revision for prep and the rehearsal and in its seventh for every later step; the two revisions are identical for prep and the rehearsal.
- **One unit ran a second attempt (disclosure, not a deviation from the declared procedure).** In O3, on its first attempt at one unit (one life and branch: four probe items, three of them target items, one from each Drift template), the reader edited `docs/decisions.md` for a `drift-chain-fault` v2 task and left an empty line between two entries. The repository reader rejects that line, so the state could not be read. The runner classes an unreadable state as an infrastructure failure and runs the unit again; on the second attempt all three target items passed. That rule is the runner's, unchanged since Milestone 1, but a file the reader leaves unreadable is the reader's own outcome, so it is filed as [#524](https://github.com/electricsheephq/bicentennial/issues/524). It changes nothing here: scored instead as a failed task (no credit), O3's `drift-chain-fault` v2 points would be 80, not 100, and c over the three trials 93⅓. c is the mean of O1 and O2; 80 is not below the low flag's 75; and the item still passes the oracle filter with two of three trials. Both attempts ran live; the unit's scores, and check 7, come from the second.

## Checks before any score (§4)
1. **Payload:** each R and O arm's 85 blocks equal the pinned control's text, byte for byte (85 of 85, 0 mismatched); F carries no block.
2. **Presence:** O had the needed fact in the probe turn's first request on all 35 target items in each of its three arms; R's presence equals the pack's scripted naive-retrieval report on 35 of 35 in both arms.
3. **Memory off:** the runner's three named tests passed at the run commit in the round's own check-3 run (its output starts with the run commit, shows 18 tests passed and ends with exit 0) and in CI at that commit ([run 43458091426](https://github.com/electricsheephq/bicentennial/actions/runs/43458091426), the push to main).
4. **Identity:** all seven arms were served `6e0b2b52fc6f`, and none disclosed a change of identity during the arm. Reference identity `6e0b2b52fc6f`; 0 arms mismatched.
5. **Completeness:** every arm scored all 35 target items; 0 BLOCKED, 0 missing.
6. **Common support:** every template uses all seven repeats (F1, F2, R1, R2, O1, O2, O3), each scoring every target item.
7. **Live units:** in every arm, 20 of 20 units ran live (0 cached or unconfirmed), and 85 of 85 probe records went to the live reader.

## The scale (§5)
An action pair scores the lower of its two twins' scores (+1 right, 0 no credit, −1 a confident false memory). A count question scores `score_milli / 1000` (keeping ±0.5). A template's points are 100 times its mean over its items on the common support, from −100 to +100; one pair or question is 20 points.

## The readings
Five bundles per template (five twin pairs, or five count questions). f and r are the means of F1, F2 and R1, R2; c is the mean of O1, O2.

| Template | f | r | c (O1, O2) | c over O1-O3 | low (c < 75) on the means | low with each O trial alone | Reading | Predicted |
|---|---|---|---|---|---|---|---|---|
| `drift-chain-fault` v2 | 0 | 100 | 100 | 100 | does not apply, margin −5/4 (−1.25) | no, no, no | **cleared** | cleared |
| `drift-config` v2 | 0 | 100 | 100 | 100 | does not apply, margin −5/4 (−1.25) | no, no, no | **cleared** | cleared |
| `drift-quote` v2 | 0 | 100 | 100 | 100 | does not apply, margin −5/4 (−1.25) | no, no, no | **cleared** | unsure |
| `recall-count` v2 | 0 | 100 | 100 | 100 | does not apply, margin −5/4 (−1.25) | no, no, no | **format validated** | format validated |

Margins are in bundles, as `table.py` prints them; one bundle (a pair or a count question) is 20 points, so the low flag's −5/4 means c is 25 points above 75. Every arm scored the same on every bundle of a template: F1 and F2 gave no credit on all 20 bundles (no confident false memory), and R1, R2, O1, O2 and O3 got all 20 right.

**Near-solved flags** (printed for every template; never part of the reading, §5), the same for all four templates:
- **Near-solved by naive retrieval** (r ≥ f + 0.7 (c − f)): applies, margin 3/2 (1.5 bundles, 30 points), stable in 12 of 12 combinations of repeats. Each template is labelled near-solved by naive retrieval: kept as a do-no-harm check and excluded from any claim that memory beats retrieval (Milestone 1 §6).
- **Near-solved without memory** (f ≥ 0.7 c): does not apply, margin −7/2 (−3.5 bundles, −70 points), stable in 6 of 6.

## The oracle filter (§5; [`FILTER.json`](FILTER.json))
Over O1, O2 and O3, every target item passed all three trials, and no trial was unscored. All 20 bundles are kept: 5 pairs each of `drift-chain-fault` v2, `drift-config` v2 and `drift-quote` v2, and 5 count questions.

## Disclosure counters (§5; read from the diagnostics after the scores; never gates)
Counts over the 35 target items of each arm, from [`counters.py`](counters.py) ([`counters.json`](counters.json)):
- **`drift-chain-fault` v2, entries written under the exact name:** 10 of 10 in every R and O arm. The no-memory arms left the file unchanged on all 10.
- **`recall-count` v2, answers the scorer could not read:** 0 in every arm. The no-memory arms' five answers each parsed and none gave the right count (each scored 0), so the shortcut [#512](https://github.com/electricsheephq/bicentennial/issues/512) describes, the right count with no memory, did not occur in this round.
- **`drift-config` v2:** changes on the hedged twins 0, and corrections left unapplied 0, in every R and O arm. The no-memory arms changed nothing, so they left all 5 corrections unapplied and passed the 5 hedged twins.
- **`drift-quote` v2, by the wording of the later statement:** every item was right in every R and O arm, so the result is the same whichever wording an item's later statement uses. (The readout's split looks for "It was said that" anywhere in the reader's first message, which can carry retrieved or handed-over text other than the item's own later statement; so its counts, 8 and 2 items in each R arm and 6 and 4 in each O arm, are not a split by the later statement's own wording.) The no-memory arms received no evidence: 10 omissions.

## Why naive retrieval scored 100 (read after the table; counts only; outside the declared reading)
From the `in_context_initial` field of each probe record and each pack's scripted naive-retrieval report (`sealed/naive_rag.json`, field `in_context`), with [`presence.py`](presence.py). Naive retrieval had the needed fact in the probe turn's first request on 34 of the 35 target items in both R arms (the one miss is a `drift-config` item, which R still passed); the oracle row had it on all 35. Naive retrieval ranks 240-character pieces of the life's messages against the task's own prompt (hashed TF-IDF, top five; `controls/naive_rag.py`, `query`), so a prompt's wording changes what it finds. Target items whose needed fact naive retrieval puts in view, by pack:

| Template | Public lives, v1 prompt (Milestone 1's pack) | Public lives, v2 prompt (the rehearsal build) | This pack, v2 prompt |
|---|---|---|---|
| `drift-chain-fault` | 10 of 10 | 10 of 10 | 10 of 10 |
| `drift-config` | 0 of 10 | 7 of 10 | 9 of 10 |
| `drift-quote` | 10 of 10 | 10 of 10 | 10 of 10 |
| `recall-count` | 5 of 5 | 5 of 5 | 5 of 5 |

These are the scripted reports; where a live R arm ran on the pack (Milestone 1's two and this round's two), its first requests match them item for item. On `drift-chain-fault`, `drift-quote` and `recall-count`, naive retrieval found the needed fact on every item with either prompt. In Milestone 1 it failed those tasks where the oracle row failed them: no row with evidence scored a `drift-chain-fault` task, it asserted the quoted value on 7 of 10 `drift-quote` tasks in both repeats, and three of its count answers did not parse. With the v2 prompts, neither row failed them on this pack. On `drift-config`, the v2 prompt's own words led retrieval to the needed fact: on the same public lives, on none of ten tasks with the v1 prompt and on seven with v2 (the two builds of the public lives have the same histories and the same needed facts; only the task prompts differ).

The predictions were written before any v2 pack existed. The rehearsal build, made at the run commit before the draw, already shows naive retrieval finding the needed fact on 32 of the 35 target items, but its report was not read until after the table.

## Predictions (§7) against the result (points; one pair or question = 20)
| Template | F predicted | F | R predicted | R | O (c) predicted | c | Reading predicted | Reading |
|---|---|---|---|---|---|---|---|---|
| `drift-chain-fault` v2 | −20 to 0 | 0 | −60 to 20 | **100** | 60 to 100 | 100 | cleared | cleared |
| `drift-config` v2 | −20 to 0 | 0 | −40 to 20 | **100** | 60 to 100 | 100 | cleared | cleared |
| `drift-quote` v2 | −20 to 0 | 0 | −60 to 20 | **100** | 40 to 100 | 100 | unsure | cleared |
| `recall-count` v2 | 0 | 0 | 0 to 60 | **100** | 80 to 100 | 100 | format validated | format validated |

F and c fell inside every predicted range, and the readings came out as predicted, with `drift-quote` (predicted "unsure: low is as likely as cleared") reading cleared. Every R prediction missed, by 40 to 80 points above the top of its range.

## What this does not prove (§9)
- One reader at one effort, one pack, five pairs or questions per template (one = 20 points).
- Control rows only: nothing about any memory system, and no claim that memory beats retrieval.
- The count question: its answer format only ([#512](https://github.com/electricsheephq/bicentennial/issues/512)).
- Scripted lives: no system's own judgment about what to store is tested.
- The seed rules borrow Ring 1's; this is not a Ring 1 run.
- That naive retrieval solves these templates on every set of lives: one pack. The `drift-config` count above differs between lives with the same prompt (7 of 10 and 9 of 10).
- Why the reader acted right on every retrieved fact: the diagnostics' counts above say what it did, not why.

## What follows (§6)
- **Cleared** (`drift-chain-fault` v2, `drift-config` v2, `drift-quote` v2): each enters the fresh-seed follow-up ([#394](https://github.com/electricsheephq/bicentennial/issues/394)) with every other kind. All 15 of their pairs passed the oracle filter and are listed in `FILTER.json`. Each carries the label "near-solved by naive retrieval": a do-no-harm check, excluded from any claim that memory beats retrieval.
- **Format validated** (`recall-count` v2): a right count now scores. The question still cannot rank memory, because its answer is 2 on every T2 life ([#512](https://github.com/electricsheephq/bicentennial/issues/512)).
- **No template read low, unstable or unresolved,** so no v3, extension pack or new round follows from this reading.
- **Before any system runs on edition 2:** the run gate must refuse a system run on a template version that has not cleared ([#520](https://github.com/electricsheephq/bicentennial/issues/520)); these readings are what it admits.
- **Before the next published live run:** an edit the reader leaves unreadable is scored as the reader's, not rerun as infrastructure ([#524](https://github.com/electricsheephq/bicentennial/issues/524)).
- **For the next template version:** a prompt is also naive retrieval's query, so a new version's scripted naive-retrieval report on the public lives (it needs no reader) is read before its predictions are written.
- On this pack, none of these four templates leaves a memory system room to beat naive retrieval. In Milestone 1 the only kind with that room was Wake (r 0, c 100).

## Reproduce
`table.py` ([`../v2-control-trials/table.py`](../v2-control-trials/table.py), at the run commit) reads the run trees, the validation pack, the frozen task list and the output of check 3's tests. It prints counts, labels, pass or fail and 12-character hash prefixes only: never task text, answers, item or bundle ids, or paths. Its output from this round's reading is [`table-output.txt`](table-output.txt), verbatim, and it wrote `FILTER.json`. From a checkout of this repository at the run commit, in a virtual environment with the package installed, and with the run trees, the pack and check 3's output from the evidence tag:

```
python results/validity-1/v2-control-trials/table.py --tasks TASKS.json --tasks-sha256 202c24ae6df54a1f0f94f4b16a83b0d5425c0fa338d051081c64855714d4f54c --packs <packs> --order F1,R1,O1,O2,R2,F2,O3 --attempts F1,R1,O1,O2,R2,F2,O3 --check3 <check3 output> --filter-out FILTER.json F1=<run> R1=<run> O1=<run> O2=<run> R2=<run> F2=<run> O3=<run>
```

The counters and the presence table come from the same trees; the counters also read the private diagnostics. The other two packs in the presence table are public: Milestone 1's (`15141b19…`, in its evidence tag) and the rehearsal build (the public T2 spec built at the run commit with template edition 2, `3e58b801…`, in this round's tag).

```
python -I counters.py --diag <diagnostics of the arm> --run <run> --packs <packs> --edition 2 --tasks TASKS.json
python -I presence.py --tasks TASKS.json --packs <packs> [--scripted <other packs> ...] R1=<run> R2=<run> O1=<run> O2=<run> O3=<run>
```
