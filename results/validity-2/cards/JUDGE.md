# Validity round 2: the judge's scores

The blind judge scored every card against the bars in [BARS.md](BARS.md), which were written before any card was drafted. It saw the cards and the code, not the designers' angles. Printed unchanged.

**Recommended:** `drift-config` K1, `drift-config` K3, `drift-config` K4, `drift-quote` K1, `drift-quote` K3, `drift-chain-fault` K1, `drift-chain-fault` K3.

## `drift-config` K1: publish

- **B1 Plan form:** pass. Names drift-config with levers 1 and 4, gives the mechanism, the prompt, 3 paraphrases, 4 anchor predictions and the oracle risk. Code goes in a new drift_config_v3.py plus editions.py, c7.py:95, a C-7 spec and tests. The g1/__init__.py registry edit is not a class file and sits outside SCORING_FILES and the controls closure (it is imported dynamically at check_selftest.py:111-114).
- **B2 Repair kept:** pass. Keeps the file and the decision rule. Dropping the entry name is labelled a DEPARTURE and argued: every gold event names only 'retry interval' (en.toml:37,49,53).
- **B3 Token audit:** pass. Every token of all 4 texts is classed with a source. The in-evidence tokens 'the' and 'retry' get a valid grep argument: 'file' (about 0.954n, since 1-(6/7)^20) and 'what' (n; the chunk footer at session_cut.py:57) are visited before 'retry' (at least n+3). Their sprint chunks (at least 20,480 tokens) exceed W=16,384, so bounded() breaks.
- **B4 Falsifiable predictions:** pass. Naive and BM25 0 (range 0-5), grep exactly 0, window exactly 100*n2/N. All are consistent with the token-less keep on B0 (OMISSION) and None on B1 (PASS, action.py:79-81).
- **B5 Oracle safety:** pass. Argues set h on B0 and the hedge twin's no-change on B1, which passes the refrain table. Extra B1 changes are FAIL_TASK and the prompt forbids them. Risk is rated low.
- **B6 Validity:** pass. (a) Sibling entries and retry policy are resolved by the entry scope and the file. (b) Every battery POLICY is <= 0; the options are v2's and the battery never reads the prompt. (c) Session-2 sprints: P=1/4; there the window holds h, and P(n2>=8)≈10% is stated.
- **B7 Editions 1/2 unchanged:** pass. Prompt-only change: no world or class edits, EDITIONS[3] is new, and the edition-3 C-7 entry is named.
- **B8 Smallest change:** pass. Prompt only, with no placement machinery.

## `drift-config` K2: reject

- **B1 Plan form:** pass. All fields are present. Its edits are a new class file plus world/targeted.py (t1_life passes selected to _build_t1, and fix_at replaces line 373), which B1 allows.
- **B2 Repair kept:** pass. Same as K1: the entry-name DEPARTURE is labelled and argued from the gold events.
- **B3 Token audit:** pass. Identical texts to K1, with the same complete classification and grep argument.
- **B4 Falsifiable predictions:** pass. Exact point predictions (window 0 on every life; lexical anchors 0 or 0-5) can be contradicted by the screen and are consistent with the reader rule.
- **B6 Validity:** FAIL. (c) The window account for session-2 lives rests on stream order (session_cut.py:114,138,140). The anchor actually sorts same-instant events by (t_sim, event_id) (anchors/__init__.py:26-28), so turn-1 chunks can precede the (2,1) event and the 'at least 20,480 tokens always follow' claim is false. The turn 2-5 chunks are only about 15.97-16.69k.
- **B5 Oracle safety:** pass. The gold spans and wording are unchanged and only their times move. B0 sets h, the B1 hedge leaves the file unchanged, and no extra-change route is added. Risk is rated low.
- **B7 Editions 1/2 unchanged:** pass. Names the scoping mechanism: an edition-3-only template field fix_at, absent in v1/v2, so editions 1/2 get the same 'at'. Notes the edition-3 C-7 entry.
- **B8 Smallest change:** FAIL. Adds placement machinery without showing that existing placement fails. It cites only P≈10% that n2>=8 on 20 lives, and n2 is not yet computed on the committed roster.
- **Fix:** Restate the window mechanism under the anchors' (t_sim, event_id) order, with the measured token margin. Resubmit only if the committed screening roster shows n2>=8, i.e. existing placement demonstrably fails.

