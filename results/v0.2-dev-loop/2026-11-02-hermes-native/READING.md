# Reading the v0.2 Developer loop results: T2-lite's first live runs, Hermes native

This is the guide to T2-lite's first two live runs, on Hermes native: run A and its repeat A′. The numbers are in `RESULT.md`, each with the file and field it comes from. The cards, the flip list and the receipts are in this folder.

Claim class: live acceptance of the T2-lite developer loop on one system (Hermes native) and one pinned model. It is not predictive of the full tier, and it never certifies.

## What T2-lite is

T2-lite is v0.2's developer loop ([#338](https://github.com/electricsheephq/bicentennial/issues/338), [developer guide](../../../docs/developers/t2lite.md)). It replays T1's two public lives, a software partner (G1) and a personal assistant (G2), each in two twin branches (B0 and B1). Only the probes go to a live model: `gpt-6.1-sol` at medium effort. Every other model call stays scripted, as at T1, so the store a system holds at each probe is the one T1 tests.

At each probe the agent answers from what its memory put in front of it. A no-memory floor answers the same probes with no memory. A developer runs their system once (A), repeats it unchanged (A′) to measure the noise, and then compares each change (B) with A. The flip list shows which items changed, and q₀ is the noise rate: the fraction of scored items whose outcome changed between two identical runs.

## What ran

