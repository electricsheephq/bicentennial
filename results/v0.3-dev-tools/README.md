# v0.3 Developer tools results

Each result has its own dated directory: `RESULT.md`, with every number printed from the runs' own files, and a `READING.md` guide in plain words. Cards and receipts are listed there by sha256; receipts are not published, because they hold machine-local fields, and the full run trees are in the benchmark's private evidence store, cited by tag. These results are developer signals: they are not predictive of the full tier, and they never certify.

| Runs | What | Code commit | Result | Guide |
|---|---|---|---|---|
| 2026-11-03 | T1's determinism after the kit batch ([#389](https://github.com/electricsheephq/bicentennial/issues/389)), on its rebuilt pack, on two hosts at once, one idle and one under load | `e687fdb9d778` | on each host, every reference system's repeat run gave the same cards, and the two hosts' 12 cards are equal; no receipt records late background work; on the loaded host, which is also smaller (12 vCPUs against 16), each run took about 2.4 times as long | [READING.md](2026-11-03-batch-determinism/READING.md) |
