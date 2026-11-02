# v0.2 Developer loop results

Each published T2-lite run pair has its own dated directory: `RESULT.md`, with every number printed from the runs' own files, a `READING.md` guide in plain words, both runs' cards and disclosures, A′'s flip list against A, and both receipts without their three machine-local fields. T2-lite results are developer signals: they are not predictive of the full tier, and they never certify ([developer guide](../../docs/developers/t2lite.md)).

| Runs | Code commit | System | Model | Items scored | q₀ (A/A′ noise rate) | Guide |
|---|---|---|---|---|---|---|
| 2026-11-02 | `c9bf10b7f56b` | Hermes native | `gpt-6.1-sol`, medium | 11 of 17 | 0/11 | [READING.md](2026-11-02-hermes-native/READING.md) |

## T1 loop time and determinism

Each T1 result has its own dated directory: `RESULT.md`, with every number printed from the runs' own files, and a `READING.md` guide in plain words. Cards and receipts are listed there by sha256; receipts are not published, because they hold machine-local fields, and the full run trees are in the benchmark's private evidence store, cited by tag. T1 results are developer signals: they are not predictive of the full tier, and they never certify.

| Runs | What | Code commits | Result | Guide |
|---|---|---|---|---|
| 2026-11-02 | T1's loop time per arm, with its breakdown, and the A/B of a shorter wait after each turn | `c9bf10b7f56b`, `047832c88603` | a T1 run takes 61-85 min on an idle bench host, against a 10 min budget; the shorter wait saved 19-24% but changed the masked ledger digest on all 12 cards, so it does not ship | [READING.md](2026-11-02-t1-loop-time/READING.md) |
