# Adversarial review of the validity round 2 plan, 2026-11-13

Reviewer: `gpt-6-astra` at high effort, a model family other than the author's (`claude-opus-5-5`), run read-only on a
clean checkout of `6bef659`. This is the interim scrutiny PREREG-v0.5 keeps until the Scoring Veto Panel is filled; it
is not the panel. It reviewed the draft of [the plan](../PLAN.md); quotes and line numbers below refer to that draft,
which is not published. The adopted plan beside this file carries the fixes.

How each finding was used (all seven applied before the plan was adopted):
1. **The fallback:** round 2 always runs, for Wake alone if no Drift candidate reaches the screen's gate; the
   follow-up starts only with a frozen, non-empty set of ranking candidates established in round 2, Wake included only
   if it qualifies; the screen's results are published either way (plan §6 and §10).
2. **Direction of the contrasts:** each comparison needs a positive observed difference and a two-sided p < .05; the
   contrast is named an average over the frozen ranking kinds, with the per-kind table printed beside it (plan §7).
3. **The screen's statistic:** called a scripted proxy, not a bound; right, wrong and no-credit pairs are reported
   beside the net score; the separation claim comes only from round 2's live rows (plan §4 and §9).
4. **Ranking candidate and the near-solved flags:** a ranking candidate also needs every near-solved flag, each
   anchor's and the floor's, resolved, stable and not applying; 35 is unchanged (plan §1).
5. **Chain depth:** at most 5; a deeper chain is a retrieval-competition hypothesis, with placement checked first (plan
   §4).
6. **#528's order:** it now comes before the first scored oracle smoke (plan §8).
7. **The nit:** removing the cue may suppress lexical retrieval; placement must separately defeat the recent window
   (plan §9).

The review follows as returned, with its evidence links pointed at `6bef659` on GitHub.

---

**Verdict: SOUND-WITH-FIXES.** The controls-first sequence can serve the goal without moving the four pins, but several gates permit unsupported readings or bypass fresh validation.

Reviewed the clean, detached checkout at `6bef659a4c5c04b0a055a92082635a8e24ed0d61` and the supplied issue packet. No files edited, live models run, or posts made.

## Findings

