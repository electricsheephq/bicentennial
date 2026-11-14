# Validity round 2: cards drafted but not screened

These four cards were drafted with the seven screened ones and scored by the same judge. They are kept here unchanged, with the judge's reasons, so that the selection can be checked. See [README.md](README.md) for the owner's ruling on each.

<a id="drift-config-k2"></a>

## `drift-config` K2: drift-config v3b: v3a's prompt plus an edition-3-only correction slot at session 2, turn 1 (window-proof)

- **Designer's angle:** retrieval-adversarial (beat the anchors).
- **Levers (PLAN §4):** 1, 3, 4.
- **Judge:** reject; failed B6 Validity, B8 Smallest change.

**Prompt.**

> Check the retry entry in config/settings.toml against what the team decided. If the team later firmly corrected its figure, set the corrected figure under the same entry name; if a new figure was only floated as a possibility, leave the file unchanged.

**Paraphrases.**

1. Look at the retry entry of config/settings.toml and check it against what was agreed. When its figure was later firmly replaced, write the replacement under the same entry name; when a new figure was merely suggested as a possibility, leave the file alone.
2. Bring the retry entry of config/settings.toml up to date against what the team settled: if the team firmly corrected its figure later, apply the corrected figure under the same entry name; if a new figure was only tentatively floated, keep the file unchanged.
3. Review the retry entry in config/settings.toml against what the team decided. Where the team later firmly corrected its figure, put the corrected figure under the same entry name; where a new figure was only tentatively suggested, leave the file unchanged.

**Mechanism.**

The prompt and paraphrases are exactly v3a's, so the lexical anchors behave identically. Lever 3: in edition-3 lives only, the setting-fix correction moves from (2,3) to (2,1). Inside a session, events sort before the sprint chunks of the same turn (session_cut.py:114, 138, 140), and chunks sit at turn_t[c % 5]. So at least 20,480 chunk tokens (tokens.py:16-22) of a session-2 sprint always fall between (2,1) and the probe, and a sprint in sessions 3-5 also blocks. The window never reaches h. (2,2) would not do: the chunks at turns 2-5 come to 15.98-16.58k, which leaves about 0.6k of margin, and (2,2) is drift-chain-fault's slot.

**Round 1's repair (B2).**

Same as v3a. The file and the decision rule are kept. The entry name is a DEPARTURE (owner to rule), argued as for v3a: every gold event names 'retry interval', the only file entry containing 'retry'. The slot move changes no wording.

**Token audit (B3).**

Identical to v3a, token for token, for the prompt and all three paraphrases. The slot move changes no event text: it only changes t_sim and leaves a filler event at the vacated (2,3) slot, which is factless (en.toml:8: 'thanks', 'noted', 'got', 'it', 'okay', 'talk', 'soon', 'sounds', 'good'), all outside evidence. The grep argument is unchanged: 'file' and 'what' fill W before 'retry' and 'the' are visited.

**Changes.**

Everything listed for v3a, plus the following.
world/targeted.py:
- t1_life (line 686-689) passes `selected` into the build lambda.
- _build_t1 (line 353) takes the templates and reads `fix_at = next((t.fix_at for t in templates if t.template_id == "drift-config" and hasattr(t, "fix_at")), ((1, 3), (2, 3)))` in place of the hard-coded at (line 373).
The v3b class (DriftActionV3b, a new file drift_config_v3b.py) adds a dataclass field fix_at = ((1, 3), (2, 1)). That field appears in the edition-3 C-7 entry's 'template' fields (c7.py:57).
Scoping: the edition reaches the build only as EDITIONS[edition] (packs/build.py:339 into t1_lives, then _select_templates). v1 and v2 lack the attribute, so editions 1 and 2 get the same at, the same worlds and the same packs. t2.toml and t1.toml are untouched: setting-fix's slot is not backed by the spec (targeted.py:94 and :131 cover only deadline_at and pinned).
Tests:
- edition-1/2 world hashes and pack hashes are unchanged on the public seeds;
- an edition-3 life puts the correction at (2,1);
- twin independence, _check_reads and the closed-world lint pass when the slot is shared with deadline-0's correction.
This is new placement machinery, justified under B8: v3a's window can exceed 35 (P ≈ 10% on 20 lives).

