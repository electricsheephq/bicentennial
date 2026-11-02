# Bicentennial v0.2 Developer loop: T1's loop time, and the A/B of a shorter wait

Claim class: timing measurement of T1 on one dedicated Linux host, idle, at two commits, with a same-host card-equivalence check of the second; not a loaded or developer-machine measurement; not predictive of the full tier; never certifies.

- Measurement: main at `c9bf10b7f56b0727fc4f018d664f364886c4db39`. A/B: `047832c88603372367dfb451da4a7297afa50fc4` ([#377](https://github.com/electricsheephq/bicentennial/pull/377), now a draft), which waits 1 s instead of 3 s after each ordinary turn. Both on the same host, idle.
- T1 pack hash: `094e751299fc2fbf76b2c2a541297204980c5f9d1c87893c2bb4e8155c44a17a` (measurement), `094e751299fc2fbf76b2c2a541297204980c5f9d1c87893c2bb4e8155c44a17a` (A/B).
- Each set ran three chains at once, one per reference system; each chain ran T1 twice (base, then run1), and the kit compared run1's cards with base's.
- Full run trees (cards, receipts, logs and load samples): the private evidence store, tag `bicentennial/t1-loop-time-20261102`. Receipts are not published here: they hold machine-local fields.

## Each set's verdict lines

Printed from each set's own log: the pack it built, the kit's run1-against-base comparison per system (`same` allows only the gate verdict, which differs by design: base is CONFORMANCE_PASS and run1 PASS), and the run's end.

Measurement:

```
2026-11-02T04:11:18Z pack T1=094e751299fc2fbf76b2c2a541297204980c5f9d1c87893c2bb4e8155c44a17a
2026-11-02T07:00:58Z determinism hermes-native: same
2026-11-02T07:00:58Z determinism holographic: same
2026-11-02T07:00:58Z determinism mem0-oss: same
2026-11-02T07:00:58Z done t1main: runs_ok=1; T1=094e751299fc2fbf76b2c2a541297204980c5f9d1c87893c2bb4e8155c44a17a; packing receipts, cards, log and load
```

A/B:

```
2026-11-02T08:19:33Z pack T1=094e751299fc2fbf76b2c2a541297204980c5f9d1c87893c2bb4e8155c44a17a
2026-11-02T10:37:01Z determinism hermes-native: same
2026-11-02T10:37:01Z determinism holographic: same
2026-11-02T10:37:01Z determinism mem0-oss: same
2026-11-02T10:37:01Z done t1drain2: runs_ok=1; T1=094e751299fc2fbf76b2c2a541297204980c5f9d1c87893c2bb4e8155c44a17a; packing receipts, cards, log and load
```

## Loop time

Every number below is printed by `t1loop_numbers.py` from the runs' own receipts, with the field it comes from.

### Per run

| Code | System | Run | W | No-memory arm | System arm | Wiped arm | Outside the arms |
|---|---|---|---|---|---|---|---|
| c9bf10b | hermes-native | base | 3,664 s | 122 s | 1,287 s | 1,291 s | 965 s (26%) |
| c9bf10b | hermes-native | run1 | 3,670 s | 122 s | 1,291 s | 1,293 s | 964 s (26%) |
| c9bf10b | holographic | base | 3,728 s | 121 s | 1,298 s | 1,302 s | 1,006 s (27%) |
| c9bf10b | holographic | run1 | 3,724 s | 122 s | 1,300 s | 1,303 s | 999 s (27%) |
| c9bf10b | mem0-oss | base | 5,082 s | 123 s | 1,492 s | 1,498 s | 1,969 s (39%) |
| c9bf10b | mem0-oss | run1 | 5,095 s | 122 s | 1,501 s | 1,500 s | 1,972 s (39%) |
| 047832c | hermes-native | base | 2,815 s | 105 s | 886 s | 899 s | 925 s (33%) |
| 047832c | hermes-native | run1 | 2,794 s | 105 s | 878 s | 890 s | 920 s (33%) |
| 047832c | holographic | base | 2,862 s | 104 s | 902 s | 904 s | 952 s (33%) |
| 047832c | holographic | run1 | 2,849 s | 103 s | 897 s | 895 s | 953 s (33%) |
| 047832c | mem0-oss | base | 4,139 s | 106 s | 1,042 s | 1,050 s | 1,941 s (47%) |
| 047832c | mem0-oss | run1 | 4,106 s | 105 s | 1,033 s | 1,045 s | 1,923 s (47%) |

Source: each run's system and wiped receipt.json: wall_end_ms − wall_start_ms, and timings[] (pin_check_ms, sessions[].wall), slower branch per arm and life.

### Critical path (per arm and life, the slower branch; summed)

| Code | System | Run | Waits after turns | Waits at session ends | Turns | Opening sessions | Spawn and import | Close | Pin checks, gates, resume, workspace |
|---|---|---|---|---|---|---|---|---|---|
| c9bf10b | hermes-native | base | 1,290 s (35%; 430 waits) | 330 s (9%; 110) | 549 s | 375 s | 71 s | 75 s | 27 s |
| c9bf10b | hermes-native | run1 | 1,290 s (35%; 430 waits) | 330 s (9%; 110) | 550 s | 379 s | 72 s | 76 s | 27 s |
| c9bf10b | holographic | base | 1,290 s (35%; 430 waits) | 330 s (9%; 110) | 552 s | 385 s | 72 s | 81 s | 28 s |
| c9bf10b | holographic | run1 | 1,290 s (35%; 430 waits) | 330 s (9%; 110) | 553 s | 386 s | 72 s | 81 s | 29 s |
| c9bf10b | mem0-oss | base | 1,500 s (30%; 430 waits) | 330 s (6%; 110) | 581 s | 511 s | 72 s | 106 s | 34 s |
| c9bf10b | mem0-oss | run1 | 1,500 s (29%; 430 waits) | 330 s (6%; 110) | 584 s | 518 s | 73 s | 109 s | 33 s |
| 047832c | hermes-native | base | 438 s (16%; 430 waits) | 330 s (12%; 110) | 554 s | 397 s | 76 s | 85 s | 29 s |
| 047832c | hermes-native | run1 | 438 s (16%; 430 waits) | 330 s (12%; 110) | 552 s | 388 s | 74 s | 81 s | 28 s |
| 047832c | holographic | base | 438 s (15%; 430 waits) | 330 s (12%; 110) | 561 s | 406 s | 75 s | 88 s | 30 s |
| 047832c | holographic | run1 | 438 s (15%; 430 waits) | 330 s (12%; 110) | 560 s | 397 s | 74 s | 84 s | 30 s |
| 047832c | mem0-oss | base | 544 s (13%; 430 waits) | 330 s (8%; 110) | 589 s | 536 s | 75 s | 113 s | 35 s |
| 047832c | mem0-oss | run1 | 544 s (13%; 430 waits) | 330 s (8%; 110) | 588 s | 530 s | 74 s | 105 s | 34 s |

Source: receipt.json timings[].sessions[]: drain (the last entry is the session-end wait), turn, open, spawn (which includes import), close, and the remaining timers. Overlapping timers are not added to each other.

### 047832c against c9bf10b

| System | Run | W before | W after | Saved |
|---|---|---|---|---|
| hermes-native | base | 3,664 s | 2,815 s | 849 s (23%) |
| hermes-native | run1 | 3,670 s | 2,794 s | 876 s (24%) |
| holographic | base | 3,728 s | 2,862 s | 865 s (23%) |
| holographic | run1 | 3,724 s | 2,849 s | 875 s (23%) |
| mem0-oss | base | 5,082 s | 4,139 s | 942 s (19%) |
| mem0-oss | run1 | 5,095 s | 4,106 s | 990 s (19%) |

## The A/B against the measurement, card by card

Printed by `compare-cards.py`, which removes the four commit pins, says which of them differ, and prints only the JSON paths that differ, never values. The A/B's bar was 12 of 12 cards equal.

```
hermes-native/t1/base/system/card.json: differs (commit pins that differ: benchmark_commit, director_commit, generator_commit, scorer_commit)
  card.masked_ledger_digest
hermes-native/t1/base/wiped/card.json: differs (commit pins that differ: benchmark_commit, director_commit, generator_commit, scorer_commit)
  card.masked_ledger_digest
hermes-native/t1/run1/system/card.json: differs (commit pins that differ: benchmark_commit, director_commit, generator_commit, scorer_commit)
  card.masked_ledger_digest
hermes-native/t1/run1/wiped/card.json: differs (commit pins that differ: benchmark_commit, director_commit, generator_commit, scorer_commit)
  card.masked_ledger_digest
holographic/t1/base/system/card.json: differs (commit pins that differ: benchmark_commit, director_commit, generator_commit, scorer_commit)
  card.masked_ledger_digest
holographic/t1/base/wiped/card.json: differs (commit pins that differ: benchmark_commit, director_commit, generator_commit, scorer_commit)
  card.masked_ledger_digest
holographic/t1/run1/system/card.json: differs (commit pins that differ: benchmark_commit, director_commit, generator_commit, scorer_commit)
  card.masked_ledger_digest
holographic/t1/run1/wiped/card.json: differs (commit pins that differ: benchmark_commit, director_commit, generator_commit, scorer_commit)
  card.masked_ledger_digest
mem0-oss/t1/base/system/card.json: differs (commit pins that differ: benchmark_commit, director_commit, generator_commit, scorer_commit)
  card.masked_ledger_digest
mem0-oss/t1/base/wiped/card.json: differs (commit pins that differ: benchmark_commit, director_commit, generator_commit, scorer_commit)
  card.masked_ledger_digest
mem0-oss/t1/run1/system/card.json: differs (commit pins that differ: benchmark_commit, director_commit, generator_commit, scorer_commit)
  card.masked_ledger_digest
mem0-oss/t1/run1/wiped/card.json: differs (commit pins that differ: benchmark_commit, director_commit, generator_commit, scorer_commit)
  card.masked_ledger_digest
0 of 12 cards equal apart from the commit pins
exit 1
```

## Files

| Set | Run | Arm | card.json sha256 | receipt.json sha256 |
|---|---|---|---|---|
| measurement | hermes-native/base | system | `c64e8ae2cf9ed52a4d76e4be391e1d6eb9bad05daaa1bbbf25c9e906c9bb8b4e` | `3bcb497b63290f98e47b373404d8badebb2c5c5af25d0bf7b2c1e86248bd20f7` |
| measurement | hermes-native/base | wiped | `d78548968c8e208b291e13c8c5bd03cb9daa9f5d7712f0143cbaa3f82ea9e599` | `087715001dc962689f4af78171a0626be774a352cc06983d30dd5e52b01ef150` |
| measurement | hermes-native/run1 | system | `c21e99359ba10b2337fa9c6e386608ebf90c5837a3e6db64045ed7a88c264b7b` | `e074c26fc34cbfa93b3af23cfc21b69c10f19e212ec625845c8f3b5cea1ecb02` |
| measurement | hermes-native/run1 | wiped | `d78548968c8e208b291e13c8c5bd03cb9daa9f5d7712f0143cbaa3f82ea9e599` | `ab5c61aa66fe35a5481f444e5a15dd9c35d518b1b04c5c86cd8d188681e5eaf3` |
| measurement | holographic/base | system | `d29c91c58a1827dfaaecfac56b7195ef786b46748705293f8f7245d994efbe39` | `4f5d937f036008e878b00d51b215e5de17e70bb5582a077bccc6894f8d8cc4fa` |
| measurement | holographic/base | wiped | `b1f6be89a82e375d3386e1de2bc6cae51a4ae295be3d5fb5796da219b1d71ba5` | `4e186193e1ae368f22f325b2082800d73f97da47edb2adacf9b5d67c51345b82` |
| measurement | holographic/run1 | system | `7ea8ee487fe2658719a28e7824e9f1901150eb658c8c0c19dc5e13ed55f6ad9e` | `a7792fb96962e8be28f55e71823ef5941d040234c8689499b4549f9bffb45735` |
| measurement | holographic/run1 | wiped | `b1f6be89a82e375d3386e1de2bc6cae51a4ae295be3d5fb5796da219b1d71ba5` | `ee72fefb5824156df6e87bbdb182ad63e35251c8239f21b2fa67872412bed672` |
| measurement | mem0-oss/base | system | `abdec0b3996f3d74d559dfa53a9b5d4bcf4f90019fa2cf0099fba2052397ff70` | `9ab51c56a891f79b0d57a803df3b33143f168594c4076f954e1bbff6d288927c` |
| measurement | mem0-oss/base | wiped | `a780a97ac8f09dd045614f0668c6a650b6535a3b36a7bbc24e52284830b5fe4b` | `8a5b7102ae716a0ac7ec1cde17a99a6807041e1ddbbf4c38e63cdfca168e7a9c` |
| measurement | mem0-oss/run1 | system | `a763b12cd4e9238bea26d844e43c7e5ed20812e7b166258a7301cde62e6379c7` | `0934eb3c64e8de2bb8525c0473f99ff0fba5c2b0000f4cc307fa24c7d51f4601` |
| measurement | mem0-oss/run1 | wiped | `a780a97ac8f09dd045614f0668c6a650b6535a3b36a7bbc24e52284830b5fe4b` | `eefc452e98514b1757caf7f877b4fcce9b1cd2cbaab78df2babea0d9e8284372` |
| A/B | hermes-native/base | system | `ee8ba49b21131776f83a8a9fd09deeebc6651b44eb1f3b8ae07211d27c658460` | `3956384bc55aaccf6aa0763abeca1d012e561409a23702be5880b0b1a01a68e5` |
| A/B | hermes-native/base | wiped | `eebfa9e2a34c667b4c7681b32a0593ceb79bbe64b873ff00cf75a637bdd8cfc4` | `a3fba3102355023986827bd054c86a4c6d45cd7afd5671712ac1eaaa374444c1` |
| A/B | hermes-native/run1 | system | `ce7a665568c16e80c01023443120580031308712acbc253f09dc56fcbf427489` | `d228f1266a8a8ccb0c066b2310f7784f0c5d5ca63cedd1a476dd035c7d8d2657` |
| A/B | hermes-native/run1 | wiped | `eebfa9e2a34c667b4c7681b32a0593ceb79bbe64b873ff00cf75a637bdd8cfc4` | `fccc8b3f8d174136d97e5edf2f746b9f8c10596c0c187a9ecf73961bb94e70e0` |
| A/B | holographic/base | system | `f3688e14d0dd236be1c55836f9b145a30fee7b9acc6b6d6a0a3d9591b8e37dc3` | `df76ae05bd2cddf8ff6a1e3fa620c59200f3b6fcde1be9829220f7f8baaf04f6` |
| A/B | holographic/base | wiped | `6ac78f3dffe815a01393c8b86a3e7064b2565066f79648f2e63e4a4eb5f335fc` | `9907ae0fc4ff9ed2741b53a8557c1d54c36a04bfe8ca88f8a1be07a40cf67072` |
| A/B | holographic/run1 | system | `33b092471f90575fd6a8dec8ee18942e75b973b6c12f5b7370046813e12011ac` | `bceece7ef4bd1065cd031b06a2995adb838d86777dad59416c006bb4ba4d4881` |
| A/B | holographic/run1 | wiped | `6ac78f3dffe815a01393c8b86a3e7064b2565066f79648f2e63e4a4eb5f335fc` | `2f3056d686387e874ceef42fd9d0684a65bbab43d5e7a5f5b30de4e8770521e4` |
| A/B | mem0-oss/base | system | `a443a0c584c157a1083a860182fad24005a429b6c302c3dc10a40b3438c2f08b` | `b0521d6023ee73bd160838a810bdbe0a5125dac2a6a640ec65c37a11b30c4c46` |
| A/B | mem0-oss/base | wiped | `0a0eab6d3f924362dff6c7fb74fddf3e616ab46c1aeb365ff675d5fc4ce1f0df` | `cb18af92257fd5697c4425274fb756186362971f36ebcb5b86b26310a15e8b20` |
| A/B | mem0-oss/run1 | system | `29e2ceabaee0d652fd214448d76236a7473980a90cd0ee6bed431f1740d5174c` | `5b642a7d44a36411f8dba940511630536eea4a0a17cbf70600e59e0ecdcc3996` |
| A/B | mem0-oss/run1 | wiped | `0a0eab6d3f924362dff6c7fb74fddf3e616ab46c1aeb365ff675d5fc4ce1f0df` | `9b9df51494bf58f88522bebd2b4104605b0e2d2c1dd688f46f1d75e69eee389a` |
