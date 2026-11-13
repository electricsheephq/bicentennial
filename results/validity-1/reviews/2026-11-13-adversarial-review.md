# Adversarial review of the validity round 1 plan and declaration, 2026-11-13

Reviewer: `gpt-6-astra` at high effort, a model family other than the author's (`claude-opus-5-5`), run read-only. This is the interim scrutiny PREREG-v0.5 keeps until the Scoring Veto Panel is filled; it is not the panel. The first pass reviewed the owner's working implementation plan for the repair: its rules are carried by the declaration beside this file, and its code by the implementation pull requests the results page names. The second pass reviewed the declaration, and the third checked the declaration's fixes. The text below is the reviewer's own, unedited.

How each finding was used:
- **The plan's four:** all applied before the declaration was written. The pack build and the run gate take the template edition. Completeness covers the count questions. Half points are kept. The count question is read for its format only, and [#512](https://github.com/electricsheephq/bicentennial/issues/512) tracks giving each life its own count.
- **The declaration's eight:** all applied in the declaration.
- **The third pass's one remaining point** (the identity tie-break) was applied before merge.

## First pass, on the repair plan

All evidence below is from `41056c9`. Four findings:

1. **MERGE_BLOCKING — Edition selection must reach scoring-case reconstruction.**  
   **Evidence:** `src/bicentennial/packs/build.py:108–116,140–150`; `src/bicentennial/packs/catalogue.py:19–20`.  
   `_templates()` reconstructs templates from the global **v1** catalogue, independently of the templates used to generate the life. One version per ID prevents collisions but does not fix this lookup. With edition-2 generation and the existing reconstruction, replaced refs are absent from the edition-2 freeze, causing `PackRefused("c7")`; merging freezes instead leaves v2 action items paired with v1 tables.  
   **Smallest fix:** explicitly pass the selected edition registry through `_prepare()` to `_templates()`, or resolve each record’s `(template_id, template_version)` through `BY_REF`. Preserve the v1 catalogue for T0.

2. **MERGE_BLOCKING — The reading rule does not cover incomplete count trials.**  
   **Evidence:** `results/milestone-1/DECLARATION.md:24–25,94–96`; `results/milestone-1/2026-11-11-separation-table/table.py:498–506,535–540,648–650`.  
   The borrowed completeness check covers **action tasks**. The plan omits check 6 and gives admission only “not low and stable,” without an unresolved state for missing count scores. For example, four correct count answers and one unavailable answer in every O repeat can yield a stable result above 75 while the fifth frozen question remains unvalidated. Keeping it in TASKS.json does not resolve the missing observation.  
   **Smallest fix:** apply completeness, identity and common-support rules to all 35 target items, including the five questions. After the permitted rerun, missing required observations make the affected reading **unresolved**, preventing admission.

3. **RELEASE_BLOCKING — The singleton reading omits valid half-point scores.**  
   **Evidence:** `src/bicentennial/score/qa.py:139–147`; `src/bicentennial/items/templates/g2/recall_count.py:35–38`.  
   The proposed `(+1, 0, -1)` scale describes these actions, but count answers can score **+0.5 or −0.5** when confidence is below 500. Declaring a question a one-item bundle settles filter grouping, not its numerical reading. Rounding these scores can change the 75-point decision.  
   **Smallest fix:** predeclare singleton score as `score_milli / 1000`, retaining half-points; action pairs retain the minimum of their two scores. Include half-point cases in P4’s synthetic checks.

4. **NON_BLOCKING — The count limitation contradicts “the floor cannot produce it.”**  
   **Evidence:** `src/bicentennial/world/targeted.py:265–269,418–423`; `src/bicentennial/items/templates/g2/recall_count.py:29–38`; `src/bicentennial/score/qa.py:115–120,144–147`.  
   The acknowledged fixed count is an executable shortcut: always answering `2` with asserted confidence and `citation: null` receives full credit. The scorer accepts an absent citation despite the new prompt requesting one. Two F repeats that abstain cannot establish that evidence is necessary. This limitation predates v2; it is not introduced by the prompt repair.  
   **Smallest fix:** remove the categorical floor guarantee for count and explicitly describe its admission as **format/readability validation only**, insufficient to admit it as a memory-discriminating task. No scorer change is needed for this repair phase.

1. **Pin safety: held.** The proposed G1 initializer change is outside the static control closure and v1 C-7 class-source hashes; the separate G2 package preserves that boundary.
2. **Coexistence: finding 1.** The proposed mutant-role registration otherwise addresses `check_roles`.
3. **Four prompts: finding 4.** No additional evidence-free shortcut was established for the three action prompts.
4. **Validation and reading: findings 2 and 3.**
5. **Feasibility: finding 1.** The T2 tier and five-G1/five-G2 composition fit the runner; no separate need to edit the protected runner files was established.
## Second pass, on the declaration

1. **MERGE_BLOCKING — Overlapping states have competing actions.** `results/validity-1/DECLARATION.md` §§5–6: O scores of 60, 80, 100 make c=70 both **low** and **unstable**, triggering either v3 or an extension. Unresolved can also coexist with observed low scores. **Smallest fix:** freeze precedence, e.g. unresolved → unstable → stable-low → admitted/format-validated.

