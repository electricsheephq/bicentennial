# Validity round 2, then the fresh-seed follow-up: the plan

Adopted by the maintainers on 13 November 2026, after an adversarial review by a model family other than the
author's (`gpt-6-astra`, sound with fixes: [the review](reviews/2026-11-13-plan-review.md)); its six required fixes and
its one nit are applied here. Every repository fact below was checked against `main` at `6bef659`. This is a plan, not
a declaration: round 2's declaration is written after the oracle smoke (§5) and reviewed before it merges. The
predictions in §4 were written before any screen report.

## 0. Decisions
| # | Decision | Why |
|---|---|---|
| D1 | The follow-up runs **exploratory**, with Ring 1's seed rules borrowed (draw after every arm is frozen, commitment posted, seeds disclosed after); the first run under Ring 1's full contract is a later item | The full contract needs a lite-audit tool that does not exist, #452's receipts, #320 resolved (RING0 §14.7 says "resolved", #394 says "checked") and roster shakedowns; ranking kinds, not the contract, are the bottleneck today |
| D2 | Anchors: BM25 = the existing BM25 scoring (`api/adapters/bm25.py`, k1 = 6/5, b = 3/4) on naive retrieval's own chunks, top five; grep = a scripted transcript grep (below); recent window = the last W = 16,384 estimated tokens of visible events | W is T2's developer-tier window (C-5, `tiers/life_specs/t2.toml` `window`); a larger window is the stricter anchor |
| D3 | The three anchors live **outside the controls pin** for this step (a new package that no `controls/*.py` file imports), each report and card carrying the anchor's own spec and code hashes | Every `controls/*.py` file and its imports are in the controls pin (`controls/cache.py` lines 64-66), so anchors there would move it and every existing pack would stop verifying mid-milestone |
| D4 | A harder version is a **v3 of an existing Drift id** that replaces its v2 in edition 3, and only if it reads a ranking candidate in round 2; otherwise the cleared v2 stays | Each G1 life has four action slots, all in use (`drift-chain-fault`, `drift-config`, `drift-quote`, `wake-loop`); a new template id would change the probe budget |
| D5 | The count question rides the follow-up as `recall-count-v1`, carried and **unread**; a v3 whose answer varies is out of this step unless it is ready when round 2 freezes, and #512 stays open | v1 is an edition-1 ref the gate accepts; v2 is not admitted (#520) |
| D6 | Round 2's pack is **ten G1 lives** and no G2 lives | Only G1 lives carry scored actions, so this doubles pairs per template (5 to 10) at about the same cost |
| D7 | A live oracle smoke on public lives screens the finalists before round 2 | The scripted oracle is 100 by construction; the main risk of the likeliest lever (no cue in the prompt) is the oracle row, and one arm (~400 sends) finds it before a 13-arm round |

## 1. Aim and readings
**Aim.** Task kinds on which the oracle-evidence row sits well above the best of the four naive anchors, measured on
fresh control-only lives; then one fresh-seed run that places Hermes native between the floor, the anchors and the
oracle row on every kind, on at least 12 lives with scored actions. No kind is promoted or dropped on a real system's
score (ROADMAP, Repair; Milestone 1 declaration §6).

| Reading (control rows only) | Rule |
|---|---|
| cleared / low / unstable / unresolved | round 1's rule unchanged (validity-1 declaration §5) |
| ranking candidate | cleared; the best of the four anchors' live points <= 35; and every near-solved flag (each anchor's and the floor's, below) resolved, stable and not applying; all stable in every combination of one repeat per row |
| near-solved by an anchor | that anchor's points >= f + 0.7 (c - f) (Milestone 1 declaration §4, applied to each of the four anchors) |
| near-solved without memory | f >= 0.7 c (Milestone 1 declaration §4) |
| do-no-harm check | cleared and not a ranking candidate |