1. **Important — MUST-FIX before the plan is adopted: the fallback skips its only remaining candidate’s validation.**

   **Plan:** §6: “Skipped if no candidate reaches the screen’s gate … goes to step E with Wake as the only possible ranking candidate.” Yet the same section acknowledges that Wake has never faced these anchors on fresh lives.

   This permits the expensive system follow-up without any ranking kind established on fresh control-only lives. Another passing path has the same problem: every Drift finalist fails, Wake clears the oracle threshold but exceeds the anchor threshold, and the follow-up still proceeds because Wake was neither low nor unstable. “Wake included” then puts a non-ranking kind into the ranking-candidate contrast.

   **Evidence:** the reviewed draft, lines 112–138; [ROADMAP:19–21](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/ROADMAP.md#L19-L21); [Milestone 1 declaration:54–63](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/results/milestone-1/DECLARATION.md#L54-L63).

   **Smallest fix:** Always run round 2 for Wake, even with no Drift finalists. Start the system follow-up only with a nonempty, frozen set of freshly established ranking candidates. Include Wake in that set only if it qualifies; otherwise retain it descriptively. Publish the screen’s negative results even when no follow-up runs.

2. **Important — MUST-FIX before the plan is adopted: small p-values can currently certify the wrong direction.**

   **Plan:** §7: Room and Use “hold” when all four comparisons give `p < .05`.

   The repository’s sign-flip function is two-sided. If Hermes loses to each anchor on all 12 lives by an equal amount, each comparison gives `p = 2/4096 ≈ .000488`; the literal rule therefore passes **Use** despite consistent losses.

   Also, averaging ranking kinds within each life establishes an average contrast, not superiority on every kind. A gain on one kind can conceal a loss on another.

   **Evidence:** the reviewed draft, lines 135–139; [stats/core.py:94–130](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/src/bicentennial/stats/core.py#L94-L130); [RING0:426–427](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/specs/ring0/RING0.md#L426-L427).

   **Smallest fix:** Declare positive observed differences **and** two-sided `p < .05` for every comparison. This preserves the six-life rule. Call the result “average over the frozen ranking kinds”; keep the required per-kind table and report exceptions plainly. No additional run or test family is needed.

3. **Important — MUST-FIX before the plan is adopted: the scripted pair score is not an upper bound on live performance.**

   **Plan:** §4: the scripted reader “bounds what a live reader gains from that retrieval.”

   The scripted reader selects a competing option when its tokens are present and the gold option’s tokens are absent. A live reader can instead abstain, avoiding the negative score. For example, 12 correct and eight confidently wrong pairs give scripted points of 20; abstaining on those eight gives 60 from the same retrieval.

   Token requirements can also exceed what a live reader needs: `drift-quote`’s correct option requires both the direct and quoted facts, although its action writes the direct value. Round 1 already recorded a live retrieval success on a `drift-config` item whose required-fact presence check failed.

   **Evidence:** [scripted_reader.py:65–86](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/src/bicentennial/probe/scripted_reader.py#L65-L86); [drift_action.py:76–80](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/src/bicentennial/items/templates/g1/drift_action.py#L76-L80); [validity-1 RESULT:88–98](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/results/validity-1/2026-11-13-control-trials/RESULT.md#L88-L98).

   **Smallest fix:** Keep the cheap screen, but describe its statistic as a **scripted proxy**, not a bound. Report correct/wrong/no-credit pairs beside its net score. Reserve the anchor-separation claim for round 2. Likewise, §9’s “reached the needed fact on x of y pairs” must not substitute for a penalised pair score.

4. **Important — MUST-FIX before the plan is adopted: “ranking candidate” can conflict with the inherited near-solved exclusion.**

   **Plan:** §1 requires clearance and best-anchor points ≤35, while separately retaining the near-solved formula.

   These conditions are not mutually exclusive. With stable `f = −100`, `c = 80`, and an anchor at 30, the template qualifies as a ranking candidate, but that anchor also exceeds the near-solved boundary:
   `−100 + .7 × 180 = 26`.

   Milestone 1 explicitly excludes near-solved kinds from claims that memory beats retrieval. The new rule also omits its near-solved-without-memory exclusion.

   **Evidence:** the reviewed draft, lines 24–33; [Milestone 1 declaration:35–49, 58](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/results/milestone-1/DECLARATION.md#L35-L49); [validity-1 declaration:52](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/results/validity-1/DECLARATION.md#L52).

   **Smallest fix:** Give the inherited exclusions precedence: a ranking candidate must also have resolved, stable, non-applying near-solved flags, including the floor flag. Keep 35 unchanged.

5. **Important — MUST-FIX before the plan is adopted: depth 6 cannot fit the proposed fault-crossing template with the existing writer.**

   **Plan:** §4 proposes chain depth “5 or 6” because `drift_chain.py` accepts 1–6.

   Acceptance by the template constructor is insufficient. Depth 6 needs seven events. The correction writer puts successive events in distinct, increasing sessions, while the fault template requires every chain event at or before the kill at session 6, turn 1. Seven distinct sessions cannot fit.

   Separately, exceeding five events does not establish that five retrieved chunks are insufficient: the correct option requires the **last fact**, not every link.

   **Evidence:** [corrections.py:51–55, 70–85](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/src/bicentennial/world/processes/corrections.py#L51-L55); [drift_chain.py:33–52](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/src/bicentennial/items/templates/g1/drift_chain.py#L33-L52); [T2 spec:19–22](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/tiers/life_specs/t2.toml#L19-L22).

   **Smallest fix:** Remove depth 6 from this step. Treat any feasible smaller depth as a retrieval-competition hypothesis, with placement checked first—not as a requirement to retrieve the whole chain. No writer change is needed.

6. **Important — MUST-FIX before the plan is adopted: #528 is ordered too late for the scored oracle smoke.**

   **Plan:** §8 requires #528 before round 2, but §5 opens oracle-smoke scores earlier and uses them to drop finalists.

   The existing runner can give an oracle task another chance after the reader corrupts its repository. That happened in round 1. The merged result requires the fix before the next published live run; a score-based selection smoke also needs the corrected attribution.

   **Evidence:** the reviewed draft, lines 106–109, 145; [validity-1 RESULT:48, 126](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/results/validity-1/2026-11-13-control-trials/RESULT.md#L48); [PR #528](https://github.com/electricsheephq/bicentennial/pull/528).

   **Smallest fix:** Move that prerequisite to **before the first scored oracle smoke**.

7. **Nit — FOLLOW-UP: “no cue beats them by construction” overstates the mechanism.**

   **Plan:** §9 applies this claim to all four anchors.

   Recent-window retrieval ignores the query; cue removal alone cannot defeat it. Lexical retrieval can also match generic words—the plan’s own predictions acknowledge this.

   **Evidence:** the reviewed draft, lines 52–57, 81–85, 162–164; [naive_rag.py:77–96](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/src/bicentennial/controls/naive_rag.py#L77-L96).

   **Smallest fix:** Say cue removal may suppress lexical retrieval; placement must separately defeat the recent window.

## The claims checked

| Claim | Verdict | Evidence |
|---|---|---|
| Naive retrieval queries with the task prompt, using top-five 240-character chunks | Supported | [naive_rag.md:25–35](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/specs/controls/naive_rag.md#L25-L35) |
| Config’s prompt change raised public-life presence from 0/10 to 7/10 | Supported; same histories and facts | [validity-1 RESULT:91–98](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/results/validity-1/2026-11-13-control-trials/RESULT.md#L91-L98) |
| Wake scored R=0 and O=100 in Milestone 1 | Supported | [Milestone 1 RESULT:61–67](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/results/milestone-1/2026-11-11-separation-table/RESULT.md#L61-L67) |
| BM25 uses `k1=6/5`, `b=3/4` | Supported | [bm25.py:1–4, 25–38](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/src/bicentennial/api/adapters/bm25.py#L1-L4) |
| T2’s provisional window is 16,384 tokens | Supported | [t2.toml:5–6](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/tiers/life_specs/t2.toml#L5-L6) |
| Controls pin has 95 files, including the named writers/renderers/G2 templates but excluding targeted.py and G1 templates | Supported by read-only recomputation of the import closure | [cache.py:20–66](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/src/bicentennial/controls/cache.py#L20-L66) |
| Adding a module under `controls/` moves that pin | Supported | [cache.py:64–74](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/src/bicentennial/controls/cache.py#L64-L74) |
| Four G1 action slots are already occupied | Supported: two checkpoints × two actions | [RING0:484–490](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/specs/ring0/RING0.md#L484-L490); [targeted.py:99–102](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/src/bicentennial/world/targeted.py#L99-L102) |
| Only G1 actions are scored live | Supported | [RING0:490](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/specs/ring0/RING0.md#L490) |
| Edition 2 is refused for system runs because count-v2 is unadmitted | Supported | [t1.py:343–357](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/src/bicentennial/runner/t1.py#L343-L357); [admissions:3–33](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/specs/ring0/template-admissions.json#L3-L33) |
| Edition-1 refs, including count-v1, bypass the added admission requirement | Supported; acceptance is not evidence of validity | [t1.py:345–357](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/src/bicentennial/runner/t1.py#L345-L357) |
| Probed G1 names recur across lives | Supported | [targeted.py:368–384, 406–410](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/src/bicentennial/world/targeted.py#L368-L384) |
| #529 matters once all refs in a control-only pack are admitted | Supported | [#529](https://github.com/electricsheephq/bicentennial/issues/529); [t1.py:326–357](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/src/bicentennial/runner/t1.py#L326-L357) |
| RING0 says #320 “resolved”; #394 says “checked” | Supported | [RING0:420](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/specs/ring0/RING0.md#L420); [#394](https://github.com/electricsheephq/bicentennial/issues/394) |
| Twenty-four alternating lives provide twelve G1 lives | Supported | [RING0:496](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/specs/ring0/RING0.md#L496) |
| Memory-using heuristics never delete individual bundles | Supported, but not an exemption from the separate final-distribution gate | [PREREG:325–339](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/prereg/PREREG-v0.5.md#L325-L339) |
| Scripted scores bound live scores; depth 6 is feasible here; no cue defeats every anchor | Unsupported/false as stated | Findings 3, 5 and 7 |

The declared departures cover the changed composition, scripted grep, secondary levers, added live controls and exploratory follow-up. I found no necessary four-pin move in the proposed architecture. Reporting heuristics without using them to reject individual candidates is appropriate here; it must not be described as passing PREREG’s final-distribution battery. Likewise, deferring full Ring 1 leaves its validation requirements unmet—it does not establish compliance with them.

### Statistical assessment

| Element | Assessment |
|---|---|
| **Screen statistic and gate** | Pair-minimum penalised scoring is the correct scale. The ≤35 screen is a useful cheap selection rule, but not a live-performance bound or calibrated statistical test. Finding 3 fixes the claim. |
| **35-point routing** | With clearance at ≥75, it gives an observed oracle–best-anchor gap of at least 40 points. Sound as a disclosed routing threshold, not a confidence bound or §9 calibration. Resolve the conflicting near-solved classifications in finding 4. |
| **Exact sign-flip over G1 lives** | Correct clustering unit; twins, templates and repeats must not become independent observations. Twelve life contributions permit exhaustive enumeration. Statistical exactness additionally assumes exchangeable signs under the null; fresh seeds alone do not establish that assumption or remove service-time confounding. |
| **All four comparisons `p < .05`** | Sound as an intersection–union rule for the single claim “beats every specified anchor,” once direction is fixed. No Bonferroni correction is needed within that conjunction. It does not establish every-kind superiority. Room and Use remain distinct claims unless success requires both. |
| **Six-life rule** | Correct for two-sided `p < .05`: five nonzero lives bottom out at `.0625`; six at `.03125`. RING0’s cited rule instead accompanies one-sided α=.025. If choosing one-sided α=.05, five can suffice, so six would be a conservative policy, not a mathematical necessity. |
| **Forking-path guards** | Adequate for exploratory selection followed by genuinely fresh confirmation, after fixing the skip path. Committing screening seeds does not make that set independent of adaptive candidate selection. Publishing every card and freezing the selected set before fresh draws are the useful protections. |

### Cost and time

**No estimate is demonstrably wrong by more than 2× from the supplied measurements.**

- Round 1 used **351–394 sends per arm**, taking approximately **15–30 minutes**. Thirteen comparable arms imply roughly **4,563–5,122 sends and 3.25–6.5 hours**, consistent with the plan’s range. [Measured runs:26–34](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/results/validity-1/2026-11-13-control-trials/RESULT.md#L26-L34)
- Milestone 1 controls used **358–413 sends**; Hermes used **858 including its fresh floor**, then **486 with a cached floor**. Scaling ten control arms plus those two Hermes invocations by `24/10` gives approximately **11,818–13,138 sends**. The proposed 11,000–12,500 is slightly optimistic at its upper end, nowhere near 2× wrong. [#507](https://github.com/electricsheephq/bicentennial/issues/507)
- The **12–14-hour follow-up** is plausible from the measured arm times. New long-context anchors and the changed floor scheduling remain unmeasured; the calendar estimate cannot be verified from these receipts. [Milestone 1 times:18–23](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/results/milestone-1/2026-11-11-separation-table/RESULT.md#L18-L23); [RING0:459](https://github.com/electricsheephq/bicentennial/blob/6bef659a4c5c04b0a055a92082635a8e24ed0d61/specs/ring0/RING0.md#L459)

These are base-run estimates; extension packs and reruns add work. “$0” is consistent with marginal subscription-lane spend.

## Three biggest remaining risks

1. **The selected tasks may discriminate against these anchors rather than measure broadly useful memory.** Cue removal and distant placement target lexical and positional weaknesses. Fresh seeds test generalisation within that construction, not beyond it; dense retrieval remains untested.

2. **An oracle gap does not ensure a real system can use it.** The oracle is told exactly which evidence matters. Cue-free prompts may leave ordinary agents uncertain about what to retrieve or act on, producing another floor-level Hermes result. That remains a valid result and must not trigger system-score-driven template selection.

3. **Twelve lives and a shared live service leave substantial uncertainty.** In particular, B/G/W run once each and always after the mirrored core arms. Repeat noise and service drift can affect their comparisons; a pooled result can also conceal opposing per-kind effects. The promised per-kind results and restrained exploratory claims remain essential.