2. **MERGE_BLOCKING — Extension pooling is undefined.** `results/validity-1/DECLARATION.md` §6 says “pooled reading” without specifying whether stability compares six individual O arms or three corresponding pooled repeats. Those can disagree: packs scoring 60/100/100 and 100/60/100 have pooled repeats 80/80/100, but individual arms cross 75. It also leaves whether previously resolved templates are reclassified open. **Smallest fix:** specify pooling, stability comparisons, affected templates, and the outcome when the extension is incomplete; retain each bundle’s own three-trial filter.

3. **MERGE_BLOCKING — A repeatedly stopped arm has contradictory handling.** `results/validity-1/DECLARATION.md` §4.5–7 promises unresolved after one rerun, but imports `results/milestone-1/DECLARATION.md` §11.8, where any stopped unit fails check 7; §4’s closing paragraph then requires repair and another rerun before scores open. **Smallest fix:** explicitly terminate a second stopped attempt as an invalid, unresolved result, publishing checks and missing observations without opening invalid scores.

4. **MERGE_BLOCKING — Identity selection is not frozen.** `results/validity-1/DECLARATION.md` §4.4 does not choose the reference identity when arms disagree, including ties, and imports parent readings 4–9 but not §11.15’s within-arm drift rule. The parent `results/milestone-1/2026-11-11-separation-table/table.py:383–391` supplies both rules in implementation. **Smallest fix:** state the reference/tie rule and require absent or positive drift disclosures to count as mismatches.

5. **MERGE_BLOCKING — Filter handling of excluded trials is incomplete.** `results/validity-1/DECLARATION.md` §5 defines unknown as unscored, but an identity-mismatched O arm can contain scores. “Never pooled” does not expressly determine whether those scores enter this separate filter. The parent `table.py:673–686` treats excluded arms as unknown and distinguishes failed from unresolved bundles. **Smallest fix:** adopt those two rules explicitly. The singleton count rule and exclusion of +500 from passing are already clear and consistent with the stated adaptation.

6. **MERGE_BLOCKING — Void-draw evidence is not deliverable by the specified failure path.** `results/validity-1/DECLARATION.md` §2 requires failed placements and void draws to be published. Plan §3/P3 adds a spare pool, but `src/bicentennial/world/targeted.py:697–753` keeps the placement table/replacements locally and raises before returning them on either terminal placement error. **Smallest fix:** require P3 to retain the drawn list and failure-prefix receipt on those exits, then publish every void receipt alongside the successful draw.

7. **NON_BLOCKING — “As in Milestone 1” obscures a changed stability rule.** `results/validity-1/DECLARATION.md` §5 tests instability only for low; parent `results/milestone-1/DECLARATION.md` §4 tests all three flags across repeat combinations. Stable O=100, F=0 and R repeats 0/100 illustrate the difference. **Smallest fix:** explicitly identify the narrowed admission rule and say whether near-solved instability is still disclosed. This need not add an admission gate.

8. **NON_BLOCKING — Two factual descriptions exceed the plan.** `results/validity-1/DECLARATION.md` §1 says v1 and v2 never share a pack, but plan §2 retains unchanged v1 templates in edition 2. `results/validity-1/README.md`’s opening question treats all four templates as potential memory-ranking tasks, contradicting the count limitation. **Smallest fix:** say “one version per template ID per pack” and distinguish three action-validity checks from one count-format check.

Q1: F1–F5; count singleton and half-point handling held.
Q2: F1–F2, F4–F6.
Q3: F5, F7; the 75 threshold held.
Q4: F8.
Q5: F3, F6.
## Third pass, the check of the declaration's fixes

1. **resolved** — §5 now fixes precedence: unresolved → unstable → low → admitted/format validated.
2. **resolved** — §6 defines corresponding pooled repeats, affected templates, incomplete-extension handling, final instability handling, and separate bundle filters.
3. **resolved** — §4 terminates a second failed validity check with all templates unresolved; only checks and missing observations are published, without opening scores.
4. **partly resolved — MERGE_BLOCKING** — §4.4 adds the modal identity and drift rules, but its tie-break says “that of the arm that ran first.” For identities A/B/B/B/C/C/C, B and C tie, while the first arm is A. Smallest fix: choose the earliest arm **among the tied most-common identities**.
5. **resolved** — §5 explicitly treats excluded-arm trials as unscored and distinguishes passing, failed, and unresolved bundles.
6. **resolved** — §2 now requires retaining and publishing each void draw’s seed list, commitment, and placement table through the stop. This resolves the declaration requirement; implementation is not proven by this delta.
7. **resolved** — §5 explicitly distinguishes low-only admission stability from disclosed near-solved stability across repeat combinations.
8. **resolved** — §1 allows unchanged v1 templates alongside the four v2s; README separates action validity from count-format validation.

**New problems introduced:** none identified beyond the remaining F4 ambiguity.

**Recommended next steps:** clarify F4’s tie-break in one phrase; no broader changes are needed for these findings.