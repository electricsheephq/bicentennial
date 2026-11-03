# Reading T1's determinism results after v0.3's kit batch

This is the guide to v0.3's kit-batch determinism check: T1 run on the code commit that ends the kit batch, on two hosts at once, one idle and one under load. Each host ran T1 twice for each of the three reference systems. The lines and tables are in `RESULT.md`, each printed from the runs' own files.

Claim class: a determinism check of T1 at one commit on two dedicated Linux hosts, one idle and one under induced load. It is not a measurement on a developer's machine, it is not predictive of the full tier, and it never certifies.

## Why it is checked

Several accepted fixes changed what the kit measures, and each one would have forced its own pack rebuild and determinism check. v0.3 landed them as one batch instead ([#389](https://github.com/electricsheephq/bicentennial/issues/389)), followed by one rebuild and one check. Among them: the pack builder now normalises SQLite's file header, so a pack's hash no longer depends on the SQLite version of the host that built it ([#412](https://github.com/electricsheephq/bicentennial/pull/412)); Mem0's scripted extraction reply has the format Mem0 expects ([#423](https://github.com/electricsheephq/bicentennial/pull/423)); each checkpoint settles once on the real store ([#427](https://github.com/electricsheephq/bicentennial/pull/427)); decoys are declared as competing values ([#424](https://github.com/electricsheephq/bicentennial/pull/424)); and each receipt records the wait after each turn, background work that outlasts it, and unit timing ([#426](https://github.com/electricsheephq/bicentennial/pull/426)). T1's pack moved with them, from v0.2's `278fb65a…` to `475a8403…`. #389 accepts the batch when the rebuilt packs' hashes are published and the determinism pair's cards are equal on every stable field on both hosts.

## What ran

- **Commit:** `e687fdb9d7782fc692df3d60d882ac2eb6e81026`, `main` after the batch's last pull request ([#436](https://github.com/electricsheephq/bicentennial/pull/436)).
- **Hosts:** the two dedicated Linux bench hosts used for v0.2's check, with 16 and 12 vCPUs, each running nothing else. The kit and every worker ran at the lowest CPU and I/O priority.
  - **Idle host (16 vCPUs):** nothing else ran, and the kit's busy check read the host as idle at every reading (3,090 readings across its 12 receipts).
  - **Loaded host (12 vCPUs):** one `yes` process per CPU at the runs' own priority, for the whole run, as in v0.2's check. The kit's busy check read the host as busy at every reading (3,090), and all 12 `yes` processes were still alive when the last chain ended.
- **Layout:** on each host, three chains at once, one per reference system (Hermes native, Holographic, Mem0 OSS). Each chain ran T1 twice, base and then run1, and the run script compared run1's cards with base's.
- **Pack:** both hosts built the same T1 pack, `475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7`.
- **The wait after each turn:** 3 s in every run, the kit's default at this commit.
- **Egress:** each host's allowlisting proxy is the only route out for the runs' user, and the runs ran with it unset. The proxies' logs show no connection during the runs, and no receipt records a failed egress sample.

## What the results show

- **Each host, run1 against base:** for every system, run1's cards equal base's, apart from the gate verdict, which differs by design. The run script's card comparison printed `same` for Hermes native, Holographic and Mem0 OSS, on the idle host and on the loaded host.
- **Idle against loaded:** all 12 cards are equal, and none of their commit pins differ.
- **Gates:** as designed in every run. The system arm reads CONFORMANCE_PASS on base and PASS on run1, the wiped-store control fails T1's gate in every run, and every run is COMPLETE.
- **Background work:** no receipt records a background request that arrived after the wait following its turn, on either host.
- So T1 stays deterministic on stable fields after the kit batch, on its rebuilt pack, idle and under load. This is the determinism half of #389's acceptance.

## What the numbers measure, and what they do not

- **"Same"** means byte-equal cards, apart from the base run's gate verdict (CONFORMANCE_PASS against run1's PASS). Each card includes the masked ledger digest, which changes if the masked content of any request or reply changes, if a scripted request is filed under another turn, or if another recorded field, such as a request's status, changes. The digest also covers the run lock, which holds the commit, the pack and the system's artifact and no fact about the host, so runs at one commit on two hosts are comparable.
- **Idle against loaded** compares the two hosts' cards for every system, run and arm: 12 cards, with the commit pins compared as well.
- **Wall times** come from the receipts. Each run took about 2.4 times as long on the loaded host (Hermes native 3,709-3,713 s idle against 8,911-8,915 s loaded, Holographic 3,775-3,776 s against 9,078-9,085 s, and Mem0 OSS 5,201-5,205 s against 12,283-12,372 s). That is the cost of a machine kept fully busy, not a developer-machine loop time, and the two hosts also differ in size, so not all of the difference is load. On the idle host the times are within 1.5% of v0.2's check, which used the same host and the same 3 s wait.
- **The limits:** two hosts and one load pattern, at one commit. The check does not show that every host or every kind of load gives the same cards, and it covers T1 only: T0's packs are checked by the T0 run on the same commit, reported on the batch's issues.

## Files

`RESULT.md` holds the lines, tables and each card's and receipt's sha256. The full run trees (cards, receipts, logs and load samples) are in the benchmark's private evidence store, tag `bicentennial/kit-batch-determinism-20261103`.
