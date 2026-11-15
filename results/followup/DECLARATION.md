# Fresh-seed follow-up declaration: Hermes native beside the controls on the four ranking kinds

**Status:** written 14 November 2026 (UTC), with its draw amended on 15 November, after validity round 2's results ([page](../validity-2/2026-11-14-control-trials/RESULT.md)), before any seed for this run is drawn and before any of its arms runs. It is merged before the draw, and the results page names its commit. This is an **exploratory, developer-tier** run on fresh seeds with Ring 1's seed rules borrowed, except its draw (§2, §9), and not its full contract ([PLAN](../validity-2/PLAN.md) D1): no bar, no rank, no certification, not "Ring 1", and not predictive of the full tier (PREREG-v0.5 §6). It was reviewed before merging by a model family other than the author's and by fresh Claude reviewers. The other family's passes are published beside it verbatim, the Claude reviewers' findings in summary, each with how it was used ([declaration](reviews/2026-11-14-declaration-review.md), [draw](reviews/2026-11-15-draw-amendment-review.md)).

## 1. Why, and what is read
Round 2 found four **ranking candidates** on one control-only pack: `drift-chain-fault` v3, `drift-config` v3, `drift-quote` v3 and `wake-loop` v1. On each, the oracle-evidence row scored 100 and the best of four lexical and positional anchors at most 25. This run asks two questions on 30 fresh lives that no one had seen when the system and the controls were frozen, 15 of them with scored actions ([PLAN](../validity-2/PLAN.md) §7, [#394](https://github.com/electricsheephq/bicentennial/issues/394)):
- **Room:** on fresh lives, does the oracle row still sit above every anchor on the ranking kinds?
- **Use:** how much of that room does a real memory system use? The system is **Hermes native** (H), as registered, the only system this run reads.

The four kinds are the **frozen ranking set**. The packs' other scored kinds are printed descriptively, except `recall-count-v1`, which is carried unread (§5). No kind is promoted or dropped because of how H scored on it.

## 2. The lives
- **Thirty lives from one draw,** at the run commit, after this declaration merges: thirty design seeds and forty-eight ordered spares, derived from a public beacon round named before its value exists (next item), disjoint from every committed seed. Positions 1 to 30; odd positions are G1 (software partner, scored actions), even positions G2.
- **The draw, so that no one can choose the lives, the operator included.**
  - **The round.** The run script posts on #394, as the account that merged this declaration, the number of a round of the drand quicknet beacon (chain `52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971`, one round every 3 seconds), with the run commit's full 40-character id and H's frozen identity (§3). Round n is due at 1692803367 + (n − 1) × 3 seconds after the Unix epoch. The script names a round due at least fifteen minutes after its own clock and saves it before posting; a retry or a restart reuses the saved round while it is due more than ten minutes ahead. Before posting a first post it reads #394, and it makes no further first post while an on-time commitment post of a draw that is not void exists. After a late post it posts again with a new round.
  - **Which post counts.** A commitment post is a comment on #394 by the account that merged this declaration, made after the merge, whose first line is `Follow-up draw: first post`, and that gives the full 40-character id of a commit that was already on main, holding this declaration unchanged, when the post was created. A post's time is its GitHub creation time, and posts created in the same second are ordered by comment id, lower first. A commit was on main when a post was created only if GitHub's record shows that the pull request that brought it to main merged in an earlier second; a commit's own dates count for nothing, so a commit that reaches main later never makes a post a commitment post. A post is on time when created at least ten minutes before its round is due; a late post never counts. A comment counts as it was created: a later edit or deletion changes nothing. Commitment posts that give the same round are one post, dated by the earliest and carrying every value that the earliest carries. The draw of the earliest on-time commitment post counts; if that draw is void, the draw of the next on-time commitment post counts, and so on. The run uses the commit that the counted post names, and that commit never changes. No post of a draw is ever edited or deleted.
  - **The seeds.** The round's randomness then fixes the 78 seeds. Candidate k, for k = 0, 1, 2 and so on, is the SHA-256 of the round's 32 randomness bytes followed by k as eight big-endian bytes, read as an integer from its first eight bytes (big-endian) and shifted right by one bit, so it has 63 bits. A candidate that appears as a whole number in a file tracked at the run commit, or equals an earlier candidate, is skipped. The first 30 candidates kept are the design seeds, in position order, and the next 48 are the ordered spares. Anyone with the round and the run commit can recompute the list.
  - **Reading the round.** The script reads the round from two relays, `api.drand.sh` and `drand.cloudflare.com`, and uses it only when both serve the same round with exactly `round`, `randomness` and `signature`, and the randomness is the sha256 of the signature. A relay that is down, behind or disagreeing is read again. These checks guard the script's own read. What makes the round checkable is drand's public record of it, against which anyone can compare the round as read.
  - **Nothing replaces a counted draw except a placement void.** A late round is waited for. The run stops, and no new draw is made under this declaration, if the round has not been read this way within 24 hours of its due time, or if, before the first arm starts, the three packs or their task lists cannot be made at the commit that the counted post names. A failed build is retried exactly once: the three packs and their task lists are rebuilt from the round at that commit, from a fresh checkout; if that rebuild fails too, the run stops, and if it succeeds, the run goes on. These are the draw's only stops, and both come before the first arm: after it starts, only §4's rules end the run, and §5 reads what is missing. The reason is posted at once on #394 by the account that merged this declaration, in a comment whose first line is `Follow-up draw: stop`; a stop's time is that post's GitHub creation time, and any later declaration for this follow-up reports the stopped draw. Both stops fall after the counted draw's round is due, and a stop leaves every reading unresolved (§5), with §6's consequences.
- **Three packs of T2's shape:** A = positions 1 to 10, B = 11 to 20, C = 21 to 30. Each pack is the public T2 spec with only its seeds replaced, so its lives keep the spec's names and shape: within a pack, the i-th odd position is `t2-g1-i` and the i-th even position `t2-g2-i` (i = 1 to 5), each life with ten sessions, two twin branches, a kill at session 6 and a model-label swap at session 8. A life is named by its pack and its name. Every pack passes the run gate's system-run composition unchanged ([#539](https://github.com/electricsheephq/bicentennial/issues/539) is not needed).
- **Placement:** the seed tool's dry run places the packs in order A, B, C, each by round 1's rule (its §2) and T2's limits, walking a pack's lives in the spec's row order. A life whose design seed fails takes the next spare that no earlier pack or life has used: the spares are one ordered list shared by the three packs, so no spare is used twice. A failing life takes at most eight replacements (T2's limit for a life). A pack's dry run stops when a second life in it fails its design seed, when its failing life would need a ninth replacement, or when the spares run out. Then the whole draw is void: its list, its posts and the placement tables up to the stop are published with the results, its seeds are never used, and the draw of the next on-time commitment post counts (above), by the same rules. A void counts only when it follows the rule above and the seed tool at the run commit reproduces it from the round; otherwise the counted draw stands.
- **Template edition 3,** per id the newest admitted version: the three Drift v3s (admitted after round 2), `wake-loop-v1`, `recall-count-v1` carried and unread (PLAN D5), edition 1 elsewhere.
- **The commitment,** in two posts on #394, both before any pack is built. The first, a commitment post (above), carries the beacon round, the run commit and H's frozen identity (§3). The second, by the same account after that round is read, with the first line `Follow-up draw: second post`, carries the round, the drawn list's sha256, the draw time (the round's due time, in UTC) and the round's randomness: RING0 §14.7's draw receipt. It only records the list: the list is the one the round and the run commit give. Then all three packs are built and their task lists frozen, and each pack's hash and its task list's sha256 are posted, before the first arm.
- **Public from the round on.** Once the round is out, anyone with it and the run commit can recompute the lives. Nothing in the run can follow them: the run commit and H's identity are fixed in the first post before the round's value exists, and the reader, the controls, the placement and the reading are fixed at that commit. With the results, the spec, the drawn list, the placement tables and the task lists are committed beside them, with every comment on #394 by that account whose first line is `Follow-up draw: first post`: its comment id and creation time, the commit it names, the pull request that brought that commit to main and its merge time, and whether the post counted and why. These packs are not control-only: H runs on them. Any later run on them is on known lives and must say so.

## 3. What runs
- **One commit for everything:** a main commit holding this declaration; the admissions of the three v3s; #564, #565 and #566 ([#526](https://github.com/electricsheephq/bicentennial/issues/526)'s step 2, which decides what is rerun and what is scored for a system arm); the seed tool's three-pack mode; the follow-up's task-list and reading scripts and its card cutter; and the run script. The four code pins are printed beside round 2's.
- **Reader:** the pinned reader model at its pinned effort, through the benchmark's own login, as in round 2.
- **Rows:** F, no memory; R, naive retrieval (top five); B, BM25; G, scripted grep; W, recent window (W = 16,384 tokens); O, oracle evidence; H, Hermes native. R, B, G and W are the four anchors; B, G and W are at round 2's spec and code hashes ([cards README](../validity-2/cards/README.md#anchor-identities)); G and W run the reader with compaction at twice W, as in round 2. H is the registry's `hermes-native` entry, frozen before the draw: its registry entry's sha256, its install pins, and the `system_hash`, `harness_hash` and `route_table_hash` the run gate records for it at the run commit (printed at the rehearsal by the gate's preparation step, which sends nothing) are posted with the commitment (§2), and every H arm must carry them (§4).
- **Twelve arms per pack, packs in order A, B, C (36 arms):** F, R, O, H, H, O, R, F, O, as in Milestone 1, then B, G and W once each, in an order rotated across the packs: A: B, G, W; B: G, W, B; C: W, B, G. The first eight arms of each pack are mirrored; the ninth is O's third trial; the rotation keeps any one anchor from always running last.
- **H's floor:** each pack's H arms share one floor cache, empty before that pack's H1. H1 measures its no-memory floor live and writes the cache; H2 may take its floor from it. A rerun of H1 is still H1, so it runs with a fresh, empty cache and measures its floor afresh; H2 keeps the cache H1 first wrote (Milestone 1's §11.16). The floor enters no reading; the page prints on how many units each H arm's floor was live.
- **Target items:** every action item of the four ranking kinds on the G1 lives: one twin pair per kind per G1 life, 20 pairs per pack, 60 pairs in all (15 per kind).
- **Frozen task lists:** one per pack, as round 2's §3, with that pack's 40 target items; each list's sha256 is posted before the first arm (§2).
- **Send bound** (#507; PLAN §7 and §10): every arm runs with `--max-sends 1000`.
  - A control arm is one phase, so it makes at most 1,000 live sends. An H arm spends the bound twice, as the runner does for every system run (the T2 guide's `--max-sends`): once on the identity check and the live floor units, then afresh on the system's units. So it makes at most 2,000.
  - **Measured on T2-shaped packs (85 probe turns):** control arms used 343 to 413 sends. That covers round 1's seven arms (351 to 394), the oracle smoke (343), the anchor check's B, G and W (397, 373 and 399) and Milestone 1's F, R and O (358 to 413). Milestone 1's H arms used 858 with the floor measured live and 486 with the floor from the cache, both phases together; their runs recorded no split by phase.
  - **Rule:** the bound is at least twice the highest control figure (413). For H, it is more than twice H2's 486, whose floor came from the cache, and H1's floor phase is one no-memory pass like F's. An H arm's 2,000 is more than twice H1's 858. On round 2's all-G1 pack (90 probe turns, all on G1 lives) the arms used 418 to 546 under the same bound; that is another pack shape.
  - **Reaching the bound:** an arm refused at its bound (`spend_stop`) keeps no card and is read as missing; it is rerun once, whole, with the same bound (round 2's §3). The bound does not change once an arm has run.
- **Sittings:** the 36 arms take about 15 to 18 hours (PLAN §10), over as many sittings as the machine allows; every arm runs at the run commit, in the order above.
- **Reruns** (round 2's §3) run after all 36 arms have run once. An arm is rerun only when two things hold: the latest run of the reading script names it pending or invalid under §4, and that run was made after every attempt so far. After any rerun the reading script runs again before the next one, because a control arm's rerun can change the reference identity. The reading script prints no score while any arm is pending. A passing arm is never rerun. Every attempt and every run of the reading script is published.
- **Rehearsal** at the run commit, before the draw. It uses a rehearsal draw of public integers, extending the screening set's rule (design seeds 2001 to 2030, spares 2031 to 2078; [screening README](../validity-2/screening/README.md)), and covers:
  - placement of three packs, build and install;
  - the run gate's preparation step for H on an edition-3 T2-shaped pack: it accepts the system run, sends nothing, and prints the three hashes posted with the commitment;
  - the task lists, the reading script's refusal path with no arms, and check 3;
  - the derivation, on an already published round: its first candidates equal the seed tool's known-answer test for that round, and the two-relay and hash checks run. The rehearsal packs still use the public integers.

  No reader sees the rehearsal packs.

## 4. Checks before any score is read
- **Control arms (F, R, B, G, W, O):** round 2's checks 1 to 8 (its §4) on each pack's 40 target items. Check 2's presence is read against that pack's scripted anchor reports. Check 8 (no compaction) and the 2W setting apply to control arms only.
- **H arms:**
  - **check 4 (identity):** as below; also, each H arm's card carries the posted `system_hash`, `harness_hash` and `route_table_hash`;
  - **check 5 (completeness):** a system failure is a scored failure, never an exclusion;
  - **check 6 (repeats and common support);**
  - **check 7, as it applies to a system arm:**
    - its probe records (each system unit's `t2lite_probes.json`) cover the pack's target items, each once;
    - each target item's probe record was served by the live reader (`live.served_by`), unless that item's own final outcome is a scored system failure (`SYSTEM_FAILURE`);
    - a unit that stopped early did so on a stop its run records charge to the system (#526's step 2, #564 to #566). An infrastructure stop leaves its items unscored, and check 5 reruns the arm;
    - system units have no cache path (the runner caches only the no-memory floor), so none can come from a cache.
  - H's own context handling is part of the system, so check 8 does not apply; its summariser tokens are printed, not checked.
  - An H arm that fails check 7 is rerun once, whole; each arm is rerun at most once, whatever check it failed. If the rerun fails any check, the arm is never pooled, its trials count as unscored, and Use reads unresolved. Room and the per-kind readings use control rows only, so they stand.
- **One reference identity** (round 1's check 4), taken over the 30 control arms: the identity most of them were served, a tie going to the tied identity served first in the control arms' run order. Every arm, H's included, must match it; H's arms do not count toward it, so a kind's reading never depends on them. An arm is rerun once when it was served another identity, or its run discloses a change of identity, or records none (Milestone 1's §11.15). If it is still mismatched, it is published separately, never pooled, and its trials count as unscored (§5).
- **Unreadable state** (#524, #537, #564, #565) counts as scored; each arm's count is published.
- **A control arm failing check 1, 2, 3 or 7:** the fault is fixed and the arm rerun before any score is opened (round 1's §4). The run ends if the fix would change the run commit, or if the rerun fails any of checks 1, 2, 3 or 7 (each arm is rerun at most once, whatever check it failed). Then no score is opened, the checks and the missing observations are published, and every reading is unresolved (round 1's §4; PLAN §10).

## 5. How it is read
- **Scale:** round 2's §5: an action pair scores its lower twin (+1, 0, −1); a row's points are 100 times its mean pair score. With 15 pairs per kind, one pair is about 6.7 points.
- **Pooled repeats:** repeat k of a row is that label's k-th arm on all three packs together (for example F's first repeat is F1 of A, B and C). F, R and H have two repeats, O three, and B, G and W one each. f, r, b, g, w and h are the means of each row's repeats; c is the mean of O's first two repeats, and O's third enters the stability check and the filter (round 2's §5).
- **Missing data** (round 1's check 6): a reading or comparison needs each repeat it uses complete and identity-matched, with every target pair scored.
  - A kind's reading and flags use the control rows only: F, R, B, G and W, and O's three trials. H never enters them.
  - Room's comparisons use O1, O2 and each anchor's repeats; O3 is not needed. Use's comparisons use H1, H2 and each anchor's repeats.
  - A reading or comparison is unresolved when a repeat it uses is still missing, mismatched or incomplete after its one rerun, or when one of that repeat's target pairs is still unscored. So an H arm's loss leaves the kinds' readings and Room as they are.
  - Such a row is still printed with the pairs it scored, marked incomplete (Milestone 1's §11.1).
  - No pack, life or pair is dropped to rescue a reading, so each comparison is over all 15 G1 lives or unresolved (PLAN §1 asks for at least 12).
- **Per kind:** each row's points, per pack and pooled. Each kind gets round 2's reading on the pooled repeats (its §5): the first that applies of unresolved, unstable, low, ranking candidate and cleared.
  - A flag's stability is checked over every combination of one repeat per row (round 1's rule):
    - an anchor's near-solved flag: F × that anchor × each O trial, which is 6 combinations for B, G or W and 12 for R;
    - the floor's flag: F × each O trial, 6;
    - the low flag: each O trial alone, 3.
  - A kind whose reading here differs from round 2's is named.
- **The two declared contrasts,** over the 15 G1 lives.
  - **A life's score for a row** is its mean pair score over the four ranking kinds' pairs on that life (one pair per kind), averaged over the row's repeats: F, R and H over their two, O over O1 and O2 (as c), and B, G and W over their one.
  - **Room:** O minus each anchor (R, B, G and W): four comparisons. **Use:** H minus each anchor: four comparisons.
  - **Each comparison reads, in this order:**
    1. **unresolved** under the missing-data rule above;
    2. **inconclusive** when fewer than six lives have a nonzero difference. This is RING0 §14.7's six-life rule: with five, the smallest possible two-sided p is .0625;
    3. **holds** when the mean difference over the lives is positive and the exact two-sided sign-flip p over the lives is below .05 (`bicentennial.stats.core.sign_flip_p`, exhaustive for up to 20 lives; a zero difference does not change p);
    4. **does not hold** otherwise.
  - **A contrast** does not hold when any of its four comparisons does not hold, and the page names each one that failed. Otherwise it is unresolved when any comparison is unresolved; otherwise inconclusive when any is inconclusive; otherwise it holds.
  - Beside each contrast, the page prints each kind's own difference for each of its comparisons (pooled points). It names every kind on which a difference is zero or negative, because the contrast is an average over the four.
- **Other kinds, descriptive:** `recall-value-v1` on the G1 lives and `drift-asof-v1` on the G2 lives. Each row's points are printed per pack and pooled; they enter no reading. `recall-count-v1` is carried unread (PLAN D5): no score of its items is printed or published. G2's action items are not scored live (T2).
- **Also printed:**
  - H minus F per kind and per life (Milestone 1's §5);
  - the oracle filter's yield over O's three trials per pack (round 1's §5);
  - each anchor's scripted score beside its live score per pack;
  - every arm's sends, times and identity.
- **Cards:** each arm's card is published cut by the card cutter (§3) to the items this run reads, the target pairs and the two descriptive kinds' items, with the full card's sha256. The full card stays in the evidence store.
- **No do-no-harm contrast** (§9).

## 6. What the result triggers
- Nothing is gated on H's result, and nothing about H is ranked. No admission changes: the gate's entries record round 2's reading.
- **The ranking set after this run** is the kinds that read ranking candidate here, provided Room holds.
  - A kind that reads anything else (unresolved, unstable, low or cleared) leaves the set for any later claim, until a new validity reading on fresh control-only lives says otherwise.
  - If Room does not hold, or reads inconclusive or unresolved, room is not shown on fresh lives for any kind, so all four leave on the same terms. The page names the comparisons that failed and the kinds on which they went the other way.
- **Room holds:** the kinds still in the set left room above every anchor on fresh lives, with this reader. That supports using them to compare memory systems, but does not by itself validate them; validation stays the pilot's (ROADMAP).
- **Use** is reported for Hermes native only, whatever it reads: how far it sits above each anchor on these lives. It triggers nothing, and it is not a claim about memory systems in general.
- The results page and a status on #394 report every row, both contrasts, each kind's reading, and every departure below.

## 7. Predictions, written before the draw (pooled points; one pair is about 6.7)
Each cell gives a central value, then a range. The control columns come from round 2's live results. The H column comes from Milestone 1's Hermes native, on earlier versions of these templates, so it is a weak prior. O is c, the mean of O1 and O2.

| Kind | F | R | B | G | W | O | H |
|---|---|---|---|---|---|---|---|
| `drift-chain-fault` v3 | 0; −7 to 0 | 0; −13 to 7 | 0; −13 to 7 | 0; −13 to 7 | 0; −13 to 13 | 100; 80 to 100 | 20; −40 to 80 |
| `drift-config` v3 | 0; −7 to 0 | 0; −13 to 7 | 0; −13 to 7 | 0; −13 to 7 | 25; 0 to 60 | 100; 80 to 100 | 0; −40 to 60 |
| `drift-quote` v3 | 0; −7 to 0 | 0; −13 to 7 | 0; −13 to 7 | 0; −13 to 7 | 0; −40 to 7 | 100; 80 to 100 | 0; −40 to 60 |
| `wake-loop` v1 | 0; −7 to 0 | 0; −13 to 7 | 0; −13 to 7 | 20; 0 to 40 | 25; 0 to 50 | 100; 80 to 100 | 0; −20 to 40 |

- **Room:** holds, on all four comparisons (O about 100; the best anchor at most about 25 on any kind).
- **Use:** does not hold: H is predicted below at least one anchor on the ranking set's average (most likely W).
- **Readings:** every kind reads ranking candidate, so none leaves the ranking set.
  - The likeliest exception is `drift-config`, through the recent window. W scores a pair on a life whose first long sprint is in session 2, a chance of 1/4 per life (cards README ruling 10). W above 35 needs six or more of the 15 lives, which has a probability of about 15% under that placement model.
  - `wake-loop`'s grep and recent window (20 and 25 on round 2's pack) carry a similar risk, with no placement model behind it.
- **Checks:** no control arm compacts, none reaches its bound, every arm is served one identity, and the filter keeps at least 54 of the 60 pairs.

## 8. What was already seen when this was written
- Round 2's results, round 1's, Milestone 1's, the candidate cards, the screen's reports, the oracle smoke and the anchor check ([round 2 page](../validity-2/2026-11-14-control-trials/RESULT.md)).
- Hermes native's Milestone 1 runs on the public T2 lives, on earlier versions of the Drift templates. No one has seen H on a v3 template, or any row on these lives.
- What does not exist yet: the seeds.

## 9. Departures, decisions and extensions
| Kind | From | What |
|---|---|---|
| Departure | RING0 §15 Ring 1 composition | 30 lives in three packs of T2's shape instead of 24, so that no system-run gate changes (PLAN §7) |
| Departure | ROADMAP "the same four rows" | the anchor rows B, G and W, once per pack (PLAN §7) |
| Decision | PLAN §7 | the order of B, G and W rotated across packs. B, G and W have one repeat each, so their flags' stability uses six combinations; R's uses twelve |
| Decision | PLAN §7's 1,000-send cap | every arm runs with `--max-sends 1000`. An H arm spends it twice, as the runner does for every system run, so it makes at most 2,000 live sends |
| Decision | PLAN §7's do-no-harm kinds | none, so no one-sided contrast is computed. A do-no-harm check is a kind read cleared and not a ranking candidate (PLAN §1), and no kind here qualifies: each of the three ranking Drift ids is at a ranking-candidate v3, `wake-loop-v1` is a ranking candidate, `recall-count-v1` is carried unread (D5), and edition 1's other kinds were never read in a validity round |
| Decision | round 1's check 4 (control arms only) | the reference identity is taken over the 30 control arms and every arm must match it, so H's arms never decide which control arms are pooled |
| Decision | PLAN §1 "at least 12 lives" | no pack, life or pair is dropped to rescue a reading. A reading that lacks required data is unresolved (§5) |
| Extension | Milestone 1's check 7 (F, R and O only) | check 7 for H, as a system arm, with its own rerun rule (§4) |
| Decision | #394, RING0 §14.7 | exploratory, with Ring 1's seed rules except its draw (below) and not its full contract (PLAN D1) |
| Departure | RING0 §14.7's draw (a cryptographic generator; a draw receipt with the draw time and a commitment, posted before the run; seeds disclosed with the results) | the seeds come from a public beacon round named before its value exists, so no draw can be chosen or quietly redrawn, checkable against outside records of #394 (§10); the draw receipt carries the draw time. The lives are public from that round on, not sealed until the results: one frozen system runs, so nothing in the run can follow them, and a sealed seed or secret would give the operator a stop that could follow the scores ([review](reviews/2026-11-15-draw-amendment-review.md)) |
| Extension | PREREG §9; Milestone 1 §4; PLAN §11 | the 75, 0.7 and 35 rules read per kind, as round 2 reads them. Here the reading sets the ranking set for later claims (§6); PLAN §11 used 35 for routing only |

## 10. What this does not prove
- One reader at one effort, one system, 15 lives with scored actions, 15 pairs per kind: one pair is about 6.7 points.
- Not Ring 1, not a rank, not a certification. Nothing about memory systems other than Hermes native at its frozen version.
- "Retrieval" means the four lexical and positional anchors; dense retrieval is untested.
- A held contrast is an average over four kinds; the per-kind table says where it holds.
- Missing data is never imputed. One arm lost after its rerun leaves every reading that needs it unresolved.
- Scripted lives; the live tiers score G1 actions only.
- The commitment rests on GitHub's records of #394 and of the pull-request merges. An edit shows in a comment's public history, but a deletion may leave no mark on the issue, so readers check the published list of posts against their own copies or a public archive of #394.
- The lives were public from the beacon round on. The frozen identities, not secrecy, keep the arms from following them.
- Before the first arm, the operator can still cause a stop (§2) after the lives are known, for example by not letting the script read the round within 24 hours. A stop is public and leaves every reading unresolved, so it can only take kinds out of the ranking set (§6), never keep one in.
- On `drift-quote` and `drift-chain-fault`, a pass shows that the scored entry is right, not that the sweep was complete (cards README ruling 5).