## `drift-config` K3: publish

- **B1 Plan form:** pass. All required fields are present. Code goes in a new drift_action_v3.py plus the registry, editions, c7 and tests. No pinned file is edited.
- **B2 Repair kept:** pass. Keeps the file and v2's rule ('only raised as a possibility' verbatim). The entry-name DEPARTURE is labelled, and argued from the single-subject linking(p,h) spans.
- **B3 Token audit:** pass. Verified: no token of the 4 texts is in the config evidence set (be … with, plus 'setting' from SETTING-dddddd). Outside-only tokens are sourced: config/settings/toml/in/set from the session-1 reads, a/it/was from the quote and factless cells, 'stands' from the sprint footer. The absent list is complete, so no grep argument is needed.
- **B4 Falsifiable predictions:** pass. Naive, BM25 and grep exactly 0 (no shared term, so dot=0 and score=0); window exactly 100*k/n with k computable. Consistent with keep/None.
- **B5 Oracle safety:** pass. Argues B0 sets h, the B1 hedge makes no change (v2 hedge wording), and there is no evidence for other entries. Residual is asking (OMISSION). Risk is rated low.
- **B6 Validity:** pass. (a) batch_size's correction is committed (world.py:260-262) and later hedges or quotes are excluded by the rule; 'after it was committed' excludes uncommitted kinds. (b) All POLICIES <= 0. (c) Session-2 lives about 25%; the window is right there (8.7-13.1k < W).
- **B7 Editions 1/2 unchanged:** pass. No world, render or placement edit and old classes untouched; the edition-3 C-7 entry is specified.
- **B8 Smallest change:** pass. Prompt only. It explicitly declines the (2,1) placement fix unless the screen shows the window above 35.

## `drift-config` K4: publish with fix

- **B1 Plan form:** pass. All fields are present. New drift_action_v3.py, registry, editions, c7 and tests; the cue_words literal-prompt rule is respected, and no pinned file is edited.
- **B2 Repair kept:** pass. Keeps the file and the rule (widened to reports and quotes). The entry-name DEPARTURE is labelled and argued (phrasebank.py:128-130 puts the subject verbatim in every span).
- **B3 Token audit:** FAIL. Paraphrase 1's token 'reflects' ('so it reflects all firm corrections') appears in no class: it is in neither the ABSENT nor the OUTSIDE list, so not every \w+ token is classed.
- **B4 Falsifiable predictions:** pass. Naive, BM25 and grep 0 (range 0-0, 0/0/20); window +5·N2. Exact and consistent with keep/None and the lower-twin rule.
- **B5 Oracle safety:** pass. B0 is retract plus assert, so write h. The B1 soft hedge means change nothing. 'Never add entries' blocks additions, and the end state is diffed. Risk is rated low.
- **B6 Validity:** pass. (a) Sibling entries resolve under the rule. Non-settings are excluded by name, tasks are flagged, and 'never add' covers additions. (b) All <= 0. (c) 2,441/10,000 draws with a session-2 sprint, P(N2>=8)=0.09, accounted for.
- **B7 Editions 1/2 unchanged:** pass. Prompt-only change; C-7 hashes MRO files only (c7.py:49), and the edition-3 entry is named.
- **B8 Smallest change:** pass. Prompt only.
- **Fix:** Add 'reflects' to the token audit: it is absent from every G1 event under the same static scan (sources as for the other absent tokens).

## `drift-config` K5: reject

