# Reading T1's turn-wait results (#388)

This is the guide to v0.3's check of T1's wait after each scripted turn: can T1 wait 1 s instead of 3 s without changing what memory systems store or what the card says? The lines and tables are in `RESULT.md`, each printed from the runs' own files.

Claim class: an A/B of T1's wait after each turn at one commit on two dedicated Linux hosts, both idle, with a store check of every Hermes session. It is not a loaded or developer-machine measurement, it is not predictive of the full tier, and it never certifies.

## Why it is checked

After each ordinary scripted turn, T1 waits for the memory system's background work to finish before the next turn. At 3 s, these waits were 29-35% of each T1 run's critical path (430 waits per arm and life, 1,290-1,500 s of a 3,700-5,200 s run). A shorter wait makes the developer loop faster, but only if nothing a memory system writes depends on it. #388 set the bar before any run: at 1 s, the cards must be byte-equal, no receipt may record background work that outlasts the wait, and every session's store must be equal, apart from values that also differ between two runs at the same wait.

## What ran

- **Commit:** `e687fdb9d7782fc692df3d60d882ac2eb6e81026`, the commit of step 10's determinism check. **Pack:** T1 `475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7` in every run.
- **Systems:** the three reference systems (Hermes native, Holographic, Mem0 OSS), each as one chain; the three chains ran at once.
- **The A/B:** on the 16-vCPU host, idle. The 3 s set is step 10's idle run ([results](../2026-11-03-batch-determinism/RESULT.md)); the 1 s set ran next on the same host with `--turn-wait 1`. Each chain ran T1 twice, base and run1.
- **The store checks:** on the 12-vCPU host, idle, base runs only. The first check recorded each Hermes session's raw store hash. The corrected check recorded every store surface each system declares, per session, with run-specific values masked; it ran at 3 s, at 1 s, and at 3 s again.
- **Egress:** each host's allowlisting proxy is the only route out for the runs' user, and the runs ran with it unset. None of the 54 receipts records a failed egress sample: 12 in each A/B set and 6 in each of the five store-check runs.

## What the results show

- **Cards:** at 1 s, all 12 cards (three systems, base and run1, system and wiped-store arms) are byte-equal to those at 3 s.
- **Other run files:** every other file is equal too, apart from two kinds that record the wait: each JUnit file's `t1.turn_wait_s` property (equal once that property is masked) and each receipt, which also holds timings.
- **Background work:** no receipt, at either wait, records a background request that arrived after the wait following its turn.
- **Time:** each T1 run took 18-23% less wall time at 1 s: 829-856 s less for Hermes native and Holographic, 957-966 s less for Mem0 OSS. The waits after turns fell from 1,290 s to 438 s on Hermes native's critical path.
- **The first store check could not decide.** Its raw hash differed for every session, even between the two no-memory floors that ran the same life, branch and session in one run. A store's raw bytes hold run-specific values (Hermes session ids, clock times, the sandbox path), so a raw hash cannot compare two runs. The corrected check was declared on #388 before it ran.
- **The corrected store check passed.** At 1 s against 3 s, every strict item was equal: the same sessions (693 rows, 646 keys in each run), no store file changed after the adapter's own hash, the same files, tables and columns, and every table's row count. Masked digests differed in 18 items, and each of those 18 also differs between the two 3 s runs, so the bar excuses them as run-to-run variation. None was left unexcused. The cards of all three runs are equal.

So the default wait after an ordinary scripted turn becomes 1.0 s for T1 and T2-lite (RING0 §13 E35). Session ends, turns followed by a kill or a restart, and compaction turns keep 3.0 s. T0 has no scripted turns and keeps recording 3.0. T2 (`bicentennial t2`) keeps 3.0 s, because this check measured T1 lives. Comparing a new run with one made before this change needs `--turn-wait 3`.

## The 18 masked items that differ between runs at the same wait

Each item is a store surface whose masked digest differed between the two 3 s runs, and also at 1 s against 3 s. Row counts are strict, so none of them is a missing or extra row; they are values inside rows, or files whose content varies. The number of sessions each item touches varies from run to run.

1. **Hermes's `spawn-ledger.json`**, its record of the processes it started (322 sessions in the 3 s pair).
2. **Holographic's `memory_store.db`, table `meta`:** the table's rows and its `value` column (2 items, 194 sessions).
3. **Mem0's vector store (`qdrant/collection/mem0/storage.sqlite`), table `points`:** the table's rows and its `id` column, Mem0's randomly generated point ids (2 items, 194 sessions).
4. **Hermes's `state.db`, table `session_model_usage`:** the columns `billing_base_url`, `cost_source`, `cost_status`, `input_tokens`, `output_tokens`, `api_call_count`, `model` and `task`, its per-session accounting of model calls (8 items, 36-40 sessions).
5. **Hermes's `cache/local_endpoint_probes.json`**, its cache of local endpoint checks (32 sessions).
6. **Hermes's `state.db`, table `messages`:** the table's rows and its `display_identity` column (2 items, 17 sessions).
7. **Hermes's `state.db`, table `messages_fts_data`:** the full-text index's rows and its `block` column, the index's internal blocks (2 items, 17 sessions).

Within one run, the two twin no-memory floors also differ in 7 masked items (Hermes's tool-discovery cache, MCP schema cache and spawn ledger, its stored system prompts, and each session's system prompt hash), so some store values vary even between identical sessions of one run.

## What the numbers measure, and what they do not

- **"Byte-equal"** cards include the masked ledger digest, which changes if the masked content of any request or reply changes, if a scripted request is filed under another turn, or if another recorded field changes.
- **The store check** compares digests and counts only, never content. Its masking covers Hermes session ids, clock times, random UUIDs, the sandbox root and the director port.
- **The calibration** excuses an item only if it also differs between two runs at the same wait. An effect of the shorter wait confined to the values of those 18 items would not show here; row counts, files, tables, columns and every other masked digest would.
- **The limits:** one commit, three reference systems, two idle Linux hosts. A system whose background work runs longer, or a loaded machine, could need a longer wait; each receipt counts background requests that arrive after the wait, so such a run says so. The check does not cover T2, which keeps 3.0 s, or other systems. In both arms, T1's compile check waited 3.0 s, because at that commit it took the host's own default, so the check's own 1.0 s wait, the default after this change, was not measured. It compares tool results written during each turn, after each check session's full 3.0 s end wait, and a mismatch refuses the run.

## Files

`RESULT.md` holds the lines, tables and each card's sha256. The full run trees (cards, receipts, logs, load samples and the store checks' session rows) are in the benchmark's private evidence store, tags `bicentennial/kit-batch-determinism-20261103` (the A/B's 3 s set) and `bicentennial/t1-turn-wait-20261103` (every other set). Receipts are not published here because they hold machine-local fields.