**Extension, flagged:** PREREG-v0.5 §9's 75 and 35 are per-track targets the pilot sets on its calibration set. This
plan applies 35 per template on a T2-size pack to route template versions. Live control rows "enter no Ring 0 gate,
bar or calibration target" (RING0 §15, extension of 11 November), so these readings freeze no scalar, rung or target.

## 2. Facts that shape the design
- A task's prompt is naive retrieval's query (`specs/controls/naive_rag.md`); round 1's `drift-config` v2 prompt raised
  naive retrieval's finds from 0 of 10 to 7 of 10 on the same lives. Wake's prompt names nothing, and Wake is the one
  kind where naive retrieval scored 0 and the oracle row full marks (Milestone 1 RESULT).
- Event wording lives in pinned files: the controls pin's 95 files include `world/processes/*.py`,
  `render/phrasebank.py`, `render/template.py` and every G2 template; they exclude `world/targeted.py` and
  `items/templates/g1/*` (computed from `controls/cache.py`). So prompt and placement levers on G1 templates are
  available without a pin move; levers that rewrite correction wording are not.
- Edition 2 cannot carry a system run (`recall-count-v2` is not admitted), so the follow-up needs an edition 3.
- The probed G1 entities carry the same names in every life (`world/targeted.py`); disclosed under either contract.
- Admitting round 2's finalists would admit every template of its control-only pack: #529 is due first.

## 3. Step A: the three anchors
- **Freeze:** each anchor's spec is merged with its code and tests before its first report on any pack; every report and card records the anchor's spec and code hashes; any change is a new anchor version and voids earlier reports; the anchors move into the controls pin at the next deliberate pin move, with the pack rebuild it needs.
- Each anchor is an adapter with `query(task, now)`, so the existing control runner and the scripted reader give its
  per-item report unchanged; each has a one-page spec in `specs/controls/`, deterministic and system-agnostic like
  `naive_rag.md`, computed only from events visible at `now`.
- **grep:** search terms are the prompt's words (naive retrieval's `\w+` over `str.lower()`) that occur in at least one
  visible event, rarest first by event count; for each term in that order, the matching whole events, newest first,
  until W tokens are filled. **Departure, flagged:** DESIGN §8's "grep agent" (a live reader with a search tool) is
  not built here; every page says "scripted grep".
- **Recent window:** the most recent visible events, newest last, up to W = 16,384 estimated tokens
  (`world/tokens.py`). Reports also print presence at 4,096 and 65,536 tokens, never read as a flag.