- **B1 Plan form:** pass. All fields are present. Code is a new class plus world/targeted.py t1_life and line 373, which B1 allows.
- **B2 Repair kept:** pass. Same as K4: the departure is labelled and argued.
- **B3 Token audit:** FAIL. It reuses K4's audit ('ABSENT: as in v3a'), which leaves paraphrase 1's token 'reflects' unclassed.
- **B4 Falsifiable predictions:** pass. Lexical anchors 0-0; window 0 (range 0-5), with a mechanism that correctly uses the event_id order of same-instant chunks.
- **B5 Oracle safety:** pass. The same spans reach the oracle whatever the slot. B0 writes h and B1 makes no change. Risk is rated low, and slot sharing at (2,1) is flagged for verification.
- **B6 Validity:** pass. (a) As K4. (b) All <= 0. (c) In session-2 lives (24.4%) the turn 2-5 chunks (15,971-16,689) plus later events exceed W, with a range of 0-5 allowed.
- **B7 Editions 1/2 unchanged:** pass. Scoped by the ClassVar SETTING_FIX_AT on the v3b class only (v1/v2 lack it), so _build_t1 arguments are unchanged for editions 1/2. The C-7 entry is noted.
- **B8 Smallest change:** FAIL. New placement machinery without showing that existing placement fails. v3a's expected window is 24 with P(>35)=0.09, which does not show the window failing.
- **Fix:** Classify 'reflects'. Resubmit the placement change only if the committed screening roster shows N2>=8 (a demonstrated window failure).

## `drift-quote` K1: publish

- **B1 Plan form:** pass. All fields are present. A separate new drift_quote_v3.py keeps C-7 hashes independent; registry, editions, c7 and tests; no pinned file is edited.
- **B2 Repair kept:** pass. Keeps the file and restates the quote rule. The entry-name DEPARTURE is labelled and argued: both gold events name 'lock timeout', and 'missing' excludes flush_timeout_ms.
- **B3 Token audit:** pass. Every token is classed with sources. The in-evidence 'the' and 'timeout' get a grep argument: 'file' (about 0.954n, which wins ties alphabetically) fills W first. In the rare session-2 case where 'timeout' comes first, only q (2,4) is reached and d (1,4) is at least 20.5k back.
- **B4 Falsifiable predictions:** pass. Naive and BM25 0 (range -5 to 0), grep -10 to 0, window exactly -100*n2/N. Consistent with refrain/other-1 and the fork twin.
- **B5 Oracle safety:** pass. Argues D over Q on both fork twins by 'set directly, not ... quoted later', with the name copied 'exactly as written'. No extra-change route on the act table. Risk is moderate.
- **B6 Validity:** pass. (a) flush_timeout_ms is present and committed, so 'missing' settles the entry. (b) All POLICIES <= 0. (c) In session-2 lives (about 1/4) the window is confidently wrong (q without d), so window points are <= 0.
- **B7 Editions 1/2 unchanged:** pass. Prompt only; no targeted.py change; the drift-quote-v3 C-7 entry is noted.
- **B8 Smallest change:** pass. Prompt only.

## `drift-quote` K2: publish with fix

