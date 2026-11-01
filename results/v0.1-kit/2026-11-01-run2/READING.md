# Reading the v0.1 Kit results: second official run

This is the guide to the results of the Bicentennial v0.1 Kit's second official run, on the v0.1 maintenance kit. The numbers are in `RESULT.md` and the machine-readable manifest. The first official run's results stay on main, in [`results/v0.1-kit/2026-10-30/`](https://github.com/electricsheephq/bicentennial/blob/main/results/v0.1-kit/2026-10-30/READING.md). This page covers six things:
- what changed since the first run;
- the acceptance verdict;
- what the numbers measure, and what they do not;
- what each system's results point to;
- how repeatable the runs were;
- what to keep in mind before comparing systems.

## What changed since the first run

The packs, the scoring rules and the acceptance checks did not change. The kit, the host and the busy measurement did.
- **The kit is the v0.1 maintenance kit** (`maint/v0.1`, commit `6a612d46e718`, #302). It carries four errata from the next kit, so that the second run can repeat byte for byte, and nothing else (RING0 §13):
  - **E15, the whole-number port mask (#278):** the director port is masked only as a whole number, never as part of a longer one.
  - **E17, arrival time outside the cursor (#287):** the masked ledger digest leaves out `sim_now` on requests without a turn cursor, such as Mem0's background embedding requests. The record keeps it.
  - **E19, the MCP discovery wait (#71):** whenever T1 configures MCP servers (G2's environment server), Hermes waits up to 60 s for them before it builds the agent, instead of the pin's 1.5 s. A life's harness record lists the setting under `config_deviations`.
  - **E13, unbound sockets on macOS (#205):** the egress sampler ignores an unconnected TCP or UDP socket named `*:*`, on macOS only. This run's host is Linux, so E13 changes nothing here.
  - E12, E14, E16 and E18 stay next-kit errata. None of the four carried errata adds a card field. The pre-registration changelog records them as a Ring 0 contract change with no PREREG version change: PREREG-v0.4 stays frozen.
- **The acceptance script is the same file.** `scripts/v01_acceptance.py` is byte-identical to the first run's, with the same 17 checks.
- **The packs are the same; their hashes are not.** Every item file is byte-identical to the first run's, and so is every world file apart from two SQLite version fields in its header, which depend on the build host (below). The controls pin moves with the projection code, so the pack hashes change: T0 `737625ebdbee50df990a7b7929fd57eca8a90cdd148c9c0c46aeaacf0d7c5b9d` and T1 `b2e233207ac54115a77d9c0280e3cdb0c809df31e27430a59b401beae1aa4c41`. The T0 hash also depends on the build host: a macOS build of the same pack code gives 392caba9…. The cause is in each world database's header, where SQLite writes its own version number and the change count it was written at: the macOS host links SQLite 3.54.1, and the Linux bench hosts link 3.53.1. With those two fields (8 bytes) zeroed, every file in the two trees hashes equal, so the world content is identical (#327). T1's hash also differs from the macOS build's ece52d64…, for the same reason: with those 8 bytes zeroed, all 49 of its files hash equal.
- **The host is an x86_64 Linux cloud host with 16 vCPUs (Ubuntu 24.04), dedicated to the benchmark:** nothing else was scheduled on it during the runs. The first run ran on a 14-core macOS machine that also ran other work.
  - All 17 runs ran one after another, in the official order, every process at the lowest CPU and I/O priority.
  - Setup fetched public inputs only, from GitHub and PyPI, through the host's allowlisting proxy, the only route out for the runs' user. The runs ran with the proxy unset, with no keys, and at $0.
- **Busy and idle are measured by design.** The first run took its busy measure from the machine's own release-gauntlet marker. This run induces the load: hermes-native's second T1 repeat ran with one CPU-bound process per CPU beside it, and the host's busy command read 10 only while that load ran. "Loop time" below gives the details.
- **Digests are not comparable across the two runs.** E15 and E17 change what the masked ledger digest covers, and the host and output paths differ too (#282). Compare the two runs' scores and verdicts, not their digests or card hashes.

## The acceptance verdict

The kit's acceptance script **rejected** this run. 1 of its 17 checks failed (`t1_identical`), with four failures: for each of Holographic and Mem0, the first repeat differs from the base run and the second repeat from the first. The other 16 held.
- The one failed check, `t1_identical`, failed on a single card field in two systems: the system arm's masked ledger digest, the fingerprint of the requests a run sent, differs between Holographic's base run and each of its repeats, and likewise for Mem0, while every item, score and run status matches, and so does every gate verdict apart from the base run's, which differs by design. A diagnostic on the same kit and packs (#328) traced the same field's differences, in its own two runs, to two mechanisms. This run kept no T1 ledgers, so its own differences are attributed to them, not measured. The second maintenance kit (#329) addresses both, and the third official run will show whether the repeats hold.
- The only difference that is by design is the T1 base run's gate. A base run has no baseline, so its gate is a conformance gate that records no baseline digest or regressions, while each repeat is gated against the base run's card. "How repeatable the runs were" below gives the details.
- So this run is not the `v0.1` release either. The `v0.1` tag waits for an accepted run of all 17 runs on one fixed commit (#29).
- The rehearsal for this run had already shown Holographic's and Mem0's T1 differences, and #328 measured both causes in its own runs on the same kit and packs. The second maintenance kit (#329) addresses both, and a two-run T1 pre-check on its candidate (`6c9362c`, which differs from the merged kit only in docs and a test) gave equal digests in both arms for both systems. A third official run on that kit started on 2026-11-01; its results will be published separately.
- The results are published anyway, because they still show which evidence each system stored, kept and put in front of the agent. The failures are findings in their own right.

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

All three systems completed both T0 runs and all three T1 runs (the base and two repeats), and the reference adapter completed both of its T0 runs. No run was refused or rerun.

**The reference adapter, `reference_store` (T0 only), is not a system under test.**
- It is the kit's own minimal implementation of the adapter contract: a verbatim event store whose query returns the event with the most word overlap, the newest on a tie. When that event is a quote or a hedge, the query also returns the same actor's best-matching earlier assertion on the same words.
- The kit builds its controls and fault mutants on it, uses it as the conformance reference, and uses it as the regression corpus's pass oracle.
- Its row shows that the pipeline works end to end. Its item scores are not a baseline to compare systems against.

**Controls** run beside every system:

| Control | Where | What it shows |
|---|---|---|
| No-memory floor | Cached per pack, at T0 and T1. T1 also runs a probe-only Hermes arm with memory off | What an agent gets with nothing stored. At T1 the probe-only arm is used only to check the wiped control. |
| Oracle evidence and full history | Cached per pack, at T0 and T1 | The ceiling: the evidence handed over directly. Full history is bounded by the context window; at T1 no item fits it. |
| Wiped-store control | T1: one per system | The same system with its store wiped before each probe. It **must fail**, and it did in every run. |
| Naive RAG | — | Not run in v0.1. |

LCM-X, the benchmark's sponsor, is not run by the benchmark. Its own maintainers run the public kit on equal terms (RING0 §12).

## How to read a result

**Gates are plumbing verdicts. They never rank or certify.**
- **A T0 gate fails** on any failing invariant, any item the system failed to run (SYSTEM_FAILURE), or a honeypot hit. Item scores never move a T0 gate.
  - The adapter-level invariants are checked once per run and copied onto every pack's gate. So one run-level failure fails every pack.
  - The reason appears in the run's `adapter_invariants.json`, not in the pack's own `invariants.json`.
- **A T1 gate** also checks conformance: the regression corpus of known-faulty stores, and the wiped control. It fails a restart-crossing bundle that scores below the system's own baseline card. The first run of a system reads CONFORMANCE_PASS; repeats read PASS.

**Scores are the card's own aggregates**, per stage and track: a twinned item pair counts at its lower score (twin-bundle minima) and an item with no twin at its own score, averaged per life. Items come in two kinds:
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

Each table also carries the four baselines (RING0 §6, PREREG §2), aggregated like its score. At T0 they are the pack cards' cached controls: the no-memory floor scores 0, and the oracle-evidence and full-history ceilings score 1000, on every pack. A T1 card keeps a control's value only for a pack with one track, so the T1 cards show null; the T1 rows give the two T1 packs' cached controls instead. These T1 values, and the count below, are carried from the first run's guide, since every T1 item file is unchanged. Full history has no result at T1: it is bounded by the context window, and no T1 item's history fits (0 of 9 items in G1, 0 of 8 in G2). Naive RAG is not run in v0.1.

### reference_store

**T0:** 86 cards; gates PASS 86.

| Stage | Track | Cards | Score (milli) | Items | No memory | Oracle evidence | Full history | Naive RAG |
|---|---|---|---|---|---|---|---|---|
| act | Drift | 42 | 1000 (mean) | PASS 84 | 0 | 1000 | 1000 | not run in v0.1 |
| act | Keep | 17 | 411 (mean) | FAIL_MEMORY 6, OMISSION 8, PASS 20 | 0 | 1000 | 1000 | not run in v0.1 |
| act | Wake | 6 | 333 (mean) | OMISSION 8, PASS 4 | 0 | 1000 | 1000 | not run in v0.1 |
| remember | Drift | 6 | 1000 (mean) | correct 6 | 0 | 1000 | 1000 | not run in v0.1 |
| remember | Recall | 12 | 666 (mean) | correct 10, wrong 2 | 0 | 1000 | 1000 | not run in v0.1 |
| survive | Drift | 1 | 1000 | correct 1 | 0 | 1000 | 1000 | not run in v0.1 |
| survive | Recall | 2 | 1000 (mean) | correct 2 | 0 | 1000 | 1000 | not run in v0.1 |
Adapter invariants: INV-VERB PASS, INV-NEW PASS, INV-PAIR PASS, INV-FORGET PASS
Pack invariants: INV-FORGET NOT_EXERCISED 75, INV-FORGET PASS 11, INV-NEW NOT_EXERCISED 79, INV-NEW PASS 7, INV-PAIR NOT_EXERCISED 86, INV-VERB INCONCLUSIVE 1, INV-VERB NOT_EXERCISED 79, INV-VERB PASS 6

### Hermes native

**T0:** 86 cards; gates FAIL 86.

| Stage | Track | Cards | Score (milli) | Items | No memory | Oracle evidence | Full history | Naive RAG |
|---|---|---|---|---|---|---|---|---|
| act | Drift | 42 | 571 (mean) | FAIL_MEMORY 8, OMISSION 18, PASS 58 | 0 | 1000 | 1000 | not run in v0.1 |
| act | Keep | 17 | 1000 (mean) | PASS 34 | 0 | 1000 | 1000 | not run in v0.1 |
| act | Wake | 6 | 1000 (mean) | PASS 12 | 0 | 1000 | 1000 | not run in v0.1 |
| remember | Drift | 6 | 1000 (mean) | correct 6 | 0 | 1000 | 1000 | not run in v0.1 |
| remember | Recall | 12 | 916 (mean) | correct 11, unknown 1 | 0 | 1000 | 1000 | not run in v0.1 |
| survive | Drift | 1 | 1000 | correct 1 | 0 | 1000 | 1000 | not run in v0.1 |
| survive | Recall | 2 | 1000 (mean) | correct 2 | 0 | 1000 | 1000 | not run in v0.1 |
Adapter invariants: INV-VERB PASS, INV-NEW PASS, INV-PAIR PASS, INV-FORGET FAIL
Pack invariants: INV-FORGET FAIL 11, INV-FORGET NOT_EXERCISED 75, INV-NEW NOT_EXERCISED 58, INV-NEW PASS 28, INV-PAIR NOT_EXERCISED 86, INV-VERB NOT_EXERCISED 79, INV-VERB PASS 7

**T1, system arm:** 1 card; gates PASS 1.

| Stage | Track | Cards | Score (milli) | Items | No memory | Oracle evidence | Full history | Naive RAG |
|---|---|---|---|---|---|---|---|---|
| act | Drift | 1 | 1000 | PASS 10 | 0 | 1000 | no result | not run in v0.1 |
| act | Keep | 1 | -1000 | FAIL_MEMORY 2 | 0 | 1000 | no result | not run in v0.1 |
| act | Wake | 1 | 1000 | PASS 2 | 0 | 1000 | no result | not run in v0.1 |
| survive | Drift | 1 | 1000 | correct 1 | 0 | 1000 | no result | not run in v0.1 |
| survive | Recall | 1 | 500 | correct 1, unknown 1 | 0 | 1000 | no result | not run in v0.1 |
Regression corpus: PASS 20

**T1, wiped arm:** 1 card; gates FAIL 1.

| Stage | Track | Cards | Score (milli) | Items | No memory | Oracle evidence | Full history | Naive RAG |
|---|---|---|---|---|---|---|---|---|
| act | Drift | 1 | 0 | OMISSION 9, PASS 1 | 0 | 1000 | no result | not run in v0.1 |
| act | Keep | 1 | 0 | OMISSION 2 | 0 | 1000 | no result | not run in v0.1 |
| act | Wake | 1 | 0 | OMISSION 2 | 0 | 1000 | no result | not run in v0.1 |
| survive | Drift | 1 | 0 | unknown 1 | 0 | 1000 | no result | not run in v0.1 |
| survive | Recall | 1 | 0 | unknown 2 | 0 | 1000 | no result | not run in v0.1 |
Regression corpus: FAIL 20

### Holographic

**T0:** 86 cards; gates PASS 86.

| Stage | Track | Cards | Score (milli) | Items | No memory | Oracle evidence | Full history | Naive RAG |
|---|---|---|---|---|---|---|---|---|
| act | Drift | 42 | 1000 (mean) | PASS 84 | 0 | 1000 | 1000 | not run in v0.1 |
| act | Keep | 17 | 1000 (mean) | PASS 34 | 0 | 1000 | 1000 | not run in v0.1 |
| act | Wake | 6 | 0 (mean) | OMISSION 12 | 0 | 1000 | 1000 | not run in v0.1 |
| remember | Drift | 6 | 1000 (mean) | correct 6 | 0 | 1000 | 1000 | not run in v0.1 |
| remember | Recall | 12 | 1000 (mean) | correct 12 | 0 | 1000 | 1000 | not run in v0.1 |
| survive | Drift | 1 | 1000 | correct 1 | 0 | 1000 | 1000 | not run in v0.1 |
| survive | Recall | 2 | 1000 (mean) | correct 2 | 0 | 1000 | 1000 | not run in v0.1 |
Adapter invariants: INV-VERB PASS, INV-NEW PASS, INV-PAIR PASS, INV-FORGET INCONCLUSIVE
Pack invariants: INV-FORGET INCONCLUSIVE 11, INV-FORGET NOT_EXERCISED 75, INV-NEW NOT_EXERCISED 58, INV-NEW PASS 28, INV-PAIR NOT_EXERCISED 86, INV-VERB NOT_EXERCISED 79, INV-VERB PASS 7

**T1, system arm:** 1 card; gates PASS 1.

| Stage | Track | Cards | Score (milli) | Items | No memory | Oracle evidence | Full history | Naive RAG |
|---|---|---|---|---|---|---|---|---|
| act | Drift | 1 | 1000 | PASS 10 | 0 | 1000 | no result | not run in v0.1 |
| act | Keep | 1 | 1000 | PASS 2 | 0 | 1000 | no result | not run in v0.1 |
| act | Wake | 1 | 0 | OMISSION 2 | 0 | 1000 | no result | not run in v0.1 |
| survive | Drift | 1 | 1000 | correct 1 | 0 | 1000 | no result | not run in v0.1 |
| survive | Recall | 1 | 1000 | correct 2 | 0 | 1000 | no result | not run in v0.1 |
Regression corpus: PASS 20

**T1, wiped arm:** 1 card; gates FAIL 1.

| Stage | Track | Cards | Score (milli) | Items | No memory | Oracle evidence | Full history | Naive RAG |
|---|---|---|---|---|---|---|---|---|
| act | Drift | 1 | 0 | OMISSION 9, PASS 1 | 0 | 1000 | no result | not run in v0.1 |
| act | Keep | 1 | 0 | OMISSION 2 | 0 | 1000 | no result | not run in v0.1 |
| act | Wake | 1 | 0 | OMISSION 2 | 0 | 1000 | no result | not run in v0.1 |
| survive | Drift | 1 | 0 | unknown 1 | 0 | 1000 | no result | not run in v0.1 |
| survive | Recall | 1 | 0 | unknown 2 | 0 | 1000 | no result | not run in v0.1 |
Regression corpus: FAIL 20

### Mem0 OSS

**T0:** 86 cards; gates FAIL 86.

| Stage | Track | Cards | Score (milli) | Items | No memory | Oracle evidence | Full history | Naive RAG |
|---|---|---|---|---|---|---|---|---|
| act | Drift | 42 | 1000 (mean) | PASS 84 | 0 | 1000 | 1000 | not run in v0.1 |
| act | Keep | 17 | 1000 (mean) | PASS 34 | 0 | 1000 | 1000 | not run in v0.1 |
| act | Wake | 6 | 166 (mean) | OMISSION 10, PASS 2 | 0 | 1000 | 1000 | not run in v0.1 |
| remember | Drift | 6 | 1000 (mean) | correct 6 | 0 | 1000 | 1000 | not run in v0.1 |
| remember | Recall | 12 | 1000 (mean) | correct 12 | 0 | 1000 | 1000 | not run in v0.1 |
| survive | Drift | 1 | 1000 | correct 1 | 0 | 1000 | 1000 | not run in v0.1 |
| survive | Recall | 2 | 1000 (mean) | correct 2 | 0 | 1000 | 1000 | not run in v0.1 |
Adapter invariants: INV-VERB PASS, INV-NEW PASS, INV-PAIR PASS, INV-FORGET FAIL
Pack invariants: INV-FORGET FAIL 11, INV-FORGET NOT_EXERCISED 75, INV-NEW NOT_EXERCISED 58, INV-NEW PASS 28, INV-PAIR NOT_EXERCISED 86, INV-VERB NOT_EXERCISED 79, INV-VERB PASS 7

**T1, system arm:** 1 card; gates PASS 1.

| Stage | Track | Cards | Score (milli) | Items | No memory | Oracle evidence | Full history | Naive RAG |
|---|---|---|---|---|---|---|---|---|
| act | Drift | 1 | 1000 | PASS 10 | 0 | 1000 | no result | not run in v0.1 |
| act | Keep | 1 | -1000 | FAIL_MEMORY 2 | 0 | 1000 | no result | not run in v0.1 |
| act | Wake | 1 | 0 | OMISSION 2 | 0 | 1000 | no result | not run in v0.1 |
| survive | Drift | 1 | 1000 | correct 1 | 0 | 1000 | no result | not run in v0.1 |
| survive | Recall | 1 | 1000 | correct 2 | 0 | 1000 | no result | not run in v0.1 |
Regression corpus: PASS 20

**T1, wiped arm:** 1 card; gates FAIL 1.

| Stage | Track | Cards | Score (milli) | Items | No memory | Oracle evidence | Full history | Naive RAG |
|---|---|---|---|---|---|---|---|---|
| act | Drift | 1 | 0 | OMISSION 9, PASS 1 | 0 | 1000 | no result | not run in v0.1 |
| act | Keep | 1 | 0 | OMISSION 2 | 0 | 1000 | no result | not run in v0.1 |
| act | Wake | 1 | 0 | OMISSION 2 | 0 | 1000 | no result | not run in v0.1 |
| survive | Drift | 1 | 0 | unknown 1 | 0 | 1000 | no result | not run in v0.1 |
| survive | Recall | 1 | 0 | unknown 2 | 0 | 1000 | no result | not run in v0.1 |
Regression corpus: FAIL 20

## What each system's results point to

These are measured behaviours under Ring 0's scripted conditions, with the evidence that produced them. Each finding below was traced to the cards and to the system's pinned source, and a second, independent check tried to refute it. Each one names any part that is inferred rather than observed.

This run reproduced every score, item verdict and invariant that the findings below rest on, so they carry over from the first run unchanged.

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
- Its lower Keep, Recall and Wake scores follow from its retrieval rule: one event, plus an earlier assertion only when that event is a quote or a hedge. In every miss the evidence was still stored, but another event was returned. The same packs' oracle and full-history controls score 1000.
- Its gates pass, because T0 gates do not read item scores.
- No test pins its item outcomes yet, so a scoring change could move this row unnoticed. The next kit pins them (#277).
- One pack, `G2/Keep/keep-incidental@1/s3-d1-kill/1`, reads INV-VERB INCONCLUSIVE. Its fault-free twin failed both items, so the crash comparison had nothing informative to compare.

### Mem0 OSS
1. **Forgetting fails in the store, though the text never reaches the agent (T0).**
   - After `mem0_delete`, search no longer returns the forgotten text, and no forgetting probe found it in the agent's context. The store scan still finds it.
   - Mem0 keeps a history database, `.mem0/history.db` in the worker's sandbox home, inside its declared store. A memory's text stays there in the row for its original add, and again as the old value in the row for its delete. The cards record no hit paths, so a diagnostic rerun of Mem0's T0, on this kit and these packs, logged them (#135). All 17 pack-level hits were in `history.db`. After the run-level check's forget, the text was in `history.db` and also in the local vector store's file, `qdrant/collection/mem0/storage.sqlite`, though Mem0 had confirmed the delete.
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
   - **Why:** Mem0's recall and its prefetch each return at most 10 memories, ranked by similarity alone. Its BM25 and entity boosts need fastembed and spaCy, which the plug-in does not declare, so the locked install (the plug-in's declared dependencies) has neither.
   - *Inferred, and reproduced offline* under Ring 0's similarity stand-in (E10): Place 3's statement ranks 4th, on shared words ("is", "place", "the"), while Place 1's ranks 14th, outside the 10 returned. The reproduction assumes that Mem0 stored each message's text verbatim, which was not checked.
   - As in point 2, that order is the stand-in's, not Mem0's under a trained embedding model. So this −1000 shows what a 10-memory similarity cut does under the stand-in, not a ranking choice by Mem0.
   - **What reached the agent** is worked out from the scripted reader's choice rule, because T1 keeps no request bodies. The card's stage attribution, `retrieved`, says only that the code is somewhere in the retained store, and for Mem0 that store includes Hermes's own session files. So it does not show that the code was in Mem0's vector store. The next kit records which surface held it (#294).
   - **Other systems:** Hermes native fails this item the same way (Hermes native, point 3). Holographic passes it, but Place 3's code was in its context too. It passed because the correct option is listed first and the reader takes the first option present. So this item does not yet test choosing between look-alike values once both are in context (#293).
   - What this points to: rerunning this item with a trained embedding model (the live tiers, v0.2) before reading it as Mem0's ranking.
5. **T1 Wake, 0: the open decision never reaches the agent.**
   - As at T0, the Wake item opens a session with a generic prompt, "Pick up where we left off in the repository.", that names nothing in the decision stated in session 3.
   - Both twins refrain: OMISSION, scored 0. The item carries a duty, so the card also counts each refrain as a harmful omission.
   - Under the stand-in, the decision's statement ranks 180th of 181, and the 10 memories returned win on common words (*inferred*, reproduced offline as above). As in point 2, that order is the stand-in's; what holds without it is that Mem0 has no path that surfaces an open decision without a matching query.
   - **Other systems:** Holographic fails the same way, and Hermes native passes both items. Hermes native's frozen `MEMORY.md` snapshot does not depend on the prompt, and it holds the early writes, this decision among them (Hermes native, point 3). That is *inferred*, not traced in its code.
   - What this points to: the same as point 2.
6. **Everything else passes at T1.** Drift and Recall score 1000, and the regression corpus passes all 20. The wiped control fails, as it must.

**To rerun one T0 pack:** `bicentennial t0 --system <system> --packs <installed T0 tier directory> --pack pack/<pack path> --pack-hash <T0 pack hash> --out <new path>`, with `PYTHONHASHSEED=0`, at the maintenance kit's commit. For the three systems under test, add `--hermes <Hermes checkout>`, and for Holographic and Mem0 also `--plugin-source <plug-in checkout>`, at the pins in `systems/registry/` at the kit's commit (Hermes v0.22.2; the Mem0 plug-in at `43849c6`; Holographic 0.13.0 at `a6d0093`). `--out` must not exist yet: the kit refuses an existing directory, even an empty one (`out_exists`). Repeat `--pack` to rerun several packs. The pack hash depends on the build host (see "What changed since the first run").

## How repeatable the runs were

- **What differs:** only Holographic's and Mem0's T1 system arms differ. For each of the two, the base run and both repeats each have a different masked ledger digest: the second repeat differs from the first (`t1_not_identical`), and the first from the base run (`t1_base_differs`). No other card field differs, apart from the base run's gate, by design, so every item verdict, score, gate verdict and run status is identical. Their wiped arms, all of Hermes native's T1 cards and every system's T0 runs are byte-identical across repeats. An independent comparison of each system's full repeat output trees found no other differing file, apart from the base run's gate, by design: between the base run and the first repeat, every system's system card and both arms' JUnit files record it. The run receipts differ only in fields that change on every run: timings, ports, process ids, temporary paths and load, and at T1 also the busy readings and the digest of the unmasked request bodies.
- **The first run's causes, one by one:**
  - Mem0's T0 runs (#287, E17): fixed: its two runs are byte-identical on all 86 cards.
  - hermes-native's busy T1 repeat (#71, E19): fixed: the busy repeat, under induced load on all 16 CPUs, is byte-identical to the first repeat in both arms.
- **Holographic's and Mem0's T1 repeats (#328).** In this run, Holographic: its base run and both repeats each have a different masked ledger digest in the system arm, and no other card field differs; its wiped arm repeated byte for byte. Mem0: the same: its base run and both repeats each have a different masked ledger digest in the system arm, and no other card field differs; its wiped arm repeated byte for byte. This run kept no T1 ledgers, so its differences are attributed, not measured: the diagnostic below, on the same kit and packs, traced every differing record to two mechanisms.
  - v0.1 does not keep T1 ledgers, so a card names a T1 difference only by its field. The causes come from a diagnostic on the same kit and packs: it started each system's two T1 runs together, kept every masked ledger record, and compared the two runs' records with reports that give field paths, shapes and counts, never text.
  - **Holographic (#270):** the wiped arm repeated, with all 1,667 records matched. In the system arm, 1,645 of 1,666 records matched. Each of the other 21 is a tool result that differs only in its facts' `created_at` and `updated_at` stamps: SQLite dates of the host's real day, one second apart. The worker's Python clock follows the life's simulated time, but SQLite's own clock stays real, and Holographic's facts take their dates from SQLite (see "Holographic stores mixed dates" below).
  - **Mem0:** the wiped arm repeated, with all 3,335 records matched. In the system arm, 3,302 of 3,334 records matched. The other 32, 16 replay turns and 16 tool results, differ in one kind of line only. Hermes saves an oversized memory recall to a spill file named after a random version-4 UUID written without hyphens, and replays the file's path with the turn. v0.1's `random-uuid` mask matches hyphenated UUIDs only, so the name stayed in the masked digest.
  - This kit already carries E17 and E19, so neither cause is the arrival stamp (#287) or the tool-order race (#71) that the first run's guide named as likely. The first run kept no T1 ledgers, so the causes of its Holographic and Mem0 differences are not established.
  - The second maintenance kit (#329) adds two errata: E18 makes SQLite's clock follow the simulated clock, and E21 masks the spill file's name. On that kit's candidate (`6c9362c`), a two-run T1 pre-check gave equal masked digests in both arms, for both systems; the third official run decides whether the repeats hold.
- **Isolation:** every run passed its isolation check. Outside the kit, the host let the runs' user reach loopback only, where the host's allow-listing proxy listens (127.0.0.1:8888). The runs had the proxy unset, and the proxy, which denies by default, logged no connection during them. No run was refused or rerun.

## Disclosures to read beside the numbers
- **The maintenance kit (RING0 §13 E13, E15, E17, E19; #302).** The second run's code commit is `maint/v0.1`, not the first run's db9c0c5 and not main. Main has moved on to next-kit and v0.2 work, including E12, E14, E16 and E18, none of which is in this run. The second maintenance kit (#329) adds E18 and E21, for the T1 differences #328 found. A card shows the errata only through its code commit; E19's setting is in each G2 life's harness record, which no card or receipt includes.
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
  - Its two T0 runs were byte-identical in this run too. At T1, though, the real dates reach the agent's requests. On this kit's rehearsal and in a diagnostic, they made Holographic's masked ledger digest differ between runs (#328; see "How repeatable the runs were"). Every score and verdict is identical across its repeats. Date-dependent behaviour is not measured.
  - The second maintenance kit's E18 makes SQLite's clock follow the simulated clock (#329). That kit is not this run's.
- **Cards depend on the length of the output path (#282).** Each unit's sandbox root lies under the run's output path, and its length reaches stable fields: a citation offset in the card, the masked ledger digest and, in the wiped arm, the number of director requests. This run's repeats used paths of equal length, so their comparison is unaffected. A reproduction at another path length will not match these cards' digests or citation offsets, and neither does the first run, whose host and paths differ. Root lengths also differ inside this run's own layout: the system's name is in its output path (71, 69 and 66 characters for hermes-native, Holographic and Mem0) and the arm's name is in each unit's path, so each system and each arm saw a slightly different number of context bytes. v0.1 compares no systems, and every gate compares a system with its own baseline. The maintenance kit does not carry the fix: the next kit gives the sandbox root a fixed text (#282, merged on main in #309).
- **Forgetting through the plug-in host (#135).** T0 sends each forget request for Mem0 and Holographic through the plug-in host. For each forgotten event, the host searches the system's store for the event's text and decides each returned row by its text:
  - a row whose text equals a forgotten event's text is deleted, even when a kept event has the same text;
  - a row whose text equals only kept events' texts is kept;
  - any other row is decided by containment. It is deleted when the events whose texts it contains, or is contained in, are all forgotten. When they include a forgotten and a kept event, the host keeps the row and counts it (`forget_ambiguous`). When they are all kept, or there are none, the row is kept and not counted.

  v0.1's cards record neither the count nor the host's searches. A diagnostic rerun of both plug-in systems' T0, on this kit and these packs, logged them (#135). The count stayed 0 for both systems, in the run-level check and in all 17 pack-level forgets. In the run-level check, the host's search returned the row holding the forgotten text and the host deleted it, so the host kept no row holding the text:
  - **Mem0:** Mem0 confirmed the delete, but the text stayed in its own files, `.mem0/history.db` and `qdrant/collection/mem0/storage.sqlite`. Its `INV-FORGET` failure is the store's own retention, not the host's.
  - **Holographic:** the removal succeeded, and a byte scan of the checkpoint after the forget found no copy of the text. `INV-FORGET` stays INCONCLUSIVE, as in the official runs, because the store scan cannot read one of the store's files (`opaque_store`).
- **Lenient reader (RING0 §1).** When the current value and a stale or decoy value both reach the agent, the reader acts on the current one. A store that keeps stale values beside current ones loses nothing here. The share of items with a competing value present is printed per system and track. That share misses the Keep look-alike item, whose decoys are not declared as competing values, and there the reader passes whenever the true value is present, because it is listed first (#293). Supersession is judged by a model in the live tiers.
- **Loop time.** Each T1 run's wall time is in its receipt, and the manifest publishes the idle and busy maxima. The slowest T0 pack took 91.9 s idle (target 60 s; 688 packs). T0 was not measured busy: no T0 run ran under load, and the manifest says so (`kit.busy.T0`). The slowest T1 run took 1.41 h idle (8 runs) and 2.46 h busy (1 run), against a 10-minute target. All 19 misses are listed in the manifest; they are disclosed, not a bar (PREREG §8 bar 5).
  - A run counts as busy if any of its readings of the host's busy command was nonzero, and as idle if every reading was 0. On this host the busy command reads 10 only while the induced load runs, and 0 otherwise; nothing else sets it, and it never reads 11. All three systems are registered as light, so the kit's machine guard admits them at either reading.
  - The load is one CPU-bound process per CPU (16 in all), at the runs' own lowest priority, in a process group of its own. It ran for the whole of hermes-native's second T1 repeat, the designated busy run, and the run would not have counted unless every load process was still running when it ended. Load averages were sampled every 15 s.
  - The designated busy run, hermes-native's second repeat: 2.46 h (8,867 s), against 1.02 h for the quiet run. Every reading of the host's busy command read busy (266 in the system arm, 249 in the wiped arm), and all 16 load processes were alive when it ended. Over its 591 load samples, the one-minute load average rose from 1.0 at the start; across all of them its median was 16.4 (5th percentile 11.4, highest 17.3).
  - The designated quiet run, hermes-native's first repeat, started and ended with no load process running: 1.02 h (3,669 s). Every reading of the host's busy command read 0 (266 in the system arm, 249 in the wiped arm), and its receipt records load averages of 1.00, 0.93 and 0.82 (over 1, 5 and 15 minutes).
  - The load competes with the run as an equal, at the same priority. It does not model a machine whose other work has priority, or a memory- or disk-bound load.
  - The busy maximum is one run, so it is hermes-native's speed under this load, not a maximum across systems.
  - These loop times are not comparable with the first run's: the host, its CPU count and the load all differ.
  - Where a T1 run's time goes is not yet measured. The runner collects per-session timings but does not write them out. A reading of the code points to the waits for in-flight work after each turn, and to repeated worker start-ups. Measuring this is the first developer-loop task for v0.2 (#267).

## What these results do not show
- They do not rank systems on real conversations. They show whether each system's plumbing holds under scripted, model-free conditions.
- They do not show extraction, summarisation or retrieval quality with a trained model.
- Ring 0's scripted queries are fixed sentences. A system's behaviour on other wordings, such as Hermes's search on queries that end in a period, can differ.
- The repeats that held are shown on this host, with these pins and this output layout, and with one T1 repeat, hermes-native's, under induced load; other hosts and loads are not shown. Holographic's and Mem0's T1 masked ledger digests did not repeat; the cause is attributed from a diagnostic on the same kit and packs (#328), not measured in this run. Cards match only at the same output-path length (#282).
