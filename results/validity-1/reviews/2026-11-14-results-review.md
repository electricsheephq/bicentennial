# Adversarial review of the validity round 1 results page, 2026-11-14

Reviewer: `gpt-6-astra` at high effort, a model family other than the author's (`claude-opus-5-5`), run read-only on the results commit with the run trees, the packs, the operator records and the reader's diagnostics. This is the interim scrutiny PREREG-v0.5 keeps until the Scoring Veto Panel is filled; it is not the panel. The text under each pass is the reviewer's own, unedited.

How each finding was used:
- **Finding 1 (the disclosure came after the draw):** fixed. The page now says the draw post went up 27 seconds after the draw and before the pack was built. §2 requires the post before the build, which holds.
- **Finding 2 (three target items, not four):** fixed. The unit's four probe items are described as three target items and one other item, and only the target items' result is reported. The same slip in the follow-up issue's text ([#524](https://github.com/electricsheephq/bicentennial/issues/524)) was corrected.
- **Finding 3 (the margins' unit):** fixed. The page says margins are in bundles (one bundle is 20 points) and gives the near-solved margins in points as well.
- **A fresh-context Claude review** (two lenses: numbers, and claims and conformance) re-derived every number on the page and found the same errors as findings 1 and 2, plus five more. All were fixed: the opening said "nothing was rerun" although one O3 unit ran a second attempt (now "no arm was rerun", with a pointer to the disclosure); the page and the roadmap line said all four templates enter the follow-up, which only a cleared template does (the count question's format is validated only); the arms' times come from each arm's run record, not its card; three sentences generalised beyond this pack and this reader (each is now limited to this pack); and the README linked this file before it existed (it lands in the same change).

## First pass, on the results page

Reviewed `18fdd743` read-only. The table replay reproduced all 142 non-writing output lines exactly; all seven counter reports and the presence table also reproduced. No files changed. The linked remote CI run could not be independently checked because the GitHub API connection failed.

1. **MERGE_BLOCKING · Important — The disclosure chronology is wrong**

   **Location:** `RESULT.md:45`

   **Sentence:** “Both were disclosed in the draw post, before the draw.”

   **Evidence:** `draw.json`’s `drawn_at` is **16:07:05Z**. `draw.rec` records the post at **16:07:32Z**, and `draw.body` opens by saying the seeds have been drawn. The disclosure followed the draw by 27 seconds.

   **Fix:** Say “Both were disclosed in the draw post, after the draw and before the validation pack was built.” This correction does **not** invalidate §2’s commitment procedure: it requires posting before the build, not before the draw.

2. **MERGE_BLOCKING · Important — The retried unit contained three target items, not four**

   **Location:** `RESULT.md:48`

   **Exact text:** “one life, one branch, four target items”; subsequently, “the second attempt passed all four items.”

   **Evidence:** Matching the retried unit in `units.json` (`attempts: 2`) against `TASKS.json.rows` yields **three target items**: one each from the three repaired Drift templates. Its fourth item is `wake-loop-v1`, outside the declared target list. The diagnostic `score.json` records confirm the distinction. Declaration §3 excludes other items from published results.

   **Fix:** Write “four probe items, three of them target items” and “the second attempt passed all three target items.” Avoid reporting the fourth item’s score.

   The mechanism and sensitivity calculation are otherwise correct: `read_state` raises `ValueError`; `_cause` maps it to `INFRA_FAILURE`; `score_item` returns `Infra`; `_unit_attempts` retries the unit. Both attempts’ `probe.json` records say `live.served_by: live`. Substituting zero credit for the affected task gives O3 **80**, leaves **c = 100**, preserves the reading and filter, and changes the three-trial mean to **93⅓**. The pinned procedure does not require an additional whole-arm rerun here.

3. **NON_BLOCKING · Nit — The margins lack units**

   **Locations:** `RESULT.md:67–70,75–76`

   **Exact text:** “margin −5/4 (−1.25)”, “margin 3/2 (1.5)”, and “margin −7/2 (−3.5)”.

   **Evidence:** `table.py` prints these as `margin_bundles`. They are bundle-equivalent margins, not points: respectively **−25, +30 and −70 points**, divided by 20.

   **Fix:** Add: “Margins are expressed in bundles: one pair or count question equals 20 points.” The values themselves are correct.

**Overall verdict: SOUND-WITH-FIXES.**

The substantive conclusions follow from the declaration and supplied evidence. Scores, flags, stability counts, predictions and filter outcomes support three **cleared** readings and one **format validated** reading, with all four labelled near-solved by naive retrieval. The retrieval explanation is supported: the public-pack comparison preserves the relevant histories and checks, while `NaiveRag.query` uses the changed prompt; the scripted presence counts and live first-request records agree. These remain follow-up eligibility results, not validated ranking tasks or evidence about memory systems. I found no additional privacy issue in the reviewed files; publication of the draw, spec and placement table is expressly required. The two factual corrections above should precede publication.