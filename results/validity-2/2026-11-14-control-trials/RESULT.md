# Validity round 2: the control trials of three Drift finalists and Wake (#536)

Claim class: exploratory, developer-tier template validity. Thirteen live control arms (F no memory x2, R pinned naive retrieval x2, B BM25 x2, G scripted grep x2, W recent window x2, O oracle evidence x3) at one commit on one fresh, control-only validation pack of ten G1 lives, read by the rules in [`DECLARATION.md`](../DECLARATION.md), which was merged before the draw. No bar, no certification, no real system, and not predictive of the full tier.

## The result in one paragraph
All thirteen arms ran once each, in the declared order, at one commit. Every check passed: no arm compacted, none reached the send cap, all were served one identity, and none was rerun (one arm redid five units after harness timeouts; see the disclosures). On all four templates the oracle-evidence row scored 100 in each of its three trials, the no-memory row scored 0, and naive retrieval and BM25 scored 0. Grep scored 0 on the three Drift finalists and 20 on `wake-loop`; the recent window scored 0 on `drift-chain-fault` and `drift-quote`, 10 on `drift-config` and 25 on `wake-loop`. No arm scored any pair −1. By the declared rule, all four read **ranking candidate**: the best of the four anchors is at most 25, no near-solved flag applies, and every flag reads the same in every combination of repeats. So, on this pack and with this reader, the oracle row is at least 75 points above the best of the four lexical and positional anchors on each of the four: room a memory system could use, not a gain any system has shown. The fresh-seed follow-up ([#394](https://github.com/electricsheephq/bicentennial/issues/394)) starts with these four as its ranking set. Twenty-two of the 24 predicted cells held, and every reading came out as predicted. The two misses are `wake-loop`'s grep (20; predicted 0, range −20 to 10) and recent window (25; predicted 0, range −20 to 20). Those predictions came from the scripted anchor report on another set of lives, where each anchor scored 0. On this pack the scripted reports, which use no live reader, also fall above both ranges (grep 20, recent window 30): live grep matched its scripted score, and the live recent window scored 5 points lower.

## The runs
- **Run commit** `37407877fe43f00a1c7c2b49d5df19109509bf85`, the merge of [#550](https://github.com/electricsheephq/bicentennial/pull/550) (the control-only pack list, [#529](https://github.com/electricsheephq/bicentennial/issues/529)). It contains the declaration ([#555](https://github.com/electricsheephq/bicentennial/pull/555)), template edition 3 ([#551](https://github.com/electricsheephq/bicentennial/pull/551)), the seed tool's round 2 ([#552](https://github.com/electricsheephq/bicentennial/pull/552)) and the reading script ([#554](https://github.com/electricsheephq/bicentennial/pull/554)).
- **Draw:** drawn at 13:31:30Z at the run commit. Its sha256 `176962c47d70da85b23fc86fd6e392fda700b9eac93d92011ca6ab68b1700a6b` and the run commit were posted on #536 ([13:32:02Z](https://github.com/electricsheephq/bicentennial/issues/536#issuecomment-6878020791) by GitHub's clock). The run script read the post back at 13:31:57Z by the machine's clock, which ran at least 5 seconds behind GitHub's: 27 seconds after the draw, on the same clock, and before the pack was built. The drawn list ([`draw.json`](draw.json)), the validation spec ([`t2-validity.toml`](t2-validity.toml)) and the placement table ([`placement.json`](placement.json)) are published beside this page; `sha256sum draw.json` gives the posted hash.
- **Placement:** all ten design seeds placed on the first try, so no spare was used and nothing failed. Validation spec sha256 `1279f52378e711136c952a045b7554560f2d1d06a8990fc385d130acf2efb521`, placement table sha256 `0028b6a209db7f1788f30228513f32d566fe74a75c48f73396bbc795fca52dce`. Every setting in the validation spec equals the public T2 spec's, and each of its ten lives has the public spec's G1 life shape; only the seeds differ, and every life is G1 (§2).
- **Validation pack** hash `a850d736367f010d5613508ba097cddab6076ee04a6903e6de103d5ab9faaf69` (template edition 3: version 3 of the three Drift finalists, `wake-loop` version 1, version 1 of the others). **[`TASKS.json`](TASKS.json)** sha256 `68875226655e2fc1cb6aa47675bbe8995716dd941d04641145ff3bac905ec3c4`, posted on #536 with the pack hash ([13:37:42Z](https://github.com/electricsheephq/bicentennial/issues/536#issuecomment-6878085969) by GitHub's clock); the run script read the post back at 13:37:37Z by the machine's clock, 5 seconds before F1's invocation started. The pack's hash joined the control-only list in [#561](https://github.com/electricsheephq/bicentennial/pull/561) before these results, so a non-control run on it is refused whatever any admission says.
- **Code pins,** the same as round 1's (measured on whole-tree checkouts of both run commits):

  | Pin | Round 1 (`0dfff9c`) | This round (`3740787`) |
  |---|---|---|
  | controls | `848935cdb04f` | `848935cdb04f` |
  | reader | `90ed83e9bed4` | `90ed83e9bed4` |
  | scoring code | `925f3fc812fd` | `925f3fc812fd` |
  | scorer (every `score/*.py`) | `0e5979ff5aff` | `0e5979ff5aff` |

  Every arm's card names the run commit and carries Milestone 1's harness (`dbf03edef301`), route table (`0490592ab5b0`) and write-turn package (`cf5d8ed51482`) hashes.
- **Reader:** `gpt-6.1-sol` at `medium` effort, served as identity `6e0b2b52fc6f` (a sha256 prefix) on every arm, the same identity as in round 1 and Milestone 1.
- **Order and times (UTC, 14 November 2026, from each arm's run record, as the reading script prints them):**

  | Position | Arm | Row | Start | End | Live sends (cap 1,000) |
  |---|---|---|---|---|---|
  | 1 | F1 | no memory | 13:37:44 | 13:53:44 | 508 |
  | 2 | R1 | naive retrieval | 15:00:56 | 15:23:55 | 520 |
  | 3 | B1 | BM25 | 15:23:59 | 15:42:00 | 518 |
  | 4 | G1 | grep | 15:42:04 | 16:03:20 | 503 |
  | 5 | W1 | recent window | 16:15:27 | 16:34:11 | 502 |
  | 6 | O1 | oracle evidence | 16:34:15 | 17:02:50 | 418 |
  | 7 | O2 | oracle evidence | 17:02:56 | 17:26:16 | 418 |
  | 8 | W2 | recent window | 17:26:22 | 17:44:28 | 528 |
  | 9 | G2 | grep | 17:44:32 | 18:05:16 | 508 |
  | 10 | B2 | BM25 | 18:05:20 | 18:41:04 | 546 |
  | 11 | R2 | naive retrieval | 18:41:10 | 19:47:01 | 520 |
  | 12 | F2 | no memory | 19:47:10 | 20:20:09 | 504 |
  | 13 | O3 | oracle evidence | 20:20:13 | 20:39:08 | 419 |

  The actual order is the declared one, so each row's centre is 6.5 as declared (O3 at 13). No arm was rerun.
- **Waiting for an idle machine.** The run script starts an arm only when the machine's busy marker shows no other benchmark work. R1's first invocation waited 61 minutes (13:53:45Z to 14:54:53Z) while another session's benchmark row ran, then gave up (exit 4) before the run script numbered an invocation: no pack read, no unit, no send, so it is not an attempt. The second started at 14:56:53Z, waited four minutes, and started its arm at 15:00:53Z. W1's invocation waited 12 minutes (16:03:22Z to 16:15:23Z). Neither wait changed the order.
- **Every invocation:** apart from R1's first invocation above, each label was invoked once, and each invocation was an attempt (it created its output). The runner's machine guard refused no invocation of this round's arms (zero for each of the thirteen labels).
- **Every run on this pack hash:** the thirteen arms above, and no other so far (§2: control rows only); the control-only list (#561) refuses any later non-control run on it.
- **Run trees** are in the private evidence store under tag `bicentennial/validity2-20261114`, with the reader's diagnostics, check 3's output, every operator log, the operator scripts, and the records of the anchor check and the oracle smoke. Every arm's card is published beside this page in [`cards/`](cards/), cut by [`cut_cards.py`](cards/cut_cards.py) to the 80 target items: the entries of each life's `recall-value` item, which hold scores this round never read, are left out, and every other field is the run tree's. [`full-card-sha256.json`](cards/full-card-sha256.json) gives the sha256 of each full card, which stays in the evidence store. Every card reads `"seed_source": {"kind": "public"}`, because the run commit's runner writes that value for every T2 run ([`t2.py`, line 117](https://github.com/electricsheephq/bicentennial/blob/37407877fe43f00a1c7c2b49d5df19109509bf85/src/bicentennial/runner/t2.py#L117)); this pack's lives came from the hidden draw that [`draw.json`](draw.json) now publishes, not from public seeds ([#571](https://github.com/electricsheephq/bicentennial/issues/571)). F1's and F2's full cards share one sha256: a card holds no label, times or sends, and the two no-memory arms scored every item alike, so their cards are byte-identical, while their run trees differ.
- **How the run was held to the declaration:** round 1's operator script, adapted for this round's labels, rows, edition and issue, and published beside this page as [`run-v2.sh`](run-v2.sh) with local paths replaced; every arm ran this version, last changed before the draw. Its checks are round 1's (listed on [round 1's page](../../validity-1/2026-11-13-control-trials/RESULT.md#the-runs)), with check 8's compaction rule added to the arms' reruns. It was reviewed before the draw by a Codex reviewer (`gpt-6-astra`) in two rounds, and by a fresh Claude reviewer in the second. The guard rule below, and then its narrowing, were each reviewed by the Codex reviewer; those reviews and the fixes they led to are in the evidence store. A fresh Claude reviewer (`claude-opus-5-5`) reviewed each as well; its two reports were not saved as files at the time, and are copied verbatim from the reviewer's transcript into the evidence store beside the others. The arms were invoked one at a time, in the declared order, by a small wrapper, `chain-arms.sh` (in the evidence store), written after the draw and before F1 (13:33:51Z). It stopped at the first fault that would also spoil the next arm, and when an invocation made no attempt (exit 3, the machine guard's refusal, or exit 4, no idle machine within the wait) it ran the same command again after two minutes, as the run script says to. Its log counts its own calls, so R1's two appear there as invocations 1 and 2; the run script numbered only the second.
- **The guard rule** (a clarification of the run script, made after the declaration and before any arm): a refusal by the runner's machine guard, which comes before any pack read, unit or send, is not an attempt. Such a refusal uses neither the label's attempt nor its rerun. Every invocation is published with its exit and, for a refusal, its retained refusal record and diagnostics; every other invocation that created output counts as an attempt. No arm of this round was refused that way. The anchor check's three refused invocations are listed below.
- **Run gate:** at the run commit, the gate accepts this pack's composition (ten G1 lives on edition 3) for control runs only ([#539](https://github.com/electricsheephq/bicentennial/issues/539)), and every arm passed `--control`.

## Before the run: the rehearsal, the anchor check and the oracle smoke
- **The rehearsal** (the run script requires a passed rehearsal at the run commit before the draw; disclosed in the draw post): from 09:14:56Z, at the run commit, the run script rehearsed its place, build, install, run-gate, task-list, reading and check-3 steps on the committed screening seeds (design seeds 2001 to 2010), and every step passed. Placement found ten G1 lives with no replacement; the edition-3 pack built (hash `4b8a98f3bdd8`) and installed; the run gate accepted a control run and refused a system run (`template_not_admitted`); the task list held its 80 target rows, 20 per template; the reading script, run with no arms, listed every arm as missing and computed no check and no reading; and check 3 passed (71 tests). That refusal path is the only reading the rehearsal made; its output, copied from the rehearsal's log, is [`rehearsal-reading-output.txt`](rehearsal-reading-output.txt). The reading on this page's pack is the one in [`table-output.txt`](table-output.txt). No reader saw the rehearsal pack, and nothing in it was drawn.
- **The oracle smoke** ([#535](https://github.com/electricsheephq/bicentennial/issues/535)) ran one live oracle arm on the public lives built with edition 3, at the commit that registered it, with the cap at 1,000: each finalist scored 5 of 5 pairs right, 343 sends for 85 probe turns, no compaction. It kept all three finalists.
- **The anchor check** ([#536](https://github.com/electricsheephq/bicentennial/issues/536)): one live arm each of B, G and W on the public lives at `d4ce038`, to test the anchor rows' live path before the draw. B's invocation ran from 12:15:02Z to 12:27:34Z, G's from 12:55:40Z to 13:14:17Z and W's from 13:14:17Z to 13:31:11Z; each arm's own run record starts and ends within two seconds of these. Each completed its 20 units and 85 probe items with no rerun and no compaction, served the configured model, and used 397, 373 and 399 sends. Only completion, sends, compaction and identity were read; no score.
- **Three refused invocations of the anchor check.** From 09:03:57Z to 09:04:04Z, the anchor check's first operator script started one invocation per anchor (B, then G, then W) without waiting for an idle machine, while the busy marker showed another benchmark row running: a mistake in that script. The runner's machine guard refused each before reading the pack (`roots_below_min`: with another row running, the marker allowed fewer parallel workers than the spec's minimum). None read a pack, ran a unit or made a send:

  | Anchor | Start | End | Exit | Refusal record | Standard output | Standard error | Diagnostics |
  |---|---|---|---|---|---|---|---|
  | B (`bm25`) | 09:03:57Z | 09:04:00Z | 3 | `{"code":"roots_below_min"}` | empty | `roots_below_min` | a manifest listing no file |
  | G (`grep`) | 09:04:00Z | 09:04:02Z | 3 | `{"code":"roots_below_min"}` | empty | `roots_below_min` | a manifest listing no file |
  | W (`recent_window`) | 09:04:02Z | 09:04:04Z | 3 | `{"code":"roots_below_min"}` | empty | `roots_below_min` | a manifest listing no file |

  That script numbered no invocations and kept no sequence numbers, so these records have none. They show the refusal's shape, not the race the guard rule is for (other work starting after an arm's idle check): the marker already showed another row when they started. They were moved aside by hand into the anchor check's `refused-1/` folder (per anchor: the output and diagnostics folders, standard output and error, start and end times, and the busy marker's reading, 10) and, under the guard rule, are not attempts. The script was then given the marker wait. A launch at 09:08:35Z waited at the marker and was stopped before starting any arm, so that its record keeping could be fixed after review; the launch at 09:12:39Z ran the three arms above, waiting for an idle marker before each. It would have archived any refusal itself, under a numbered invocation, and there was none. That launch carried the guard rule's first Codex-reviewed version; this round's run script carries the narrowed version. No later invocation was refused under either.
- The records of the rehearsal, the oracle smoke and the anchor check, its three refusals included, are in the evidence store with this round's run trees. Beside this page, [`smoke/`](smoke/) publishes the oracle smoke's reading of the three finalists (`oracle-reading.txt`, made by `read_smoke.py`) and both checks' run records without any score (`records.json`, made by `records.py`: each arm's times, units, probe items, item reruns, compaction, sends, run status and served identity). Their cards stay in the evidence store, because they also hold scores that were never read: all of the anchor check's, and the smoke's for every template but the finalists.

## Deviations from the declaration
- **None in the arms:** each ran once, in the declared order, at the run commit, on the declared pack; none compacted and none reached the cap.
- **Sends above the first projection (a disclosure, not a deviation from the declared procedure).** The arms used 418 to 546 sends for 90 probe turns, 4.6 to 6.1 a turn, above round 1's 4.1 to 4.6 (§3). The three oracle arms (418, 418 and 419) matched the first projection (about 420 an arm); the other ten (502 to 546) were above it. Every arm stayed within the second projection (about 790, if every send had gone to G1 turns) and below the cap of 1,000; none was refused. Round 1's rate mixed G1 and G2 turns; every probe turn of this pack is on a G1 life, which is what the second projection allowed for.
- **R2 redid five of its twenty units (a disclosure, not a deviation from the declared procedure).** Between about 18:57Z and 19:34Z every unit then running stalled: each took 38 to 47 minutes instead of about 10 to 12, including three that finished on their first attempt. In that window, 24 starts of the reader's worker timed out (`open_timeout`, a harness failure), in five units: four needed a second attempt and one a third (27 item reruns in all, as the run record counts them). The runner voided those attempts and scored only each unit's last, as the declared procedure says. Each arm's receipt records the machine's load averages when it is written, at the arm's end: R2's 15-minute load average was 29.2, the highest of the thirteen (R1's was 10.5; the other twelve ranged from 10.2 to 19.7). B2 and F2 took about twice as long as their first repeats and R2 almost three times, but only R2 had any rerun. The run records no cause for the stall beyond the `open_timeout` diagnostics. R2's scored outcomes equal R1's item for item: all 90 probe items have the same score, failure class, verdict and chosen option. The run commit does not record why an attempt failed ([#481](https://github.com/electricsheephq/bicentennial/issues/481); a per-arm count of such events arrived later, in [#560](https://github.com/electricsheephq/bicentennial/pull/560)), so the cause was read from each item's diagnostics. No other arm had a timeout.

## Checks before any score (§4)
1. **Payload:** each R, B, G, W and O arm's 90 blocks equal the pinned control's text, byte for byte (90 of 90, 0 mismatched, 0 recorded but not recomputed); F carries no block. B's, G's and W's control records name their anchors at the spec and code hashes their cards' predictions were made against, G's and W's carry `reader_window` 32,768, and both checks pass for every arm.
2. **Presence:** O had the needed fact in the probe turn's first request on all 80 target items in each of its three arms. Each of R, B, G and W matches the pack's scripted report for its anchor on 80 of 80 target items, in both of its arms.
3. **Memory off:** check 3's run at the run commit passed. [`check3-output.txt`](check3-output.txt) starts with the run commit, shows 71 tests passed and ends with exit 0; it is published with two local paths replaced. Its 71 tests include the 15 the reading script requires: the floor's memory-off test, each block row's block test, each anchor's presence test and each arm's reader configuration. CI at the run commit passed too ([run 43579503101](https://github.com/electricsheephq/bicentennial/actions/runs/43579503101), the push to main).
4. **Identity:** all thirteen arms were served `6e0b2b52fc6f`, and none disclosed a change of identity during the arm. Reference identity `6e0b2b52fc6f`; 0 arms mismatched.
5. **Completeness:** every arm scored all 80 target items; 0 BLOCKED, 0 missing.
6. **Common support:** every template uses all thirteen repeats (F1 to O3), each scoring every target item.
7. **Live units:** in every arm, 20 of 20 units ran live (0 cached or unconfirmed), 90 of 90 probe records went to the live reader, and no unit stopped.
8. **No compaction:** no arm's receipt records any `summariser` tokens, from any attempt of any unit.

**Unreadable state:** no arm labelled any item `unreadable_state` (0 in each of the thirteen arms, from each arm's disclosure record), so the rule of #524 and #537 changed no score.

## The scale (§5)
An action pair scores the lower of its two twins' scores (+1 right, 0 no credit, −1 a confident false memory). A template's points are 100 times its mean over its pairs on the common support, from −100 to +100; one pair is 10 points.

## The readings
Ten bundles (twin pairs, one per life) per template. f, r, b, g and w are the means of each row's two arms; c is the mean of O1 and O2.

| Template | f | r | b | g | w | c (O1, O2) | c over O1-O3 | Best anchor | Reading | Predicted |
|---|---|---|---|---|---|---|---|---|---|---|
| `drift-chain-fault` v3 | 0 | 0 | 0 | 0 | 0 | 100 | 100 | 0 | **ranking candidate** | ranking candidate |
| `drift-config` v3 | 0 | 0 | 0 | 0 | 10 | 100 | 100 | 10 (w) | **ranking candidate** | ranking candidate if W stays at or below 35; otherwise cleared |
| `drift-quote` v3 | 0 | 0 | 0 | 0 | 0 | 100 | 100 | 0 | **ranking candidate** | ranking candidate |
| `wake-loop` v1 | 0 | 0 | 0 | 20 | 25 | 100 | 100 | 25 (w) | **ranking candidate** | ranking candidate |

- **The best anchor is at most 35** for every template: the highest is `wake-loop`'s recent window, 25.
- **No near-solved flag applies,** on the means or in any combination of repeats. Each anchor's flag (x ≥ f + 0.7 (c − f)) reads "does not apply" in 12 of 12 combinations, and the floor's (f ≥ 0.7 c) in 6 of 6. The closest is the recent window's on `wake-loop`, 4.5 pairs (45 points) below its threshold; then grep's on `wake-loop` (5 pairs) and the recent window's on `drift-config` (6 pairs); every other flag is 7 pairs below. Margins are in pairs, as `table.py` prints them.
- **Low (c < 75)** does not apply to any template, on the means or with any O trial alone: c is 25 points above 75.
- **Arm by arm:** O1, O2 and O3 got all 40 pairs right. G1 and G2 each got 2 `wake-loop` pairs right; W1 and W2 each got 1 `drift-config` pair right; on `wake-loop`, W1 got 2 right and W2 got 3. Every other pair in every F, R, B, G and W arm got no credit, and no arm gave a confident false memory on any pair.

## Scripted beside live (§5)
Each anchor's scripted report, computed when the pack was built and with no live reader, scored on the same scale over the same 40 pairs, beside the live row (the mean of its two arms). Printed only; never part of a reading.

| Template | Naive retrieval, scripted / live | BM25 | Grep | Recent window |
|---|---|---|---|---|
| `drift-chain-fault` v3 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| `drift-config` v3 | 0 / 0 | 0 / 0 | 0 / 0 | 10 / 10 |
| `drift-quote` v3 | 0 / 0 | 0 / 0 | 0 / 0 | −10 / 0 |
| `wake-loop` v1 | 0 / 0 | 0 / 0 | 20 / 20 | 30 / 25 |

They agree on 14 of the 16 cells. On `drift-quote`, the scripted recent window scored −10, where neither live W arm lost a point. On `wake-loop` it scored 30, as W2 did; W1 scored 20. The reading prints net points only, so the scripted pairs are not broken down here.

## The oracle filter (§5; [`FILTER.json`](FILTER.json))
Over O1, O2 and O3, every target item passed all three trials, and no trial was unscored. All 40 bundles are kept, ten pairs per template (§7 expected at least 36).

## Predictions (§7) against the result (points; one pair = 10)
Each cell: the result, then the prediction (central value; range). The two misses are in bold.

| Template | F | R | B | G | W | c | Reading |
|---|---|---|---|---|---|---|---|
| `drift-config` v3 | 0 (0; −10 to 0) | 0 (0; −20 to 10) | 0 (0; −20 to 10) | 0 (0; −20 to 10) | 10 (25; 0 to 60) | 100 (95; 80 to 100) | ranking candidate (predicted: ranking candidate if W stays at or below 35; otherwise cleared) |
| `drift-quote` v3 | 0 (0; −10 to 0) | 0 (0; −20 to 10) | 0 (0; −20 to 10) | 0 (0; −20 to 10) | 0 (−35; −70 to 0) | 100 (95; 80 to 100) | ranking candidate (predicted) |
| `drift-chain-fault` v3 | 0 (0; −10 to 0) | 0 (0; −20 to 10) | 0 (0; −20 to 10) | 0 (0; −20 to 10) | 0 (0; −20 to 20) | 100 (95; 80 to 100) | ranking candidate (predicted) |
| `wake-loop` v1 | 0 (0; −10 to 0) | 0 (0; −20 to 10) | 0 (0; −20 to 10) | **20 (0; −20 to 10)** | **25 (0; −20 to 20)** | 100 (100; 80 to 100) | ranking candidate (predicted) |

- **22 of the 24 cells held,** and all four readings came out as predicted.
- **The two misses, on `wake-loop`,** are 10 and 5 points above the top of their ranges. Wake's predictions came from edition 1's scripted anchor report on the screening set, where each anchor scored 0. On this pack the scripted reports also fall above both ranges: grep 20 and the recent window 30. Live grep matched its scripted score, and the live recent window scored 5 points lower (W1 20, W2 30). Check 2 shows that the live anchor arms had the needed fact in their first request on exactly the items where the scripted reports put it; it measures presence, not why a pair was scored. `wake-loop` still ranks: its best anchor is 75 points below c.
- **`drift-config`'s known risk** (§7): four or more lives with the first long sprint in session 2 would have put W above 35 and stopped it from ranking. Under the placement model that had a probability of about 22%, which is not the probability of a ranking reading, because the live scores and every stability check still decide. W scored one pair in each of its two arms (10 points).
- **§7's checks:** no arm compacted; no arm reached the send cap; all thirteen arms were served one identity; the filter kept 40 of the 40 pairs (at least 36 expected). All four held.

## What this does not prove (§9)
- One reader at one effort, one pack, ten pairs per template: one pair is 10 points.
- Control rows only: nothing about any memory system.
- "Retrieval" means the four lexical and positional anchors; dense retrieval is untested.
- On `drift-quote` and `drift-chain-fault` a pass shows that the scored entry is right, not that the sweep was complete.
- Scripted lives; not a Ring 1 run.
- A ranking candidate is a ranking candidate on this pack with this reader: never cell admission, a Stage A census, "calibrated", or a validated ranking task.
- On `drift-config` the recent window scores every life whose first long sprint is in session 2, so its reading depends on this pack's placement.
- Why grep and the recent window found `wake-loop`'s evidence on some of these lives: the counts above say where, not why.

## What follows (§6)
- **Ranking candidates:** `drift-chain-fault` v3, `drift-config` v3, `drift-quote` v3 and `wake-loop` v1. Each v3 is admitted in the run gate's admission list (`specs/ring0/template-admissions.json`) by a separate change after this page merges, with the reading `cleared`, which is what the gate checks, and the label "ranking candidate"; #529, which §6 requires first, landed in the run commit. `wake-loop` v1 is in edition 1, which the gate already admits. The cleared v2 of each Drift id stays admitted, for edition 2.
- **The fresh-seed follow-up ([#394](https://github.com/electricsheephq/bicentennial/issues/394)) starts,** with these four as its frozen ranking set; every other kind is carried descriptively. Edition 3 holds all three v3s, so the follow-up needs no new edition (§6). Its declaration ([PLAN](../PLAN.md) §7: 30 fresh lives in three packs, each with the rows F R O H H O R F O and then B, G and W) is merged before its seeds are drawn.
- **No template read low, unstable or unresolved,** so no extension pack follows.
- **Before the follow-up's first system arm:** [#526](https://github.com/electricsheephq/bicentennial/issues/526) lands, because it decides what is rerun and what is scored ([PLAN](../PLAN.md) §8).
- On this pack, all four templates leave room above every anchor: c is 100, and the best anchor is at most 25. Whether a memory system uses that room is the follow-up's question.

## Reproduce
`table.py` ([`../control-trials/table.py`](../control-trials/table.py), at the run commit) reads the run trees, the validation pack, the frozen task list and the output of check 3's tests. It prints counts, labels, pass or fail and 12-character hash prefixes only: never task text, answers, item or bundle ids, or paths. Its output from this round's reading is [`table-output.txt`](table-output.txt), verbatim; it was the only run of the reading script on this pack, and it wrote `FILTER.json` (the rehearsal's run, with no arms, is described above). `TASKS.json` was published after the run, so copy it out of main first. Then, from the root of a checkout at the run commit, in a virtual environment with the package installed, and with the run trees, the pack and check 3's output from the evidence tag (the copy beside this page differs from it in two local paths only):

```
git checkout 3740787
F=$(mktemp -d); git show origin/main:results/validity-2/2026-11-14-control-trials/TASKS.json > "$F/TASKS.json"
python results/validity-2/control-trials/table.py --tasks "$F/TASKS.json" --tasks-sha256 68875226655e2fc1cb6aa47675bbe8995716dd941d04641145ff3bac905ec3c4 --packs <packs> --order F1,R1,B1,G1,W1,O1,O2,W2,G2,B2,R2,F2,O3 --attempts F1,R1,B1,G1,W1,O1,O2,W2,G2,B2,R2,F2,O3 --check3 <check3 output> --filter-out FILTER.json F1=<run> R1=<run> B1=<run> G1=<run> W1=<run> O1=<run> O2=<run> W2=<run> G2=<run> B2=<run> R2=<run> F2=<run> O3=<run>
```
