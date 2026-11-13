# Validity round 2: the seven screened candidate cards

Published before any candidate report. Each card is printed as its designer wrote it; the only addition is the owner's fix to `drift-config` K4's token audit, marked. How the cards were made and chosen, and what was seen before, is in [README.md](README.md). The four cards that are not screened are in [NOT-SCREENED.md](NOT-SCREENED.md); the judge's full scores are in [JUDGE.md](JUDGE.md).

- `drift-config`: [K1](#drift-config-k1), [K3](#drift-config-k3), [K4](#drift-config-k4)
- `drift-quote`: [K1](#drift-quote-k1), [K3](#drift-quote-k3)
- `drift-chain-fault`: [K1](#drift-chain-fault-k1), [K3](#drift-chain-fault-k3)

<a id="drift-config-k1"></a>

## `drift-config` K1: drift-config v3a: retry cue drowned in sprint logs, rule restated without evidence words (prompt only)

- **Designer's angle:** retrieval-adversarial (beat the anchors).
- **Levers (PLAN §4):** 1, 4.
- **Judge:** publish; every bar passed.

**Prompt.**

> Check the retry entry in config/settings.toml against what the team decided. If the team later firmly corrected its figure, set the corrected figure under the same entry name; if a new figure was only floated as a possibility, leave the file unchanged.

**Paraphrases.**

1. Look at the retry entry of config/settings.toml and check it against what was agreed. When its figure was later firmly replaced, write the replacement under the same entry name; when a new figure was merely suggested as a possibility, leave the file alone.
2. Bring the retry entry of config/settings.toml up to date against what the team settled: if the team firmly corrected its figure later, apply the corrected figure under the same entry name; if a new figure was only tentatively floated, keep the file unchanged.
3. Review the retry entry in config/settings.toml against what the team decided. Where the team later firmly corrected its figure, put the corrected figure under the same entry name; where a new figure was only tentatively suggested, leave the file unchanged.

**Mechanism.**

Lever 1, partial: the subject cue is cut from 'retry interval' to 'retry'. 'interval' is rare and sits in evidence. 'retry' is in every sprint-log line ('"retry":', session_cut.py:53-54), so it is counted in more events than any filler. Lever 4: the decision rule is restated without 'value', 'correction', 'for', 'that', 'not', 'sure', 'no' or 'with'. Every text also carries two sprint-only fillers, 'what' (in every chunk, :57) and 'file' (in about 95% of chunks, :21). Grep's rarest-first order (anchors/grep.py:14) visits those fillers first. Their newest sprint chunks fill W (anchors/__init__.py:37-43) before 'retry' or 'the' is visited. The path words config/settings/toml make the session-1 tool-read chunks win the TF-IDF and BM25 top 5. Placement is unchanged: correction at (2,3) (targeted.py:373), probe at checkpoint 5.

**Round 1's repair (B2).**

File: kept (config/settings.toml). Decision rule: kept and restated ('firmly corrected' means set it; 'only floated as a possibility' means leave the file unchanged). Entry name: DEPARTURE for the owner to rule on. 'retry interval' becomes 'the retry entry ... under the same entry name'. Why a reader handed only the evidence still gets the entry: every gold event (original, its commit, and the correction or hedge) puts 'retry interval' in the subject slot (targeted.py:369-373; en.toml:37,49,53). It is the only entry the evidence names, and the prompt's 'retry' plus 'same entry name' points to it. The file holds only batch_size, flush_timeout_ms and retry interval (world.py:63; targeted.py:369), so a reader that opens the file finds one entry with 'retry' in it. 'retry policy' is a decision and quiet_retry is a flag; both live in other files (codebase_model.py PATHS). Quote rule: not applicable.

**Token audit (B3).**

Classes are from a static scan, not a build. G1 renders only these phrasebank cells: en.toml:8, 37-38, 49, 53 and 94. Modality is always 'stated' (processes/__init__.py:121-126) and the speech acts are assert, hedge and quote (corrections.py:78; twin.py:193). The scan also covered names, predicates and stems (world.py:58-67; targeted.py:369-384, 404-410), the tool reads (diffs.py:23-33, 28-29; service_template files), git log subjects (diffs.py:69-70) and sprint text (session_cut.py:20-21, 53-57). Evidence events: original plus commit (en.toml:37) and correction (en.toml:49+37) on B0, hedge (en.toml:53) on B1, each with subject 'retry interval', predicate 'value' and object 'SETTING-dddddd'.
ABSENT from every G1 event: against, agreed, alone, apply, as, at, bring, check, corrected, date, decided, entry, figure, firmly, floated, if, its, keep, later, leave, look, merely, new, of, only, possibility, put, replaced, replacement, review, same, settled, suggested, team, tentatively, to, unchanged, under, up, when, where, write.
OUTSIDE EVIDENCE ONLY:
- config: app.py:3,7; test_app.py:6; the 'config format' decision event, its commit and the git log.
- settings: README.md:3; app.py:6-7; test_config.py:5,10; '# Service settings' header (diffs.py:28).
- toml: app.py:7,11,15.
- in: test_app.py:13; test_config.py:10,12.
- name: app.py:18-19.
- set: test_config.py:19.
- and: README.md:3; test_config.py:15.
- a: README.md:3; en.toml:94 phrase 1 (quote events only).
- was: en.toml:94 phrase 0 (quote events only).
- it: en.toml:8 'Got it, thanks.'; en.toml:94 phrase 0.
- what: sprint footer, every chunk, count = n (n = 32-33 chunks per sprint, from the pure _chunk).
- file: sprint message 'spool file rotated', in about 95% of chunks.
IN EVIDENCE: 'the' (en.toml:37 phrase 0, :49 phrase 0, :53) and 'retry' (subject). The same two in the prompt and all three paraphrases.
Grep argument: at checkpoint 5 at least one sprint is visible, because the first sprint falls in sessions 2-5 (scale.py:67). Event counts:
- the outside-only terms: 1-6 events each, about 0.5k tokens in total;
- file: about 0.95n;
- what: exactly n;
- retry: at least n+4 (every chunk, plus the original, commit and correction or hedge, plus the retry-policy decision);
- the: far above n (every chunk header plus most fact events).
Terms are visited in ascending count, ties alphabetical (grep.py:14), so file and then what come before retry and the. Their events are sprint chunks only (618-668 tokens each). Newest first, about 25 of them fill W = 16,384, and bounded() breaks. retry and the are never visited, in every life, including lives whose sprint falls in session 2: there the chunks are newest first inside session 2, and the correction event holds neither 'file' nor 'what'. Banned words, each rarer than n and in evidence: interval, value, correction, for, that, not, sure, no, s (any apostrophe), with, must, be, now, on, definitely, setting (the SETTING-dddddd tokens, processes/__init__.py:37-60).

**Changes.**

New file src/bicentennial/items/templates/g1/drift_config_v3.py: DriftActionV3(DriftAction), with BINDING_FIELDS=("chain_id",). instances() takes v1's single instance and replaces only the prompt. Table ids become drift-config-corrected-v3 / -hedged-v3. Options, gold_spans and twin are unchanged. A lever_mix override keeps the keys and records 'prompt cue reduced (lever 1), rule reworded (lever 4)'.
items/templates/g1/__init__.py gets TEMPLATES_V3, and G1_MUTANT_ROLES iterates over it too. It is not a class file. The pin closure misses it because score/check_selftest.py:111-115 imports it dynamically; v2 set the precedent.
items/editions.py: EDITIONS[3] = {"G1": _swap(_swap(g1.TEMPLATES, g1.TEMPLATES_V2), finalists), "G2": g2.TEMPLATES}, and C7_FILES[3] = "specs/ring0/c7-edition3.json".
items/c7.py:95: choices become (1, 2, 3).
Commit specs/ring0/c7-edition3.json. Its drift-config-v3 entry carries the class and its MRO source hashes (c7.py:46-69) and the lever-mix departure.
Tests:
- test_editions.py:127-133 refuses edition 4 instead of 3;
- EDITIONS[1] and [2] objects and the edition-1/2 C-7 files are unchanged;
- the public T2 pack hashes for edition 1 (15141b19...) and edition 2 (3e58b801...) are unchanged;
- a prompt-lint test on one built life: every token of the prompt and paraphrases is in its class, and a filler is present.
No change to world/targeted.py, controls/*, render/*, score/*, world/processes/* or the existing class files. Editions 1 and 2 stay byte-identical: their template objects, the class files in their MRO and the world code are untouched.

**Predicted pair scores (points out of 100; a pair scores its lower twin).**

- **Naive retrieval:** 0 (range 0 to 5). The top-5 TF-IDF chunks (naive_rag.py:77-97) come from: app.py ('settings', 'config' and 'toml' with document frequency 1-6); test_config ('settings', 'in', 'set'); '# Service settings' x2; README; quote chunks ('was'). The correction chunk shares only 'the' x2 and 'retry' x2 (inverse document frequency about 0.3): hand estimate cosine about 0.9 against at least 5 for the fifth chunk. B0: h absent, so keep and OMISSION 0 (action.py:89-90). B1: no option selected, so PASS (action.py:79-81). Pair 0. A wrong pair is impossible because the corrected table has no disqualifier (g1/__init__.py:33). v1's prompt, which included 'interval', already scored 0/5.
- **BM25:** 0 (range 0 to 5). Same competitors. The evidence chunk scores about 3 ('the' at count 2, plus 'retry'); the fifth chunk scores at least 7 ('settings' idf about 4.4, 'toml' about 5.9, 'in'/'set'/'name' about 5-6, 'was' about 5.4). Sprint footer chunks ('what' plus 'file') score about 3-5. h is never in the top 5. Pair 0.
- **Grep:** 0, exactly, on every life, prompt and paraphrase. 'file' (about 0.95n) and 'what' (n) are visited before 'retry' (at least n+4) and 'the'. Their sprint-chunk events fill W, and the correction event is never selected. B0 gives OMISSION, B1 gives PASS, so every pair is 0.
- **Recent window:** Exactly 100·n2/N, where n2 counts the lives whose first long sprint is session 2. n2 can be computed with the pure build_schedule on the placed screening roster before any report. On the public G1 lives n2 = 0 (sprints (3,10), (4,10), (4,10), (4,9), (5,7)), so 0. On 20 fresh lives the expectation is 25, 90% range 10 to 40 (P(first sprint = 2) = 1/4; 535 of 2,000 arbitrary seeds). Mechanism: a sprint in sessions 3-5 (at least 20,480 tokens) hides (2,3). With the sprint in session 2, only the chunks at turns 3-5 (11.5-12.1k, computed) and sessions 3-5 (an estimated 0.5-1.8k) follow (2,3). So h is reached and the pair is right.

**Risk to the oracle-evidence row (B5).**

low. B0: the reader holds the original, the commit and 'Correction, confirmed: ... definitely no longer P ... must be H' (en.toml:49,37). The prompt's 'firmly corrected' matches, so it runs set_entry(config/settings.toml, 'retry interval', H). B1 (hedge twin): 'Maybe the value for retry interval is H' or 'retry interval might go with H' (en.toml:53) matches 'only floated as a possibility', so it leaves the file unchanged and the refrain gold passes. Extra changes: the prompt scopes to one entry and orders the file left unchanged in the hedge case. Any extra change on B1 would score FAIL_TASK 0, because the whole repository state is compared (check_selftest.py:83; hermes_score.py:55), and the prompt rules that out explicitly. Residual risk: 'figure' for a SETTING-dddddd code, and the name having to come from the evidence. Round 1's v2 scored 15/15 with the same evidence.

**No-memory battery (B6b).**

Options and tables are identical to v1/v2, so these are the same as edition 2.
- do_nothing: 0 (B0 OMISSION, B1 PASS)
- always_abstain: 0
- always_never_observed: 0
- always_forgotten: 0
- always_ask: 0 (OMISSION on both twins, action.py:77-78)
- generic_default: -100 (B0's update[h] passes B0; B1 changed:update gives FAIL_MEMORY)
- generic_default_reverse: 0 (B1's keep)
- fire_on_every_cue: -100 (the union is {set h})
- channel_distrust: 0
- comply_always: -100
- resist_always: 0
All ≤ 0. The construction check (battery.py:122-139) already passes for these options.

**Validity (B6).**

Capability: recalling that the decided value of the one retry setting was firmly corrected in session 2 (and, on the twin, only hedged), at least three sessions and three cold restarts later. The subject's only lexical handle, 'retry', is buried in every one of the 32-66 visible log chunks.
Ambiguity a real system faces and the oracle does not:
(i) 'retry' also names the retry-policy decision and the quiet_retry flag. Both live in other files, and the path settles it.
(ii) Other entries of the same file carry later hedges or quotes (batch_size's hedge, flush_timeout_ms's quote, world.py:181,240-248), and lock timeout is missing. The prompt is scoped to the retry entry and orders 'leave the file unchanged', so none of them is in scope. If a real system edits them on B1 it fails, which is the round-1 rule.
Battery: every POLICY ≤ 0 (see battery).
Recent window: the probe is at checkpoint 5 (_assign_checkpoints, targeted.py:290-345) and the correction at (2,3). The first sprint is uniform over {2,3,4,5}: sprint_ranges are ((2,5),(7,10)) (scale.py:67), and candidates exclude the kill (6) and the swap (8) (scale.py:72-75; schedule.py:83-87). So about 1 life in 4 has its first sprint in session 2, the window reaches h there, and the pair scores right. On 20 lives P(n2 ≥ 8) ≈ 10%, which would break the ≤35 gate. This card therefore cannot guarantee ≤35 on the window: n2 is computed from the committed roster before any report, and card v3b is used if n2 ≥ 8.

*Designer's confidence, a belief and not a bar:* 55.

<a id="drift-config-k3"></a>

## `drift-config` K3: drift-config v3: the file, not the entry; v2's decision rule reworded so it shares no word with the evidence (prompt only)

- **Designer's angle:** oracle-safety-first (keep the evidence reader right).
- **Levers (PLAN §4):** 1, 4.
- **Judge:** publish; every bar passed.

**Prompt.**

> Check config/settings.toml. If an entry was firmly corrected after it was committed, set its corrected content; if new content was only raised as a possibility, or only quoted or reported, leave such an entry unchanged.

**Paraphrases.**

1. Review every entry in config/settings.toml. Where an entry was firmly corrected after being committed, write its corrected content. Where an entry only had new content floated as a possibility, or quoted or reported, keep it as it stands.
2. Look over config/settings.toml entry by entry: an entry firmly corrected since it was committed gets its corrected content; an entry whose new content was only raised as a possibility, or only quoted or reported, stays unchanged.
3. Apply to config/settings.toml only firm corrections made after an entry was committed, writing each corrected content; an entry whose new content was only raised as a possibility, or only quoted or reported, keeps its current content.

**Mechanism.**

Lever 1, no cue: the prompt names config/settings.toml but not the entry. Lever 4: v2's rule is restated in words that appear in no evidence event. Placement is unchanged: probe at checkpoint 5, evidence at (1,3) and (2,3) (targeted.py:369-373). After the rewording, no \w+ token of the prompt or of any paraphrase occurs in either twin's evidence events. Those events are the original chat statement, the commit, and the B0 correction or the B1 hedge (drift_action.py:55; common.py:44-49). Hashed TF-IDF and BM25 therefore give every evidence chunk dot = 0 or score = 0, so it is never ranked (naive_rag.py:84-89; anchors/bm25.py:17-18). Grep only returns events that contain a prompt term (anchors/grep.py:11-18), so it never returns one either. The scripted reader therefore never sees h. B0 falls to the token-less keep (an OMISSION, 0) and B1 to None (PASS), so every lexical pair is 0. Only the recent window can reach h, and only on lives whose first sprint is in session 2.

**Round 1's repair (B2).**

What is kept. The file (config/settings.toml) and v2's decision rule (drift_action_v2.py:20-21): set a firm correction, leave a value that was only raised as a possibility. 'A firm correction replaced its value' becomes 'firmly corrected after it was committed', and 'only raised as a possibility' is kept word for word. One clause is added, 'or only quoted or reported', because a no-cue prompt covers every entry and flush_timeout_ms carries a quote mention (g1 world.py:181, 240-248). DEPARTURE for the owner to rule on: the entry name 'retry interval' is dropped. Why a reader given only the evidence still knows the entry: the gold spans are linking(p, h) (drift_action.py:55; common.py:44-49). Every one of those events, in both twins, names one subject only ('retry interval'), whose original value p sits in the file at k (precondition at drift_action.py:39). So the file comes from the prompt and the entry and its value from the evidence. B0 carries a retract of p and an assert of h, so set h. B1 carries only a hedge of h, so leave it.

**Token audit (B3).**

Every \w+ token of the four texts (prompt plus paraphrases) was checked against the G1 vocabulary built from the code. That covers the phrasebank cells G1 uses, entity names and stems, sprint chunks, and the session-1 tool reads. EVIDENCE vocabulary for this item, both twins: en.toml:37 (assert hard), :49 (retracted hard), :53 (hedge soft); subject 'retry interval' (targeted.py:369); predicate 'value'; object 'SETTING-dddddd'. The stem is set at targeted.py:372 and the token format at world/processes/__init__.py:55-60, and the token is rendered verbatim (render/template.py:115-117), so 'setting' is an evidence word. Chat stamps are digits only (render/dates.py:61). Full set: be, confirmed, correction, definitely, for, from, go, interval, is, longer, maybe, might, must, no, not, now, on, retry, s, scratch, setting, sure, that, the, value, with, plus digits. (1) IN EVIDENCE: none, in the prompt or in any paraphrase. (2) OUTSIDE THE EVIDENCE ONLY: 'config' (session-1 reads of service/app.py and service/config.py via diffs.py:31-33; the 'config format' decision, g1 world.py:61). 'settings', 'toml' (session-1 reads only: README, app.py, the TITLES heading at diffs.py:28). 'in', 'set' (session-1 reads: tests/test_app.py 'for line in lines', tests/test_config.py 'set(values)'). 'a' (en.toml:94 phrase 2 'Quote from a note', in the lock timeout and flush_timeout_ms quote events; README). 'it', 'was' (en.toml:94 phrase 1 'It was said'; en.toml:8 'Got it'). 'stands' (sprint chunk 'What stands out?', render/session_cut.py:57). (3) ABSENT from every G1 event: check, if, an, entry, firmly, corrected, after, committed, its, content, new, only, raised, as, possibility, or, quoted, reported, leave, such, unchanged, review, every, where, being, write, had, floated, keep, look, over, by, since, gets, whose, stays, apply, to, firm, corrections, made, writing, each, keeps, current. Grep argument: there is no evidence token, so grep's rarest-first pass collects only session-1 reads, quote events, factless lines and sprint chunks. That holds in every life, whatever the sprint placement. Unchanged from round 1: v1/v2's 'interval' is rare and sits in every setting-fix event, which is why grep scored 5/0/0 on v1.

**Changes.**

New file src/bicentennial/items/templates/g1/drift_action_v3.py with DriftActionV3(DriftAction). It sets BINDING_FIELDS = ('chain_id',) (needed because items/bindings.py is keyed by class path). It calls super().instances() and replaces only the prompt and the table ref, to drift-config-corrected-v3 or drift-config-hedged-v3. It overrides lever_mix to record 'round-2 lever 1 (no cue) + lever 4; departure from C-7's lever-mix shape (validity-2 PLAN §4)'. items/templates/g1/__init__.py gets a TEMPLATES_V3 entry with the v2 tables under v3 ids, and the G1_MUTANT_ROLES comprehension extends to TEMPLATES_V3. That is the same edit #519 made for v2. The file is not a class file; score/check_selftest.py:111-114 imports it dynamically, and round 1's scorer pin did not move after #519 (validity-1 RESULT.md:15-20). items/editions.py: EDITIONS[3] = {'G1': _swap(_swap(g1.TEMPLATES, g1.TEMPLATES_V2), <the v3 finalists>), 'G2': g2.TEMPLATES} (recall-count-v1 is carried, per D5), and C7_FILES[3] = 'specs/ring0/c7-edition3.json'. items/c7.py:95 choices become (1, 2, 3). Commit specs/ring0/c7-edition3.json. Tests: tests/items/test_editions.py:127-133 moves its refusal case to edition 4. Add a test that no \w+ token of the v3 prompt occurs in any gold-span text on test lives. Add a test that catalogue-v0.toml c7_sha256 and c7-edition2.json are unchanged. Why editions 1 and 2 stay byte-identical: no world, placement or render file changes. The world build never reads templates (targeted.py:353-396). Templates enter only through _assign_checkpoints, compile and the twin plan (targeted.py:290, 609), taken from the edition's own EDITIONS entry, and the edition 1 and 2 template objects and class files are untouched. Nothing in world/targeted.py or the tier specs changes. Edition-3 C-7 entry: ref drift-config@3, class drift_action_v3.DriftActionV3, MRO sources drift_action.py, common.py and drift_action_v3.py, tables *-v3, and the lever-mix departure note.

**Predicted pair scores (points out of 100; a pair scores its lower twin).**

- **Naive retrieval:** 0 exactly (0 right / 0 wrong / n no credit) on the public lives and the screening set. No evidence chunk shares a word with the prompt, so none gets dot > 0. Without h, B0 takes keep (OMISSION 0, score/action.py:89-90) and B1 takes None (PASS, action.py:79-81).
- **BM25:** 0 exactly: BM25 scores only shared tokens (api/adapters/bm25.py:26-38, tokens = \w+ over casefold) and the anchor keeps only score > 0 (anchors/bm25.py:17-18). No evidence chunk is ever in the top 5.
- **Grep:** 0 exactly: grep collects only events containing a prompt term (anchors/grep.py:11-18), and no evidence event contains one. This does not depend on placement.
- **Recent window:** Exactly 100*k/n points, where k is the number of lives whose first sprint is in session 2; those pairs are right, all others get no credit. Public G1 lives: first sprints are in sessions {3,4,4,4,5}, computed with t1_schedule, so 0. Screening set: k is computable from the committed seeds before any report. Expected 25 (k ~ Bin(20, 1/4)), 80% interval 10-40. The chance that k >= 8, which would push the window above 35, is about 10%.

**Risk to the oracle-evidence row (B5).**

low. B0 gold is the original, the commit and the correction ('...no longer p...must be h'); the rule 'firmly corrected after it was committed, set its corrected content' gives set_entry(config/settings.toml, retry interval, h). B1 gold is the original, the commit and the hedge ('Maybe the value for retry interval is h' or 'retry interval might go with h'); 'only raised as a possibility... leave such an entry unchanged' gives no change, which passes the refrain table. The hedge-twin wording is v2's, which the oracle passed 15 of 15 (RESULT.md:85). No new way to make a harmful change: the gold-only reader has no evidence about batch_size or flush_timeout_ms, the prompt asks for no addition, and B1 passes only with no change, which the rule asks for. Residual: 'Check config/settings.toml' could tempt a reader to audit the whole file or ask the user. Asking scores OMISSION (action.py:77-78). The smoke would show this.

**No-memory battery (B6b).**

Options, tables and twin are v2's, and the battery never reads the prompt (controls/battery.py:72-77), so: do_nothing 0, always_abstain 0, always_never_observed 0, always_forgotten 0, channel_distrust 0, resist_always 0 (empty plan: B0 OMISSION, B1 PASS). always_ask 0 (OMISSION on both, action.py:77-78). generic_default -100 (B0's gold update applied to B1 hits changed:update, FAIL_MEMORY). generic_default_reverse 0 (B1's first option, keep, has no steps). fire_on_every_cue -100 and comply_always -100 (the union is {update h}, so B1 fails). All <= 0.

**Validity (B6).**

What it measures: without a cue, recalling which settings entry got a firm correction that was never committed, and its value, across 3+ sessions and cold restarts. Lexical retrieval gets no hook. Ambiguity a real system faces and the oracle does not: the file can also hold batch_size and flush_timeout_ms. batch_size's correction is committed at its own instant (g1 world.py:260-262; COMMIT_LAG_S = 0), so it is not pending; its later hedge, and flush_timeout_ms's later quote, are excluded by the rule's 'only raised as a possibility, or only quoted or reported'. So with full memory B0 has exactly one change and B1 none. The remaining real-system risk is adding lock timeout, which is not asked for and would fail the B1 refrain. Sprint placement: T2's first sprint is uniform over {2,3,4,5}; a tally over 3,000 synthetic schedules gave 730/735/741/794 (scale.py:61-70). In the ~25% of lives with the first sprint in session 2, about 32 chunks of 620-663 estimated tokens are cut round-robin over the session's turns (session_cut.py:118-138). About 7.7k of chunk tokens sit at turns 4-5 and 0-3.9k more at turn 3 after the correction, plus small sessions 3-5 (estimated <= 1.5k, unmeasured). That is about 8.7-13.1k, under W, so the window holds the (2,3) correction or hedge and gets the pair right. The original at (1,3) is out of view, but it is not needed. In sprint-3/4/5 lives the sprint (>= 20,480 tokens) lies between the evidence and the probe, so the window misses. Session-2 sprints: none on the public lives; expected 5 of 20 on the screening set; risk to round 2's 10 fresh lives: P(window > 35) is about 22%. A fix exists (setting-fix slot (2,1), edition-aware) but needs new placement machinery; under B8 it is not proposed unless the screen shows the window above 35.

*Designer's confidence, a belief and not a bar:* 60.

<a id="drift-config-k4"></a>

## `drift-config` K4: drift-config v3a: apply every firm correction to config/settings.toml, no entry named (lever 1, prompt only)

- **Designer's angle:** mechanism-validity (the separation must be a memory capability).
- **Levers (PLAN §4):** 1.
- **Judge:** publish with fix; failed B3 Token audit.

**Prompt.**

> Bring config/settings.toml up to date, applying firm corrections only, and only to settings entries (deadlines, rules and decisions stay out), keeping entry names exactly as written in chat. Where a settings entry was later firmly corrected, write what it was corrected to. Where a new figure was only raised as a possibility, or only reported or quoted, change nothing. Never add entries.

**Paraphrases.**

1. Update config/settings.toml so it reflects all firm corrections to settings entries and nothing else; deadlines, rules and decisions stay out, and entry names stay exactly as written in chat. If an entry had its figure firmly corrected later, set what it was corrected to; if a change was merely floated as a possibility, or merely reported or quoted, leave it alone. Never add entries.
2. Apply all firm corrections to config/settings.toml, settings entries only (deadlines, rules and decisions stay out), using entry names exactly as written in chat: whenever an entry was firmly corrected after its first figure, write what it was corrected to. Possibilities only raised, and figures only reported or quoted, change nothing; never add entries.
3. Make config/settings.toml match all firm corrections made in chat to settings entries (deadlines, rules and decisions stay out), under entry names exactly as written in chat: an entry firmly corrected after its first figure gets what it was corrected to. Anything only raised as a possibility, or only reported or quoted, changes nothing, and entries are never added.

**Mechanism.**

Remove every word the evidence events contain. The task becomes a sweep: apply every firm correction to a settings entry. Grep, BM25 and naive retrieval then have no term that touches the original (1,3), its commit, or the correction/hedge at (2,3). The decisive token h appears only in the correction event (template.py:156-160). The probe sits at checkpoint 5 in every life: _assign_checkpoints takes the earliest hostable checkpoint under the cap of 2 actions (targeted.py:308-345), and placement.json shows this for every round-1 G1 life. The evidence is in sessions 1-2. So the recent window misses it except in lives whose first long sprint is in session 2. Options, tables and twin type are v2's, unchanged.

**Round 1's repair (B2).**

KEPT: the file (config/settings.toml). KEPT and widened: v2's decision rule (drift_action_v2.py:20-21). 'A firm correction replaced its value, set the new value' becomes 'later firmly corrected, write what it was corrected to'. 'Only raised as a possibility, leave unchanged' is kept. The rule now also says that reports and quotes change nothing, so it is true for every entry in the file, not only the probed one. No quote rule applies to this id.
DEPARTURE, for the owner to rule on: the entry name 'retry interval' is dropped. Replaced by: the entries that got a firm correction, plus 'keeping entry names exactly as written in chat'.
Why a reader handed only the evidence still knows the entry: the gold spans are the original chat event, its commit and the (2,3) event (linking(p,h), drift_action.py:55). All carry one subject. Each clause holds {subject} exactly once (phrasebank.py:128-130), so the string 'retry interval' appears verbatim in every span. The B0 span is a retract plus assert, i.e. a firm correction, so the reader writes retry interval=h. The B1 span is 'Maybe the value for retry interval is ...' / '... might go with ...' (en.toml:53), which is a possibility, so the reader changes nothing. Where (file and entry), when (decision rule) and what are all fixed by prompt plus evidence.

**Token audit (B3).**

METHOD. A static vocabulary of every G1 event class:
- fact clauses from the cells G1 renders (assert.stated.hard affirm/negate, assert.retracted.hard affirm, hedge.stated.soft affirm, quote.stated.hard affirm; en.toml:37-38,49,53,94);
- every G1 subject and predicate (world.py:58-67; targeted.py:369-384,405-409);
- STEM-dddddd values (processes/__init__.py:55-60);
- chat stamps, digits only (dates.py:60-61); factless lines (en.toml:8);
- sprint chunks (session_cut.py:20,53-57);
- session-1 tool reads: template files, titles and the template git log (diffs.py:23-33,76-79,160-170);
- the session-6 git log of commit subjects.
Modality is always 'stated', so observed and propose cells never render (processes/__init__.py:126, world.py:127).
Config evidence vocabulary, B0 and B1 together: be confirmed correction definitely for from go interval is longer maybe might must no not now on retry s scratch setting sure that the value with, plus digits. Note: 'setting' IS in evidence, because SETTING-dddddd lower-cases to 'setting' (targeted.py:372). The digest says otherwise.
IN EVIDENCE: none, in the prompt or in any paraphrase.
OUTSIDE EVIDENCE ONLY:
- config: tool reads service/app.py, tests/test_app.py; the 'config format' decision, world.py:62
- settings: README.md, app.py, test_config.py, the '# Service settings' title (diffs.py:28)
- toml: app.py only
- decisions: README.md, test_app.py, '# Decisions'
- and: README.md, test_config.py
- in: test_app.py, test_config.py
- set: test_config.py
- a: quote phrase #1 (en.toml:94) and README.md
- was, it: quote phrase #0 (en.toml:94) and 'Got it, thanks.' (en.toml:8)
- never: negate phrase #0 (en.toml:38), used only by commitment cancellations
- what, out: the sprint line 'What stands out?' (session_cut.py:57)
ABSENT: add added after all alone an anything apply applying are as bring change changes chat corrected corrections date deadlines else entries entry exactly figure figures firm firmly first floated gets had if its keeping later leave made make match merely names new nothing only or possibilities possibility quoted raised reported rules so stay to under up update using whenever where write written.
Grep: no prompt token is in evidence, so no argument is needed. Grep's terms collect only tool reads, quote, filler and cancellation events, and sprint chunks. None carries h.
The audit is static. Before the screen, confirm with per-term event counts on built lives.

**Owner's fix (judge, B3):** paraphrase 1's token `reflects` is absent from every G1 event: no G1 text source (`render/`, `items/`, `world/`, `sandbox/`) contains `reflect` or `reflects`, and none of the 1,558 visible G1 events on the ten public lives does.

**Changes.**

NEW FILE src/bicentennial/items/templates/g1/drift_action_v3.py:
- class DriftActionV3(DriftAction), declaring BINDING_FIELDS=("chain_id",) (bindings.py:10-25,55-56).
- instances() calls super(), then returns Instance(key, probe_point, prompt=<literal>, options, gold_spans, decisive_fact_id unchanged, decision_table_ref = drift-config-corrected-v3 or -hedged-v3).
- The prompt is a keyword literal, because the cue_words.py walker needs that (cue_words.py:69-80). It contains no CUE_PHRASES.
- lever_mix is overridden to record 'cue removed from prompt (round-2 lever 1)'.
EDIT items/templates/g1/__init__.py (no class in it, outside every pin): add TEMPLATES_V3 with v2's two tables under -v3 ids, and run G1_MUTANT_ROLES over TEMPLATES_V3 too, because check_selftest.py:111-119 reads it.
EDIT items/editions.py:
- EDITIONS[3] = _swap of the edition-2 G1 tuple with the finalists; G2 = g2.TEMPLATES (recall-count-v1, plan D5);
- C7_FILES[3]="specs/ring0/c7-edition3.json".
EDIT c7.py: --edition choices (1,2,3) (c7.py:95).
COMMIT specs/ring0/c7-edition3.json.
TESTS:
- tests/items/test_editions.py: registries, BY_REF count, the edition-3 refusal case at :127-133, NEW_FILES;
- v3 keeps v2's options, tables and bindings;
- a vocabulary test: prompt words ∩ evidence-event words = ∅ on a built T1 G1 life.
EDITIONS 1 AND 2 STAY BYTE-IDENTICAL: no existing class file is edited. C-7 entries hash only the source files in each class's MRO (c7.py:46-50), so the c7-partial pin (test_editions.py:91-103) and c7-edition2.json are unchanged. Worlds do not depend on prompts. G1_MUTANT_ROLES only gains keys, and lookups are per table (check_selftest.py:146-147). No controls/render/score/world.processes file is touched (the controls pin's 95 files exclude targeted.py, items/templates/g1/* and editions.py; computed from cache.CONTROL_FILES).
EDITION-3 C-7 ENTRY 'drift-config-v3': cell DRIFT-CUR, primary chain_depth, lever_mix.template noting the departure from the C-7 lever-mix shape (PLAN §4 last paragraph).

**Predicted pair scores (points out of 100; a pair scores its lower twin).**

- **Naive retrieval:** 0, range 0 to 0. Pairs right/wrong/no credit: 0/0/20 on screening, 0/0/5 on public lives. No prompt or paraphrase word occurs in any evidence event, so no evidence chunk has dot>0 (naive_rag.py:88) and h never reaches the context. B0: update needs h, so keep (no tokens) is chosen: no change, OMISSION 0 (action.py:89-90). B1: both options carry h and none is token-less, so select returns None (scripted_reader.py:65-68): no steps, PASS (action.py:79-81). Pair = lower twin = 0.
- **BM25:** 0, range 0 to 0; 0/0/20. A BM25 score is >0 only on a shared term (api/adapters/bm25.py:32-38; anchors/bm25.py:17-18), so no evidence chunk ranks. B0 keep → 0; B1 PASS; pair 0.
- **Grep:** 0, range 0 to 0; 0/0/20. Grep keeps only events that match a prompt term (anchors/grep.py:11-18). Every term's events are tool reads, quote/filler/cancellation events or sprint chunks, never the event that holds h. So the outcome is the same as naive retrieval's, on every life and with any sprint placement.
- **Recent window:** +5·N2 points. N2 = number of screening lives whose first long sprint is in session 2. Pairs: right N2, wrong 0, no credit 20−N2.
  Public lives: 0 (first sprints 3,4,4,4,5, from build_schedule).
  Before the screening seeds are committed: expected 24, range 10-35 (P≈0.88 for 2≤N2≤7). It becomes exact once the seeds are committed, because build_schedule is pure.
  Mechanism: the probe is at checkpoint 5. A first sprint in 3-5 puts ≥20,480 tokens (sprint_floor, tokens.py:16-18) between the evidence and the probe, so 0. A first sprint in session 2 leaves only the turn-3..5 chunks after the (2,3) event (11,487-12,191 tokens over 400 schedules) plus sessions 3-5, all under 16,384. The window then holds h in B0, and update gives PASS.

**Risk to the oracle-evidence row (B5).**

LOW. B0: the gold spans show one subject with an explicit retract+assert ('Correction, confirmed: ... no longer p. For retry interval, the value is definitely h.', en.toml:37,49). The prompt maps that to 'write what it was corrected to' under the chat name, so set retry interval=h.
B1 (hedge twin): the span is a SOFT hedge (twin.py:187-196), which the prompt calls 'only raised as a possibility: change nothing'. That is the same rule that gave 0 hedged-twin changes over 15 oracle trials in round 1 (validity-1 RESULT, counters).
No new route to a harmful extra change: there is no evidence for any other entry; 'Never add entries' forbids additions; a re-write of p is a no-op because the G1 trace compares end state (hermes_score.py:53-55).
Residual risks: the reader may write a normalised name (retry_interval); 'keeping entry names exactly as written in chat' targets this. The reader may hesitate in B0 without a named entry. The D7 smoke checks both.

**No-memory battery (B6b).**

Options, tables and twin type are v2's. B0 (update[h], keep[]); B1 (keep[h], update[h]); gold first (compile.py:75-79). _plan is at battery.py:72-77.
- do_nothing, always_abstain, always_never_observed, always_forgotten, channel_distrust, resist_always: no steps. B0 OMISSION 0, B1 PASS → pair 0.
- always_ask: OMISSION 0 on both (action.py:77-78) → 0.
- generic_default: B0's first option, update. B0 PASS, B1 changed:update → FAIL_MEMORY → pair −100.
- generic_default_reverse: B1's first option, keep (no steps) → 0.
- fire_on_every_cue and comply_always: the union is {update} → −100.
All ≤ 0; identical to v2's rows.

**Validity (B6).**

WHAT IT MEASURES: whether the system recalls, at session 5 and across three cold restarts, which settings entry got a firm correction, and tells it apart from a hedge on the twin. That is 'sync the config with what we decided', for an implied subject.
(a) AMBIGUITY A REAL SYSTEM FACES THAT THE ORACLE DOES NOT. The base world mirrors the decoys on sibling entries: batch_size has a committed correction then a hedge; flush_timeout_ms a committed original then a quote; lock timeout an uncommitted original plus a quote (world.py:181,240-266; commits land at each assert instant, codebase_model.py:41). Under the prompt's rule the only state change is retry interval→h in B0, and none in B1. Re-writing batch_size's committed value changes nothing, because the state is diffed. So the probe has one right answer for a full-memory system.
Residual: other firm corrections visible at 5 belong to non-settings (both deadline chains at session 2, the relaxed rule, the key-rotation cancellation). Deadlines, rules and decisions are excluded by name; tasks are not. A system that files one of these into settings.toml fails B1 only (refrain gold: any change → FAIL_TASK, action.py:79-91). Values carry DUE/RULE/TASK vs SETTING/CONST codes, so this is resolvable from memory. Flagged.
File view: the live reader appears to work in a real checkout (round 1's O3 edited docs/decisions.md directly). Verify.
(b) Battery: all ≤ 0, see battery.
(c) Sprint placement: the first sprint is uniform over {2,3,4,5} (schedule.py:83-87; scale.py:63-64 minus kill 6 and swap 8). Session 2 came up in 2,441 of 10,000 draws (24.4%), 0/5 public lives and 0/5 round-1 lives. Expected 4.9 of 20 screening lives; P(N2≥8)=0.09, which would fail the 35 gate. In round 2's 10 lives, P(N2≥4)=0.21, which would push the live window to ≥40. In those lives the window is right: that is a real 'recent enough' success, not an artifact. Card v3b removes it.

*Designer's confidence, a belief and not a bar:* 70.

**The judge's reasons.**

- B3 Token audit: Paraphrase 1's token 'reflects' ('so it reflects all firm corrections') appears in no class: it is in neither the ABSENT nor the OUTSIDE list, so not every \w+ token is classed.
- Fix named by the judge: Add 'reflects' to the token audit: it is absent from every G1 event under the same static scan (sources as for the other absent tokens).

<a id="drift-quote-k1"></a>

## `drift-quote` K1: drift-quote v3: 'the missing timeout entry', quote rule restated, the name taken from the conversation

- **Designer's angle:** retrieval-adversarial (beat the anchors).
- **Levers (PLAN §4):** 1, 4.
- **Judge:** publish; every bar passed.

**Prompt.**

> Add the missing timeout entry to the settings file config/settings.toml, under its name exactly as written in our conversation. Use the figure set directly, not one only reported or quoted later.

**Paraphrases.**

1. In the settings file config/settings.toml, add the timeout entry still missing, named exactly as in our conversation. Take the figure set directly; figures only reported or quoted later do not replace the directly set figure.
2. Work out which timeout entry the settings file config/settings.toml still lacks, and add the entry under its exact name in our conversation, using the figure set directly rather than any figure reported or quoted later.
3. Complete the settings file config/settings.toml by adding its missing timeout entry, named exactly as in our conversation; use the directly set figure, and ignore any figure only reported or quoted later.

**Mechanism.**

Lever 1, partial: 'lock' is rare and occurs only in d and q, so it is dropped. 'timeout' is kept: it appears in about 95% of log chunks ('batch flush timeout', session_cut.py:20). 'setting' is dropped: it is fatal, because every SETTING-dddddd token yields that word (processes/__init__.py:37-60). Lever 4: the quote rule is restated without 'was', 'it', 'that', 'said', 'a', 'quote', 'for' or 'value'. Every text has 'file' (in about 95% of chunks), and one paraphrase also has 'out' (in every chunk), as fillers. A 'right' answer needs d's session-1 event (1,4), and no prompt word rarer than the chunk count occurs in it. The path words keep the TF-IDF and BM25 top 5 on tool reads. Placement is unchanged: d at (1,4) and q at (2,4) (targeted.py:384), probe at checkpoint 5.

**Round 1's repair (B2).**

File: kept. Quote rule: kept and restated: 'use the figure set directly, not one only reported or quoted later'. Entry name: DEPARTURE (owner to rule). 'lock timeout' becomes 'the missing timeout entry ... under its name exactly as written in our conversation'. Why a reader handed only the evidence still gets it: both gold events put 'lock timeout' in the subject slot (en.toml:37 and 94; targeted.py:380), and it is the only entity in the evidence. The words 'exactly as written' guard against snake_case. Among the timeout entries, flush_timeout_ms is already in the file (world.py:63, committed at world.py:260-266), so 'missing' leaves only lock timeout, which the template requires to be absent from the file (drift_action.py:74).

**Token audit (B3).**

Same scan sources as the config card. Evidence events: d from en.toml:37 (either phrase), q from en.toml:94 (either phrase), subject 'lock timeout', predicate 'value', SETTING-dddddd.
ABSENT: add, adding, any, as, by, complete, conversation, directly, do, entry, exact, exactly, figure, figures, ignore, its, lacks (only the unused observed cells have it), later, missing, named, one, only, or, our, quoted, rather, replace, reported, still, take, than, to, under, use, using, which, work, written.
OUTSIDE EVIDENCE ONLY: config, settings, toml, in, name, set, and (sources as in the config card); not (en.toml:38 phrase 1, :49 phrase 1, i.e. negate and retract events, never in d or q); file (sprint, about 0.95n); out (sprint footer, exactly n, paraphrase 2 only).
IN EVIDENCE: 'the' (en.toml:37 phrase 0, :94 both phrases) and 'timeout' (subject). The same two in the prompt and all three paraphrases.
Grep argument: count(timeout) ≈ 0.954n + 2. 'flush_timeout_ms' is a single \w+ token, so it does not count. count(file) ≈ 0.954n and is visited first on ties (alphabetical). count(out) = n.
Whichever term is visited first, its newest-first events are sprint chunks. At checkpoint 5 with the sprint in sessions 3-5, they fill W, and 'the' is never reached.
In a life whose sprint is in session 2, if 'timeout' happens to come before both fillers (about 7% of those lives, rarer when 'out' is present), newest-first it reaches q at (2,4) after about 7.7k chunk tokens. It stops before d at (1,4), which needs all of session 2's chunks (≥20.5k). So q only, which picks other-1: wrong, never right.
No text holds a word of d's event that is rarer than n: for, lock, value, definitely, setting, must, be, now, on and s are all banned. Also banned because they hit q: it, was, that, said, quote, a, note.

**Changes.**

New file src/bicentennial/items/templates/g1/drift_quote_v3.py: DriftQuoteV3(DriftQuote), BINDING_FIELDS=("chain_id",), prompt replaced only, table drift-quote-v3 (holds:current; changed:other gives FAIL_MEMORY). It uses a separate file so the config and quote iterations never move each other's C-7 source hashes.
Also as for v3a: __init__.py TEMPLATES_V3 and roles; EDITIONS[3] and C7_FILES[3]; c7.py:95 choices; specs/ring0/c7-edition3.json, whose drift-quote-v3 entry records the lever-1/4 departure in lever_mix 'others'; tests (refuse edition 4, edition-1/2 hashes unchanged, prompt-lint).
No targeted.py change. Editions 1 and 2 stay byte-identical.

**Predicted pair scores (points out of 100; a pair scores its lower twin).**

- **Naive retrieval:** 0 (range -5 to 0). Right needs both the d chunk and the q chunk in the top 5. Each shares only 'the' and 'timeout' (hand estimate cosine 0.2-0.4) against at least 8 tool or negation chunks above 5. If q alone made the top 5, the pair would be wrong (-5 per pair); this is not predicted.
- **BM25:** 0 (range -5 to 0). d and q score about 4.2 ('the' about 1.9, 'timeout' about 1.6). The fifth chunk scores at least 7: '# Service settings' x2 about 7.0; app.py, test_config and test_app at least 9; README about 7; 'not' chunks about 5-7.
- **Grep:** -10 to 0 (expected about -2; 0 on the public lives). Right is impossible: see the token audit. Wrong only in lives whose first sprint is session 2 and where 'timeout' is visited before the fillers: then q is selected without d, the reader picks other-1, and the pair scores -1.
- **Recent window:** Exactly -100·n2/N (0 on the public lives; on 20 fresh lives the prior is -25, 90% range -40 to -10). In lives whose first sprint is session 2, q at (2,4) lies about 8-10k tokens from the end (turn 4-5 chunks 7.66-7.84k, computed, plus sessions 3-5) and is reached. d at (1,4) never is. So both twins pick other-1 and the pair scores -1. In all other lives nothing is reached: refrain, 0.

**Risk to the oracle-evidence row (B5).**

moderate. B0: the reader holds d ('For lock timeout, the value is definitely D', or '... must be D, from now on', en.toml:37) and q ('It was said that ... must be Q', or 'Quote from a note: ...', en.toml:94). 'Set directly, not ... quoted later' selects D. The name 'lock timeout' is copied 'exactly as written'. B1 (fork twin, D changed): the same reasoning on B1's own evidence. Extra changes: the act gold has no disqualifier on other entries, and the prompt invites none. Risks: the entry name now comes from the evidence (a snake_case 'lock_timeout' fails the check; 'exactly as written' mitigates), and 'figure' is used for a code. Round 1's v2, which carried the same rule, scored 15/15.

**No-memory battery (B6b).**

Options are unchanged from v1/v2 (current[d,q], other-1[q], refrain).
- do_nothing: 0
- always_abstain: 0
- always_never_observed: 0
- always_forgotten: 0
- always_ask: 0
- generic_default: 0 (B0 passes; on B1, d0 is neither d1 nor q, so FAIL_TASK 0)
- generic_default_reverse: 0
- fire_on_every_cue: 0 or -100 (the union is applied in canonical order, so the last value wins and at most one twin holds current)
- channel_distrust: 0
- comply_always: 0 or -100
- resist_always: 0
All ≤ 0.

**Validity (B6).**

Capability: recalling a value told once in session 1 against a later quoted competitor, three or more sessions and restarts later, when the only subject word ('timeout') sits in about 95% of the log chunks.
Ambiguity a real system faces and the oracle does not: the file holds another timeout entry (flush_timeout_ms, present and committed), and 'missing' settles it. Other decided-but-unwritten facts (decisions, milestones) belong to other files or kinds. A real system may still mistake log 'timeout' noise for the setting; that is a retrieval failure, not an artifact.
Battery: every POLICY ≤ 0.
Recent window: probe at checkpoint 5, d at (1,4), q at (2,4). The window can never reach d. In about 1 life in 4 (first sprint in session 2) it reaches q and is confidently wrong. Otherwise it scores 0. The window's points are therefore ≤ 0, whatever n2 is, and no placement change is needed.

*Designer's confidence, a belief and not a bar:* 65.

<a id="drift-quote-k3"></a>

## `drift-quote` K3: drift-quote v3: write every firmly decided settings entry at its latest direct figure, none named (lever 1, prompt only)

- **Designer's angle:** mechanism-validity (the separation must be a memory capability).
- **Levers (PLAN §4):** 1.
- **Judge:** publish; every bar passed.

**Prompt.**

> Write into config/settings.toml every settings entry decided firmly in chat (deadlines, rules and decisions stay out), named exactly as in chat, each at its latest figure stated directly, adding any entry this file lacks; any figure only reported or quoted later replaces nothing.

**Paraphrases.**

1. Put every settings entry firmly decided in chat into config/settings.toml (deadlines, rules and decisions stay out), under its name exactly as written in chat and at its latest directly stated figure, adding any entry missing there; later reports or quotes of another figure change nothing.
2. config/settings.toml should hold every settings entry decided firmly in chat, deadlines, rules and decisions aside. Write each one under its exact chat name at its latest figure given directly, adding whatever entry this file lacks; any figure merely reported or quoted afterwards replaces nothing.
3. Record in config/settings.toml all settings entries decided firmly in chat (never deadlines, rules or decisions), each named exactly as in chat and at its latest figure someone stated directly, including any entry still missing; figures only reported or quoted later replace nothing.

**Mechanism.**

Remove every word of the d event (1,4) and the q event (2,4), including 'setting' (from the SETTING- token) and the quote-cell words a/it/was/that. The prompt becomes 'write every settings entry decided in chat at its latest direct figure'. The scored entry is lock timeout, which is not in the file (drift_action.py:74). Writes to other entries are harmless: the gold is act, the table has no disqualifier besides changed:other, and no benign extras (__init__.py:51-52; action.py:82-84). The probe is at checkpoint 5 in every life. Options and tables are v2's.

**Round 1's repair (B2).**

KEPT: the file. KEPT, reworded: the decision rule. v2 said 'use the value that was set for it directly' (drift_action_v2.py:36-37); v3 says 'at its latest figure stated directly'. For lock timeout d is the only direct statement, so the two coincide. KEPT, reworded: the quote rule. v2 said 'a value that was only reported or quoted later does not replace it'; v3 says 'any figure only reported or quoted later replaces nothing'.
DEPARTURE, for the owner to rule on: the entry name 'lock timeout' is dropped. Replaced by: 'every settings entry decided firmly in chat ... named exactly as in chat ... adding any entry this file lacks'.
Why a reader handed only the evidence still knows the entry: both gold spans (d: assert.stated.hard; q: quote.stated.hard, en.toml:37,94) carry the single subject 'lock timeout' verbatim (phrasebank.py:128-130). So the reader writes lock timeout=d, not q, by the quote rule.

**Token audit (B3).**

METHOD: as in drift-config v3a. Quote evidence vocabulary, d and q with either phrase: a be definitely for from is it lock must note now on quote s said setting that the timeout value was, plus digits. 'setting' comes from SETTING-dddddd (targeted.py:383). a, it, was, that come only from the quote cells (en.toml:94). Note: v2's prompt contained a, for, it, lock, setting, that, the, timeout, value and was.
IN EVIDENCE: none, in the prompt or in any paraphrase.
OUTSIDE EVIDENCE ONLY:
- config: app.py, test_app.py; 'config format' decision
- settings: README.md, app.py, test_config.py, '# Service settings'
- toml: app.py
- decisions: README.md, test_app.py, '# Decisions'
- and: README.md, test_config.py
- in: test_app.py, test_config.py
- name: app.py 'def flag(name)'
- file: sprint 'spool file rotated', session_cut.py:21
- never: negate phrase en.toml:38 (cancellations)
- out: sprint 'What stands out?'
ABSENT: adding afterwards all another any as aside at change chat deadlines decided directly each entries entry every exact exactly figure figures firmly given hold including into its lacks later latest merely missing named nothing of one only or put quoted quotes record replace replaces reported reports rules should someone stated stay still there this under whatever write written.
Note: 'quotes' and 'quoted' are different \w+ tokens from 'quote'.
Grep: no evidence token, so no argument is needed. Confirm with event counts on built lives.

**Changes.**

NEW FILE items/templates/g1/drift_quote_v3.py (or a second class in drift_action_v3.py): class DriftQuoteV3(DriftQuote) with BINDING_FIELDS=("chain_id",). instances() calls super() and returns Instance(... prompt=<literal>, decision_table_ref="drift-quote-v3") with options, gold_spans and decisive fact unchanged; lever_mix records 'cue removed (lever 1)'.
EDIT __init__.py: a TEMPLATES_V3 entry _template(DriftQuoteV3, "drift-quote", "DRIFT-CUR", "verbatim retention", version=3, tables=(_table("drift-quote-v3", ("holds:current",), ("changed:other",)),)), and G1_MUTANT_ROLES over it.
EDIT editions.py: EDITIONS[3] and C7_FILES[3] (shared with the other cards). EDIT c7.py: --edition choices. Commit c7-edition3.json.
Tests as in drift-config v3a, plus a vocabulary test against the quote evidence.
Editions 1 and 2 byte-identical: no existing class file is edited (c7.py:46-50 hashes MRO files only), worlds do not depend on prompts, no pin is touched. Edition-3 C-7 entry 'drift-quote-v3' records the lever-1 departure.

**Predicted pair scores (points out of 100; a pair scores its lower twin).**

- **Naive retrieval:** 0, range 0 to 0. Pairs right/wrong/no credit: 0/0/20 (public 0/0/5). No shared term with the d or q events, so neither token is in context. The scripted reader picks refrain (token-less, scripted_reader.py:65-68): OMISSION 0 on both twins (action.py:89-90). Pair 0.
- **BM25:** 0, range 0 to 0; 0/0/20. No evidence chunk scores >0, so refrain on both twins.
- **Grep:** 0, range 0 to 0; 0/0/20. No grep term matches d or q. a/it/was/that are absent from the prompt, so even phrase-#0/#1 q events are never pulled. Refrain on both twins.
- **Recent window:** −5·N2 points: right 0, wrong N2, no credit 20−N2. Public lives: 0. Before the screening seeds: expected −24, range −35 to −10.
  Mechanism: in lives whose first sprint is in session 2, q (2,4) has only the turn-4..5 chunks (7,630-7,836 tokens) plus sessions 3-5 after it, so it is in view; d (1,4) is ≥20,480 tokens back. The scripted reader then picks other-1 [q], which is changed:other, FAIL_MEMORY. The fork twin changes only d, so this happens on both twins and the pair is −1. In other lives neither token is present: refrain, 0.

**Risk to the oracle-evidence row (B5).**

MODERATE. The quote rule is the history that matters. In Milestone 1, v1's oracle-equivalent row asserted the quoted value on 7 of 10 tasks; v2's explicit rule fixed it (10/10, validity-1 RESULT). v3 keeps the rule's content: 'latest figure stated directly; any figure only reported or quoted later replaces nothing'.
On both twins (the fork changes d) the reader sees one direct assertion (d, session 1) and one quoted line (q, session 2), so it writes lock timeout=d0 or d1.
New risks:
(1) Without a named entry, the reader must take the name from the evidence; 'named exactly as in chat' covers it. A snake_case normalisation (lock_timeout, by analogy with batch_size in the file) would fail.
(2) The reader may not add an entry it cannot see named.
No route to a harmful extra change: the reader has no evidence for other entries, and extras are not penalised on this act table. D7's smoke is the check.

**No-memory battery (B6b).**

Options and tables are v2's: B0 (current[d0,q], other-1[q], refrain), B1 (current[d1,q], other-1[q], refrain).
- do_nothing, always_abstain, always_never_observed, always_forgotten, channel_distrust, resist_always: no steps, OMISSION 0 on both → 0.
- always_ask: 0.
- generic_default: lock timeout=d0. B0 PASS; in B1 it holds neither d1 nor q, so FAIL_TASK 0 → 0.
- generic_default_reverse: d1. B0 FAIL_TASK 0, B1 PASS → 0.
- fire_on_every_cue, comply_always: the canon-sorted union writes d0, d1, q; the last write wins. If it is q: FAIL_MEMORY on both, −100. If d0 or d1: 0.
All ≤ 0; identical to v2's rows.

**Validity (B6).**

WHAT IT MEASURES: recalling, at session 5, a setting decided in session 1 that never landed in the file, under its own name, and not letting a later quoted figure overwrite it. A user wants this ('add the settings we agreed on'), and it is for an implied subject.
(a) Ambiguity a real system faces that the oracle does not. A real system will write several settings: batch_size and flush_timeout_ms at their committed values (no-ops); retry interval=h in B0 (the latest direct figure; not scored here); lock timeout=d. Only lock timeout is checked, and extra writes cannot cost credit on this act table. So the 'which entry' search the oracle never faces cannot make a full-memory system fail.
The remaining failure modes are memory failures: forgetting d across four sessions and cold restarts, or taking q. Type judgment (decisions are 'choice' with DECISION codes; lock timeout's value is a SETTING code) only matters if the system omits lock timeout.
The config and quote probes share checkpoint 5 but each starts from its own state0 (packs/build.py g1_cases state0=repo_state).
(b) Battery ≤ 0.
(c) Sprint placement: session-2 first sprints in 24.4% of draws. There the window is confidently wrong (q without d), which is a realistic recency failure and lowers the window's score. Never a gate risk: the best anchor stays 0.

*Designer's confidence, a belief and not a bar:* 60.

<a id="drift-chain-fault-k1"></a>

## `drift-chain-fault` K1: drift-chain-fault v3: 'the milestone after the beta', exact line form, name from the conversation

- **Designer's angle:** retrieval-adversarial (beat the anchors).
- **Levers (PLAN §4):** 1, 4.
- **Judge:** publish; every bar passed.

**Prompt.**

> Record the current target of the milestone after the beta in docs/decisions.md, as one line of the form "- <name>: <value>", where <name> is the milestone name exactly as written in our conversation.

**Paraphrases.**

1. In docs/decisions.md, write one line "- <name>: <value>" giving the latest agreed target of the milestone after the beta, with <name> exactly as our conversation names the milestone.
2. Add an entry to docs/decisions.md recording the current target of the milestone following the beta, as one line "- <name>: <value>" using the milestone name exactly as written in our conversation.
3. Put in docs/decisions.md the current target of the milestone after the beta: one line "- <name>: <value>", with <name> being the milestone name exactly as written in our conversation.

**Mechanism.**

Lever 1 (DEPARTURE: §4 lists lever 1 only for config and quote): 'general', 'release', 'deadline' and 'due' (the DUE-dddddd stems) are all rare evidence words, so all are removed. The subject is cued relationally by 'the beta', a word found only in deadline-0's events, which are not evidence. Lever 4: the target is 'the current target', with no 'for', 'that' or apostrophes. The existing placement already acts as lever 3: the probe is pinned at checkpoint 10 (targeted.py:101-102), and the evidence is at (1,2) and (2,2). The second sprint (7, 9 or 10) always lies between, and every chunk contains 'the' and 'is'. Depth stays 1, so t2.toml is not touched.

**Round 1's repair (B2).**

File and line form: kept ('- <name>: <value>' in docs/decisions.md). Last-link rule: kept as 'current target'. Entry name: DEPARTURE (owner to rule). v2's 'the entry name is exactly "general release"' becomes '<name> is the milestone name exactly as written in our conversation'. Why a reader handed only the evidence still gets it: both gold link events put 'general release' in the subject slot (en.toml:37 and 49; world.py:59), and it is the only milestone in the evidence. A milestone called 'general release' is, by its name, the one after a beta. The words 'exactly as written' carry v2's fix against 'general release deadline'.

**Token audit (B3).**

Evidence events: link 0 (en.toml:37) and link 1 (en.toml:49 retract plus :37 assert), subject 'general release', predicate 'deadline', DUE-dddddd.
ABSENT: add, after, agreed, an, as, being, conversation, current, entry, exactly, following, form, giving, latest, milestone (the kind is never rendered), names, of, one, our, put, record, recording, target, to, using, where, write, written. 'record' and 'as' are absent because G1 never renders observed or propose cells.
OUTSIDE EVIDENCE ONLY:
- beta: deadline-0 events (1,1) and (2,1) only (world.py:59, 244-246; t2.toml:33).
- docs and md: test_app.py:11.
- decisions: README.md:3; test_app.py:11-12; '# Decisions' header.
- line: test_app.py:13-14.
- in: test_app.py:13; test_config.py:10,12.
- name: app.py:18.
- value: the predicate of the constant and setting events; test_config.py:12-15; never in deadline-1 events.
- with: en.toml:53 phrase 1; README.md:3.
IN EVIDENCE: 'the' (en.toml:37 phrase 0, :49 phrase 0) in the prompt and all three paraphrases; 'is' (en.toml:37 phrase 0, :49 both) in the prompt only.
Grep argument: the probe is at checkpoint 10 and the kill at session 6. The second sprint falls in {7, 9, 10} (scale.py:67, 72-75) and is at least 20,480 tokens. Every chunk header holds 'the' and 'is' (session_cut.py:56), so both counts are far above n. Visited after all outside-only terms (about 1k tokens), their newest-first events fill W inside the second sprint, before session 6. The session-2 link events are never selected, whichever session holds the first sprint. Banned because they are rarer than n and in evidence: general, release, deadline, due, for, that, s (apostrophes), no, longer, correction, confirmed, scratch, sure, definitely, must, be, now, on, not, from (the 'from now on' variant), decision.

**Changes.**

New file src/bicentennial/items/templates/g1/drift_chain_v3.py: DriftChainV3(DriftChain), BINDING_FIELDS=("chain_id", "depth"). __post_init__ refuses fault≠True, as v2 does (drift_chain_v2.py:16-19). The prompt is replaced only; options and gold_spans are v1's. Table drift-chain-fault-v3 (holds:current; changed:other).
Also: __init__.py TEMPLATES_V3 and roles; EDITIONS[3] and C7_FILES[3]; c7.py:95 choices; the c7-edition3.json entry, whose lever_mix 'others' records lever 1 and 4 on a cell whose primary lever is chain_depth (value 1) — the C-7 lever-mix departure the plan flags; tests as for the other cards.
No targeted.py and no t2.toml change, since depth is unchanged. Editions 1 and 2 stay byte-identical.

**Predicted pair scores (points out of 100; a pair scores its lower twin).**

- **Naive retrieval:** 0 (range -5 to 0). Top 5: the test_app chunk ('docs', 'decisions', 'md', 'line', 'in', each with document frequency 1); '# Decisions' x2; the beta link chunks x2 ('beta' in 2 chunks); 'value' fact chunks. The general-release chunks share only 'the' and 'is': hand estimate cosine about 1.5 against at least 5. A wrong pair would need link 0 in the top 5 without link 1; this is not predicted.
- **BM25:** 0 (range -5 to 0). Link 1 scores about 5.4 ('the' and 'is' at count 2). At least 8 chunks score 7 or more: beta about 11, value chunks about 8.7, '# Decisions' about 7, test_app at least 20.
- **Grep:** 0, exactly, on every life and every text (see the grep argument): the link events are never selected, so refrain and 0.
- **Recent window:** 0, exactly, on every life. The probe is at checkpoint 10, and the second sprint (≥20,480 tokens in session 7, 9 or 10) always lies after the session-2 evidence, whether or not the first sprint is in session 2.

**Risk to the oracle-evidence row (B5).**

moderate. B0: the reader holds 'For general release, the deadline is definitely A' and 'Correction, confirmed: the deadline for general release is definitely no longer A ... must be B'. The last link is explicit, so the reader writes '- general release: B'. B1 (fork twin, B changed): the same on B1's own evidence. The fault crossing does not affect a reader handed the evidence. Risks: (i) the gold-only reader never sees 'beta' and must accept that 'general release' is the milestone after the beta. It is the only milestone it holds, but a cautious reader could abstain. (ii) The value is labelled 'target', not 'deadline'. (iii) The name comes from the evidence. Extra changes: 'one line' and an act gold with no disqualifier on other entries.

**No-memory battery (B6b).**

Options are unchanged (current[last], other-1[f0], refrain).
- do_nothing: 0
- always_abstain: 0
- always_never_observed: 0
- always_forgotten: 0
- always_ask: 0
- generic_default: 0 (on B1, B0's last value is neither current nor f0, so FAIL_TASK)
- generic_default_reverse: 0
- fire_on_every_cue: 0 or -100 (the union is applied in order and the last value wins; if f0 comes last, both twins give FAIL_MEMORY)
- channel_distrust: 0
- comply_always: 0 or -100
- resist_always: 0
All ≤ 0.

**Validity (B6).**

Capability: recalling the last link of a corrected chain across a kill (session 6), when the subject is named only by its relation to another milestone, and that other milestone is itself a corrected chain of the same kind: beta release, at (1,1) and (2,1).
Ambiguity a real system faces and the oracle does not: the beta's own corrected deadline is a same-kind distractor. That is a fair memory test, since 'after the beta' rules it out. docs/decisions.md holds other decisions, but they are not milestones.
Battery: every POLICY ≤ 0.
Recent window: the checkpoint is pinned at 10 and the second sprint always falls between the evidence and the probe. Lives whose first sprint is session 2 make no difference.

*Designer's confidence, a belief and not a bar:* 55.

<a id="drift-chain-fault-k3"></a>

## `drift-chain-fault` K3: drift-chain-fault v3: record every milestone's current target in docs/decisions.md, none named (lever 1, prompt only)

- **Designer's angle:** mechanism-validity (the separation must be a memory capability).
- **Levers (PLAN §4):** 1.
- **Judge:** publish; every bar passed.

**Prompt.**

> Record every milestone in docs/decisions.md as one line, "- <name>: <target>", where <name> matches how each milestone was named in chat, in lower case and with nothing added, and <target> gives its current target code after all corrections.

**Paraphrases.**

1. Write one line per milestone into docs/decisions.md in this form: "- <name>: <target>". Use each milestone name just as written in chat, lower case, nothing added; use its current target code once all corrections apply.
2. In docs/decisions.md, add a line "- <name>: <target>" per milestone: <name> copied exactly as chat named this milestone, lower case and alone; <target> its latest firm target code after corrections.
3. List each milestone in docs/decisions.md, one line apiece shaped "- <name>: <target>", taking <name> verbatim as named in chat (lower case, nothing extra) and <target> as its current target code once all corrections apply.

**Mechanism.**

Remove general, release, deadline and due (from DUE-dddddd) and every clause word, so no lexical anchor touches the deadline-1 links at (1,2) and (2,2). The prompt becomes a sweep over milestones: beta release and general release, both depth-1 chains corrected in session 2 (targeted.py:94,365-366). Only 'general release' is scored; a beta release line or other extra lines are harmless on this act table. The probe stays pinned at 10 (targeted.py:101) after the kill at 6, so the fault diagnostic is kept (drift_chain.py:44-47). Depth stays 1 (lever 2 would need deadline_at, i.e. spec, edits and adds nothing against the lexical anchors).

**Round 1's repair (B2).**

KEPT: the file (docs/decisions.md) and v2's line form "- <name>: <value>" (drift_chain_v2.py:26-27). KEPT and made explicit: the decision 'current after all corrections'. No quote rule applies.
DEPARTURE, for the owner to rule on: v2's literal entry name (the repair for v1's 0-of-10 oracle row) is dropped. Replaced by: '<name> matches how each milestone was named in chat, in lower case and with nothing added'.
Why a reader handed only the evidence still knows the entry: both gold spans render the subject 'general release' verbatim, once per clause (phrasebank.py:128-130; en.toml:37,49), so the exact entry string can be read off the evidence. The (2,2) span's retract clause marks the old value and its assert clause gives the last link, so the value is fixed too.

**Token audit (B3).**

METHOD: as in drift-config v3a. Chain evidence vocabulary, both links with either phrase: be confirmed correction deadline definitely due for from general is longer must no not now on release s scratch sure that the, plus digits ('due' from DUE-dddddd, world.py:59).
IN EVIDENCE: none, in the prompt or in any paraphrase. 'corrections' is a different \w+ token from 'correction'.
OUTSIDE EVIDENCE ONLY:
- docs, md, line: tests/test_app.py
- list: tests/test_config.py
- name: service/app.py
- decisions: README.md, test_app.py, '# Decisions'
- and: README.md, test_config.py
- in: test_app.py, test_config.py
- a: README.md; quote phrase #1, en.toml:94
- was: quote phrase #0, en.toml:94
- with: README.md; hedge phrase #1, en.toml:53
ABSENT: add added after all alone apiece apply as case chat code copied corrections current each every exactly extra firm form gives how into its just latest lower matches milestone named nothing once one per record shaped taking target this use verbatim where write written.
The session-6 git log has no milestone names: milestones are never committed, because PATHS has no milestone kind (codebase_model.py:13).
Grep: no evidence token, so no argument is needed.

**Changes.**

NEW FILE items/templates/g1/drift_chain_v3.py: class DriftChainV3(DriftChain) with BINDING_FIELDS=("chain_id","depth") and __post_init__ requiring fault=True, as in v2. instances() calls super() and returns Instance(... prompt=<literal f-string with no subject>, decision_table_ref="drift-chain-fault-v3"); lever_mix records 'cue removed (lever 1), primary lever chain_depth unchanged at 1'.
EDIT __init__.py: TEMPLATES_V3 entry _template(DriftChainV3, "drift-chain-fault", "DRIFT-CUR", "verbatim retention", chain_id="deadline-1", fault=True, version=3, tables=(_table("drift-chain-fault-v3", ("holds:current",), ("changed:other",)),)), and G1_MUTANT_ROLES over it.
EDIT editions.py, c7.py, and commit c7-edition3.json, as for the other cards.
Tests: test_editions updates, a vocabulary test, v3 keeps v2's options, tables and bindings.
Editions 1 and 2 byte-identical: no existing class file is edited, worlds do not depend on prompts, the pinned checkpoint and deadline_at are unchanged. Edition-3 C-7 entry 'drift-chain-fault-v3' records a lever other than the primary one (a departure from the lever-mix shape).

**Predicted pair scores (points out of 100; a pair scores its lower twin).**

- **Naive retrieval:** 0, range 0 to 0. Pairs right/wrong/no credit: 0/0/20 (public 0/0/5). No shared term with the link events, so neither the last nor the stale DUE token is in context. Refrain on both twins (scripted_reader.py:65-68): OMISSION 0. Pair 0.
- **BM25:** 0, range 0 to 0; 0/0/20. No link-event chunk scores >0, so refrain.
- **Grep:** 0, range 0 to 0; 0/0/20. No term matches a link event, so refrain on both twins.
- **Recent window:** 0, range 0 to 0; 0/0/20, on every life. The probe is pinned at 10. The second long sprint lies in 7, 9 or 10 (scale.py:63-64 minus swap 8) and is ≥20,480 tokens, so it always sits between the session-1/2 links and the probe. The window never sees a DUE token: refrain, 0.

**Risk to the oracle-evidence row (B5).**

MODERATE. The last link: the (2,2) span renders the retract clause first (template.py:85-86) and then 'For general release, the deadline is definitely <last>', so a reader takes the asserted value. That holds on both twins (the fork changes the last value).
The risk is the entry string. v1's oracle row scored no chain-fault task, and v2 fixed that by spelling the name out. v3 gives a naming rule (exactly as named in chat, lower case, nothing added) that the evidence satisfies, but a reader may still write 'general release deadline'.
Format risk: a malformed line is scored as the reader's under #524/#537. 'One line' limits it.
No harmful extra: the reader has no evidence for beta release, and extra lines are not penalised. D7's smoke decides.

**No-memory battery (B6b).**

Options and tables are v2's: B0 (current[f1], other-1[f0], refrain); B1 (current[f1'], other-1[f0], refrain), fork on the last link.
- do_nothing, always_abstain, always_never_observed, always_forgotten, channel_distrust, resist_always: 0.
- always_ask: 0.
- generic_default: f1. B0 PASS; in B1 it is neither current nor other, so FAIL_TASK → 0.
- generic_default_reverse: f1'. B0 FAIL_TASK → 0.
- fire_on_every_cue, comply_always: the last of f0, f1, f1' in canon order wins. If f0: changed:other on both, −100. Otherwise 0.
All ≤ 0; identical to v2's rows.

**Validity (B6).**

WHAT IT MEASURES: carrying the current value of each tracked item through a correction, over eight sessions and across a process kill, with the item implied by its kind (milestones). A real system must enumerate beta release and general release from memory and drop stale targets.
(a) Ambiguity a real system faces that the oracle does not: which things are 'milestones'. beta release and general release are the only DUE-coded entities. A system that also lists commitments (release checklist, key rotation) or writes beta release loses nothing: the act table checks only the general release entry, and extras are not penalised. Writing every milestone is the honest reading of the prompt, so the extra lines are expected, not errors.
(b) Battery ≤ 0.
(c) Placement: checkpoint 10 is pinned. The window misses the evidence in 100% of lives, because the second sprint (7/9/10) always intervenes; session-2 first sprints (24.4% of draws) are irrelevant here.
The separation measured is against lexical retrieval only. Dense retrieval on 'milestone target' is untested (PLAN §9).

*Designer's confidence, a belief and not a bar:* 55.
