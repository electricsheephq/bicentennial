# Reading T1's determinism results on the v0.2 release commit

This is the guide to v0.2's T1 determinism check: the release's code commit, run on two hosts at once, one idle and one under load. Each host ran T1 twice for each of the three reference systems. The lines and tables are in `RESULT.md`, each printed from the runs' own files.

Claim class: a determinism check of T1 at one commit on two dedicated Linux hosts, one idle and one under induced load. It is not a measurement on a developer's machine, it is not predictive of the full tier, and it never certifies.

## Why it is checked

T1 is the CI smoke tier, and it is built to be deterministic: the same commit, pack and system give byte-identical cards, apart from the base run's gate verdict, which differs by design. v0.1's runs showed this on v0.1's kit. Since then, main has changed many files that T1 runs. Among them: T1's reader now names its turn and counts earlier answers by their content ([#371](https://github.com/electricsheephq/bicentennial/pull/371)); each probe item gets its own probe session ([#335](https://github.com/electricsheephq/bicentennial/pull/335)); the life runner and the director's compiler gained T2-lite's live path, which keeps T1's path by design; and the labels on item records and cards changed ([#375](https://github.com/electricsheephq/bicentennial/pull/375)), which moved T1's pack. So each release checks determinism again on its own code commit, with one host idle and one kept busy. The v0.2 row of `ROADMAP.md` asks for it: T1 stays deterministic on stable fields, checked by one A/A′ pair per reference system run in parallel.

## What ran

- **Commit:** `436750ecd900631e38fda99bc28cc6ee464b5f40`, the release's last code change. The `v0.2` tag differs from it only in results, docs and the README and roadmap.
- **Hosts:** two dedicated Linux bench hosts, with 16 and 12 vCPUs, each running nothing else. The kit and every worker ran at the lowest CPU and I/O priority.
  - **Idle host (16 vCPUs):** nothing else ran, and the kit's busy check read the host as idle at every reading.
  - **Loaded host (12 vCPUs):** one `yes` process per CPU at the runs' own priority, for the whole run, as in v0.1's busy run. The kit's busy check read the host as busy at every reading, and all 12 `yes` processes were still alive when the last chain ended.
- **Layout:** on each host, three chains at once, one per reference system (Hermes native, Holographic, Mem0 OSS). Each chain ran T1 twice, base and then run1, and the run script compared run1's cards with base's.
- **Pack:** both hosts built the same T1 pack, `278fb65a975ddfed8f75dde34e6fa9fcfc19ea3b205b408705c98e55900afa5c`.
- **Egress:** each host's allowlisting proxy is the only route out for the runs' user, and the runs ran with it unset. The proxies' logs show no connection during the runs, and the kit's egress sampler recorded no failed sample in any receipt.

## What the results show

- **Each host, run1 against base:** for every system, run1's cards equal base's, apart from the gate verdict, which differs by design. The run script's card comparison printed `same` for Hermes native, Holographic and Mem0 OSS, on the idle host and on the loaded host.
- **Idle against loaded:** all 12 cards are equal, and none of their commit pins differ.
- **Gates:** as designed in every run. The system arm reads CONFORMANCE_PASS on base and PASS on run1, the wiped-store control fails T1's gate in every run, and every run is COMPLETE.
- So T1 stays deterministic on stable fields on the release commit, idle and under load. This meets the last open condition in the v0.2 row of `ROADMAP.md`.

## What the numbers measure, and what they do not

- **"Same"** means byte-equal cards, apart from the base run's gate verdict (CONFORMANCE_PASS against run1's PASS). Each card includes the masked ledger digest, which changes if the masked content of any request or reply changes, if a scripted request is filed under another turn, or if another recorded field, such as a request's status, changes. So a change in what was sent or answered, including one caused by background work that outlasts the wait after a turn, would show as a difference. A background request's arrival time alone would not, because background requests carry no turn. The digest also covers the run lock, through two recorded fields (`lock_hash` and `attempt_id`). The lock holds the commit, the pack and the system's artifact, and no fact about the host, so runs at one commit on two hosts are comparable. Across two commits they are not, which is why the shorter-wait A/B could not decide ([#383](https://github.com/electricsheephq/bicentennial/pull/383)).
- **Idle against loaded** compares the two hosts' cards for every system, run and arm: 12 cards, with the commit pins compared as well.
- **Wall times** come from the receipts. They are T1's loop time on the release commit, idle and busy, which RING0 §6 asks to publish. Under load the runs take longer: each run took about 2.4 times as long on the loaded host (Hermes native 3,712-3,761 s idle against 8,980-8,991 s loaded, Holographic 3,768-3,800 s against 9,134-9,153 s, and Mem0 OSS 5,174-5,177 s against 12,246-12,346 s). That is the cost of a machine kept fully busy, not a developer-machine loop time, and the two hosts also differ in size, so not all of the difference is load. The idle host is the one that ran v0.2's loop-time measurement ([`2026-11-02-t1-loop-time`](../2026-11-02-t1-loop-time/READING.md)), and no change between that measurement's commit and this one touched the harness or its waits.
- **The limits:** two hosts and one load pattern, at one commit. The check does not show that every host or every kind of load gives the same cards. Pack hashes depend on the build host's SQLite version ([#327](https://github.com/electricsheephq/bicentennial/issues/327)), so other hosts can build another pack, and cards are references only for packs with the same hash.

## Files

`RESULT.md` holds the lines, tables and each card's and receipt's sha256. The full run trees (cards, receipts, logs and load samples) are in the benchmark's private evidence store, tag `bicentennial/t1-determinism-v02-20261102`.
