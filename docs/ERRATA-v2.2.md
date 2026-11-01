# Errata to design v2.2 and the planning documents

**Status:** v0.1, written by the benchmark session for the v0.1 Kit (#29). Its line numbers cite the documents as they stood before design v2.3, on main at 8740caf.

**Precedence.** PREREG-v0.4 is the only normative source for every frozen quantity (PREREG-v0.4 line 5; DESIGN line 17). Where DESIGN, a genre document or a spike specification says something different, PREREG governs. The difference is recorded here and fixed in the next version of the document it touches; nothing is re-frozen. Where PREREG itself leaves a case open, the entry gives the provisional rule the v0.1 Kit runs under, labelled "provisional", and queues the case for PREREG-v0.6. The benchmark session decides that version. PREREG-v0.5 carries only DV48.

**Numbering** continues the errata recorded at the PREREG-v0.4 freeze (`prereg/CHANGELOG.md`, #26):
- **E1:** the run-lock list leaves out the tool lists.
- **E2:** the replication-family cost terms.
- **E3:** the 24-hour status lines.

Those three stand as written there. `specs/ring0/RING0.md` uses the entries below.

## Design text, where PREREG governs

**E4. `memory_write` is never stubbed: live tiers only.**
- **The text:** DESIGN §6.2 (line 458) says `memory_write` requests "go live and are never stubbed".
- **What governs:** PREREG §6 (lines 387-388) runs T0 with no model and T1 with a scripted model, at $0.
- **The correction:** the never-stubbed rule binds the tiers that call a live model, T2 and up, and the measurement ladder.
- **At T0 and T1:** memory-write requests follow the content-blind write rule (RING0 §2), labelled wiring-only.

**E5. Two "(pre-reg)" marks with no PREREG text.**
- **The text:** DESIGN §4.2 marks two values "(pre-reg)": the simulated span of 3-26 weeks (line 221), and incidental details mixed with decoys at 3 or more times their rate (line 229).
- **What governs:** PREREG-v0.4 contains neither value, so neither is frozen.
- **In v0.1:** both are queued for PREREG-v0.6. Until then they are provisional generator configuration, labelled "provisional pending PREREG-v0.5" in the completion record draft (K02); the label keeps its earlier wording. From the next kit, the generator's own labels for both values read "provisional pending PREREG-v0.6" (#318). They are never chosen or revised from any real system's results.

**E6. The adapter contract gains a settle step.**
- **The text:** DESIGN §6.9 (lines 641-647) lists `reset`, `ingest`, `query`, `checkpoint` and `restore`, `forget` and `stats`.
- **The finding:** S5 found 6 surveyed systems whose writes become searchable only after background work (S5 finding 1).
- **The addition:** `settle` runs before every checkpoint and every probe.
  - Settled means the system was observed to report its queue drained, within its declared bound.
  - Reaching the bound without that observation is a SYSTEM_FAILURE for the items it precedes, even if the call returns normally (RING0 §11).
- **Scope:** this adds a step and changes no frozen quantity.

**E7. The genre documents are from the design-v1 era.**
- **The documents:** `docs/genres/G1-software-partner.md` and `docs/genres/G2-personal-assistant.md` predate design v2.
- **Superseded parts,** where DESIGN v2.2 and PREREG-v0.4 govern:
  - **The `exposure` table** (G1 line 11). Exposure is recorded in the director's ledger, which is the ground truth for exposure (DESIGN §6.2). The world database is written once by the generator and is read-only at run time.
  - **`fact.event_id`** (G1 line 9). A fact links to every event that asserts, retracts or mentions it through the link table (DESIGN §4.1), not to one event.
  - **The F1-F13 families** (G1 line 3 and its family table). Items belong to tracks and cells (PREREG §2), and the family table is illustrative only.
  - **Token sizes:** 4-10M per life (G1 line 27) and 5-10M (G2 line 66). A full-tier life is about 1M tokens plus its long sprints, about 2.3M at W = 128K (PREREG §6).
  - **Sessions of 10-200 turns** (G1 line 32). A scripted session has about 5 assistant turns (PREREG §6, §10).
- **What stays:** the world processes, entities and channels in both documents remain the genre design.

**E15. Developer regression sets do not stock the public corpus (T2-lite, #338).**
- **The text:** [DESIGN §9.1](DESIGN.md#91-developer-rings-and-tiers-no-decision-bar) says a result's repro bundle "joins the regression corpus run in T1".
- **What governs:** [PREREG-v0.5 §6](../prereg/PREREG-v0.5.md#6-tiers-rings-subsets-and-branches) stocks the public corpus "never from one system's failures"; PREREG governs.
- **The correction:** T2-lite flip lists and rerun commands form the developer's own regression set and never stock the public regression corpus. Public stocking remains from controls, reference stubs and equal runs over every board system.

## Spike criteria

**E8. S7 A2 passes on introduced hits.**
- **The text:** `spikes/s7/SPEC.md` (line 12) defines A2 as "no write-turn body carries a string the harness request did not", then states an expected count of 0 for its literal scan.
- **The finding:** the scan also finds strings that the harness's own request already carried. Examples are a repeated user turn, or an answer already in the conversation or in memory.
- **The correction:** the count of 0 applies to **introduced** hits only: a string held more times in the forwarded body than in the expected body built from the harness request. That is A2's own first sentence.
- **The result:** S7 Part A reports 0 introduced hits on both runs, so A2 passes. Inherited hits are reported, never hidden (S7 REPORT, A2).

**E9. S6 in v0.1 runs without Learn chains.**
- **The text:** DESIGN §6.10 and PREREG §6 give S6 the cost of the Learn chains on each life's critical path.
- **The conflict:** Learn chains are a v0.2 deliverable (ROADMAP).
- **In v0.1:** S6 reports their term, C_learn, as missing, with the break-even that S6b computed. The term is measured in v0.2, before any Learn chain enters a run of record.

## Cases PREREG-v0.4 leaves open (provisional rules; queued for PREREG-v0.6)

**E10. A missing QA envelope after a system failure.**
- **The conflict:**
  - PREREG §3 (line 227) scores "a missing or unparseable envelope" −1 on a QA item.
  - PREREG §7 (line 548) gives SYSTEM_FAILURE (a crash, a timeout inside the declared limits, an out-of-contract request, a resource-limit violation or a refusal) the treatment 0.
  - A QA item whose system crashed has a missing envelope, so both rules apply.
- **The provisional rule:** cause decides first, as PREREG §7 requires.
  - When the ledger classifies the item as SYSTEM_FAILURE, it scores **0** in the ordinary row and **−1** in the worst-case row (PREREG §7, lines 548 and 561).
  - The §3 penalty of **−1** for a missing or unparseable envelope applies when the probe turn completed with no system-failure classification.
- **Why:** both treatments are frozen. Reading §3's "missing" envelope as the one a completed turn fails to produce keeps both. PREREG's own guard against crashing instead of answering is the worst-case row, which prints every system failure at −1.
- **At T0 and T1:** the scripted reader always emits an envelope when the recall call returns. A crash or timeout of the recall call is a SYSTEM_FAILURE under this rule.
- **For PREREG-v0.6:** it states this precedence in the text.

**E11. A bundle whose two items carry different classes.**
- **The conflict:** a bundle scores the minimum of its two items (PREREG §2). PREREG does not say what happens when one twin item is scored and the other is a non-result.
- **The provisional rule:**
  - **The twin minimum applies only when both items carry a score.** A SYSTEM_FAILURE and a FAIL_TASK are scores.
  - **When either item is a non-result,** the bundle takes that item's class and carries no score.
  - **When the two items are different non-results,** the bundle takes the one that excludes more. BLOCKED comes first (excluded for every system in the comparison), then N/A_EXPOSURE, then N/A_CLOCK (both excluded for that system).
- **Effect on the figures:** coverage and the 5% infrastructure-exclusion rule (PREREG §7) count bundles by the class this rule gives.
- **Item records are unchanged.** Each item keeps its own class, and the bundle rule never replaces it:
  - a failed action item still counts as incorrect in per-item action accuracy (PREREG §3);
  - every system failure still shows in the worst-case row (PREREG §7).

  For example, a bundle of a SYSTEM_FAILURE and an N/A_EXPOSURE item is unscored, but the failed item stays incorrect in accuracy.

## The ROADMAP's Act wording

**E12. Act in the v0.1 Kit.**
- **The text:** the ROADMAP's v0.1 row ships "Ring 0 developer packs for the Remember, Survive and Act stages".
- **The clarification:** at T0 and T1, Act is the scripted reader's evidence-conditioned action, executed and scored by the real action scorer. It carries the label "evidence-conditioned scripted action; not an Act judgement" (RING0 §3), because a scripted policy measures whether the evidence was available, not what a model does with it. The live tiers (v0.2) carry the Act stage proper.
- **Where it is fixed:** the ROADMAP carries a note to this effect.

**E13. API-mode adapter ingest checks (Phase 1, #213; addition to DESIGN §6.9).**
- Before a system's first block, the API-mode runner runs `text_full_length` and `actor_stored` on the benchmark's adapter for that system, against a stand-in for the system's API that keeps everything it is given. It refuses the system if either check fails: loss in benchmark-written adapter code must not be charged to the system.
- A field the system's API cannot carry is declared through `UNSUPPORTED_FIELDS` and disclosed. Only actor is declarable for now; the corresponding check is skipped, and the separate `declared()` result identifies the skip rather than a storage pass.
- Every other conformance result of a real system is its measured behaviour: it is reported and never a refusal. These checks against the stand-in do not gate real-system retrieval, extraction, compaction or other measured behaviour.
- The controls' expected results are fixed in their tests. In particular, naive RAG fails exactly `supersession_current` and `text_full_length`; its actor storage passes.
- This adds the Phase 1 API-mode rule without changing PREREG-v0.4 or any frozen quantity. Ring 0's checks and host delivery disclosures are specified in RING0 §13 E12.

## Certification

**E14. Certification's size holds under the t calibration (#240).**
- **The text:** DESIGN §7.7 (line 926) says that under the intersection-union test "the rule's size is at most 5% with no multiplicity correction".
- **The finding:** with few life pairs, the percentile bound of the Rademacher wild cluster bootstrap undercovers. The bootstrap's spread is √((n−1)/n) of the usual standard error, and the normal quantile ignores t tails. Under a normal approximation, R-a's nominal bound certifies about 6.05% of systems whose true margin is 0, at 24 life pairs (#240).
- **The correction:**
  - The size is at most 5% under the t calibration that #240's ruling adopted.
  - Every bootstrap bound that certification uses takes the level p_n = Φ(−t_{n−1, 1−α}·√(n/(n−1))) instead of the fixed percentile (#242, #251).
  - The operating-characteristic simulation (#245) checks the bound. The bound is the first of the three pass criteria of PREREG-v0.4's freeze gate for PREREG-v1: a certification rate of at most 5% with margin 0 in every cell. The other two are at least 80% with +10 in every cell, and at most 20% with +10 in every cell but one at −10 (PREREG-v0.4 line 44).
- **Scope:** PREREG-v0.4 fixes the bootstrap, its weights, the draw count and the seed, not the percentile index, so no frozen quantity changes. The v0.1 Kit is unaffected, because its T0 and T1 runs never certify.