- **System:** Hermes native, the built-in memory of the pinned Hermes harness (hermes-agent v0.22.2: the `memory` tool with `MEMORY.md`, plus `session_search`).
- **Kit:** benchmark commit `c9bf10b7f56b`, with T1 packs built and installed on the run's machine (pack hash in `RESULT.md`). Pack hashes depend on the build host's SQLite version ([#327](https://github.com/electricsheephq/bicentennial/issues/327)), so the same commit built on another machine can give another hash, and these cards are references only for packs with this hash.
- **Items:** 17 per run, from both lives' probes. Six are G2 actions, which T2-lite does not score live yet ([#358](https://github.com/electricsheephq/bicentennial/issues/358); live G2 action scoring is v0.3, [#118](https://github.com/electricsheephq/bicentennial/issues/118)). That leaves 11 scored items per run.
- **Runs:** A, then A′ with `--aa-of A --baseline A`. A′ reuses A's no-memory floor from the cache, so it sends only the system's probes.
- **Machine:** a 14-core macOS machine that also runs other work. "Loop time" below says what else ran during each run.

## The results

- **A and A′ gave the same outcome on every item.** The flip list has no rows, and q₀ is 0/11: none of the 11 items scored in both runs changed (`flips.json`: `counts`, `q0`).
- **One pair of runs is a small sample.** No change in 11 items is consistent with a true per-item change rate of up to about 24% (the 95% upper bound, if items change independently). More A/A′ pairs narrow it.
- **The outcomes, the same in both runs** (`card.json`: `items[].score_milli` and `items[].base_verdict`):
  - 6 items scored +1: three questions whose deciding fact had been through a crash, a compaction or a system swap before the question (stage `survive`), and three correct actions;
  - 4 items scored 0: one omission and three task failures unrelated to memory (`FAIL_TASK`);
  - 1 item scored −1: a wrong action driven by a false or stale memory (`FAIL_MEMORY`). That is the penalty the design gives a confident false memory.
- **The live model was the pinned one throughout.** Both cards record `gpt-6.1-sol` served as `gpt-6.1-sol`, and neither run recorded an identity drift.

## What the numbers measure, and what they do not

- Each score says whether the live model, given what Hermes native's memory surfaced at that probe, answered or acted correctly, in the fixed answer format. A failure class names a failure that is not the memory's: `FAIL_TASK`, a task failure unrelated to memory, scores 0.
- The flip list compares A′ with A. Every row in it is noise, because nothing changed between the runs. q₀ is that noise rate on this system and model.
- The runs check that the loop works end to end on a real system and a live model: the live sends, the floor cache, the flip list, q₀, and the numbers each run publishes.
- They do not rank systems, and they do not predict the full tier. The results never feed boards, gates, admission, rungs or the public regression corpus.

## Loop time, requests, holds, sends and spend

- **Loop time.** A took 89.5 min and A′ 72.2 min (`receipt.json`: wall times). A′ reused A's no-memory floor from the cache, so it ran only the system's four units: 90 live sends against A's 163, and 1,737 director requests against 1,958. Each system unit took 16-19 minutes (the sum of its sessions' wall times, `receipt.json`: `timings[].sessions[].wall`), and each of A's four floor units took 2-4 minutes.
- **Holds.** None in either run (0 waits, 0 ms held), and both runs ended normally (`closed`).
- **Spend** reads 0 because the run's stack uses zero-price accounting on a plan lane. That is how the cost is recorded, not a claim that the service is free.
- **Other work on the machine.** Each session that ran other work on this machine during the runs reported it, with times:
  - **During A** (05:54:48Z-07:24:22Z):
    - test runs by other projects, each one process at niceness 10 or 19 using about one core, from 05:52:56Z to 06:04:06Z and as short runs of seconds between 06:56Z and 07:09Z, and one single-process test run at normal priority from 07:09:13Z to 07:18:08Z;
    - an embedding measurement, one process at niceness 10 using about one core, from 05:56:52Z to 05:58:41Z and from 06:47:12Z to 06:55:58Z;
    - another project restarted a long-running agent service twice. The first attempt, 06:51:41Z-06:54:28Z, copied part of a 1.8 GB store and was stopped safely; a desktop app also started a service then, using about one core in bursts for about 20 s. The second, 07:02:59Z-07:04:02Z, copied about 1.8 GB and 5.7 GB of data, followed by a store capture at niceness 19 from 07:04:20Z to 07:05:06Z. These were mostly disk I/O for about a minute each, and a few cores for under a minute at each restart;
    - an hourly scheduled check from another project found a new version at 07:12:00Z and ran four short live agent sessions until 07:19:23Z, at normal priority and about 0.2-0.7 core. Its other hourly checks took seconds;
    - this benchmark's own focused tests, one process at niceness 19, from 07:20:26Z to 07:23:36Z;
    - reviews on remote models, which read local files only, and short git commands.
  - **During A′** (07:24:36Z-08:36:52Z):
    - this benchmark's own focused tests, one process at niceness 19 using about one core, from 07:24:18Z to 08:05:58Z, and short runs at 07:43:41Z-07:43:56Z, about 08:06:50Z-08:07:11Z and 08:10:11Z-08:13:31Z; two small pack builds of a few seconds each at about 07:42Z;
    - reviews on remote models that read local files and ran git commands only, from about 07:20Z, at about 07:31Z-07:40Z and at 07:50:14Z-07:57:42Z;
    - one hourly scheduled check at about 08:19Z, which took seconds.

  No other benchmark or measurement ran during A′. T2-lite's receipt records the load average at the end of each run (`load_milli`, the one-, five- and fifteen-minute load averages: about 5.1, 4.6 and 4.7 at A's end, and 3.6, 3.7 and 3.8 at A′'s, on 14 cores), but it takes no busy-marker readings, so its receipts do not say whether the machine was busy. This section does.
- **Why the runs take this long.** T2-lite runs its units one at a time: the floor's four (two lives × two branches), then the system's four. Each Hermes native system unit replays its branch's 20 sessions through the real harness before its probes, which took 16-19 minutes per unit here. T1's per-session costs are T2-lite's too ([#267](https://github.com/electricsheephq/bicentennial/issues/267)), so cutting them cuts both: the first cut, a 1 s wait instead of 3 s after each turn ([#377](https://github.com/electricsheephq/bicentennial/pull/377)), lands after these runs.

## Disclosures

- **G2 actions are not scored live.** Their rows carry no score, and the card lists their ids in `not_scored_live` (#358).
- **Flip rows.** `twin_flip` is filled on each flip row, and the match fields follow the scored envelope ([#372](https://github.com/electricsheephq/bicentennial/pull/372)).
- **The floor cache.** A′ reuses A's floor from a cache keyed on the pack, the model, the effort, the answer contract, the harness and the benchmark commit. In this kit the key does not include the served model's identity; [#374](https://github.com/electricsheephq/bicentennial/pull/374) adds that check after these runs.
- **These cards are references at this commit only.** A later kit that moves the packs refuses them as a baseline or A/A′ card: [#375](https://github.com/electricsheephq/bicentennial/pull/375), which lands after these runs, changes two card labels, so cards made before it no longer validate (`invalid_card:<side>`). To compare with these runs, check out this commit.
- **Probes can write memory.** Isolation is per checkpoint, not per question.
- **The window W = 16K is provisional.**
- **Receipts.** The receipts here drop three machine-local fields (`temporary_paths`, `process_ids` and `ports`). Every other field is as written. The full run trees are in the benchmark's private evidence store, tag `bicentennial/t2lite-l6b-20261102`.

## How to repeat these runs

Follow the [developer guide](../../../docs/developers/t2lite.md#run-it): build and install a T1 pack at the same commit, then run A and A′ with the commands in `RESULT.md`. You need your own login for the live model. A run on another machine or at another time can differ, which is what q₀ measures.
