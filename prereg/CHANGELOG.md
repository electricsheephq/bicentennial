# Pre-registration changelog

Every change to the pre-registration after a freeze makes a new version, recorded here. Every result discloses the version it used.

## Ring 0 erratum, 2026-11-14: score two system-caused harness failures once (#526)
- **System failures:** a live G1 reader that creates the previously absent `act-state` entry is scored once as `SYSTEM_FAILURE` with cause `act_state_collision`, and a system plug-in worker's malformed or wrongly shaped reply after ready is scored once with cause `worker_protocol`; control and floor workers are unchanged.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 erratum, 2026-11-14: score the repository files that parse when one is unreadable (#537)
- **T2 and T2-lite, live G1 actions:** amending #524 below, after a live probe the runner reads each of the four repository files separately through the pinned parser. The action state contains the files that parse; only an unreadable file's predicates read False. Disqualifiers, admissible states and benign extras on readable files count as usual (PREREG-v0.5 §3). A stale write on a readable file can therefore score FAIL_MEMORY, −1, even when another file is unreadable; if all files are unreadable, the changed state still matches neither and scores FAIL_TASK, 0.
- **Accounting and evidence:** the item keeps its `unreadable_state` label and the same per-arm disclosure count and coverage accounting. Diagnostics write the partial state as `act.json` and keep the workspace. Any harness-made file error stays infrastructure, as do workspace roots replaced by files or symbolic links (#526).
- **Known limit:** a file that does not parse reads as having no entries. So a stale value written into a file that itself fails to parse scores FAIL_TASK, 0, not −1; one empty line in `docs/decisions.md` is enough to make that file unreadable. Likewise, a right write with an unrelated file left unreadable scores PASS, as unnamed collateral edits do on the readable path.
- **Pins and results:** no code pin moves, and no published card or score changes. The #524 entry and its Known limit remain as history.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 contract change, 2026-11-14: control-only T2 composition (#539, §15)
- **RING0 §15:** for validity round 2 (`results/validity-2/PLAN.md` D6), a control run (`--control`) also accepts a T2 pack of ten G1 lives. A system run still requires five G1 and five G2 lives.
- **Scope and pins:** control rows enter no Ring 0 gate, bar or calibration target. No code pin moves.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 erratum, 2026-11-13: a repository the reader leaves unreadable is scored, not rerun (#524)
- **T2 and T2-lite, live G1 actions:** after a live probe, when the reader's own edits leave a repository file unreadable (malformed content, bad UTF-8 or TOML, deep nesting, a deleted file, a file replaced by a directory, or a path through a file), the item is scored as a changed state that matches neither the admissible nor the disqualifying predicates (FAIL_TASK, 0). It carries the label `unreadable_state`, and `disclosures.json` counts such items per arm. Before this change such a unit was classed as infrastructure, run again and, if it failed again, BLOCKED. Other operating-system errors (permissions, descriptors, I/O) stay infrastructure, as does a workspace root the reader replaces with a file or a symbolic link (#526).
- **Accounting:** these items now count as scored, toward coverage, and no longer toward the infrastructure exclusion (PREREG §7, DESIGN §12a). Known limit: while one file is unreadable every predicate reads False, so a disqualifier on another file that still parses is masked, and a stale write there scores 0, not −1. #537 scores the files that parse, before the next scored live run.
- **Pins and results:** no code pin moves, and no published card or score changes. Round 1's results page discloses the one unit that ran a second attempt under the old rule (`results/validity-1/2026-11-13-control-trials/RESULT.md`).
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 erratum, 2026-11-13: a system run's floor runs first, under its own send budget (#507, §14.8)
- **RING0 §14.8:** in a T2 system run, the identity check and the live no-memory floor's uncached units now run before any of the system's units. Each phase has its own `--max-sends`, so a system run makes at most twice that many live sends. The system arm's units therefore no longer share slots or the live service with the floor's units, and "a run's arms interleave" no longer holds between the floor and the system arm. An arm's time is computed as before: its own units are replayed with their measured times, plus the run's time outside every unit. The floor's units are unit time, so they count in no arm's time; the identity check before them, and any gap between the phases, is outside every unit and counts in every arm's time, as before. The arm's units are now measured without the floor running beside them. An arm time measured before this change with a live floor beside it, such as the 4 November T2 arm (`results/v0.3-dev-tools/2026-11-04-t2-live-arm/`), was measured with the floor's units sharing the slots and the live service, so it is not directly comparable. Control runs (`--control`) stay one phase.
- **Pins and results:** no code pin moves, and no card, score or published result changes. A complete system run discloses `max_sends` and `phase_sends`, and a credential, spend or live stop keeps `attempts.json` unless its builder fails (a credential scan that finds login material takes precedence and leaves only the refusal).
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 contract change, 2026-11-11: live control arms at T2 (#496, §15)
- **RING0 §15:** for Milestone 1's step 2 (`results/milestone-1/DECLARATION.md`), `bicentennial t2` gains a probe-only live control arm, `--control no_memory|naive_rag|oracle_evidence`, run alone over the whole pack and left out of `--help`. Each probe item gets the pinned control's text at the item's sealed probe time in one framed block at the top of the probe turn's user message; the live reader answers with memory off and no search tool, and everything else equals the no-memory floor. A control arm never reads or writes the floor cache, and its run directory adds `control.json` (the arm, the frame's hash, the control key hash per life and each item's text hash). Its card names the arm in an optional `control` field; a system card is unchanged.
- **Scope:** these rows are developer-tier diagnostics, labelled live control rows; they are never cached as or pooled with the scripted controls and enter no Ring 0 gate, bar or calibration target. The documented T2 command and the cached scripted columns are unchanged. No frozen scoring rule, pinned control code or calibration target changes, and no code pin moves.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 erratum, 2026-11-05: the reproduction checks' budgets and tries (#393, §14.8)
- **RING0 §14.8:** the snapshot-probe reproduction budget (k = 3 in ≤ 5 min) and the live-class budget (k = 3 within 3 × T2's per-life budget, 18 min) are RING0's own, set before any measurement; PREREG-v0.5 §6 sets no reproduction budget, and §14.8 had attributed them to it. A reproduction's time is the whole `bicentennial repro` command on the monotonic clock, from after its argument refusals, its checks of the pins, the pack and the bundle included, with its stage split published.
- **Counting:** an item's try is its first started batch, on its bundle from A (the first-started run of the completed pair), and it counts only at k = 3 with `identical` starting conditions; a try that does not count or does not complete ends the search and the bar is not met; a refusal before the started record uses no try, and the command refuses that way a start whose relocation it can already see, unless asked to run relocated; inside a completed try, a run that is INFRA or BLOCKED, or that stopped before the point where its bundle's copy was taken, counts as not reproduced; a run that got past that point is judged by its failure class, a system failure included; an item whose probe its life in A never reached is skipped and uses none of the five tries; the live-class check is one replay with the candidate, whose probe is run 1, plus 2 restored probes whose starting conditions must be `identical` to that replay's own record, all 3 passing.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 contract change, 2026-11-05: the login-home operator check reads an entry's own flag (#475)
- **Operator firewall:** T2 and T2-lite refuse an outside entry whose own `benchmark_operator_runs` is false under an operator-marked login home, with `operator_identity`, as they already refuse a built-in whose flag is false. The login-home and policy checks share one exclusion predicate; existing refusal codes and their order stay unchanged. No code pin moves.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 erratum, 2026-11-05: the baseline's entry, versions and receipt (#390, §14.2, §14.4, §14.8)
- **RING0 §14.2:** the off-roster flag is the entry's recipe table. A registered system is one selected by the name of a file in `systems/registry/`; such a file may not carry a recipe, and an outside entry may not take a registered name. The no-memory file there is T2's floor control. v1 and every candidate differ only in `artifact.version`, `artifact.sha256`, a public 40-character `recipe.archive_tree.ref` and `fresh_install_hash`. The top-5 receipt queries each T1 item with its `recall_query`. Its first part decides: in event-id and in stream order, v1 scores exactly the chunks the control scores, each with the control's score, and its search tool returns that scoring's top 5 up to the order of equal scores; any other difference is a defect. Its second part discloses the effect of what v1 stores and gates nothing.
- **RING0 §14.4 and §14.8:** a v1 result is a v1 score from a run whose probe answers come from a live model. #390's T0 and T1 runs of v1 and the receipt (none had been made when the erratum was written) come before the declaration and are published with it, and their entry may differ from the declared one only in `fresh_install_hash`. A defect they expose may be fixed before the declaration, in v1 or in the benchmark, by a general change that restores the specified behaviour (a benchmark fix applies to every system and is recorded here); beyond such fixes, their scores and the receipt's per-item results never choose or change the T2 pack, the scoring and selection, or §14's rules. §14.8's first measured T2 arm is #479's `hermes-native` arm. No code pin moves.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 contract change, 2026-11-05: outside entries with write tools (#390)
- **Developer loop, RING0 §14.2:** an outside entry's scripted writes use its recipe's write mapping. All tiers and `pins` check declared tool coverage with the existing mapping refusal codes; scripted structured formats remain unsupported. No code pin moves.
- **Recorded values:** `write_turn_package_hash` changes once for every system because `director/scripted.py` changed. Values derived from it (the lock hash, run and attempt ids, and ledger digests) change with it. No other recorded value of a built-in system changes. The developer report refuses a pair of T2 runs made before and after this change because their `pins.write_turn_package_hash` differs.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 contract change, 2026-11-04: outside registry entries (#390)
- **Developer loop, RING0 §14.2:** all tiers and pin measurement accept an outside entry through `--entry`. Its recipe supplies the plug-in configuration without code-table rows, and its complete admitted declaration contributes to the system hash. Built-in declarations, routes and recorded values retain their rules.
- **Admission:** outside names cannot shadow built-ins; recipe values use the existing plug-in and worker rules plus bounded archive arguments. Operator exclusions follow normalized entry, artifact and recipe identities and measured forbidden artifact digests. Outside write tools and scripted structured formats are refused pending responder recipe routing. No code pin moves.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 erratum, 2026-11-04: the clock that times an arm (#460, §14.8)
- **RING0 §14.8:** unit intervals and the run's elapsed time use monotonic offsets from the run's start, so a wall-clock step changes no arm time. `units.json` publishes the offsets and `units_json_inputs` supplies the recomputation inputs; receipts keep their wall-clock stamps, and time the machine spends suspended counts toward no arm time. A backward wall-clock step larger than the run's elapsed time still fails the receipt's existing check, and the run publishes nothing. No code pin moves.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 change, 2026-11-04: the default turn wait is 1.0 s (#388, §13 E35)
- **RING0 §13 E35 (E30):** T1 and T2-lite default to 1.0 s of quiet time after an ordinary scripted turn, where it was 3.0 s. 0.5 to 3.0 stays the accepted range, and session ends, kill or restart turns and compaction turns keep 3.0 s. The one-commit A/B found byte-equal cards and no late background work on all three reference systems; a store check of every Hermes session, with run-specific values masked, found equal stores apart from 18 items that also differ at the same wait; and each T1 run took 18-23% less time.
- **Pins and results:** no code pin moves, and no card, score or hashed output changes. Receipts, JUnit properties and T2-lite disclosures record `1.0` at the default; T0's receipts keep `3.0`. A T2-lite baseline must match the current run's benchmark commit, so a T2-lite run made before this change is rerun at the current commit rather than compared directly, and `--turn-wait 3` reproduces its old waits; T1's baseline gate checks the pack and seed, not the wait.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 erratum, 2026-11-04: the developer report's per-life table and T2 operating metrics (#392, §14.10)
- **RING0 §14.10:** the verdict-free report adds each life's paired difference, each version's lift over its own no-memory floor, and counts of lives opposing the pooled and per-cell signs. T2 operating deltas use the system arm's receipt, with wall time from its §14.8 arm time, independent of floor-cache state. The file-based command refuses incomparable or unfinished runs and derives its reproducible seed from the input card bytes. No code pin moves.
No PREREG version change; PREREG-v0.5 remains frozen.

## Kit, 2026-11-04: the T2 command (#391)
- **Developer loop:** `bicentennial t2` runs the public T2 pack through the shared unit core, publishing a per-item card, retained pre-probe copies for eligible failures, per-arm receipts and recomputable RING0 §14.8 arm time with effective slots. See the replay-order erratum below for the replay rule. Each unit reports `pre_probe_ms` and `keep_ms`, including the keep-lock wait.
- **Floor and publication:** per-life/branch no-memory entries exclude system and slot count from their keys and require a matching live served identity. Credential scanning precedes cache publication. The T2 guide documents outputs, refusals and the unmeasured live budget; T1 and T2-lite retain their bytes. No code pin moves.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 erratum, 2026-11-04: the replay order (#391, §14.8)
- **RING0 §14.8:** the replay order fixes the dependence on floor-cache state announced by the preceding spec erratum. Each arm's units, and the floor's own replay, use admission order: largest predicted time first (43 s per replay session and 49 s per probe session), ties in card order. A fresh floor cannot change that order; shared slots, the live service and the machine can still change measured unit times.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 erratum, 2026-11-04: when a run ends (#391, §14.8)
- **RING0 §14.8:** one run end is stamped after the credential scan of the outputs, including kept copies, and used by `units.json` and all three receipts. Only writing and scanning those four files, publishing floor-cache entries and the final receipt and card renames follow. Recomputed arm time includes the full output scan.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 erratum, 2026-11-04: an arm's time leaves out the floor (#391, §14.8)
- **RING0 §14.8:** a dated erratum states what an arm's time counts. The no-memory floor is a control, and PREREG §6 sets T2's budget for "the candidate arm against cached controls", so the floor's units count in no arm's time, whether they ran in the run or came from the cache; the floor's own replayed time is reported beside the arms. A fresh floor can still change the order in which an arm's units started, and so its replay; the T2 command fixes a replay order that the floor cannot change before any arm's time is published (#391). A unit's time includes the harness work inside it (probe clones, the copy before each probe, scoring, and keeping failed items' copies, with any wait to keep), and "setup and scoring" means the run's time when no unit is running: before its first unit, after its last, and in any gap between units. `runner/arm_time.py` now replays only an arm's own units. Nothing publishes an arm's time yet: the T2 command will write it to `units.json`.
- **Pins and results:** no code pin moves, and no card, score or published result changes.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 erratum, 2026-11-03: the T2 placement window (#391, §13 E34, §15)
- **RING0 §13 E34, §15:** T2's life spec states `evidence_by = 8`, the last checkpoint minus the life spec's 2-session minimum distance, and a `replacements` list (empty: a failing design seed is replaced by the next unused integer from 14, and the freeze stops if a second design seed fails or if one row fails 8 replacement seeds in a row). For T2 only, the generator writes dedicated facts inside sessions 1–8 (G1 `decision-t2-0`, `decision-t2-1`; G2 `trip-t2`, `gate-t2`). `recall-value`, `wake-loop`, `recall-count` and `keep-incidental` point at them in the generator and the pack builder alike, and the original facts stay as unasked noise. A question that cannot be placed at any checkpoint raises `PlacementError("checkpoint")`, naming its template. No code pin moves, and T0 and T1 packs do not change.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 contract change, 2026-11-03: INV-FORGET exempts unchanged installed files (#435)
- **RING0 §13 E33 (§7, E26, E32):** both T0 store-snapshot scans exempt an opaque non-database file only when it is a regular file whose size and SHA-256 equal the host's install listing for the same relative path, recorded in memory after install and config and before any session (the listing the host's checkpoint already uses), without following symlinks. Raw hits still fail. Exemptions count as `unchanged` / `absent` in `invariants.forget_scan`; other keys stay. Text, SQLite databases and side files, scans without an install listing and API-mode checkpoints retain their rules. Relative to the preceding scanner, INCONCLUSIVE `opaque_store` can become PASS only when every opaque file matches its install listing and no other doubt or failure remains, or INCONCLUSIVE `sqlite_unreadable` or `sqlite_freelist` when that doubt remains. No other verdict changes. Only the scorer pin moves; earlier packs are rebuilt. v0.1's frozen kit keeps its rule.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 contract change, 2026-11-03: INV-FORGET reads compressed values and linked split SQLite tokens (#425, #417)
- **RING0 §13 E32 (§7, E26), #425:** SQL BLOBs are also searched in the output one level of zlib, gzip, bz2 or xz decoding returns before the decoder stops (output a decoder discards when it raises, as for a bz2 or xz value with a bad check, is not), in UTF-8 and both UTF-16 encodings, capped at 64 MiB per value. A header that yields nothing stays ordinary bytes. Recognized databases named like side files get their own SQL scans and non-database side files. Relative to #417, absent or INCONCLUSIVE can become FAIL `store_hit` for a token in a decoded value or a database named like a side file. Absent can become INCONCLUSIVE `opaque_store` for a zstd or LZ4 value or output reaching the cap, or `sqlite_freelist` or `sqlite_unreadable` for a database named like a side file, now scanned on its own; an INCONCLUSIVE result's reason can change. Other verdicts stay unchanged. `invariants.forget_scan` retains its keys, adds the scanner's `sqlite3.sqlite_version` as `sqlite_version` even without a SQLite scan, and gives every whole-checkpoint hit a count (`raw` / `found` in a canonical checkpoint).
- **#417:** before recovery, private-copy scanning follows SQLite page-number links across every stored main-file, WAL and rollback-journal page version, including superseded, stale and uncommitted frames and persisted journals. It checks local and overflow junctions in UTF-8 and both UTF-16 encodings, following chains until the whole needle ends. A coincidental join from unrelated reuse of the linked page counts as a hit. This changes absent or INCONCLUSIVE to FAIL `store_hit` for stores holding a linked split token, since any hit outranks a doubt. A store whose page images cannot be collected is INCONCLUSIVE `sqlite_unreadable` unless a hit gives FAIL.
- **Combined rebuild:** the scorer pin (`scorer_sha256`, over `score/*.py`) moves, so earlier packs are rebuilt once after both changes land. The other three code pins stay unchanged. v0.1's frozen kit keeps its rule.

## Ring 0 contract change, 2026-11-03: reproduction bundles v0.2 (§13 E31, #393)
- **Bundle contract:** `snapshot-probe` and `live` share the T2 item identity and failed outcome; snapshots identify the kept copy and D6 startup inputs, and live bundles identify the system artifact. Existing v0.1 `replay-from-schedule` bundles and writer bytes stay unchanged. Replay-context members live only in the schema, outside every code pin, so they can grow without moving a pin. Exactness means identical starting conditions, not identical answers, and awaits the restored-probe test.
- **Pins:** the controls pin moves because `contracts/repro_bundle.py` settles the class/version, kept-pointer and failure checks. Packs built before this change refuse and must be rebuilt in the kit batch's final rebuild. The reader, scoring and scorer pins stay unchanged. The `repro` command and pre-probe capture are separate work.
No PREREG version change; PREREG-v0.5 remains frozen.

## Kit, 2026-11-03: volatile background work, turn wait and unit timing (#378, #388, #391)
- **RING0 §13 E30 and §14.10:** execution receipts require per-arm background disclosures, decimal-string `turn_wait_s` and unit wall boundaries with attempts. T2-lite records units; T1 leaves units empty. The developer report's wait-comparability rule is specified here; its refusal is implemented separately. These disclosures change no score, card, stable output or frozen quantity. The controls pin moves because `report/receipt.py` is in its closure; the reader, scoring and scorer pins stay unchanged. Rebuild packs for the new controls pin.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 erratum, 2026-11-03: settle each checkpoint once on the real store (#410)
- **RING0 §13 E29 (§6, §11):** from the next kit, the life runner judges settledness once at checkpoint replay end on the real store. Probe exits on clones cannot reclassify items. A real store that is unsettled still classes every checkpoint item SYSTEM_FAILURE `unsettled`, with one checkpoint record. E29 narrows ERRATA-v2.2 E6's timing for life-runner probes.
- **Impact:** no code pin moves. T1 results for mem0-oss and omega can change when the defect fires; hermes-native and holographic outcomes keep their rule. Published results are unchanged.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0, 2026-11-03: Mem0's scripted additive extraction reply (#208)
- **RING0 §2 and §13 E28:** from this kit, the stub answers mem0ai 2.2.1's additive extraction call with the `memory` list it reads: one text-only entry per new user message, cut at 240 characters and bounded by the reply budget. Automatic extraction is exercised, and `<tier>.extraction` discloses the scripted extractive reply; E28 supersedes E11.
- **Pins and results:** no code pin moves. Mem0's T0 and T1 results can change, because T0's memory-layer host makes the same extraction call on every ingest; both are measured by the owner with runs before and after. Explicit `mem0_add` writes and other systems' replies are unchanged.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 erratum, 2026-11-03: Keep incidental decoys are declared competing values (#293)
- **RING0 §13 E27 (§1):** from the next kit, visible decoy option tokens of `keep-incidental-v1` are `planted` competing values, excluding required and forbidden tokens. First-match scoring stays unchanged: T0 and T1 item outcomes, scores and selected options do not change. Per-kind competing counters in item reports accompanying cards with these items now count decoys in context; cards' existing `competing_milli` share already uses `competing_present` and stays unchanged.
- **Pins and packs:** the controls pin moves through the compiler's option-role helper; reader, scoring and scorer pins stay unchanged. Every T0 and T1 pack's controls cache and manifest move with the controls pin, and packs containing these items also change reader keys and their dependent hashes and build diagnostics. Rebuild earlier packs. The frozen template source, world content and `world_hash` stay unchanged; no schema changes.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 erratum, 2026-11-03: the T2 shape (#391, §13 E25, §15)
- **RING0 §13 E25, §15:** adds the named `t2` preset, T1's shape rules at 10 sessions, and extends T1's 6 QA / 2 action probe cap to T2, on both compile paths (with and without fixture bindings). §15 records per-item probe isolation, the inherited provisional W = 16K window, G2 action scoring deferred until #118, and Ring 1's alternating G1/G2 composition for any life count. Only the controls pin moves; pack trees and hashes change and packs are rebuilt once with the kit batch (#389). T0 and T1 item outcomes do not change.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 contract change, 2026-11-03: INV-FORGET reads SQLite contents (#276)
- **RING0 §13 E26 (§7):** from the next kit, INV-FORGET searches private SQLite copies and their sidecars before recovery, in UTF-8 and both UTF-16 encodings, reads all SQL values, and requires integrity and zero-filled free pages to certify absence. Raw hits remain `store_hit`; binary formats other than SQLite remain `opaque_store`. The new doubt reasons are `sqlite_unreadable` and `sqlite_freelist`, ordered after `opaque_store`. Canonical host checkpoints are scanned by their carried files. T0 adds canonical JUnit property `invariants.forget_scan` with run-wide method/result counts and hit locations; verdict objects and T1 outputs are unchanged. A token split across pages in superseded copies (main-file pages that newer WAL frames replace, old WAL frames, a persisted journal) is a known gap, tracked in #417. The scorer pin (`scorer_sha256`, over `score/*.py`) moves, so packs built before this change no longer verify and are rebuilt. v0.1's frozen kit keeps its rule.
No PREREG version change; PREREG-v0.5 remains frozen.

## Kit, 2026-11-03: pack hashes no longer depend on the build host's SQLite (#327)
- **Pack builder:** from the next kit, sealed SQLite copies have fixed zeros at header offsets 92–99 before hashing. Raw DB hashes, pack manifests, pack tree hashes and tier indexes/hashes move; rebuild earlier packs. The generator's output stays unchanged. The builder's SQLite version is returned by the build API and printed on the build command's stderr, outside the hashed tier directory.
- **Kept:** all four code pins, scores, verdicts, world content and `world_hash` stay unchanged, as do the host-free pack digests. This covers writer header metadata, not future SQLite page-layout changes.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0, 2026-11-02: the v0.3 developer loop's terms (§14) and the v0.3/v0.4 split (§13 E24)
- **RING0 §14:** defines the terms of PREREG §8's developer-product acceptance bar for v0.3 (the baseline `naive-rag-dev`, real-stack, the surfacing run and the selected failure, reproduced, fixed, confirmed on Ring 1, the budgets and the declaration, what the bar publishes) and the developer report's statistics, before any run they govern. Developer tiers still carry no decision bar.
- **RING0 §13 E24 (§3, §6, §7):** live G2 action scoring and the T0 Hermes-replay fallback move to v0.4 (ERRATA-v2.2 E16), and T1's cut order starts with the costs that should change nothing on its cards, such as the wait after each turn (v0.2's A/B could not decide that, #383), each checked by an A/B at one commit.
No PREREG version change; PREREG-v0.5 remains frozen.

## Labels, 2026-11-02: deferred-work labels name no release (#340)
- **Item records, cards, packs and tier specs:** from the next kit, an item record's `filter_log` reads "not run" and its `rungs` reads "uncalibrated". T0, T1 and T2-lite cards carry "filters: not run" and "rungs: uncalibrated", as do T0 relation rows ("rungs: uncalibrated"). The tier specs' and the T0 catalogue's `levers_label` read "uncalibrated", and the catalogue's Rachael exclusions read "deferred to the live tiers". The 2026-11-01 re-plan moved rungs to v0.3 and Ring 0's item filters to the Pilot, so the old labels named the wrong release; the roadmap, not the data, now says when each ships. `items/bundle.py` and `corpus/format.py` are in the controls pin's closure, so the controls pin moves. Every T0 and T1 pack tree moves (records, manifests and indexes, and the T0 catalogue hash), and packs built before this change no longer verify and are rebuilt. Cards made before this change no longer validate, so they are refused as references: a T1 baseline as `baseline_invalid`, and a T2-lite baseline or A/A′ card as `invalid_card:<side>`. Rerun them on the rebuilt packs.
- **Kept:** the v1 templates' C-7 values that read "uncalibrated (v0.2)", every entry's lever-mix value (written by `items/c7.py`) and the G1 templates' lever-mix rungs (`items/templates/g1/common.py`), are recorded fields of their C-7 entries (`specs/ring0/c7-partial.json`), so they keep their wording until a template's next version, as the 2026-11-01 Labels entry below does for the G1 templates' lever-mix label. RING0 §13 E5 keeps its v0.1 wording as a dated record, and `scripts/v01_acceptance.py` stays byte-identical to the script the published v0.1 runs used.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 erratum, 2026-11-01: the carry-over diagnostic reads earlier answers by their content (#352, #355)
- **RING0 §13 E23 (§6):** from the next kit, T1's reader bounds the earlier probe exchanges by the turn it answers, and an earlier answer counts by its value and its citation's quote, not by its envelope's field names and confidence numbers. T2-lite's shadow reads the same exchanges. `carry_over` is a reporting flag: no answer, score or class changes. T1 cards' `carry_over` and `carry_over_milli` can change, and so can T2-lite's `carry_over` on its cards, its item rows and `t2lite_probes.json`. The reader pin moves, so packs built before this change no longer verify and are rebuilt.
No PREREG version change; PREREG-v0.5 remains frozen.

## Labels, 2026-11-01: the two provisional generator values name PREREG-v0.6 (#318)
- **`world/scale.py`:** from the next kit, the labels of the span and the decoy ratio read "provisional pending PREREG-v0.6", the version `docs/ERRATA-v2.2.md` E5 queues both values for. No output carries these two labels, but the file is in the controls pin's closure, so the controls pin moves with this change and earlier packs are rebuilt.
- **Kept:** the v1 G1 templates' lever-mix label, "provisional pending PREREG-v0.5", is a recorded field of their C-7 entries (`specs/ring0/c7-partial.json`). Changing it would make new template versions (`prereg/PREREG-v0-completion.md`, How the entries bind), so it keeps its wording until a G1 template's next version. Read it as "provisional, not pre-registered".
- **The OC base document's rule registry** names the version of every PREREG line it cites, `PREREG-v0.4 l.N`, the version the #245 ruling cites. Since PREREG-v0.5 froze, some of those line numbers hold other text in v0.5. Two cites written after that freeze used v0.5's numbers: l.463 (the bar-2 run's full pilot roster) and l.548 (σ_d's scale difference). They now point at the same text in v0.4, l.417 and l.502. The base document's provenance bytes change, and so does the C-8 hash, whose file set holds `ocsim/`, `world/scale.py` and their tests; no checked-in file records either.
No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 contract change, 2026-11-01: host keep decisions are disclosed (#135 part 2)
- **RING0 §7 and §13 E22:** from the next kit, host keep decisions survive reset and restore, each tier's JUnit discloses canonical counts as `<tier>.forget_kept`, and a failing `store_hit` also carries `host_kept` when a kept text contains a searched needle. Statuses and member counts stay unchanged; kept texts stay in memory only. The scorer pin moves (`score/invariants.py`), so packs built before this change are rebuilt. v0.1's frozen kit keeps its rule. No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 contract change, 2026-11-01: spill-file names are masked (#328)
- **RING0 §13 E21 and §4:** from the next kit, the stable projection also masks an unhyphenated version-4 UUID that names a `.txt` file after a slash in body text (`random-uuid-hex-file`). That is the name Hermes gives an oversized memory recall's spill file, which made Mem0's two T1 runs differ. Every card's `masks_hash` changes. v0.1's maintenance kit carries E18 and E21 from its third official run (#329). No PREREG version change; PREREG-v0.5 remains frozen.

## PREREG-v0.5 clarification, 2026-10-31: the anchor's seed order (#285)
- **l.814 (l.759 in PREREG-v0.4):** "in seed order" means ascending `keyed.draw(str(seed), world.unit(life, "anchor", "order"), 0, bundle_ref)`, ties broken by `bundle_ref`, where `bundle_ref` is the sha256 hex of the bundle id and the seed is the life's. `runner/dispatch.py:anchor_order` computes it for the OC base document, and the full-tier runner must use the same function (#245 B-25). No version change; PREREG-v0.5 remains frozen.

## Design erratum, 2026-10-31: the Scoring Veto Panel's timing (#321)
- **DESIGN §14 and §16** now carry PREREG-v0.5's backstop: the panel's rule binds from the first freeze after C-18 is filled, and from PREREG-v1 at the latest (PREREG-v0.5, Freezes, External veto, From when). `docs/REQUIREMENTS.md`'s three lines that say when the panel stands in, binds and holds the veto alone now carry the same two conditions. No rule changes: PREREG-v0.5 already states both. FREEZE-v0.5 verifies `docs/DESIGN.md` and `prereg/PREREG-v0.5.md` as they are at the tag `prereg-v0.5`, so its hashes stay valid. No PREREG version change; PREREG-v0.5 remains frozen.

## Ring 0 contract change, 2026-10-31: fixed sandbox roots (#282)
- **RING0 §13 E20:** from the next kit, every Hermes unit runs below a fixed per-slot base, exclusively leased for the run and inherited by workers. T0/T1 accept and disclose `--sandbox-slot`, and refuse operator paths inside any slot's base (`sandbox_overlap`); the mask is unchanged. v0.1's frozen kit keeps its layout; next-kit baselines are rebuilt. No PREREG version change; PREREG-v0.5 remains frozen.

## PREREG-v0.5, 2026-10-31: frozen (supersedes v0.4; DV48, #311)
- **DV48, agent-only validation,** at the owner's direction of 2026-10-31: no person grades, annotates, keys, audits, adjudicates or breaks a tie. `prereg/PREREG-v0.5.md` carries design v2.3. Its freeze record, `prereg/FREEZE-v0.5.md`, keeps both hashes, the freeze time and the tag.
- **What it changes** (PREREG-v0.5's closing changelog has the full list): completion slots C-16 (the validation families), C-17 (the image readers) and C-18 (the Scoring Veto Panel's families); the Scoring Veto Panel, with a two-family quorum, binding from the first freeze after C-18 is filled, and holding the veto alone, since the owner waived the external human reviewer in writing on 2026-10-31 (recorded on lcm-x #1964); the phrase bank's calibration and receipt; image fidelity from scene-graph floors, a reader ensemble and seeded mutants; judge validation on a world-state set; agent annotators and auditors for Stage A and Stage B, with mechanical legs, a recall-corrected gate and a false-error bar on the auditor pair together; the agent-key row; the feasibility-pilot label computed from the receipts; the validation row and the sealed-exposure rule (§11).
- **Not in it:** the cases `docs/ERRATA-v2.2.md` queued for PREREG-v0.5 move to PREREG-v0.6. S8's keysheet, the phrase-bank receipt gate and the C-16 to C-18 fills are follow-up issues.

## Design erratum, 2026-10-31: DESIGN edits after the PREREG-v0.4 freeze (#311)
- **FREEZE-v0.4's DESIGN hash:** `docs/DESIGN.md` was edited after the v0.4 freeze, in commits a5e3c3b and 3316337. Those edits changed no frozen quantity. FREEZE-v0.4's DESIGN hash verifies only at the freeze commit 2600616, not on later trees; its PREREG-v0.4 hash still verifies. No PREREG version change; PREREG-v0.4 remains frozen.

## Ring 0 docs, 2026-10-30: v0.1's maintenance kit (#29, #302)
- **RING0 §13 E13, E15, E17, E19:** v0.1's maintenance kit (`maint/v0.1`, #302) carries these four errata for v0.1's second official run, and their closing sentences now say so. §13's opening names them. No rule changes on main; E12, E14, E16 and E18 stay next-kit errata. No PREREG version change; PREREG-v0.4 remains frozen.

## Ring 0 contract change, 2026-10-30: Hermes waits for its MCP servers before it builds the agent (#71)
- **RING0 §13 E19:** from the next kit, the Hermes adapter's config sets `mcp_discovery_timeout` to 60 s whenever it configures MCP servers (today only at T1), so a slow environment server's tools enter the agent's first tool snapshot in the pin's sorted order instead of being appended later or left out. The harness record lists it under `config_deviations`. v0.1's frozen kit keeps the pin's default. No PREREG version change; PREREG-v0.4 remains frozen.

## Ring 0 contract change, 2026-10-30: SQLite's clock follows the simulated clock (#270)
- **RING0 §13 E18:** from the next kit, Python sqlite3's 'now' and CURRENT_* follow the simulated clock, with per-statement caching and disclosed trigger, trace-callback and schema limits. Kernel file times stay real and are disclosed per system; OMEGA's dedup TTL uses the simulated clock. v0.1's frozen kit keeps today's shim. No PREREG version change; PREREG-v0.4 remains frozen.

## Ring 0 contract change, 2026-10-30: arrival time outside the cursor leaves the masked ledger digest (#287)
- **RING0 §13 E17:** from the next kit, the masked ledger digest leaves out `sim_now` on request records without a cursor, where the stamp depends on arrival timing; the raw record keeps it. At T0 this covers every request. Records with a cursor, request and reply digests, every other field and the existing reply `created` mask keep their rules. v0.1's frozen kit keeps the old projection and its published digests are unchanged. No PREREG version change; PREREG-v0.4 remains frozen.

## Ring 0 contract change, 2026-10-30: T1 receipts record session timings (#267)
- **RING0 §13 E16:** from the next kit, T1 receipts record volatile per-run and per-session timings for pin checks, workspace rebuilds, Hermes start-up, turns, drains and egress sampling. Overlapping stages are disclosed in E16; cards and every other receipt value are unchanged. v0.1's frozen kit writes no timings. No PREREG version change; PREREG-v0.4 remains frozen.

## Ring 0 contract change, 2026-10-30: the port mask matches whole numbers only (#278)
- **RING0 §4, §13 E15:** from the next kit, ASCII-digit run values match only where no ASCII digit is adjacent, keeping unrelated numbers independent of the run's director port. Sandbox-root matches and director-id and pattern precedence stay unchanged; the E4 fresh-install mask keeps its file and address scope. Masked output and digests are unchanged wherever no collision occurred. The masks schema's run-value description says the same. Found while diagnosing #71; whether it explains #71's divergence is recorded there. v0.1's frozen kit keeps its rule. No PREREG version change; PREREG-v0.4 remains frozen.

## Ring 0 contract change, 2026-10-29: egress observation must complete (#264)
- **RING0 §13 E14:** from the next kit, a dead sampler or a registered pid with no completed sample refuses `egress_unobserved`; `upstream_record` wins across available hosts and runs. Registration samples synchronously before ready; unsampled detail names each pid and stderr log. Failed samples are counted by exception type, never refused, and `stop()` samples once after joining. v0.1's frozen kit keeps its rule. No PREREG version change; PREREG-v0.4 remains frozen.

## Design erratum, 2026-10-29: certification's size under the t calibration (#240)
- **DESIGN §7.7, ERRATA-v2.2 E14:** DESIGN's "the rule's size is at most 5%" holds under the t-calibrated bootstrap bounds that #240's ruling adopted (#242, #251), and the operating-characteristic simulation checks it. PREREG-v0.4 fixes the bootstrap, its weights, the draw count and the seed, not the percentile index. No PREREG version change; PREREG-v0.4 remains frozen.

## Ring 0 contract change, 2026-10-29: forgetting identical texts and recalling clipped writes (#135)
- **RING0 §7:** a plug-in host's forget keeps one row for each unselected event with the same written text, and with a search backend it searches each text again after a pass that issued a delete, until a pass issues none. Recall matches a clipped write on its written text, so it is cited. v0.1's frozen kit keeps the old host. No PREREG version change; PREREG-v0.4 remains frozen.

## Ring 0 contract change, 2026-10-29: unbound sockets on macOS (#205)
- **RING0 §13 E13:** from the next kit, the egress sampler ignores an lsof row on macOS only when its protocol is TCP or UDP and its name is exactly `*:*`, in both `non_loopback` and `non_loopback_seen`. Every other row counts as before, including ICMP `*:*`, wildcard binds with a port and connections with a non-loopback address on either side. Other platforms keep the existing rule. v0.1's frozen kit keeps its rule and reruns any run refused this way. No PREREG version change; PREREG-v0.4 remains frozen.

## Ring 0 contract change, 2026-10-29: adapter ingest round trips (#213)
- **RING0 §13 E12:** adds `text_full_length` and `actor_stored`, declared actor skips, single-fault mutants and test-fixed control expectations. T0 plug-in runs and T1 corpus hosts disclose write clipping counts, declared limits and delivered fields through existing JUnit properties; cards and schemas do not change. Of the hashed files only `api/adapters/mutants.py` changes, so only the mutant adapters' T0 lock hash moves; the controls hash, the reference adapters' lock hashes and naive RAG's embedder hash do not, and packs built before this change still verify.
- **DESIGN §6.9, ERRATA-v2.2 E13:** adds the Phase 1 API-mode rule: check the benchmark's adapter against a lossless API stand-in before the first block and refuse adapter ingest loss; disclose unsupported fields. Every other real-system conformance result is reported measured behaviour, never a refusal. No PREREG version change; PREREG-v0.4 remains frozen.

## Ring 0 contract change, 2026-10-28: Holographic's dependencies (#210)
- **RING0 §13 E9:** Holographic gets a benchmark lock for numpy and snowballstemmer, at pinned Hermes's own versions, and runs on its own prepared copy of pinned Hermes. Before this, it ran without numpy, which turns off its holographic vectors and structural recall. No PREREG version change.

## Ring 0 contract change, 2026-10-28: the hashed-vector stub's scale and Mem0's extraction disclosure (#207, #208)
- **RING0 §13 E10:** the hashed-vector stub maps token cosine c to (1 + c)/2 over D−1 hashed token coordinates, preserving similarity order for those token vectors while disclosing changed collisions and unvalidated hybrid weights and absolute thresholds.
- **RING0 §13 E11:** pinned Mem0's automatic extraction stores no vector memories because it does not read the stub's reply format, so results cover explicit-write storage and recall wiring and disclose that extraction is not exercised.

No PREREG version change.

## Ring 0 contract change, 2026-10-28: plug-in Python dependencies (#190)
- **RING0 §13 E9:** plug-in dependencies come from a benchmark-owned hash lock installed into a per-system copy of pinned Hermes; prepare refuses absent or unequal applicable versions. JUnit run properties disclose the lock and every real worker's distribution set. No PREREG version change; PREREG-v0.4 remains frozen.

## Ring 0 contract change, 2026-10-28: native session-start snapshot (#185)
- **RING0 §7 and §13 E7:** the Hermes native memory-layer host gives the reader the frozen session-start memory and user-profile snapshot rendered by pinned Hermes at session open, before recall and prefetch context, without adding recall citations. T0 discloses that other harness prompt injection is not exercised; T1's regression corpus uses the same host. No PREREG version changes; PREREG-v0.4 remains frozen.

## PREREG-v0.4, 2026-10-26: frozen (supersedes v0.3)
- **DV47, the run-time rule,** at the owner's direction, for the full-tier runs: locked, resumable segments replace the contiguous 24-hour window. Every replaying (arm, life) finishes within 24 h, and each system's lane work, times 1.25 for pauses, fits 96 h on every lane, for each of its board, study and Image board runs. A system's lane work and a run's lane occupancy are projected separately. The pilot's runs of record stay contiguous, within wall-time ceilings (§11).
- **Validity controls** (§6, §11): blocks of one life, in seed order; the run lock, with the served identities recorded beside it, and keyed randomness; the served-identity check; the control arms and naive RAG as arms of every block, on the pinned reader, with checkpoint-dispatched probes under a frozen pass-over rule; gates and admission computed after the last block, with per-life margins and a defined pooled gate; a 24-hour start window per block; a control mechanics check before the first block; a report-only swap-route anchor and each row's timing imbalance; a probe-only arm's cause and retry rule; the raw-archive marker as a replaying arm and the full-history oracle ceiling as a once-per-season probe-only diagnostic, both in C_marker; and the OC simulation's drift envelope, defined on the pinned reader with a stress schedule and hashed in C-8; pauses at session boundaries, with a hash proof of every agent-visible surface, holds inside sessions, and spike S9; attempts per (arm, life); the study inside its board's run; publication of runs that end early, and a restart of the stopped run only. The card discloses the segments (§10). Bar 5 reads the run-time rule (§8). §7 computes each c_l within its block and reports a first-half and second-half sensitivity, and the gates get the same sensitivity.
- **DV42's fit corrected:** the swap model's lane is counted, and C-2 pins the swap model's effort.
- **The paid-lane ceiling** is $100 per full-tier run, all systems together, down from $300 per system, checked at every block start with a spend pause. Plan and paid lanes are defined, and embedding spend and the blind panel's third family are placed (§11, C-3).
- **Errata recorded at the freeze** (#26). These are carried design text and one status line that state a rule more loosely than PREREG-v0.4's operative sections. PREREG governs where they differ (PREREG-v0.4 line 5; DESIGN line 17), and they are fixed in the next version, not by a re-freeze:
  - **E1:** DESIGN §6.7a's run-lock list (line 599) leaves out the tool lists. The lock covers "the write-turn package and the tool lists (C-6)" (PREREG-v0.4 §11).
  - **E2:** DESIGN §13 (line 1386) allows replication-family terms to be taken as the pinned family's costs times the price ratio. The terms are measured per family and by role (PREREG-v0.4 §11), at each lane's measured capacity. A price ratio may estimate only dollar spend.
  - **E3:** the status lines of design v2.2 (line 13) and PREREG-v0.4 (line 3) say every life, or every arm's run of a life, finishes within 24 h. The rule bounds every replaying (arm, life) (§6, §11), and a probe-only arm has no life bound of its own.

## PREREG-v0.3, 2026-10-26: frozen (supersedes v0.2)
- **DV42 decided after spike S6b:** the pinned agent family is OpenAI (gpt-6.1-sol at medium effort, on dedicated benchmark accounts); GLM is the replication family and the swap model.
- **The blind panel** becomes Anthropic, Zhipu and one paid third family (§4, C-3).
- **C-11** becomes the lane's sustainable capacity per account (concurrency, or a paced request rate), with the account count; the fit rule and director pacing are stated (§11).
- **The tuning disclosure** is generic (§10).
- **The owner co-sign** is removed, as recorded in the process note below.

## Process note, 2026-10-26: no owner co-sign
The owner made the benchmark session the product and release owner. Freezes bind on its own data-backed approval, with no owner co-sign. Text that mentions a co-sign in PREREG-v0.2 and design v2.0 is left unchanged so their hashes hold. It is corrected in the next version.

## PREREG-v0.2, 2026-10-26: frozen (supersedes v0.1)
- **Design v2.0:** the capability map of track rows by evaluation profiles. Its stages are Remember, Survive and Act, and each is reported separately.
- **Certification on Act only:** on the sealed board, by an intersection-union rule on the raw penalised scale. A season left underpowered by a cut issues no certificate, but every result is still published.
- **Developer rings 0-2:** rungs on system-agnostic anchors, and a monthly "transfer gap detected" bit per organisation.
- **Frontier diagnostics:** Learn chains, erasure probes and attestation twins.
- **The Image profile**, admitted through spike S8, with an approved vision budget of about $50 a season.
- **Per-item action accuracy**, defined in full. Failures are attributed by cause, not by the component that reports them.
- **The five amendments to v0.1:** long sprints by count, the Wake claim contract, per-item accuracy reported, added turn latency, and G1 task completion.
- **The 24-hour rule** is now sized on the pinned agent family's model lane (C-11). The lane itself is set by DV42 after spike S6b.
- **Decisions:** DV1-DV46, with DV42 reserved, are in `docs/DECISIONS-v2.md`.

## PREREG-v0.1, 2026-10-26: frozen (superseded by v0.2, never co-signed)
- **The 24-hour rule** (§11):
  - the full core board for one system, and the seasonal robustness study for one system, must each finish within 24 h of wall-clock time;
  - a run that cannot meets the cut order first, and then the owner decides between paid capacity and a narrower design.
- **About 5 assistant turns per scripted session.** This keeps each life's write-turn chain, its critical path, short.
- **New completion slot C-11:** the permitted concurrency, measured in S6a.
- **A rename:** the failed-pilot fallback is now PREREG-v0-narrowed.

## PREREG-v0, 2026-10-26: frozen (superseded, never co-signed)
- **The first frozen text.** It follows three adversarial review rounds, a closure check and a first-principles cost review (`docs/REVIEW-SUMMARY.md`).
- **Completion record pending.** Slots C-1 to C-10 (the pinned models, windows, write-turn package, template tables, analysis code, competitor list and ablation validation) are filled in `prereg/PREREG-v0-completion.md`, before any real memory system's first pilot run.