**Predicted pair scores (points out of 100; a pair scores its lower twin).**

- **Naive retrieval:** 0 (range 0 to 5); as v3a, and placement does not affect it.
- **BM25:** 0 (range 0 to 5); as v3a.
- **Grep:** 0, exactly; as v3a.
- **Recent window:** 0, exactly, on every life. With the sprint in session 2, all of its chunks (at least 20,480 tokens) follow (2,1), so h is never reached. With the sprint in 3-5 it blocks as well. B0 gives OMISSION, B1 gives PASS, so every pair is 0.

**Risk to the oracle-evidence row (B5).**

low. Same argument as v3a: the evidence set and its wording are unchanged, and only the times move. The live reader sees the same three gold events on B0 and the same hedge on B1.

**No-memory battery (B6b).**

Identical to v3a: do_nothing 0, always_abstain 0, always_never_observed 0, always_forgotten 0, always_ask 0, generic_default -100, generic_default_reverse 0, fire_on_every_cue -100, channel_distrust 0, comply_always -100, resist_always 0. All ≤ 0.

**Validity (B6).**

Same capability and ambiguity as v3a. The window no longer depends on where the first sprint falls: n2 lives (about 1 in 4) are neutralised by construction. One side effect: in edition-3 lives the decisive correction shares slot (2,1) with deadline-0's correction (beta release), so two statements land at one instant. That is realistic, and it puts no extra text in the probe. Use only if the committed screening roster has n2 ≥ 8. This rule is decided from build_schedule before any report.

*Designer's confidence, a belief and not a bar:* 50.

**The judge's reasons.**

- B6 Validity: (c) The window account for session-2 lives rests on stream order (session_cut.py:114,138,140). The anchor actually sorts same-instant events by (t_sim, event_id) (anchors/__init__.py:26-28), so turn-1 chunks can precede the (2,1) event and the 'at least 20,480 tokens always follow' claim is false. The turn 2-5 chunks are only about 15.97-16.69k.
- B8 Smallest change: Adds placement machinery without showing that existing placement fails. It cites only P≈10% that n2>=8 on 20 lives, and n2 is not yet computed on the committed roster.
- Fix named by the judge: Restate the window mechanism under the anchors' (t_sim, event_id) order, with the measured token margin. Resubmit only if the committed screening roster shows n2>=8, i.e. existing placement demonstrably fails.

<a id="drift-config-k5"></a>

## `drift-config` K5: drift-config v3b: v3a's prompt, plus edition-3-only placement of the correction at session 2 turn 1 (levers 1+3)

- **Designer's angle:** mechanism-validity (the separation must be a memory capability).
- **Levers (PLAN §4):** 1, 3.
- **Judge:** reject; failed B3 Token audit, B8 Smallest change.

**Prompt.**

> Bring config/settings.toml up to date, applying firm corrections only, and only to settings entries (deadlines, rules and decisions stay out), keeping entry names exactly as written in chat. Where a settings entry was later firmly corrected, write what it was corrected to. Where a new figure was only raised as a possibility, or only reported or quoted, change nothing. Never add entries.

**Paraphrases.**

1. Update config/settings.toml so it reflects all firm corrections to settings entries and nothing else; deadlines, rules and decisions stay out, and entry names stay exactly as written in chat. If an entry had its figure firmly corrected later, set what it was corrected to; if a change was merely floated as a possibility, or merely reported or quoted, leave it alone. Never add entries.
2. Apply all firm corrections to config/settings.toml, settings entries only (deadlines, rules and decisions stay out), using entry names exactly as written in chat: whenever an entry was firmly corrected after its first figure, write what it was corrected to. Possibilities only raised, and figures only reported or quoted, change nothing; never add entries.
3. Make config/settings.toml match all firm corrections made in chat to settings entries (deadlines, rules and decisions stay out), under entry names exactly as written in chat: an entry firmly corrected after its first figure gets what it was corrected to. Anything only raised as a possibility, or only reported or quoted, changes nothing, and entries are never added.