- **Live arms:** `bicentennial t2 --control` gains `bm25`, `grep` and `recent_window`, in the same framed block as
  `naive_rag`; check 2 applies to each (the first request's presence equals the scripted report, task by task).
  **Departure, flagged:** extends RING0 §15's 11 November note; a dated extension line lands with the change.
- Tests: golden outputs per anchor on a fixed life; determinism across processes; an anchor that finds nothing
  returns its "UNKNOWN"; the four code pins unchanged.

## 4. Step B: candidate cards and the screen (no reader, no cost)
**Rules for a candidate.** One card per candidate, written before its first report: lever, mechanism, predicted
scripted score of each anchor, predicted risk to the oracle row, three paraphrases of its prompt. It keeps round 1's
repair (the entry name, the decision rule, the quote rule). It lives in new G1 template files and `world/targeted.py`
(outside the pins). It comes from control rows only. At most eight cards and three screen iterations per card.

**Levers, in order of trust:**
1. No cue in the prompt (Wake-like) on `drift-config` and `drift-quote`: nothing to search with. Oracle risk: the
   repository holds other settings and decisions.
2. A deeper chain on `drift-chain-fault` (the Drift cell's primary lever), at most depth 5: depth 6 needs seven events
   in distinct sessions (`world/processes/corrections.py`) and the fault template puts every chain event at or before
   the kill at session 6. A retrieval-competition hypothesis (more same-entity events compete for five chunks; the task
   needs only the last fact), with placement checked first. Likely loses to grep.
3. Placement: needed events early, the probe late, so the recent window misses them (inside T2's placement rules).
4. A prompt that states the rule in other words: a cheap test of round 1's 0-to-7 finding; grep likely defeats it.
**Predictions, written now, before any report** (scripted pair score on the screening set, points; W = 16,384 tokens):

| Lever | naive RAG | BM25 | grep | recent window | Oracle risk |
|---|---|---|---|---|---|
| 1 alone | <= 20 | <= 20 | 20-60 (common prompt words match many events, newest first, like a window) | 20-60 (depends on placement) | moderate |
| 1 with 3 | <= 20 | <= 20 | <= 35 | <= 20 | moderate |
| 2 | 20-60 | 20-60 | >= 60 (the entity name finds every link, newest first) | depends on placement | low |
| 3 alone | >= 80 | >= 80 | >= 80 | <= 20 | low |
| 4 | 0-60 | 0-60 | >= 80 | unchanged | low |

So the likeliest finalists combine levers 1 and 3 on `drift-config` and `drift-quote`.
Not in this step: a correction that does not repeat the entity's name (needs pinned event writers); a fact spread over
several events (a new evidence writer). Both are recorded as the first items for the next pin move.
**Departure, flagged:** a lever other than the cell's primary one departs from C-7's lever-mix shape; the edition-3
C-7 entry records it and the round-2 declaration says so.

**Lives.** Iterate on the ten public T2 lives. Then a screening set of 20 G1 lives from seeds committed to the
repository before any candidate report is read (it also proves early that a G1-only pack builds and reads, which D6
needs). A frozen candidate's screening report is read once. **Extension, flagged:** the Repair rule names "the public
lives"; these are more public seeds, never used for a run of record.

**Statistic and gate** (on the screening set): each anchor's scripted pair score, a **scripted proxy, not a bound**: the scripted reader picks a
competing option when only its tokens are present, where a live reader may abstain, and its token checks can exceed
what a live reader needs. Correct, wrong and no-credit pairs are reported beside the net score; the claim that a kind
separates evidence from the anchors comes only from round 2's live rows. A candidate is a finalist only if: placement
succeeds within T2's replacement limit; the scripted oracle row scores 100; the best anchor scores <= 35; the same holds
under each paraphrase; and every no-memory policy of the simple-policy battery (`controls/battery.py` `POLICIES`) scores <= 0 on its pairs. The memory-using heuristics (`HEURISTICS`: latest mention and the rest) are printed, never a gate: they read the history, and PREREG-v0.5 §4 says they never delete a bundle.
Pair scores, not task presence: a pair scores its lower twin, so task presence does not map to §9's 35.
**Finalists:** at most one per Drift id, ordered by the primary lever first, then the lowest best-anchor score.
Every screened card and its reports are published with round 2, finalists or not.

## 5. Step C: oracle smoke (D7)
One live oracle-evidence arm (`--control oracle_evidence`) on the public T2 lives built with the candidate edition 3,
read for the finalists only: a finalist below 75 there is dropped before round 2. Recorded in round 2's "what was
already seen". Then round 2's predictions are written (ROADMAP, Repair).

## 6. Step D: validity round 2
Runs even if no Drift candidate reaches the screen's gate: Wake has never met the three anchors or had oracle trials on
fresh lives, so round 2 then targets Wake alone. Every screened card's results are published either way.
- **Pack:** one fresh control-only pack of ten G1 lives (D6), seeds drawn after the declaration merges, commitment
  posted, task list frozen at build, spec and seeds hidden until results (validity-1 declaration §2 and §3). Edition:
  the finalists, `wake-loop-v1`, the cleared v2s where no finalist replaces them, edition 1 elsewhere.
- **Targets:** the finalists' pairs and Wake's (Wake has never had oracle trials on fresh lives, and no new anchor has
  met it).
- **Arms (13, one commit, mirrored order):** F R B G W O O W G B R F O (B, G, W: BM25, grep, recent window). Round 1's
  reader, checks, single-rerun rule and oracle filter, with checks 1 and 2 extended to B, G and W.
- **Triggers:** ranking candidate: admitted with that label; cleared but not a candidate: admitted as do-no-harm;
  low: not admitted, its v2 stays; unstable: one extension pack by round 1's pooled rule; **the follow-up starts only if round 2
  establishes at least one ranking candidate; that frozen set (Wake included only if it qualifies) is the follow-up's
  ranking set, and every other kind is carried descriptively.** The page prints each anchor's scripted score beside its live score.
- **Admissions** merge only after #529.

## 7. Step E: the fresh-seed follow-up (#394)
- **Lives:** 24 from one draw (RING0 §15's Ring 1 composition: n = max(10, ceil(12/f)) with f = 5/10, G1 on odd
  positions): 12 lives with scored actions. Two packs: A = lives 1-10 (T2's shape), B = lives 11-24, which keeps
  each arm inside measured send ranges and the 1,000-send cap.
- **Edition 3:** per id the newest admitted version: `wake-loop-v1`, each Drift id at its ranking-candidate v3 or its
  cleared v2, `recall-count-v1` carried unread (D5), edition 1 elsewhere; its own C-7 file.
- **Rows per pack:** F R O H H O R F O as in Milestone 1, then B, G and W once each. Hermes native is frozen before
  the draw. **Departure, flagged:** the roadmap says "the same four rows"; the anchors are added because a claim
  against retrieval needs all four on the same lives (Milestone 1 §6). Other roster systems are not run (D1).
- **Readings:** Milestone 1's checks and flags, per kind, on the fresh lives. Two declared contrasts on each life's
  mean pair score over the frozen ranking set from round 2, exact sign-flip over the G1 lives: Room (O minus
  each anchor) and Use (H minus each anchor); each holds only if every one of the four comparisons has a positive observed difference and a two-sided p < .05 (the
  repository's sign-flip is two-sided, so a consistent loss would otherwise pass); it is an average over the frozen
  ranking kinds, so the per-kind table is printed beside it and any kind that goes the other way is named; with fewer than
  six lives where the two rows differ it reads "inconclusive" (RING0 §14.7's six-life rule). Do-no-harm kinds: H minus
  naive retrieval per life, one-sided against the system, stated as unable to show that nothing was harmed.
- **Claim class:** exploratory, developer tier, fresh seeds; descriptive; no rank, no "Ring 1", no certification.

## 8. Order and dependencies
| # | Item | Before | Lane |
|---|---|---|---|
| 1 | Merge PR #528 (#524) | the first scored oracle smoke (it decides whether a reader-corrupted repository is scored or rerun) | maintainers |
| 2 | Anchors: specs, adapters, scripted reports, live arm names, RING0 note (#531, #532) | the screen | `gpt-6.1-sol`; review by another model family with named probes |
| 3 | Screening-set seeds committed; G1-only build and read check; with #521 (`--spec` tier check) and #523 (hermetic roster tests) (#533) | the first candidate report | `gpt-6.1-sol`; maintainers' check |
| 4 | Candidate cards, v3 templates and edition-3 C-7, with #522's CHANGELOG line (#534) | the screen | cards: maintainers; code: `gpt-6.1-sol` |
| 5 | Screen reports; finalists (#534) | oracle smoke | maintainers (scripted) |
| 6 | Oracle smoke (#535) | round-2 predictions | maintainers (bench host) |
| 7 | Round-2 declaration, adversarial review (`gpt-6-astra`), merge (#536) | the draw | maintainers; `gpt-6-astra` |
| 8 | #529 | round-2 admissions | `gpt-6.1-sol`; adversarial review by `gpt-6-astra` (a guard) |
| 9 | #526 | the follow-up's first system arm (it decides what is rerun and what is scored) | `gpt-6.1-sol`; review by another model family |
| 10 | #507's cap and refusal record | Hermes native's next T2 run | per #507 |
| 11 | Follow-up declaration, review, rehearsal at the run commit, draw, run, results (#394) | | maintainers; `gpt-6-astra` |
Items 2, 3, 9 and 10 can start now; 4 starts when 2 lands (cards can be written now).

## 9. Claim discipline
- Screen: "on these public lives, the scripted anchor reached the needed fact on x of y pairs"; never that a task is
  hard or anything about a live reader. Round 2: "cleared", "a ranking candidate on this pack with this reader"; never
  cell admission (PREREG §4), a Stage A census (§5), "calibrated" in §9's sense or a validated ranking task.
- "Retrieval" always means the four scripted anchors: hashed TF-IDF, BM25, scripted grep and a recent window of W
  tokens. All four are lexical or positional. Removing the cue may suppress the lexical ones (generic words can
  still match); placement must separately defeat the recent window. Any finding says "lexical retrieval", and dense
  retrieval is named as untested.
- Forking paths: iterating against the anchors can fit these anchors and lives. Guards: cards and gates before
  reports; at most three iterations per card; every card published; a committed screening set; fresh confirmation in
  round 2; four anchors, not one.
- Every declaration and result gets an adversarial review by another model family before it merges. LCM-X is never
  run by the benchmark.

## 10. Cost, time and stop rules
| Phase | Live sends | Run time | Spend |
|---|---|---|---|
| Anchors, screen | 0 | minutes per report | $0 |
| Oracle smoke | ~400 | ~25 min | $0 (subscription lane) |
| Round 2, 13 arms | ~4,600-6,500 (G1 lives carry the action turns, so a G1-only pack may cost more per life; measured at the rehearsal) | ~3.5-7 h | $0 |
| Follow-up, packs A and B, 12 arms each | ~11,000-12,500 | ~12-14 h over two or three sittings | $0 |
Each arm's send cap is written in its declaration from measured figures with stated headroom (#507). Calendar
estimate: anchors and screen 3-5 days; round 2 2-3 days; follow-up about a week; done in early December.

**Stop rules.** A change that would move a code pin stops that item. No finalist after the card and iteration limits:
round 2 targets Wake alone, never loosen the gate. Round 2 is one pack plus at most one extension pack. Check 1, 2, 3 or 7 failing again
after its fix and one rerun ends the round with every reading unresolved (validity-1 declaration §4). No ranking candidate after round 2 (Wake included): no system follow-up; publish
the screen and round 2, and re-plan. A run gate refusal or an identity mismatch after one rerun: published as such, never pooled.

## 11. Departures and extensions
| Kind | From | What |
|---|---|---|
| Extension | PREREG §9; Milestone 1 §4 | 35 applied per template on a T2-size pack, routing only |
| Extension | ROADMAP Repair rule | a committed 20-life G1 screening set beside the public lives |
| Interim | DESIGN §8 | anchors outside the controls pin, hashed per report |
| Departure | RING0 §15 (11 November) | three new live control arm names |
| Departure | C-7 lever-mix shape | levers other than the primary one |
| Departure | validity-1 RESULT | a cleared v2 replaced by a ranking-candidate v3 does not enter the follow-up |
| Departure | RING0 §15 composition | round 2's ten-G1-life pack |
| Departure | ROADMAP "the same four rows" | three anchor rows in the follow-up |
| Decision | #394, RING0 §14.7 | the follow-up runs exploratory; the full contract is a later item |

## 12. Rejected alternatives
- The follow-up now on round 1's templates: edition 2 cannot carry a system run, and the anchors would meet a live
  reader first inside the expensive run.
- Anchors in `controls/` now (moves the pin mid-milestone); a screen against naive retrieval alone at "3 of 10 tasks"
  (`drift-config` v1 would have passed it); new template ids (no free action slot); edits to pinned event writers
  (a pin move inside a validity step); one 24-life pack (~900 sends an arm against a cap of 1,000).
- The full Ring 1 contract now: its prerequisites are real work in parallel with the validity round, and with one or
  two ranking kinds it would mostly publish ties.
- A dense-retrieval diagnostic in this step: deferred; the claim language names it untested instead.
