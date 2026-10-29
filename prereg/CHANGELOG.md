# Pre-registration changelog

Every change to the pre-registration after a freeze makes a new version, recorded here. Every result discloses the version it used.

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