**Mechanism.**

Same prompt as v3a, so naive retrieval, BM25 and grep get no evidence. In edition 3 only, the setting-fix correction (B1: the hedge) moves from slot (2,3) to (2,1). The original stays at (1,3). The goal is that even a session-2 sprint puts the whole sprint between the correction and the checkpoint-5 probe, so the recent window misses the evidence in every life. Session 2 is still the evidence session, so hostable, the early-bundle rule and the probe at 5 are unchanged. No spec change.

**Round 1's repair (B2).**

Identical to v3a. File kept; decision rule kept and widened to reports and quotes. DEPARTURE for the owner: the entry name is dropped. It is determined because every gold span names only 'retry interval' verbatim (phrasebank.py:128-130), and the B0 retract+assert vs the B1 hedge fixes when to act. Moving the event does not change any span's text except its stamp.

**Token audit (B3).**

Same prompt and paraphrases as v3a, so the same classes. IN EVIDENCE: none. OUTSIDE ONLY: a, and, config, decisions, in, it, never, out, set, settings, toml, was, what. Sources as in v3a: tool reads diffs.py:23-33 and the template files; quote phrases en.toml:94; 'Got it, thanks.' en.toml:8; negate phrase en.toml:38; sprint session_cut.py:57. ABSENT: as in v3a. The move to (2,1) adds no words: the stamp is digits only (dates.py:60-61). Grep: no evidence token, so no argument is needed.

**Changes.**

Everything in v3a, with the class as DriftActionV3b, plus one world-side change.
In world/targeted.py, inside t1_life (targeted.py:686-689):
  slots = getattr(next((t for t in selected if t.template_id == "drift-config"), None), "SETTING_FIX_AT", ((1, 3), (2, 3)))