- **B1 Plan form:** pass. All fields are present. New class in drift_action_v3.py, plus registry, editions, c7 and tests; no pinned file is edited.
- **B2 Repair kept:** pass. Keeps the file and rewords v2's quote rule. The name DEPARTURE is labelled and argued (only 'lock timeout' appears in the linking(d,q) spans; absent from the file per drift_action.py:74).
- **B3 Token audit:** pass. Verified that none of the 4 texts shares a token with the quote evidence (a … was, plus 'setting'). Outside tokens are sourced (README 'with', 'decisions'; en.toml:38/49 'never'/'not'), and the absent list is complete.
- **B4 Falsifiable predictions:** pass. Lexical anchors exactly 0 (refrain); window exactly -100*k/n. Consistent with the reader rule and the fork twin.
- **B5 Oracle safety:** pass. Argues d over q on both twins (v2 rule content), with naming as the main risk. No harmful extras (act table, benign_extras empty). Risk is moderate.
- **B6 Validity:** FAIL. (a) It claims the uncommitted items at k are 'lock timeout and four decisions'. But milestone deadlines, constraint rules and commitments are also agreed in chat and never committed (PATHS has no such kinds, codebase_model.py:13), and the prompt excludes only decisions. So the ambiguity a real system faces is left unanalysed.
- **B7 Editions 1/2 unchanged:** pass. Prompt only; the old classes are untouched; the edition-3 C-7 entry is specified.
- **B8 Smallest change:** pass. Prompt only.
- **Fix:** Extend the exclusion clause to rules, deadlines and tasks (or show why 'settings entry' excludes them), and redo the token audit for any new words.

## `drift-quote` K3: publish

- **B1 Plan form:** pass. All fields are present. New DriftQuoteV3 class file, registry entry with the drift-quote-v3 table, editions, c7 and tests; no pinned file is edited.
- **B2 Repair kept:** pass. Keeps the file and rewords the decision and quote rules. The name DEPARTURE is labelled and argued from the verbatim subject in both spans.
- **B3 Token audit:** pass. Verified that none of the 4 texts has an evidence token (the d/q set including setting, a, it, was, that). Outside tokens are sourced ('file' and 'out' from sprint, 'never' from the negate cell); 'quotes'/'quoted' ≠ 'quote'. The absent list is complete.
- **B4 Falsifiable predictions:** pass. Lexical anchors 0 (range 0-0); window -5·N2. Consistent with refrain and other-1 on the fork twin.
- **B5 Oracle safety:** pass. Argues d0/d1 over q on both twins; the reader has no evidence for other entries and extras carry no penalty. Naming and add-hesitancy risks are stated. Risk is moderate.
- **B6 Validity:** pass. (a) Deadlines, rules and decisions are excluded; other writes cannot cost credit on the act table (only changed:other disqualifies). (b) All <= 0. (c) Session-2 lives (24.4%) make the window wrong, never a gate risk.
- **B7 Editions 1/2 unchanged:** pass. Prompt only; no class or world edit; the drift-quote-v3 C-7 entry is noted.
- **B8 Smallest change:** pass. Prompt only.

## `drift-chain-fault` K1: publish

- **B1 Plan form:** pass. All fields are present. Levers 1 and 4 come from §4's list, and lever 1 on chain-fault is flagged as a departure. New drift_chain_v3.py, plus registry, editions, c7 and tests; no t2.toml or pinned edit.
- **B2 Repair kept:** pass. Keeps the file, the line form and the last-link rule ('current target'). The name DEPARTURE is labelled and argued: both links name only 'general release'.
- **B3 Token audit:** pass. Every token is classed and sourced. The in-evidence 'the' and 'is' are in every chunk header (session_cut.py:56; at least 2n events at checkpoint 10), visited last, and newest-first they fill W inside the second sprint (7/9/10) before session 2.
- **B4 Falsifiable predictions:** pass. Naive and BM25 0 (range -5 to 0); grep and window exactly 0. Consistent with refrain/other-1 and the fork twin.
- **B5 Oracle safety:** pass. The last link is explicit on both twins. The risks (beta unseen by the gold-only reader, 'target' for deadline, name from evidence) are stated, 'one line' limits extras, and risk is moderate.
- **B6 Validity:** pass. (a) The beta's corrected deadline is a same-kind distractor ruled out by 'after the beta'. (b) All <= 0. (c) Checkpoint 10 is pinned and the second sprint (at least 20,480 tokens) always intervenes; session-2 sprints are irrelevant.
- **B7 Editions 1/2 unchanged:** pass. Prompt only; depth and deadline_at unchanged; the C-7 entry with the lever-mix departure is noted.
- **B8 Smallest change:** pass. Prompt only.

