# Pre-registration changelog

Every change to the pre-registration after a freeze makes a new version, recorded here. Every result discloses the version it used.

## Ring 0 erratum, 2026-11-01: the carry-over diagnostic reads earlier answers by their content (#352, #355)
- **RING0 §13 E23 (§6):** from the next kit, T1's reader bounds the earlier probe exchanges by the turn it answers, and an earlier answer counts by its value and its citation's quote, not by its envelope's field names and confidence numbers. T2-lite's shadow reads the same exchanges. `carry_over` is a reporting flag: no answer, score or class changes. T1 cards' `carry_over` and `carry_over_milli`, and T2-lite's `t2lite_probes.json`, can change. The reader pin moves, so packs built before this change no longer verify and are rebuilt.
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