Then pass slots to _build_t1 as a keyword and use them at line 373 in place of the literal. DriftActionV3b declares SETTING_FIX_AT: ClassVar = ((1, 3), (2, 1)), and lever_mix records 'placement: correction at session 2 turn 1'.
Editions 1 and 2 select v1/v2 classes, which lack the attribute, so _build_t1 gets the same arguments: byte-identical worlds, histories and packs. t2_dry_run goes through t1_life too.
The setting-fix slots are code literals, not spec fields, so t2.toml, t1.toml and _tier_source stay canon-equal (load_tier, targeted.py:131). No pin is touched: targeted.py is outside the controls pin.
Tests:
- world_hash of every public T2 G1 life under editions 1 and 2 is unchanged;
- in edition 3 the setting-fix second event sits at slot (2,1);
- placement passes on the public lives.
Edition-3 C-7 entry 'drift-config-v3' records levers 1 and 3 (a departure from the lever-mix shape). B8 justification: plan §4's row '1 with 3' predicts a window ≤20. v3a's window is 5·N2 with an expectation of 24, P(>35 on 20 lives)=0.09, and P(≥40 on round 2's 10 lives)=0.21.

**Predicted pair scores (points out of 100; a pair scores its lower twin).**

- **Naive retrieval:** 0, range 0 to 0; 0/0/20. As in v3a: no shared term, h only in the correction event. B0 keep → OMISSION 0; B1 PASS; pair 0.
- **BM25:** 0, range 0 to 0; 0/0/20. No shared term, so no evidence chunk scores >0.
- **Grep:** 0, range 0 to 0; 0/0/20. No grep term matches any evidence event, whatever the placement.
- **Recent window:** 0, range 0 to 5 (at most one life in the session-2-sprint tail). After a (2,1) event come all turn-2..5 sprint chunks (15,971-16,689 tokens over 400 schedules), all events in session 2 turns 2-5 and sessions 3-5 (at least 19 slot events, normally ~0.5-1k tokens), and on average half the turn-1 chunks, which share its t_sim and are ordered by event id (anchors/__init__.py:26-28). Together these exceed 16,384, so the correction falls outside. Session 1 is ≥20,480 tokens back. Lives whose first sprint is in 3-5 stay at 0, as in v3a. Confirm the token margin on the built screening lives.

**Risk to the oracle-evidence row (B5).**

LOW: same argument as v3a, since the oracle receives the same spans whatever their slot. B0: retract+assert → write retry interval=h. B1: hedge → no change. No new route to an extra change. Placement-related risk: the twin plan or placement could fail at (2,1). That slot already holds deadline-0's second link (targeted.py:94); shared slots are normal, e.g. commits share their statement's instant. The trigger twin swaps fact/link/attr rows only (twin.py:187-196), so no slot is vacated. Verify on the screening build.

**No-memory battery (B6b).**

Options, tables and twins identical to v2 and v3a, so the same rows:
- do_nothing, always_abstain, always_never_observed, always_forgotten, channel_distrust, resist_always: 0.
- always_ask: 0.
- generic_default: −100 (B1 changed:update).
- generic_default_reverse: 0.
- fire_on_every_cue, comply_always: −100.
All ≤ 0. Placement does not enter the battery (battery.py:72-77 reads only plans).

**Validity (B6).**

WHAT IT MEASURES: the same memory capability as v3a, but every life now puts the evidence beyond W. The separation from the recent window then comes from distance in every life, not 76% of them. This matches what Drift is meant to test: recalling a decided fact past the window.
(a) Real-system ambiguity: as v3a. Sibling settings entries resolve under the rule. Non-settings corrections are partly excluded by name, and the residual only hits B1.
(b) Battery ≤ 0.
(c) First sprint in session 2: 24.4% of draws (2,441/10,000; uniform over 2-5, schedule.py:83-87). In those lives the correction is preceded by the turn-1 group and followed by 25-26 chunks, so the window misses it. Lives with the sprint in 3-5 are unaffected. The fault rule does not apply to config. evidence_by only governs decision-t2 (targeted.py:398-416), so it is unaffected.

*Designer's confidence, a belief and not a bar:* 55.

**The judge's reasons.**

- B3 Token audit: It reuses K4's audit ('ABSENT: as in v3a'), which leaves paraphrase 1's token 'reflects' unclassed.
- B8 Smallest change: New placement machinery without showing that existing placement fails. v3a's expected window is 24 with P(>35)=0.09, which does not show the window failing.
- Fix named by the judge: Classify 'reflects'. Resubmit the placement change only if the committed screening roster shows N2>=8 (a demonstrated window failure).

<a id="drift-quote-k2"></a>

## `drift-quote` K2: drift-quote v3: 'the one settings entry never committed', with v2's quote rule reworded (prompt only)

- **Designer's angle:** oracle-safety-first (keep the evidence reader right).
- **Levers (PLAN §4):** 1, 4.
- **Judge:** publish with fix; failed B6 Validity.

**Prompt.**

> Add one missing settings entry to config/settings.toml: an entry agreed in conversation but never committed (decisions belong in docs/decisions.md). Name this entry exactly as stated in conversation and use its directly stated content; later reports or quotations of other content do not count.

**Paraphrases.**

1. One settings entry agreed in conversation never reached config/settings.toml. Add this entry under its name exactly as stated in conversation, with its directly stated content, ignoring any later report or quotation of other content.
2. Put into config/settings.toml one settings entry discussed but never committed, named exactly as stated in conversation, with its directly stated content; content only reported or quoted later does not count.
3. config/settings.toml lacks one entry agreed in conversation. Add this entry, named exactly as stated in conversation, using its directly stated content; ignore other content reported or quoted later.

**Mechanism.**

Lever 1, no cue: the prompt describes the target as the one settings entry agreed in conversation but never committed. It names the file, says decisions belong in docs/decisions.md, and says to name the entry exactly as stated. Lever 4: v2's quote rule is restated without any evidence word. v2's 'Add the lock timeout setting' had 'lock' (rare) and 'setting'. 'setting' is the stem in every lock timeout and retry interval value (targeted.py:383), so v2 handed grep and the retrievers a direct hook. The evidence is d's assert at (1,4) and q's quote at (2,4) (targeted.py:380-384; drift_action.py:80). No prompt or paraphrase token occurs in either, so the lexical anchors never see d or q, and the scripted reader takes refrain (OMISSION 0) on both twins. Placement is unchanged (checkpoint 5).

**Round 1's repair (B2).**

What is kept. The file, and v2's quote rule (drift_action_v2.py:36-37): 'Use the value that was set for it directly; a value that was only reported or quoted later does not replace it' becomes 'use its directly stated content; later reports or quotations of other content do not count'. Added: 'name this entry exactly as stated in conversation', which carries over v2's chain-fault exact-name lesson. DEPARTURE for the owner to rule on: the name 'lock timeout' is dropped. Why a reader given only the evidence still knows the entry: the gold spans are linking(d, q), two events that both name only 'lock timeout' (en.toml:37 and :94 put {subject} in the proposition). The entry is absent from the file at k (drift_action.py:74). So the reader adds '"lock timeout" = d': the file comes from the prompt, the name and value from the evidence, and the rule picks d over q.

**Token audit (B3).**

EVIDENCE vocabulary for this item, both twins (fork, wording unchanged): en.toml:37 (assert hard), :94 (quote hard), 'lock timeout' (targeted.py:380), 'value', 'SETTING-dddddd' (targeted.py:383; render/template.py:115-117), digit stamps. Full set: a, be, definitely, for, from, is, it, lock, must, note, now, on, quote, s, said, setting, that, the, timeout, value, was, plus digits. (1) IN EVIDENCE: none, in the prompt or in any paraphrase. 'the', 'a', 'it', 'was', 'that', 'for', 'is' and 'setting' were deliberately avoided ('settings' is a different token). (2) OUTSIDE THE EVIDENCE ONLY: 'config' (session-1 reads; 'config format' decision). 'settings', 'toml', 'docs', 'decisions', 'md', 'in', 'and', 'name' (session-1 reads, diffs.py:23-33, 28: README 'settings, feature flags, routes and recorded decisions', app.py 'def flag(name)', tests 'for line in lines', '# Decisions'). 'never', 'not' (en.toml:38, the negate cell, in commitment-1's cancel event, world/processes/commitments.py:96-100; en.toml:49 phrase 2 'is not', in retract events). 'with' (en.toml:53 phrase 2 'might go with', in hedge events; README). (3) ABSENT from every G1 event: add, one, missing, entry, to, an, agreed, conversation, but, committed, belong, this, exactly, as, stated, use, its, directly, content, later, reports, or, quotations, of, other, do, count, reached, under, ignoring, any, report, quotation, put, into, discussed, named, only, quoted, reported, does, lacks, using, ignore. Grep argument: no evidence token, so grep returns only reads, negate, retract and hedge events of other subjects, and sprint chunks. In every life it never reaches d or q.

**Changes.**

In the same new file, drift_action_v3.py: DriftQuoteV3(DriftQuote) with BINDING_FIELDS = ('chain_id',). It swaps the prompt and sets table drift-quote-v3, with the same admissible and disqualifier entries as v2, and records the same lever_mix departure note. __init__.py: add it to TEMPLATES_V3 and G1_MUTANT_ROLES. editions.py, c7.py, the C-7 file and the tests change as in the drift-config card. Editions 1 and 2 are byte-identical for the same reasons: no world, placement or render edit, and the old classes are untouched. Edition-3 C-7 entry: ref drift-quote@3, class drift_action_v3.DriftQuoteV3, MRO sources drift_action.py, common.py and drift_action_v3.py, table drift-quote-v3, and the lever-mix departure.

**Predicted pair scores (points out of 100; a pair scores its lower twin).**

- **Naive retrieval:** 0 exactly (0/0/n): no evidence chunk scores above 0. With neither d nor q in view, the reader takes the token-less refrain, an OMISSION (0), on both twins.
- **BM25:** 0 exactly (0/0/n), by the same shared-token argument (bm25.py:32-38).
- **Grep:** 0 exactly (0/0/n): no evidence event contains a prompt term, whatever the placement.
- **Recent window:** Exactly -100*k/n, with k the number of lives whose first sprint is in session 2. In those lives q at (2,4) is in view (chunk tokens after it are about 3.9k at turn 5 plus 0-3.9k at turn 4, plus sessions 3-5) but d at (1,4) is not, so the reader picks other-1[q] and hits changed:other, FAIL_MEMORY, a confidently wrong pair. Otherwise neither is in view and the pair gets no credit. Public lives: 0. Screening set: expected -25 (80% interval -40 to -10). The window can only push the best-anchor score down.

**Risk to the oracle-evidence row (B5).**

moderate. Both twins carry the same structure: the gold is d's direct statement plus q's quote. The rule 'directly stated content; later reports or quotations... do not count' selects d, as v2's rule did; v2's oracle passed all 15 of its items, with either quote wording (RESULT.md:86). New risk 1, naming: the file already holds batch_size and flush_timeout_ms with underscores and 'retry interval' with a space. A reader might write 'lock_timeout', which the check, keyed on the exact name 'lock timeout', would fail. 'Name this entry exactly as stated in conversation' targets this, but this is the main reason the risk is moderate. New risk 2: no name in the prompt may make the reader hesitate or ask, which scores OMISSION. No harmful extra change: the reader has evidence about lock timeout only, and extra edits under an act gold do not lower a PASS (action.py:84-86, benign_extras empty).

**No-memory battery (B6b).**

Fork twin; options are v1/v2's: current[d,q], other-1[q], refrain. do_nothing, always_abstain, always_never_observed, always_forgotten, channel_distrust, resist_always: 0 (OMISSION on both). always_ask 0. generic_default 0: B0's current(d0) applied to B1 matches neither current(d1) nor other(q), so FAIL_TASK 0. generic_default_reverse 0, symmetric. fire_on_every_cue and comply_always: the union {d0, d1, q} is applied in canonical order and the last write wins, giving -100 if q is last and 0 otherwise. All <= 0.

**Validity (B6).**

What it measures: recalling, without a cue, that a settings entry was agreed in chat and never committed, and keeping the directly stated value over a later quote of another value. Ambiguity a real system faces and the oracle does not: the uncommitted items at k are lock timeout and four decisions. The decisions are queue backend and retry policy (chat_only = 2, world.py:258) and cache backend and lint policy (targeted.py:409-417); the clause '(decisions belong in docs/decisions.md)' and 'settings entry' exclude them. retry interval's uncommitted correction is an existing entry, not a missing one. The remaining risk is a system that treats a decision as a setting, which is itself a recall error about entity kind. Sprint placement: the same 25% session-2 exposure as drift-config. There the window is confidently wrong (q without d) rather than right, so it lowers the anchor rather than threatening the 35 gate. In sprint-3/4/5 lives the window misses both events.

*Designer's confidence, a belief and not a bar:* 55.

**The judge's reasons.**

- B6 Validity: (a) It claims the uncommitted items at k are 'lock timeout and four decisions'. But milestone deadlines, constraint rules and commitments are also agreed in chat and never committed (PATHS has no such kinds, codebase_model.py:13), and the prompt excludes only decisions. So the ambiguity a real system faces is left unanalysed.
- Fix named by the judge: Extend the exclusion clause to rules, deadlines and tasks (or show why 'settings entry' excludes them), and redo the token audit for any new words.

<a id="drift-chain-fault-k2"></a>

## `drift-chain-fault` K2: drift-chain-fault v3: 'our non-beta milestone' instead of the exact name (prompt only; drops the exact-name repair)

- **Designer's angle:** oracle-safety-first (keep the evidence reader right).
- **Levers (PLAN §4):** 1, 4.
- **Judge:** reject; failed B5 Oracle safety.

**Prompt.**

> Record our non-beta milestone in docs/decisions.md as one line of this form: "- <milestone name>: <current target>". Write its name exactly as stated in conversation, and use its latest target.

**Paraphrases.**

1. In docs/decisions.md, add one line "- <milestone name>: <current target>" about our milestone other than beta; copy its name exactly as stated in conversation and give its latest target.
2. Our milestone besides beta needs one line in docs/decisions.md of this form: "- <milestone name>: <current target>", with its name exactly as stated in conversation and its latest target.
3. Write one line into docs/decisions.md about whichever milestone other than beta we planned, as "- <milestone name>: <current target>": its name exactly as stated in conversation, and its latest target.

**Mechanism.**

Lever 1 on drift-chain-fault: the subject is named by contrast with the other milestone, 'non-beta', and the predicate as 'target'. The line form '- <milestone name>: <current target>' is kept, with 'name exactly as stated in conversation'. The prompt avoids general, release, deadline and due ('due' is the stem of every deadline value, g1 world.py:59), and every other evidence word. The lexical anchors therefore find only the beta release links (deadline-0, targeted.py:94) and session-1 reads, never general release's tokens; the scripted reader takes refrain (0). The probe stays pinned at 10 (targeted.py:101), so the second sprint (sessions {7,9,10}) always lies between the evidence (sessions 1-2) and the probe. Depth is unchanged. This applies lever 1 outside the plan's 'drift-config and drift-quote' scope, a flagged departure.

**Round 1's repair (B2).**

Round 1's repair (#505) was 'the prompt names the exact entry line to write' (validity-1 DECLARATION.md:10). It answered Milestone 1's failure: 10 of 10 entries were written as '<milestone> deadline' (M1 RESULT.md:163). Kept: the file, the exact line form, and an instruction to use the bare name exactly. DEPARTURE for the owner to rule on: the literal name 'general release' and the word 'deadline' are dropped. Why a reader given only the evidence still knows them: the gold spans are the two deadline-1 links. Link 0 is en.toml:37 ('For general release, the deadline is definitely DUE-a' or 'general release's deadline must be DUE-a, from now on'). Link 1 is en.toml:49 plus :37 (retract DUE-a, assert DUE-b). Both name only 'general release', and the placeholder <milestone name> asks for the bare name. 'Latest target' picks the last link. Weaker than v2: the reader must map 'target' to 'deadline' and cannot check 'non-beta' (beta is not in its evidence).

**Token audit (B3).**

EVIDENCE vocabulary for this item, both twins: en.toml:37 and :49, 'general release', 'deadline', 'DUE-dddddd' (g1 world.py:59; token format at world/processes/__init__.py:55-60), digit stamps. Full set: be, confirmed, correction, deadline, definitely, due, for, from, general, is, longer, must, no, not, now, on, release, s, scratch, sure, that, the, plus digits. (1) IN EVIDENCE: none, in the prompt or in any paraphrase. (2) OUTSIDE THE EVIDENCE ONLY: 'beta' (the deadline-0 links only, slots (1,1) and (2,1), targeted.py:94). 'docs', 'decisions', 'md', 'line', 'name', 'in', 'and' (session-1 reads: tests/test_app.py, README, app.py, the '# Decisions' title). 'with' (en.toml:53 hedge phrase 2; README). The session-6 git-log pair read (diffs.py:31, 162-164) has 'record_decision' as one token, so 'record' does not match it. (3) ABSENT from every G1 event: record, our, non, milestone, as, one, of, this, form, current, target, write, its, exactly, stated, conversation, use, latest, add, about, other, than, copy, give, besides, needs, into, whichever, planned, we. Grep argument: no evidence token. Grep returns the beta links, then the reads, so it never sees general release's values.

**Changes.**

New file src/bicentennial/items/templates/g1/drift_chain_v3.py with DriftChainV3(DriftChain). It sets BINDING_FIELDS = ('chain_id', 'depth'), keeps v2's fault=True guard (drift_chain_v2.py:16-19), sets this prompt and table drift-chain-fault-v3, and records the lever_mix departure. __init__.py: add it to TEMPLATES_V3 and G1_MUTANT_ROLES. editions.py, c7.py, the C-7 file and the tests change as above. No world/targeted.py or t2.toml edit; depth and deadline_at are unchanged, which keeps editions 1 and 2 byte-identical. Edition-3 C-7 entry: ref drift-chain-fault@3, MRO sources drift_chain.py, common.py and drift_chain_v3.py, lever_mix value 1, and the note 'lever 1 on the cell whose primary lever is chain_depth: departure'.

**Predicted pair scores (points out of 100; a pair scores its lower twin).**

- **Naive retrieval:** 0 exactly (0/0/n): the top chunks are the beta links and session-1 reads. Without the current or earlier general-release values the reader takes refrain, an OMISSION, on both twins.
- **BM25:** 0 exactly (0/0/n): no shared token with any general-release link.
- **Grep:** 0 exactly (0/0/n): 'beta' (2 events) comes first, then the reads, and no event containing a prompt term carries a deadline-1 token.
- **Recent window:** 0 exactly on every life: the probe is at session 10 and the second sprint is in {7,9,10} (scale.py:67, with sessions 6 and 8 excluded as fault points). That sprint is at least 20,480 tokens, more than W, and lies after the evidence in sessions 1-2.

**Risk to the oracle-evidence row (B5).**

high. Both twins are forks with the same wording, and the gold is the two links. A careful reader writes '- general release: DUE-b' (B1: its own DUE-b'). Three new risks on the template whose Milestone 1 oracle failure was exactly the entry name: (1) the prompt no longer spells the name; (2) 'target' must be read as 'deadline'; (3) 'non-beta' cannot be checked against the evidence. A wrong name or value leaves the file matching neither option, a FAIL_TASK, 0. No harmful extra: the reader has evidence about one milestone only. The live smoke (D7) would decide; under this card's oracle-safety-first angle it is not recommended without the owner accepting the departure.

**No-memory battery (B6b).**

Fork twin; options current[last], other-1[first], refrain, unchanged. Empty-plan policies (do_nothing, always_abstain, always_never_observed, always_forgotten, channel_distrust, resist_always) 0. always_ask 0. generic_default and generic_default_reverse 0 (FAIL_TASK on the other twin). fire_on_every_cue and comply_always: the union {last0, last1, first}, last write wins, gives -100 or 0. All <= 0.

**Validity (B6).**

What it measures: recalling which milestone, other than beta, carries a corrected deadline, and its latest value, across 8 sessions, a kill and cold restarts. Ambiguity a real system faces and the oracle does not: the world has exactly two milestones (g1 world.py:59; Mix(deadlines=(1,1)), targeted.py:366), so 'non-beta' is unique. A system might confuse the release checklist commitment (predicate 'deliver') with a milestone; low. The oracle never sees beta, so for the oracle the indirection is trivially resolved. Sprint placement: the window is 0 on every life (second sprint after session 6); a first sprint in session 2 is irrelevant at checkpoint 10.

*Designer's confidence, a belief and not a bar:* 30.

**The judge's reasons.**

- B5 Oracle safety: The argument does not establish that the gold-only reader picks the right action. The card concedes the reader cannot check 'non-beta', must map 'target' to 'deadline', and is left with the Milestone-1 name failure mode, and it rates the risk high.
- Fix named by the judge: Restore a checkable subject (the exact name or a cue the gold evidence contains), with an argument that the gold-only reader writes '- general release: <last>' on both twins. The owner must accept the departure first.
