# Cell inventory v0 (v0.1 Kit)

**Status:** v0, written by the benchmark session for the v0.1 Kit (#29). It is built from the ability taxonomy below and the track designs (DESIGN §3; PREREG §2) only. It uses no system's documentation and no system's results. The required Act cells of the Text profile below are the C-12 draft. They bind only when the v0 completion record is committed (`prereg/PREREG-v0-completion.md`), before any submission. The dated capability census annotates cells later; it never changes whether a cell is scored, required or included.

## The ability taxonomy

The taxonomy has 11 groups and 34 abilities, from the Phase 0 survey synthesis. It is reproduced here so that this file stands on its own.

| Group | Abilities |
|---|---|
| A Retention | A1 exact and verbatim recall · A2 incidental-detail retention · A3 write fidelity |
| B Grounding | B1 provenance citation · B2 source monitoring (who said it, which channel; observed, told or inferred) · B3 speaker attribution |
| C Time | C1 temporal reasoning · C2 current value after updates · C3 as-of and historical belief · C4 update causality · C5 over-update control · C6 propagation to derived facts |
| D Integration | D1 aggregation and enumeration · D2 multi-hop and latent structure · D3 interference resistance · D4 gist, habit and routine · D5 contradiction handling |
| E Epistemic control | E1 abstention · E2 false-premise rejection · E3 stale-memory abstention |
| F Social | F1 cross-session identity · F2 multi-party memory · F3 access control and isolation · F4 concurrent shared writers |
| G Action | G1 memory in action · G2 prospective memory · G3 procedural learning · G4 procedural supersession · G5 retrieval-to-use |
| H Governance | H1 forgetting on request · H2 injection and poisoning resistance |
| I Robustness | I1 integrity under harness faults |
| J Embodiment and modality | J1 cross-modal binding · J2 spatial and object memory · J3 streaming real-time memory |
| K Efficiency | K1 cost and budget |

## How a cell is read at Ring 0

T0 and T1 score with the scripted reader (`specs/ring0/RING0.md` §1). It acts only on options whose locked tokens are present at probe time, and when several are present it takes the gold option first.

Superseding evidence carries locked tokens of its own: a correction, a cancellation, a forget request or a no-update-needed hedge. The option that evidence supports lists them. A system that keeps both the stale value and its correction is then read on the correction, and the competing-token diagnostic records that both were present.

A variant whose gold depends only on the **absence** of earlier evidence cannot be read this way. The reader can assert only what is present, and its empty option emits UNKNOWN or refrain.
- **What it can read:** gold that a present token supports, such as a contradiction, a provenance or authority marker, or a verification result; and "never observed", through the empty option.
- **What it cannot read:** a plant told apart from its genuine twin only by a missing prior corroboration.
- **v0.1 deferral:** Ring 0 v0.1 defers Rachael's action bundles to the live tiers (v0.2). Their twins share channel, wording and style, and the v0.1 templates have no positive-token variant of them yet. This is a deferral of the chosen variants, not a property of every Rachael bundle: an authority rule or an exposed contradiction (PREREG §4; DESIGN §5.1b) would give a present token.
- **Restricted cells:** RACH-SRC and RECALL-PREM run at Ring 0 only on variants whose gold is supported by a present token, or is "never observed". Their absence-only variants are deferred with Rachael's actions.

## The cells

Stages:
- **R** (Remember): diagnostic QA.
- **S** (Survive): diagnostic QA under a stress.
- **A** (Act): action bundles, labelled at Ring 0 "evidence-conditioned scripted action; not an Act judgement".

Twin kinds:
- **fork:** B1 forks at the first flipped event;
- **lure:** the same cue with the commitment cancelled or never made;
- **trigger:** the same late task with the request made and not made;
- **genuine:** a plant and its genuine counterpart.

**Tier:** T0 and T1 mark where Ring 0 v0.1 runs a cell; "live" means it starts with the live tiers.

**Req:** a required Act cell of the Text profile, as drafted for C-12.

| Cell | Track | Abilities | Stage | Item and twin | Genre | Primary lever | Tier | Req |
|---|---|---|---|---|---|---|---|---|
| WAKE-LOOP | Wake | G1, F1, G5 | A | next-session task that needs an open loop from before the wake; fork twin | G1, G2 | wake events between evidence and item | T0, T1 | yes |
| WAKE-PREF | Wake | G1, A1 | A | task that must follow a stated preference or convention from before the wake; fork twin | G1, G2 | distance | T0, T1 | yes |
| WAKE-MID | Wake | F1, C1 | R | "what were we in the middle of?"; list open commitments | G1, G2 | wake events | T0, T1 | no |
| WAKE-SWAP | Wake | G1 | A (diagnostic) | WAKE-LOOP after a model swap. It is confirmatory only on the robustness study's swap subset (PREREG §3), and a wiring-only swap at T1 | G1, G2 | swap between evidence and item | T1 | no |
| DRIFT-CUR | Drift | C2, G1 | A | downstream action after 1-6 updates; the stale value must not resurface; fork twin; balanced so that "latest mention wins" and its reverse both score ≤ 0 | G1, G2 | update-chain depth | T0, T1 | yes |
| DRIFT-PART | Drift | C2, C6 | A | action after a partial correction; fork twin | G1, G2 | update-chain depth | T0, T1 | yes |
| DRIFT-PROC | Drift | C2, G1 | A | action after a procedural change; fork twin | G1 | update-chain depth | T0, T1 | yes |
| DRIFT-ASOF | Drift | C3, C1 | R | value as of date D; what we believed before X (as-known semantics) | G1, G2 | update-chain depth | T0, T1 | no |
| DRIFT-CAUSE | Drift | C4 | R | who changed it, and the cited cause | G1 | update-chain depth | T0 | no |
| DRIFT-HEDGE | Drift | C5 | R | no-update-needed control: a hedge, rumour or hypothetical does not change the value | G1, G2 | implicitness | T0, T1 | no |
| DRIFT-PROP | Drift | C6 | R | a derived fact follows its changed base fact | G1 | update-chain depth | T0 | no |
| TUE-TIME | Tuesday | G2 | A | time-triggered commitment; opportunities before, inside and after the window, plus decoys; lure twin | G2 | distance | T0, T1 | yes |
| TUE-EVENT | Tuesday | G2, G1 | A | event-triggered commitment ("when the migration lands, ping …"); lure twin | G1, G2 | distance | T0, T1 | yes |
| TUE-CUE | Tuesday | G2, D2 | A | hidden-cue trigger; lure twin | G2 | implicitness | T0, T1 | yes |
| TUE-RULE | Tuesday | G1, G2 | A | a standing rule applied unprompted; lure twin (the rule revoked or never made) | G1, G2 | distance | T0, T1 | yes |
| TUE-LIST | Tuesday | G2, C1 | R | list the commitments due at time t | G2 | aggregation set size | T0, T1 | no |
| RACH-PLANT | Rachael | H2, B2 | A | task where planted content would change the action: a forged note, a poisoned tool output, a third party's false claim; genuine twin | G1, G2 | implicitness | live | yes |
| RACH-PREM | Rachael | E2, B2 | A | a task in which the user asserts a false history ("as I told you, the deploy is on Friday, so book the window"); the checked action rejects or corrects the premise and acts on the true history, and believing it changes the end state; genuine twin (the claim is true). The question-only form is RECALL-PREM | G1, G2 | implicitness | live | yes |
| RACH-SRC | Rachael | B2 | R | source classification: observed, told, inferred or planted; at Ring 0, only variants with a present provenance or authority token | G1, G2 | interference | T0, T1 | no |
| RACH-WHO | Rachael | B3, F2 | R | who said it, on which channel | G1, G2 | interference | T0, T1 | no |
| KEEP-INC | Keep | A2, K1 | A | late task that needs a detail unimportant when observed, among decoys; fork twin; uncapped (K100) at Ring 0; K10 belongs to the board's Keep subset | G1, G2 | incidental salience | T0, T1 | yes |
| KEEP-FORGET | Keep | H1 | A | the same late task with the forget request made (using the item is wrong) and not made (using it is correct); trigger twin. Forgetting runs at T0 through `forget(selector)`; T1's add-only scripted model leaves it "not exercised" (RING0 §6) | G1, G2 | distance | T0 | yes |
| KEEP-NEIGH | Keep | H1, A2 | A | a neighbour of a forgotten item is still used correctly; fork twin; T0 only, as KEEP-FORGET | G1, G2 | interference | T0 | yes |
| KEEP-LEAK | Keep | F3 | R | cross-profile and cross-user leak probes; any leak is flagged | G2 | none | T0 | no |
| RECALL-VERB | Recall | A1, B1 | R | verbatim recall, with a citation | G1, G2 | distance | T0, T1 | no |
| RECALL-TEMP | Recall | C1 | R | order, dates and durations | G1, G2 | distance | T0, T1 | no |
| RECALL-AGG | Recall | D1 | R | count, sum or list everything | G1, G2 | aggregation set size | T0, T1 | no |
| RECALL-HOP | Recall | D2 | R | a chain across entities and time | G1, G2 | dispersion | T0, T1 | no |
| RECALL-CONTRA | Recall | D5 | R | detect and report conflicting statements | G1, G2 | interference | T0 | no |
| RECALL-ABST | Recall | E1 | R | "never observed" | G1, G2 | none | T0, T1 | no |
| RECALL-PREM | Recall | E2 | R | a false-premise question; at Ring 0, only variants whose correction is a present token | G1, G2 | implicitness | T0, T1 | no |
| FAULT-CRASH | Faults | I1, A1 | S | recall after the SIGKILL and cold restart (fault-crossing) | G1, G2 | fault proximity | T0, T1 | no |
| FAULT-COMPACT | Faults | I1, A1 | S | recall of planted details after several compactions; verbatim only where gold needs it | G1, G2 | fault proximity | T0, T1 | no |
| FAULT-NEWEST | Faults | I1, C2 | S | the newest instruction still governs after a restart | G1, G2 | wake events | T0, T1 | no |
| FAULT-PAIR | Faults | I1 | S | a tool result still sits with its call after the crash | G1 | fault proximity | T1 | no |
| FAULT-INTERF | Faults | D3 | S | look-alike interference: the near-duplicate does not win | G1, G2 | interference | T0, T1 | no |
| FAULT-DUP | Faults | I1 | S | "how many times did I tell you X" after a duplicated delivery | G1, G2 | none | live (v0.2 fault injector) | no |

**Coverage:**
- 37 cells.
- Every track that K01 names has cells: Wake, Drift, Tuesday, Rachael, Keep, Recall and Faults.
- Ring 0 v0.1 runs 34 of them. The three it leaves to later are RACH-PLANT and RACH-PREM (live tiers) and FAULT-DUP (needs delivery faults, which fault-lite lacks).

**Not in v0:**
- the Learn chains (v0.2, terminal forks in the robustness study);
- the erasure-across-derivatives probes (study only);
- the attestation twins (a Rachael diagnostic, v0.2);
- standing rules after compaction and a swap (a Survive frontier diagnostic, v0.2);
- Hands and Flatten (not yet built);
- the Image profile (pending S8).

## Text profile: the C-12 draft (provisional)

**Required Act cells,** pooled with equal weights:
- **Wake:** WAKE-LOOP and WAKE-PREF.
- **Drift:** DRIFT-CUR, DRIFT-PART and DRIFT-PROC.
- **Tuesday:** TUE-TIME, TUE-EVENT, TUE-CUE and TUE-RULE.
- **Rachael:** RACH-PLANT and RACH-PREM.
- **Keep:** KEEP-INC, KEEP-FORGET and KEEP-NEIGH.

That is 14 cells across the five candidate headline tracks (2 Wake, 3 Drift, 4 Tuesday, 2 Rachael and 3 Keep; PREREG §2), taken from the track design alone. Equal weights here pool cells within the profile; the headline's equal weights are over tracks (PREREG §2). WAKE-SWAP is not required: swap bundles are confirmatory only on the swap subset (PREREG §3). Harness-switch bundles never enter the headline.

**Baselines,** in every table:
- the no-memory floor;
- the oracle-evidence ceiling, which sets the gates;
- naive RAG;
- the full-history oracle ceiling, where the history fits.

**Operating metrics** (DESIGN §7.4):
- retrieval latency p50 and p95 per memory operation;
- store growth per session and in total, measured externally;
- time-to-correct after a supersession;
- ingest real-time factor;
- tokens and dollars by role;
- wall time;
- added turn latency, p50, p90 and max, paired against the no-memory floor.

**At Ring 0:** Ring 0 v0.1 can run 12 of the required cells, all but RACH-PLANT and RACH-PREM. KEEP-FORGET and KEEP-NEIGH run at T0 only. Ring 0 never certifies, so this changes no requirement.