## `drift-chain-fault` K2: reject

- **B1 Plan form:** pass. All fields are present; lever 1 outside §4's scope is flagged. New drift_chain_v3.py and registry files; no world or t2.toml edit.
- **B2 Repair kept:** pass. Keeps the file, the line form and the exact-name instruction. Dropping 'general release' is labelled a DEPARTURE and argued from the single-subject links.
- **B3 Token audit:** pass. Verified that no token is in the chain evidence. 'beta' occurs only in the deadline-0 links and the others in the session-1 reads; the absent list is complete.
- **B4 Falsifiable predictions:** pass. All four anchors exactly 0 (refrain), with mechanisms; window 0 because the second sprint lies between.
- **B5 Oracle safety:** FAIL. The argument does not establish that the gold-only reader picks the right action. The card concedes the reader cannot check 'non-beta', must map 'target' to 'deadline', and is left with the Milestone-1 name failure mode, and it rates the risk high.
- **B6 Validity:** pass. (a) Exactly two milestones (Mix deadlines=(1,1)), so 'non-beta' is unique. (b) All <= 0. (c) The window is 0 on every life at the pinned checkpoint 10.
- **B7 Editions 1/2 unchanged:** pass. Prompt only; depth and deadline_at unchanged; the C-7 entry is noted.
- **B8 Smallest change:** pass. Prompt only.
- **Fix:** Restore a checkable subject (the exact name or a cue the gold evidence contains), with an argument that the gold-only reader writes '- general release: <last>' on both twins. The owner must accept the departure first.

## `drift-chain-fault` K3: publish

- **B1 Plan form:** pass. All fields are present (lever 1). New drift_chain_v3.py with the drift-chain-fault-v3 table, plus registry, editions, c7 and tests; no pinned or spec edit.
- **B2 Repair kept:** pass. Keeps the file, the line form and an explicit 'current after all corrections' rule. Dropping the name is labelled a DEPARTURE and argued from the verbatim subject in both spans.
- **B3 Token audit:** pass. Verified that none of the 4 texts has a chain evidence token ('corrections' ≠ 'correction'). Outside tokens are sourced ('list' from test_config.py, a/was/with from cells and README); the absent list is complete.
- **B4 Falsifiable predictions:** pass. All four anchors 0 (range 0-0, 0/0/20). Consistent with refrain on both fork twins.
- **B5 Oracle safety:** pass. Argues the last link from the retract-then-assert rendering on both twins. The naming rule (lower case, nothing added) targets the name risk, and extras are unpenalised. Risk is moderate.
- **B6 Validity:** pass. (a) Enumerating milestones from memory; extra lines (beta, commitments) cost nothing on the act table. (b) All <= 0. (c) Pinned checkpoint 10 means the window misses in 100% of lives.
- **B7 Editions 1/2 unchanged:** pass. Prompt only; the pinned checkpoint and deadline_at are unchanged; the C-7 entry is noted.
- **B8 Smallest change:** pass. Prompt only; explicitly rejects a depth or spec change.

## Cross-card conflicts

