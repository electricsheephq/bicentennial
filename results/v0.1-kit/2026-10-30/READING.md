# Reading the v0.1 Kit results

This is the guide to the results of the Bicentennial v0.1 Kit's first official run. The numbers are in `RESULT.md` and the machine-readable manifest. This page covers five things:
- the acceptance verdict;
- what the numbers measure, and what they do not;
- what each system's results point to;
- how repeatable the runs were;
- what to keep in mind before comparing systems.

## The acceptance verdict

The kit's acceptance script **rejected** this run. Two of its 17 checks failed (`t0_identical` and `t1_identical`), and the other 15 held.
- Both failures are about repeatability. Across every pair of runs of the same system, no score, item verdict, invariant, control, regression-corpus result or JUnit test result changed. What differs on some cards is the masked ledger digest, a digest of each unit's stable ledger fields.
- The only other difference is by design. A T1 base run has no baseline, so its gate is a conformance gate that records no baseline digest or regressions, while each repeat is gated against the base run's card. "How repeatable the runs were" below gives the details.
- So this run is not the `v0.1` release. The kit is done when T1 is deterministic on stable fields (ROADMAP). The `v0.1` tag waits for an accepted run of all 17 runs on one fixed commit (#29).
- The results are published anyway, because they still show which evidence each system stored, kept and put in front of the agent. The repeatability failures are findings in their own right.

## What v0.1 runs

v0.1 runs Ring 0, the model-free tiers:
- **T0** drives each memory system through a fixed set of write, restart, crash and forget events and checks what it returns.
- **T1** drives each system inside the pinned Hermes agent harness, through scripted lives of sessions, and checks what evidence reaches the agent at each probe.

No language model runs. A scripted stand-in answers every model call the harness or a system makes (RING0 §2), and every T1 card says "scripted model: wiring-only".

So Ring 0 measures **evidence availability and plumbing**:
- whether a system stores what it is given;
- whether it keeps it across restarts and crashes;
- whether it forgets when told;
- whether it puts the right evidence in front of the agent.

It does not measure extraction quality, summary quality or an agent's judgement. Those need the live tiers (T2 and up, v0.2).

Spend: $0 on model calls for every Ring 0 run.

## Systems, the reference adapter and the controls

| System | What it is | Version pinned |
|---|---|---|
| Hermes native | Hermes's built-in memory (the `memory` tool with `MEMORY.md`, plus `session_search`) | hermes-agent v0.22.2 |
| Holographic | A Hermes memory plug-in, on its own copy of pinned Hermes | hermes-plugin-holographic 0.13.0 |
| Mem0 OSS | Mem0's open-source Hermes plug-in, with a local vector store | hermes-plugin-mem0 1.3.0, mem0ai 2.2.1 |

Mem0 OSS completed both T0 runs and all three T1 runs (the base and two repeats), like Hermes native. Holographic's runs are described under its T1 line.

**The reference adapter, `reference_store` (T0 only), is not a system under test.**
- It is the kit's own minimal implementation of the adapter contract: a verbatim event store whose query returns one event, the newest with the most word overlap.
- The kit builds its controls and fault mutants on it, uses it as the conformance reference, and uses it as the regression corpus's pass oracle.
- Its row shows that the pipeline works end to end. Its item scores are not a baseline to compare systems against.

**Controls** run beside every system:

| Control | Where | What it shows |
|---|---|---|
| No-memory floor | T0: cached per pack. T1: a probe-only Hermes arm with memory off | What an agent gets with nothing stored. At T1 it is used only to check the wiped control; the card shows it as null. |
| Oracle evidence and full history | T0: cached per pack | The ceiling: the evidence handed over directly. |
| Wiped-store control | T1: one per system | The same system with its store wiped before each probe. It **must fail**, and it did in every run. |
| Naive RAG | — | Not run in v0.1. |

LCM-X, the benchmark's sponsor, is not run by the benchmark. Its own maintainers run the public kit on equal terms (RING0 §12).

## How to read a result

**Gates are plumbing verdicts. They never rank or certify.**
- **A T0 gate fails** on any failing invariant, any item the system failed to run (SYSTEM_FAILURE), or a honeypot hit. Item scores never move a T0 gate.
  - The adapter-level invariants are checked once per run and copied onto every pack's gate. So one run-level failure fails every pack.
  - The reason appears in the run's `adapter_invariants.json`, not in the pack's own `invariants.json`.
- **A T1 gate** also checks conformance: the regression corpus of known-faulty stores, and the wiped control. It fails a restart-crossing bundle that scores below the system's own baseline card. The first run of a system reads CONFORMANCE_PASS; repeats read PASS.

**Scores are the card's own aggregates**, per stage and track: each item pair's lower score (twin-bundle minima), averaged per life. Items come in two kinds:
- **Action items** (stage "act") read:
  - PASS;
  - OMISSION, 0: nothing usable reached the agent;
  - FAIL_MEMORY, −1000: the agent acted on a wrong memory. A confident false memory costs far more than an honest gap.
- **Question items** (stages "remember" and "survive") read correct (+1000, or +500 when hedged), unknown (0) or wrong (−1000). Their action verdict is empty by design.

**Invariants** are model-free rules every system must keep:
- **INV-VERB:** stored text survives a crash verbatim.
- **INV-NEW:** after an update, the newest value is the one returned.
- **INV-PAIR:** a tool call and its result survive a crash together, with no orphaned result.
- **INV-FORGET:** forgotten text reaches neither the context nor the store.

An invariant reads INCONCLUSIVE when the kit cannot settle it. For example, the store scan reads every file byte for byte, but a binary file, such as a SQLite database, can hold text in a form a byte scan misses (split across pages, or encoded). So when the scan finds nothing and the store holds such a file, forgetting reads INCONCLUSIVE.

## Per-track results
Each system's first repeat (run1) is shown. Its other runs have the same scores, item verdicts, invariants and regression-corpus results (see "How repeatable the runs were"). A T0 row averages, rounded down, the aggregates of the pack cards that have that stage and track ("(mean)"; Cards counts them). T1 has one card per arm, and the wiped control must fail.

### reference_store

**T0:** 86 cards; gates PASS 86.

| Stage | Track | Cards | Score (milli) | Items |
|---|---|---|---|---|
| act | Drift | 42 | 1000 (mean) | PASS 84 |
| act | Keep | 17 | 411 (mean) | FAIL_MEMORY 6, OMISSION 8, PASS 20 |
| act | Wake | 6 | 333 (mean) | OMISSION 8, PASS 4 |
| remember | Drift | 6 | 1000 (mean) | correct 6 |
| remember | Recall | 12 | 666 (mean) | correct 10, wrong 2 |
| survive | Drift | 1 | 1000 | correct 1 |
| survive | Recall | 2 | 1000 (mean) | correct 2 |
Adapter invariants: INV-VERB PASS, INV-NEW PASS, INV-PAIR PASS, INV-FORGET PASS
Pack invariants: INV-FORGET NOT_EXERCISED 75, INV-FORGET PASS 11, INV-NEW NOT_EXERCISED 79, INV-NEW PASS 7, INV-PAIR NOT_EXERCISED 86, INV-VERB INCONCLUSIVE 1, INV-VERB NOT_EXERCISED 79, INV-VERB PASS 6

### Hermes native

**T0:** 86 cards; gates FAIL 86.

| Stage | Track | Cards | Score (milli) | Items |
|---|---|---|---|---|
| act | Drift | 42 | 571 (mean) | FAIL_MEMORY 8, OMISSION 18, PASS 58 |
| act | Keep | 17 | 1000 (mean) | PASS 34 |
| act | Wake | 6 | 1000 (mean) | PASS 12 |
| remember | Drift | 6 | 1000 (mean) | correct 6 |
| remember | Recall | 12 | 916 (mean) | correct 11, unknown 1 |
| survive | Drift | 1 | 1000 | correct 1 |
| survive | Recall | 2 | 1000 (mean) | correct 2 |
Adapter invariants: INV-VERB PASS, INV-NEW PASS, INV-PAIR PASS, INV-FORGET FAIL
Pack invariants: INV-FORGET FAIL 11, INV-FORGET NOT_EXERCISED 75, INV-NEW NOT_EXERCISED 58, INV-NEW PASS 28, INV-PAIR NOT_EXERCISED 86, INV-VERB NOT_EXERCISED 79, INV-VERB PASS 7

**T1, system arm:** 1 card; gates PASS 1.

| Stage | Track | Cards | Score (milli) | Items |
|---|---|---|---|---|
| act | Drift | 1 | 1000 | PASS 10 |
| act | Keep | 1 | -1000 | FAIL_MEMORY 2 |
| act | Wake | 1 | 1000 | PASS 2 |
| survive | Drift | 1 | 1000 | correct 1 |
| survive | Recall | 1 | 500 | correct 1, unknown 1 |
Regression corpus: PASS 20

**T1, wiped arm:** 1 card; gates FAIL 1.

| Stage | Track | Cards | Score (milli) | Items |
|---|---|---|---|---|
| act | Drift | 1 | 0 | OMISSION 9, PASS 1 |
| act | Keep | 1 | 0 | OMISSION 2 |
| act | Wake | 1 | 0 | OMISSION 2 |
| survive | Drift | 1 | 0 | unknown 1 |
| survive | Recall | 1 | 0 | unknown 2 |
Regression corpus: FAIL 20

### Holographic

**T0:** 86 cards; gates PASS 86.

| Stage | Track | Cards | Score (milli) | Items |
|---|---|---|---|---|
| act | Drift | 42 | 1000 (mean) | PASS 84 |
| act | Keep | 17 | 1000 (mean) | PASS 34 |
| act | Wake | 6 | 0 (mean) | OMISSION 12 |
| remember | Drift | 6 | 1000 (mean) | correct 6 |
| remember | Recall | 12 | 1000 (mean) | correct 12 |
| survive | Drift | 1 | 1000 | correct 1 |
| survive | Recall | 2 | 1000 (mean) | correct 2 |
Adapter invariants: INV-VERB PASS, INV-NEW PASS, INV-PAIR PASS, INV-FORGET INCONCLUSIVE
Pack invariants: INV-FORGET INCONCLUSIVE 11, INV-FORGET NOT_EXERCISED 75, INV-NEW NOT_EXERCISED 58, INV-NEW PASS 28, INV-PAIR NOT_EXERCISED 86, INV-VERB NOT_EXERCISED 79, INV-VERB PASS 7

**T1, system arm:** 1 card; gates PASS 1.

| Stage | Track | Cards | Score (milli) | Items |
|---|---|---|---|---|
| act | Drift | 1 | 1000 | PASS 10 |
| act | Keep | 1 | 1000 | PASS 2 |
| act | Wake | 1 | 0 | OMISSION 2 |
| survive | Drift | 1 | 1000 | correct 1 |
| survive | Recall | 1 | 1000 | correct 2 |
Regression corpus: PASS 20

**T1, wiped arm:** 1 card; gates FAIL 1.

| Stage | Track | Cards | Score (milli) | Items |
|---|---|---|---|---|
| act | Drift | 1 | 0 | OMISSION 9, PASS 1 |
| act | Keep | 1 | 0 | OMISSION 2 |
| act | Wake | 1 | 0 | OMISSION 2 |
| survive | Drift | 1 | 0 | unknown 1 |
| survive | Recall | 1 | 0 | unknown 2 |
Regression corpus: FAIL 20

### Mem0 OSS

**T0:** 86 cards; gates FAIL 86.

| Stage | Track | Cards | Score (milli) | Items |
|---|---|---|---|---|
| act | Drift | 42 | 1000 (mean) | PASS 84 |
| act | Keep | 17 | 1000 (mean) | PASS 34 |
| act | Wake | 6 | 166 (mean) | OMISSION 10, PASS 2 |
| remember | Drift | 6 | 1000 (mean) | correct 6 |
| remember | Recall | 12 | 1000 (mean) | correct 12 |
| survive | Drift | 1 | 1000 | correct 1 |
| survive | Recall | 2 | 1000 (mean) | correct 2 |
Adapter invariants: INV-VERB PASS, INV-NEW PASS, INV-PAIR PASS, INV-FORGET FAIL
Pack invariants: INV-FORGET FAIL 11, INV-FORGET NOT_EXERCISED 75, INV-NEW NOT_EXERCISED 58, INV-NEW PASS 28, INV-PAIR NOT_EXERCISED 86, INV-VERB NOT_EXERCISED 79, INV-VERB PASS 7

**T1, system arm:** 1 card; gates PASS 1.

| Stage | Track | Cards | Score (milli) | Items |
|---|---|---|---|---|
| act | Drift | 1 | 1000 | PASS 10 |
| act | Keep | 1 | -1000 | FAIL_MEMORY 2 |
| act | Wake | 1 | 0 | OMISSION 2 |
| survive | Drift | 1 | 1000 | correct 1 |
| survive | Recall | 1 | 1000 | correct 2 |
Regression corpus: PASS 20

**T1, wiped arm:** 1 card; gates FAIL 1.

| Stage | Track | Cards | Score (milli) | Items |
|---|---|---|---|---|
| act | Drift | 1 | 0 | OMISSION 9, PASS 1 |
| act | Keep | 1 | 0 | OMISSION 2 |
| act | Wake | 1 | 0 | OMISSION 2 |
| survive | Drift | 1 | 0 | unknown 1 |
| survive | Recall | 1 | 0 | unknown 2 |
Regression corpus: FAIL 20

## What each system's results point to

These are measured behaviours under Ring 0's scripted conditions, with the evidence that produced them. Each finding below was traced to the cards and to the system's pinned source, and a second, independent check tried to refute it. Each one names any part that is inferred rather than observed.

### Hermes native
1. **Forgetting fails, and that one finding fails all 86 T0 gates.**
   - After `memory remove`, the entry leaves `MEMORY.md`, but the original message stays in Hermes's session database. The store scan still finds it there, and `session_search` returns it in the same session.
   - The run-level forgetting check fails, and it is copied onto every pack's gate. 75 of the 86 packs fail only because of it. The other 11 also fail their own forgetting check: 5 because the text is still in the store, and 6 because it still reaches the agent.
   - This behaviour is reported upstream as NousResearch/hermes-agent#145902, reproduced there on v0.22.5; v0.1 pins v0.22.2.
   - T1 does not exercise forgetting, so this is a T0 finding only.
2. **`session_search` returns nothing for a query that ends in a period.**
   - The cause, in pinned Hermes: its search sanitiser removes `?` but leaves a final `.`. SQLite's full-text search then rejects the query as a syntax error, and Hermes's error path returns an empty list before its relaxed retry.
   - Ring 0's scripted recall queries are sentences that end in a period. So `session_search` returned nothing for 137 of hermes-native's 151 T0 items; only the 14 queries ending in `?` reached it.
   - Hermes native's T0 results therefore mostly measure its frozen session-start snapshot of `MEMORY.md`. A replay that uses the snapshot alone reproduces the option the reader chose on all 130 T0 action items.
   - Its 26 Drift misses (8 FAIL_MEMORY, 18 OMISSION) are all in packs where the update is said in the probe session itself. The snapshot predates the update, and search finds nothing.
   - What this points to: a search that tolerates ordinary punctuation. Ring 0 reports it as measured; the live tiers write their own queries.
   - The card does not name the query's form as the cause. The next kit pairs each recall query with a twin that has no final punctuation, so a card can name it (#275).
3. **Over a long life, the memory file fills up (T1 Keep, −1000).**
   - Hermes's `MEMORY.md` has a 2,200-character limit, and writes past it are rejected.
   - The T1 life writes about 100 user turns. A replay of its writes fills the file by session 3, and the last stored entry is from session 7.
   - At the probe in session 20, the value said in session 14 is not in the snapshot. The agent acts on an early-session distractor instead: FAIL_MEMORY on both twins.
   - *Inferred* from that replay; T1 keeps no request bodies.
4. **T1 Recall, 500.** One item is correct, and one is unknown. Why the second one's search, which ends in `?`, did not return all three dates is not established.

### Holographic
1. **Wake is 0 at T0 and T1 (every Wake item an OMISSION).**
   - Wake items open a fresh session with a deliberately generic question that names nothing in the stored decision.
   - Holographic's keyword search and its prefetch return nothing for it. Its session-start block carries a fact count and usage tips, never fact content.
   - The decision is in Holographic's store, but it never reaches the agent.
   - What this points to: surfacing an open decision at session start without a matching query.
   - Ring 0's T0 plug-in host does not pass a plug-in's own system-prompt blocks to the reader. Holographic's session-start block holds no fact content, so this does not change its Wake result.
2. **Forgetting is INCONCLUSIVE, because of the store format.**
   - Both forgetting probes passed, and a byte search of the whole store found no forgotten text.
   - The store is a binary SQLite file, which the kit counts as opaque: a clean byte scan of such a file cannot prove the text is gone. Holographic's forget path, read in its source, erases the fact's versions, rebuilds its search indexes and vacuums the file.
   - A scan that reads SQLite files by their contents is planned for the next kit (#276).
3. **Everything else passes.** Drift, Keep and Recall all score 1000 at T0 and T1.

### The reference adapter (`reference_store`)
- Its lower Keep, Recall and Wake scores follow from its one-event retrieval rule. In every miss the evidence was still stored, but another event was returned. The same packs' oracle and full-history controls score 1000.
- Its gates pass, because T0 gates do not read item scores.
- No test pins its item outcomes yet, so a scoring change could move this row unnoticed. The next kit pins them (#277).
- One pack, `G2/Keep/keep-incidental@1/s3-d1-kill/1`, reads INV-VERB INCONCLUSIVE. Its fault-free twin failed both items, so the crash comparison had nothing informative to compare.

### Mem0 OSS
1. **Forgetting fails in the store, though the text never reaches the agent (T0).**
   - After `mem0_delete`, search no longer returns the forgotten text, and no forgetting probe found it in the agent's context. The store scan still finds it.
   - Mem0 keeps a history database, `.mem0/history.db` in the worker's sandbox home, inside its declared store. A memory's text stays there in the row for its original add, and again as the old value in the row for its delete. *Which file the scan matched is inferred from Mem0's pinned source: the kit records no hit paths, and work directories are deleted at the end of the run.*
   - As with Hermes native, the run-level forgetting check fails, and it is copied onto every pack's gate. 75 of the 86 packs fail only because of it. The other 11 also fail their own forgetting check, all because the text is still in the store: 5 Keep forget packs with one item each, and 6 Keep neighbour packs with two.
   - What this points to: a delete that also clears the history copy, or a documented way to purge it. An open Mem0 request, mem0ai/mem0#6512, describes the same retention after `delete_all` and asks for a switch that turns the history store off in the Python SDK.
   - T1 does not exercise forgetting, so this is a T0 finding only.
2. **Wake: 2 of 12 items pass at T0, and both passes come from store size.**
   - As for Holographic, Wake items open a fresh session with a generic question that names nothing in the stored decision. Mem0's session-start block carries no memory content, and its recall and its prefetch are similarity searches that return at most 10 memories.
   - The 2 passes are the two branches of the one 2-session pack. It holds exactly 10 memories, so the search returns all of them, the decision included.
   - The other 10 items are in 3-session packs of 15 memories, and the decision is not among the 10 returned. The question shares no words with any memory, so under Ring 0's similarity stand-in (E10) every memory scores about 0.5, and their order carries no meaning. In 4 of the 5 packs the decision scores lowest because of a collision in the stand-in's hashing; in the fifth it ties with every memory, and the vector store's tie-break leaves it out. These 10 omissions measure the stand-in, not a ranking choice by Mem0.
   - What this points to: as for Holographic, surfacing an open decision at session start without a matching query. Mem0 has no path that does this, so once a store holds more memories than its result limit, an open decision reaches the agent only by chance.
3. **Everything else passes at T0.** Drift, Keep and Recall all score 1000, and every adapter invariant except forgetting passes. These numbers cover what the agent writes explicitly with `mem0_add`, its storage, and recall ranked by the stand-in's similarity; automatic extraction is not exercised (E11).
4. **T1 Keep, −1000: Mem0 sends another place's gate code.**
   - The T1 Keep item mentions Place 1's gate code once, in passing, in session 14. Three other places' codes come up elsewhere in the life.
   - At session 20 the item asks the agent to send Place 1's courier the entry details. On both twins the agent sent Place 3's code, which was said in session 2: FAIL_MEMORY. The wiped control refrains on both twins.
   - **Why:** Mem0's recall and its prefetch each return at most 10 memories, ranked by similarity alone. The BM25 and entity boosts need packages that the locked install does not have.
   - *Inferred, and reproduced offline* under Ring 0's similarity stand-in (E10): Place 3's statement ranks 4th, on shared words ("is", "place", "the"), while Place 1's ranks 14th, outside the 10 returned. The reproduction assumes that Mem0 stored each message's text verbatim, which was not checked.
   - **What reached the agent** is worked out from the scripted reader's choice rule, because T1 keeps no request bodies. The card's stage attribution, `retrieved`, says only that the code is somewhere in the retained store, and for Mem0 that store includes Hermes's own session files. So it does not show that the code was in Mem0's vector store. The next kit records which surface held it (#294).
   - **Other systems:** Hermes native fails this item the same way (Hermes native, point 3). Holographic passes it, but Place 3's code was in its context too. It passed because the correct option is listed first and the reader takes the first option present. So this item does not yet test choosing between look-alike values once both are in context (#293).
   - What this points to: recall that ranks a stored value by what it is about, not by the common words it shares with the question.
5. **T1 Wake, 0: the open decision never reaches the agent.**
   - As at T0, the Wake item opens a session with a generic prompt, "Pick up where we left off in the repository.", that names nothing in the decision stated in session 3.
   - Both twins refrain: OMISSION, scored 0. The item carries a duty, so the card also counts each refrain as a harmful omission.
   - Under the stand-in, the decision's statement ranks 180th of 181, and the 10 memories returned win on common words (*inferred*, reproduced offline as above).
   - **Other systems:** Holographic fails the same way, and Hermes native passes both items. Hermes native's frozen `MEMORY.md` snapshot does not depend on the prompt, and it holds the early writes, this decision among them (Hermes native, point 3). That is *inferred*, not traced in its code.
   - What this points to: the same as point 2.
6. **Everything else passes at T1.** Drift and Recall score 1000, and the regression corpus passes all 20. The wiped control fails, as it must.

**To rerun one T0 pack:** `bicentennial t0 --system <system> --packs <installed T0 tier directory> --pack pack/<pack path> --pack-hash <T0 pack hash> --out <empty directory>`, with `PYTHONHASHSEED=0` and the pins in `RESULT-MANIFEST.json`. Repeat `--pack` to rerun several packs.

## How repeatable the runs were
- **T0:** reference_store's, hermes-native's and Holographic's two runs are byte-identical in every card, invariant, control, JUnit, adapter-invariant and relations file. Only the receipts differ, and only in volatile fields: load, ports, process ids, temporary paths and wall times.
  - **Mem0's two T0 runs are not (#287).** All 86 card pairs differ in one field, the masked ledger digest. Every score, verdict, invariant, JUnit result, control, adapter invariant and relation is identical, so the kit's acceptance reports `t0_identical` failing for Mem0 alone.
  - A matched diagnostic that kept the ledgers named the cause (#287, issuecomment-6518269939). Two back-to-back runs of two Mem0 packs reproduced the divergence. The only stable field that differs is `sim_now`, the director's arrival-time stamp, on Mem0's background embedding requests.
  - Those requests carry no turn cursor, so the director stamps them with its clock's reading when they arrive. The plug-in's background threads land them just before or just after the clock moves. Holding that stamp fixed makes the digests equal, and what Mem0 sent and received is the same in both runs.
  - The next kit drops the arrival stamp from the stable projection for requests without a turn cursor (#287).
- **T1:** every repeat has identical scores, verdicts, invariants, regression-corpus results, controls and JUnit files.
  - **Mem0:** its two repeats differ in the masked ledger digest on both arms (system and wiped), and its first repeat differs from its base run in the same way. Every score, verdict, invariant, regression-corpus result, control and JUnit test result is identical. The T1 ledgers were not kept, so the differing ledger field is not named. The likely cause is the arrival-time stamp on Mem0's background embedding requests that #287 found at T0, but that is not confirmed at T1.
  - **Holographic:** its first repeat, rerun last on a heavily loaded machine, differs from its base run in the system arm's masked ledger digest, and its second repeat differs from the first in both arms'. Every score, verdict, invariant, regression-corpus result, control and JUnit test result is identical. Its T1 ledgers were not kept, so the differing field is not named. The likely cause is the tool-order race found for Hermes native below (#71), which can reach any arm whose environment server starts slowly.
  - **Hermes native:** one field differs. Its second repeat ran on a busy machine, and its card's masked ledger digest differs from the first repeat's.
  - Hermes native's first run and first repeat agree, and its wiped control agrees in all three runs.
  - The wiped control ran under the same load in that repeat and still agreed, so load alone does not move every digest.
  - Why the system arm's digest moved is tracked in #71, and the kit's own acceptance check reports it. A diagnostic run with every path length matched reproduced base's and run1's cards exactly. Under v0.1's port mask, no assignment of run2's director ports reproduces run2's digest from the kept records. So the masking defect fixed in #283 does not explain the divergence: run2's stable content really differed (#71, issuecomment-6516846222).
  - A diagnostic rerun under load that kept the ledgers found the cause (#71, issuecomment-6532245614). In one G2 session of the system arm, Hermes offered the same 21 tools with its 5 built-ins first and the environment server's 16 tools last; every other session offered the pin's sorted order. At the pin, a session waits at most 1.5 s for its MCP servers before it builds the agent, and a server that connects later has its tools appended. A loaded machine can start the environment server slower than that. #287's rule does not explain it. The fix (#300, RING0 §13 E19) makes Hermes wait up to 60 s. Run2's own ledgers were not kept, so this is the cause reproduced under load, not read from run2.
  - T1 cards are therefore not byte-identical across repeats under load, even though no score or verdict changed.
- **One attempt was refused and rerun (#205).**
  - Holographic's first T1 repeat refused its isolation check (`upstream_record`) after 8,611 s. The v0.1 kit records no detail, so the endpoint that tripped it is not known.
  - The likely cause is a known false positive in the v0.1 sampler. `lsof` names a socket that exists but is not yet connected `*:*`, and v0.1's rule counts that as non-loopback. The next kit stops counting it (RING0 §13 E13).
  - Holographic's runtime code makes no network calls, and its first run passed.
  - As ruled on #205, v0.1 reruns any run refused this way. The repeat reported here is the rerun, and the refused attempt is kept in the evidence store. The rerun passed its isolation check and exited 0 after 12,871 s.
  - An independent observer, run outside the kit, sampled the process tree of Holographic's second repeat about once a second, from 11 minutes after it started until it ended (8,709 samples). It saw no row that v0.1's rule would count: no unconnected `*:*` socket and no other non-loopback endpoint. The same observer sampled the rerun of the first repeat (11,552 samples). It saw one unconnected TCP `*:*` row, from a Python process, and no other non-loopback endpoint. The rerun passed its isolation check, so the kit's own sampler did not record that row.

## Disclosures to read beside the numbers
- **Hermes native reads its session-start snapshot (E7, #185).** Pinned Hermes injects a frozen memory snapshot into the system prompt at session open. The memory-layer host renders it with Hermes's own code and gives it to the reader. Other harness prompt injection is not exercised.
- **The similarity stand-in (E10, #207).** Ring 0's embedding stand-in hashes words into a vector. Its similarity is lexical overlap, reported as (1 + c)/2. That is a declared convention, not a claim about any trained embedder.
  - It matters for Mem0 only, the one system that asks Ring 0 for embeddings.
  - Mem0's locked install adds no keyword score, so it ranks by similarity alone. Its hybrid ranking needs packages that are not installed.
  - On this scale a text with no word overlap scores about 0.5, so Mem0's 0.1 threshold removes almost nothing.
  - The earlier raw scale made that threshold drop later corrections in the T1 drift corpus cases (each scored 0.083–0.089). That was an artifact of the stand-in, not Mem0's behaviour.
- **Mem0's automatic extraction is not exercised (E11, #208).** Pinned Mem0 makes one extraction call that Ring 0's stand-in answers in a format Mem0 does not read, so Mem0 stores no extracted memories at Ring 0. Mem0's results cover the facts the agent writes explicitly (`mem0_add`, stored verbatim), their storage and their recall. They give Mem0 neither credit nor blame for extraction.
- **Plug-in dependencies (E9, #190, #210).**
  - Mem0 and Holographic each run on their own copy of pinned Hermes, with a hash-locked dependency set: Mem0's client and local vector store, and Holographic's numpy and snowballstemmer. Without numpy, Holographic turns off its vector recall, so its lock is what makes these results measure Holographic as its users install it.
  - A run refuses if a locked version is missing.
  - Every plug-in and real-worker run lists the worker's installed distributions and their digest. The reference adapter has no worker, so it lists none.
- **What T0 delivers of each event (#213).** T0's plug-in host writes each event's text through the system's own write tool. It does not deliver the speaker, and no v0.1 check asks who said something. The host would cut text to a write tool's declared maximum length, but none of the three systems' write tools declares one, so nothing was cut.
- **Holographic stores mixed dates (#270).**
  - The worker's Python clock runs on the life's simulated time, but SQLite's own clock stays real.
  - Holographic's facts take `created_at` and `updated_at` from SQLite (real dates), while its version history takes Python's clock (simulated dates).
  - v0.1's reader scores citations, not dates. Holographic's date-dependent features are not probed: search and list as of a date, version history, review and temporal decay (off by default).
  - Its two T0 runs were byte-identical, so the dates change no v0.1 result, but date-dependent behaviour is not measured.
- **Cards depend on the length of the output path (#282).** Each unit's sandbox root lies under the run's output path, and its length reaches stable fields: a citation offset in the card, the masked ledger digest and, in the wiped arm, the number of director requests. The v0.1 repeats used paths of equal length, so their comparison is unaffected. A reproduction at another path length will not match these cards' digests or citation offsets. In the one comparison made, a diagnostic run whose path was 37 characters shorter, every score and verdict still matched. Root lengths also differ inside this run's own layout: the system's name is in its output path (79, 77 and 74 characters for hermes-native, Holographic and Mem0) and the arm's name is in each unit's path, so each system and each arm saw a slightly different number of context bytes. v0.1 compares no systems, and every gate compares a system with its own baseline; the next kit gives the sandbox root a fixed text before any run that compares systems or arms (#282).
- **Lenient reader (RING0 §1).** When the current value and a stale or decoy value both reach the agent, the reader acts on the current one. A store that keeps stale values beside current ones loses nothing here. The share of items with a competing value present is printed per system and track. That share misses the Keep look-alike item, whose decoys are not declared as competing values, and there the reader passes whenever the true value is present, because it is listed first (#293). Supersession is judged by a model in the live tiers.
- **Loop time.** Each T1 run's wall time is in its receipt, and the manifest publishes the idle and busy maxima. The slowest T0 pack took 59.1 s idle and 202.5 s busy (target 60 s; 344 packs each), and the slowest T1 run 1.54 h idle (2 runs) and 3.66 h busy (7 runs), against a 10-minute target. All 106 misses are listed in the manifest; they are disclosed, not a bar (PREREG §8 bar 5).
  - A run counts as busy if any of its readings of the machine's release-gauntlet marker was nonzero, and as idle if every reading was 0. A nonzero reading means the machine was not idle (usually a gauntlet row; also an unreadable marker). The benchmark never sets the marker.
  - The designated quiet run was hermes-native's first repeat: 5,557 s, with the marker at 0 on all 266 readings. Its end-of-run load average was 5.85, 6.06 and 5.75 over 1, 5 and 15 minutes, on 14 cores.
  - hermes-native's second repeat was busy: 6,458 s, with the marker nonzero on 254 of its 266 readings. Its end-of-run load average was 4.33, 7.69 and 9.25.
  - The busy maximum mixes system speed with load. Holographic's slower runs, for example, also count as busy runs.
  - Where a T1 run's time goes is not yet measured. The runner collects per-session timings but does not write them out. A reading of the code points to the waits for in-flight work after each turn, and to repeated worker start-ups. Measuring this is the first developer-loop task for v0.2 (#267).

## What these results do not show
- They do not rank systems on real conversations. They show whether each system's plumbing holds under scripted, model-free conditions.
- They do not show extraction, summarisation or retrieval quality with a trained model.
- Ring 0's scripted queries are fixed sentences. A system's behaviour on other wordings, such as Hermes's search on queries that end in a period, can differ.
- T0 is reproducible byte for byte on the same machine with the same pins and output layout, except Mem0's ledger digest (#287). T1 reproduces every score and verdict, but not every ledger byte (#71), and its cards match only at the same output-path length (#282).