Narrative context ignored (the cards' 'confidence' fields are author beliefs). Overall: 7 of 11 cards are recommended; drift-config-K4 only with its stated fix.

Cross-card conflicts:

1. **Colliding refs and table ids.**
   - drift-config K1/K2/K3/K4/K5 all claim ref drift-config@3 and tables drift-config-corrected-v3 / drift-config-hedged-v3.
   - drift-quote K1/K2/K3 all claim drift-quote@3 and drift-quote-v3.
   - drift-chain-fault K1/K2/K3 all claim drift-chain-fault@3 and drift-chain-fault-v3.
   - BY_REF (editions.py:22) needs unique refs, and G1_MUTANT_ROLES is keyed by table id. Screening several cards per id therefore needs distinct versions or table ids, or a separate candidate build per card.

2. **Shared source files.**
   - drift-config-K3 and drift-quote-K2 (and possibly drift-config-K4/K5 and drift-quote-K3) put classes in the same drift_action_v3.py. Because C-7 hashes every MRO source file (c7.py:49), iterating one card moves the other's C-7 hash. drift-quote-K1 avoids this by design.
   - All three chain cards write drift_chain_v3.py.

3. **One-time shared edits.** Every card edits items/templates/g1/__init__.py (TEMPLATES_V3, G1_MUTANT_ROLES), editions.py (EDITIONS[3], C7_FILES[3]), c7.py:95 and test_editions.py:127-133. These must land once, with one edition-3 roster of finalists.

4. **Placement fallbacks change the world for every edition-3 card.** drift-config-K2 and K5 move the setting-fix correction to (2,1) in edition 3:
   - It shares an instant with deadline-0's second link (beta). drift-chain-fault-K1 uses beta as its relational cue.
   - It changes edition-3 world event layout and ids for every other edition-3 card. Screens of the quote and chain cards under such an edition are not comparable with prompt-only editions.

5. **Paired fallbacks.** drift-config-K2 is the fallback for K1 (same prompt) and K5 is the fallback for K4. They are mutually exclusive with their bases as finalists.

6. **Contradictory instructions at checkpoint 5.** drift-quote-K3 tells the system to add every missing settings entry, while drift-config-K4 says 'Never add entries' and drift-config-K3 audits the whole file. A real system meeting both probes in one life gets contradictory instructions on config/settings.toml, unless the items are strictly independent (state0 per item).

## Facts to verify before the screen

[
 "Per-term visible event counts on built lives. The audits are static. Check that 'what' equals n exactly (sprint footer only), 'file' is about 0.954n, and 'retry' is at least n+3. For drift-quote-K1, check 'timeout' against 'file' in session-2-sprint lives. For drift-chain-fault-K1, check 'the' and 'is' at checkpoint 10.",
 "That G1 never renders observed, propose or negate-retract cells, and that commitments use only the cells claimed. This decides whether 'as', 'record', 'what', 'lacks', 'after' and 'all' stay absent.",
 "n2 (lives whose first long sprint is in session 2) on the committed screening roster, computed with build_schedule before any report. The screening seeds are not yet committed in the repository. Also re-check the public-life claim n2=0 (sprints at 3,4,4,4,5).",
 "Window token margins on built lives. After a (2,3) event in a session-2-sprint life: about 11.5-12.1k of chunks plus sessions 3-5, said to be under 16,384. After a (2,1) event: turn 2-5 chunks of 15,971-16,689 plus the other events, said to be over 16,384. Same-instant events are ordered by event_id in the anchor (anchors/__init__.py:26-28), not by stream order as drift-config-K2 assumes.",
 "Whether the live oracle-evidence reader works in a real checkout and sees file contents. drift-config-K3 relies on 'after it was committed'; drift-quote-K1 and K2 rely on 'missing' / 'never committed'.",
 "Whether action items at the same checkpoint each start from their own state0 in live runs (packs/build.py g1_cases), so sweep prompts cannot interact.",
 "Whether placement, twin planning, _check_reads and lint accept two statements at slot (2,1), with deadline-0's link. Relevant to drift-config-K2 and K5.",
 "That the edit to items/templates/g1/__init__.py stays outside every pin. Verified so far: it is outside SCORING_FILES (packs/scoring.py:17-18) and only dynamically imported by check_selftest.py:111-114. Still to confirm against the controls-pin file list and the round-1 precedent (#519).",
 "Errors in the facts digest (DIGEST-wording.md). 'setting' does occur, via SETTING-dddddd tokens on retry interval and lock timeout. The --edition choices are at c7.py:95, not :130. The session-1 tool reads contain evidence words: 'the', 's' and 'with' in README; 'for', 'from' and 'value' in the service and test files."
]
