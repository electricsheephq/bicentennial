# Bicentennial v0.3: T1's shorter wait after each turn, checked at one commit (#388)

Claim class: an A/B of T1's wait after each turn at one commit on two dedicated Linux hosts, both idle, with a store check of every Hermes session; not a loaded or developer-machine measurement; not predictive of the full tier; never certifies.

- Code commit: `e687fdb9d7782fc692df3d60d882ac2eb6e81026` in every run. T1 pack hash: `475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7` in every run.
- **The A/B** ran on one host: the 3 s set is step 10's idle run ([results](../2026-11-03-batch-determinism/RESULT.md)), and the 1 s set ran next on the same host. Each set ran three chains at once, one per reference system; each chain ran T1 twice (base, then run1).
- **The store checks** ran on the second host, base runs only. The first recorded each Hermes session's raw surface hash, which cannot compare two runs (below). The corrected check, declared on #388 before it ran, records every declared store surface with run-specific values masked.
- Full run trees (cards, receipts, logs, load samples and the store checks' session rows): the private evidence store, tags `bicentennial/kit-batch-determinism-20261103` (the A/B's 3 s set) and `bicentennial/t1-turn-wait-20261103` (every other set). Receipts are not published here: they hold machine-local fields.

## The A/B: each set's verdict lines

Printed from each set's own log: its start, the pack it built, each run's exit, the run script's run1-against-base card comparison per system (`same` allows only the gate verdict, which differs by design: base is CONFORMANCE_PASS and run1 PASS), and the run's end.

3 s:

```
2026-11-03T08:58:54Z start b10-idle: main e687fdb9d7782fc692df3d60d882ac2eb6e81026; three T1 chains, idle
2026-11-03T08:58:57Z pack T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7
2026-11-03T10:00:51Z exit 0 in 3714 s: hermes-native/t1/base
2026-11-03T10:01:53Z exit 0 in 3776 s: holographic/t1/base
2026-11-03T10:25:43Z exit 0 in 5206 s: mem0-oss/t1/base
2026-11-03T11:02:40Z exit 0 in 3709 s: hermes-native/t1/run1
2026-11-03T11:04:50Z exit 0 in 3777 s: holographic/t1/run1
2026-11-03T11:52:25Z exit 0 in 5202 s: mem0-oss/t1/run1
2026-11-03T11:52:26Z determinism hermes-native: same
2026-11-03T11:52:26Z determinism holographic: same
2026-11-03T11:52:26Z determinism mem0-oss: same
2026-11-03T11:52:26Z done b10-idle: runs_ok=1; T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7; packing receipts, cards, log and load
```

1 s:

```
2026-11-03T12:01:02Z start ab388-1s: main e687fdb9d7782fc692df3d60d882ac2eb6e81026; three T1 chains, idle, --turn-wait 1
2026-11-03T12:01:06Z pack T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7
2026-11-03T12:49:11Z exit 0 in 2885 s: hermes-native/t1/base
2026-11-03T12:50:00Z exit 0 in 2934 s: holographic/t1/base
2026-11-03T13:11:55Z exit 0 in 4249 s: mem0-oss/t1/base
2026-11-03T13:37:00Z exit 0 in 2869 s: hermes-native/t1/run1
2026-11-03T13:38:41Z exit 0 in 2921 s: holographic/t1/run1
2026-11-03T14:22:31Z exit 0 in 4236 s: mem0-oss/t1/run1
2026-11-03T14:22:32Z determinism hermes-native: same
2026-11-03T14:22:33Z determinism holographic: same
2026-11-03T14:22:33Z determinism mem0-oss: same
2026-11-03T14:22:33Z done ab388-1s: runs_ok=1; T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7; packing receipts, cards, log and load
```

## The A/B, card by card

Printed by `compare-cards.py`, which removes the four commit pins, says which of them differ, and prints only the JSON paths that differ, never values.

```
hermes-native/t1/base/system/card.json: same (commit pins that differ: none)
hermes-native/t1/base/wiped/card.json: same (commit pins that differ: none)
hermes-native/t1/run1/system/card.json: same (commit pins that differ: none)
hermes-native/t1/run1/wiped/card.json: same (commit pins that differ: none)
holographic/t1/base/system/card.json: same (commit pins that differ: none)
holographic/t1/base/wiped/card.json: same (commit pins that differ: none)
holographic/t1/run1/system/card.json: same (commit pins that differ: none)
holographic/t1/run1/wiped/card.json: same (commit pins that differ: none)
mem0-oss/t1/base/system/card.json: same (commit pins that differ: none)
mem0-oss/t1/base/wiped/card.json: same (commit pins that differ: none)
mem0-oss/t1/run1/system/card.json: same (commit pins that differ: none)
mem0-oss/t1/run1/wiped/card.json: same (commit pins that differ: none)
12 of 12 cards equal apart from the commit pins
exit 0
```

## The A/B, file by file

Printed by `runfiles388.py` from every file of both sets. A JUnit file records the run's wait as its `t1.turn_wait_s` property, so it is also compared with that value masked. Receipts hold volatile fields, so only their wait, background counts and run status are shown: `Late` counts background requests that arrived after the next turn began, and `Unattributed` those the receipt cannot tie to a turn, which in T1 includes every request from an arm's corpus hosts (RING0 §13 E30).

files: 3 s 84, 1 s 84, only in 3 s 0, only in 1 s 0
| File | Byte-equal | Equal with the wait property masked |
|---|---|---|
| `base.exit` | 3 of 3 | - |
| `base.log` | 3 of 3 | - |
| `card.json` | 12 of 12 | - |
| `controls.json` | 12 of 12 | - |
| `corpus.json` | 12 of 12 | - |
| `invariants.json` | 12 of 12 | - |
| `junit.xml` | 0 of 12 | 12 of 12 |
| `receipt.json` | 0 of 12 | - |
| `run1.exit` | 3 of 3 | - |
| `run1.log` | 3 of 3 | - |

| Set | System | Run | Arm | turn_wait_s | Late | Unattributed | Status |
|---|---|---|---|---|---|---|---|
| 3 s | hermes-native | base | system | 3.0 | 0 | 780 | COMPLETE |
| 3 s | hermes-native | base | wiped | 3.0 | 0 | 720 | COMPLETE |
| 3 s | hermes-native | run1 | system | 3.0 | 0 | 780 | COMPLETE |
| 3 s | hermes-native | run1 | wiped | 3.0 | 0 | 720 | COMPLETE |
| 3 s | holographic | base | system | 3.0 | 0 | 780 | COMPLETE |
| 3 s | holographic | base | wiped | 3.0 | 0 | 720 | COMPLETE |
| 3 s | holographic | run1 | system | 3.0 | 0 | 780 | COMPLETE |
| 3 s | holographic | run1 | wiped | 3.0 | 0 | 720 | COMPLETE |
| 3 s | mem0-oss | base | system | 3.0 | 0 | 5959 | COMPLETE |
| 3 s | mem0-oss | base | wiped | 3.0 | 0 | 5895 | COMPLETE |
| 3 s | mem0-oss | run1 | system | 3.0 | 0 | 5959 | COMPLETE |
| 3 s | mem0-oss | run1 | wiped | 3.0 | 0 | 5895 | COMPLETE |
| 1 s | hermes-native | base | system | 1.0 | 0 | 780 | COMPLETE |
| 1 s | hermes-native | base | wiped | 1.0 | 0 | 720 | COMPLETE |
| 1 s | hermes-native | run1 | system | 1.0 | 0 | 780 | COMPLETE |
| 1 s | hermes-native | run1 | wiped | 1.0 | 0 | 720 | COMPLETE |
| 1 s | holographic | base | system | 1.0 | 0 | 780 | COMPLETE |
| 1 s | holographic | base | wiped | 1.0 | 0 | 720 | COMPLETE |
| 1 s | holographic | run1 | system | 1.0 | 0 | 780 | COMPLETE |
| 1 s | holographic | run1 | wiped | 1.0 | 0 | 720 | COMPLETE |
| 1 s | mem0-oss | base | system | 1.0 | 0 | 5959 | COMPLETE |
| 1 s | mem0-oss | base | wiped | 1.0 | 0 | 5895 | COMPLETE |
| 1 s | mem0-oss | run1 | system | 1.0 | 0 | 5959 | COMPLETE |
| 1 s | mem0-oss | run1 | wiped | 1.0 | 0 | 5895 | COMPLETE |

`runfiles388.py` exit status: 0 (0: every file equal, JUnit files apart from the wait, and no late request).

## The A/B: wall times

Printed by `t1loop_numbers.py` from the runs' own receipts, with the field each number comes from.

### Per run

| Code | System | Run | W | No-memory arm | System arm | Wiped arm | Outside the arms |
|---|---|---|---|---|---|---|---|
| e687fdb-3s | hermes-native | base | 3,713 s | 122 s | 1,294 s | 1,309 s | 988 s (27%) |
| e687fdb-3s | hermes-native | run1 | 3,709 s | 124 s | 1,294 s | 1,306 s | 985 s (27%) |
| e687fdb-3s | holographic | base | 3,775 s | 122 s | 1,309 s | 1,318 s | 1,026 s (27%) |
| e687fdb-3s | holographic | run1 | 3,776 s | 124 s | 1,314 s | 1,315 s | 1,024 s (27%) |
| e687fdb-3s | mem0-oss | base | 5,205 s | 124 s | 1,509 s | 1,512 s | 2,060 s (40%) |
| e687fdb-3s | mem0-oss | run1 | 5,201 s | 125 s | 1,505 s | 1,515 s | 2,055 s (40%) |
| e687fdb-1s | hermes-native | base | 2,884 s | 103 s | 883 s | 895 s | 1,003 s (35%) |
| e687fdb-1s | hermes-native | run1 | 2,868 s | 104 s | 876 s | 892 s | 996 s (35%) |
| e687fdb-1s | holographic | base | 2,933 s | 102 s | 896 s | 900 s | 1,035 s (35%) |
| e687fdb-1s | holographic | run1 | 2,920 s | 103 s | 891 s | 900 s | 1,026 s (35%) |
| e687fdb-1s | mem0-oss | base | 4,248 s | 104 s | 1,041 s | 1,043 s | 2,060 s (49%) |
| e687fdb-1s | mem0-oss | run1 | 4,235 s | 105 s | 1,038 s | 1,047 s | 2,044 s (48%) |

Source: each run's system and wiped receipt.json: wall_end_ms − wall_start_ms, and timings[] (pin_check_ms, sessions[].wall), slower branch per arm and life.

### Critical path (per arm and life, the slower branch; summed)

| Code | System | Run | Waits after turns | Waits at session ends | Turns | Opening sessions | Spawn and import | Close | Pin checks, gates, resume, workspace |
|---|---|---|---|---|---|---|---|---|---|
| e687fdb-3s | hermes-native | base | 1,290 s (35%; 430 waits) | 330 s (9%; 110) | 552 s | 390 s | 74 s | 80 s | 28 s |
| e687fdb-3s | hermes-native | run1 | 1,290 s (35%; 430 waits) | 330 s (9%; 110) | 552 s | 388 s | 74 s | 81 s | 28 s |
| e687fdb-3s | holographic | base | 1,290 s (34%; 430 waits) | 330 s (9%; 110) | 559 s | 399 s | 75 s | 84 s | 31 s |
| e687fdb-3s | holographic | run1 | 1,290 s (34%; 430 waits) | 330 s (9%; 110) | 560 s | 400 s | 74 s | 86 s | 30 s |
| e687fdb-3s | mem0-oss | base | 1,499 s (29%; 430 waits) | 330 s (6%; 110) | 588 s | 530 s | 75 s | 112 s | 34 s |
| e687fdb-3s | mem0-oss | run1 | 1,500 s (29%; 430 waits) | 330 s (6%; 110) | 587 s | 528 s | 75 s | 112 s | 36 s |
| e687fdb-1s | hermes-native | base | 438 s (15%; 430 waits) | 330 s (11%; 110) | 553 s | 393 s | 74 s | 83 s | 29 s |
| e687fdb-1s | hermes-native | run1 | 438 s (15%; 430 waits) | 330 s (12%; 110) | 552 s | 388 s | 73 s | 81 s | 28 s |
| e687fdb-1s | holographic | base | 438 s (15%; 430 waits) | 330 s (11%; 110) | 557 s | 400 s | 75 s | 86 s | 30 s |
| e687fdb-1s | holographic | run1 | 438 s (15%; 430 waits) | 330 s (11%; 110) | 557 s | 398 s | 74 s | 84 s | 30 s |
| e687fdb-1s | mem0-oss | base | 544 s (13%; 430 waits) | 330 s (8%; 110) | 588 s | 530 s | 75 s | 110 s | 34 s |
| e687fdb-1s | mem0-oss | run1 | 544 s (13%; 430 waits) | 330 s (8%; 110) | 588 s | 532 s | 75 s | 109 s | 35 s |

Source: receipt.json timings[].sessions[]: drain (the last entry is the session-end wait), turn, open, spawn (which includes import), close, and the remaining timers. Overlapping timers are not added to each other.

### e687fdb-1s against e687fdb-3s

| System | Run | W before | W after | Saved |
|---|---|---|---|---|
| hermes-native | base | 3,713 s | 2,884 s | 829 s (22%) |
| hermes-native | run1 | 3,709 s | 2,868 s | 840 s (23%) |
| holographic | base | 3,775 s | 2,933 s | 842 s (22%) |
| holographic | run1 | 3,776 s | 2,920 s | 856 s (23%) |
| mem0-oss | base | 5,205 s | 4,248 s | 957 s (18%) |
| mem0-oss | run1 | 5,201 s | 4,235 s | 966 s (19%) |

## The first store check, and why it could not decide

The first store check ran the base runs at 3 s and then at 1 s on the second host, through a wrapper that recorded each Hermes session's end-of-session surface hash, the adapter's own digest of `HERMES_HOME`. Its verdict lines:

3 s:

```
2026-11-03T19:27:46Z start surf388-3s: main e687fdb9d7782fc692df3d60d882ac2eb6e81026; three T1 base runs, idle, --turn-wait 3, through surfdiag
2026-11-03T19:27:51Z pack T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7
2026-11-03T20:32:05Z exit 0 in 3854 s: hermes-native/t1/base
2026-11-03T20:33:21Z exit 0 in 3930 s: holographic/t1/base
2026-11-03T20:57:31Z exit 0 in 5380 s: mem0-oss/t1/base
2026-11-03T20:57:32Z done surf388-3s: runs_ok=1; T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7; packing receipts, cards, log and load
```

1 s:

```
2026-11-03T21:01:16Z start surf388-1s: main e687fdb9d7782fc692df3d60d882ac2eb6e81026; three T1 base runs, idle, --turn-wait 1, through surfdiag
2026-11-03T21:01:21Z pack T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7
2026-11-03T21:51:28Z exit 0 in 3007 s: hermes-native/t1/base
2026-11-03T21:52:46Z exit 0 in 3085 s: holographic/t1/base
2026-11-03T22:15:22Z exit 0 in 4441 s: mem0-oss/t1/base
2026-11-03T22:15:23Z done surf388-1s: runs_ok=1; T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7; packing receipts, cards, log and load
```

Printed by `compare-surf388.py`: cards equal, but every session's hash differs.

```
rows: 3s 693, 1s 693; keys: 3s 646, 1s 646
  chain hermes-native system=hermes-native wiped=False kind=probe: 3s 34, 1s 34
  chain hermes-native system=hermes-native wiped=False kind=replay: 3s 100, 1s 100
  chain hermes-native system=hermes-native wiped=True kind=probe: 3s 17, 1s 17
  chain hermes-native system=hermes-native wiped=True kind=replay: 3s 80, 1s 80
  chain holographic system=hermes-native wiped=False kind=probe: 3s 17, 1s 17
  chain holographic system=hermes-native wiped=False kind=replay: 3s 20, 1s 20
  chain holographic system=holographic wiped=False kind=probe: 3s 17, 1s 17
  chain holographic system=holographic wiped=False kind=replay: 3s 80, 1s 80
  chain holographic system=holographic wiped=True kind=probe: 3s 17, 1s 17
  chain holographic system=holographic wiped=True kind=replay: 3s 80, 1s 80
  chain mem0-oss system=hermes-native wiped=False kind=probe: 3s 17, 1s 17
  chain mem0-oss system=hermes-native wiped=False kind=replay: 3s 20, 1s 20
  chain mem0-oss system=mem0-oss wiped=False kind=probe: 3s 17, 1s 17
  chain mem0-oss system=mem0-oss wiped=False kind=replay: 3s 80, 1s 80
  chain mem0-oss system=mem0-oss wiped=True kind=probe: 3s 17, 1s 17
  chain mem0-oss system=mem0-oss wiped=True kind=replay: 3s 80, 1s 80
only in 3s: 0
only in 1s: 0
hash differs: 646
   hermes-native {'branch': 'B0', 'kind': 'probe', 'life': 't1-g1', 'run': 'bcw-f1670e67daa6c1cf', 'session': 21, 'system': 'hermes-native', 'wiped': False}
   hermes-native {'branch': 'B0', 'kind': 'probe', 'life': 't1-g1', 'run': 'bcw-f1670e67daa6c1cf', 'session': 21, 'system': 'hermes-native', 'wiped': True}
   hermes-native {'branch': 'B0', 'kind': 'probe', 'life': 't1-g1', 'run': 'bcw-f1670e67daa6c1cf', 'session': 22, 'system': 'hermes-native', 'wiped': False}
   hermes-native {'branch': 'B0', 'kind': 'probe', 'life': 't1-g1', 'run': 'bcw-f1670e67daa6c1cf', 'session': 22, 'system': 'hermes-native', 'wiped': True}
   hermes-native {'branch': 'B0', 'kind': 'probe', 'life': 't1-g1', 'run': 'bcw-f1670e67daa6c1cf', 'session': 23, 'system': 'hermes-native', 'wiped': False}
   hermes-native {'branch': 'B0', 'kind': 'probe', 'life': 't1-g1', 'run': 'bcw-f1670e67daa6c1cf', 'session': 23, 'system': 'hermes-native', 'wiped': True}
   hermes-native {'branch': 'B0', 'kind': 'probe', 'life': 't1-g1', 'run': 'bcw-f1670e67daa6c1cf', 'session': 24, 'system': 'hermes-native', 'wiped': False}
   hermes-native {'branch': 'B0', 'kind': 'probe', 'life': 't1-g1', 'run': 'bcw-f1670e67daa6c1cf', 'session': 24, 'system': 'hermes-native', 'wiped': True}
   hermes-native {'branch': 'B0', 'kind': 'probe', 'life': 't1-g1', 'run': 'bcw-f1670e67daa6c1cf', 'session': 25, 'system': 'hermes-native', 'wiped': False}
   hermes-native {'branch': 'B0', 'kind': 'probe', 'life': 't1-g1', 'run': 'bcw-f1670e67daa6c1cf', 'session': 25, 'system': 'hermes-native', 'wiped': True}
card hermes-native/system: equal 4c832f9263b9642e 4c832f9263b9642e
card hermes-native/wiped: equal 6852686b678e952c 6852686b678e952c
card holographic/system: equal 957da6144dc6a98c 957da6144dc6a98c
card holographic/wiped: equal 2f068dd5d2802705 2f068dd5d2802705
card mem0-oss/system: equal ec675c5ff22475a6 ec675c5ff22475a6
card mem0-oss/wiped: equal ae90459fe2886516 ae90459fe2886516
receipt 3s hermes-native/system: wait 3.0 late 0 egress_failed 0 busy [False] status COMPLETE wall_s 3853
receipt 3s hermes-native/wiped: wait 3.0 late 0 egress_failed 0 busy [False] status COMPLETE wall_s 3853
receipt 3s holographic/system: wait 3.0 late 0 egress_failed 0 busy [False] status COMPLETE wall_s 3929
receipt 3s holographic/wiped: wait 3.0 late 0 egress_failed 0 busy [False] status COMPLETE wall_s 3929
receipt 3s mem0-oss/system: wait 3.0 late 0 egress_failed 0 busy [False] status COMPLETE wall_s 5379
receipt 3s mem0-oss/wiped: wait 3.0 late 0 egress_failed 0 busy [False] status COMPLETE wall_s 5379
receipt 1s hermes-native/system: wait 1.0 late 0 egress_failed 0 busy [False] status COMPLETE wall_s 3006
receipt 1s hermes-native/wiped: wait 1.0 late 0 egress_failed 0 busy [False] status COMPLETE wall_s 3006
receipt 1s holographic/system: wait 1.0 late 0 egress_failed 0 busy [False] status COMPLETE wall_s 3084
receipt 1s holographic/wiped: wait 1.0 late 0 egress_failed 0 busy [False] status COMPLETE wall_s 3084
receipt 1s mem0-oss/system: wait 1.0 late 0 egress_failed 0 busy [False] status COMPLETE wall_s 4440
receipt 1s mem0-oss/wiped: wait 1.0 late 0 egress_failed 0 busy [False] status COMPLETE wall_s 4440
VERDICT STORES_DIFFER CARDS_EQUAL
```

That hash covers raw bytes, and a store's bytes hold run-specific values: Hermes session ids (a date, a time and random hex), clock times and the sandbox path. The no-memory floors of chains holographic and mem0-oss are twins: the same life, branch, session and kind in the same run. Printed by `floor-twins388.py`, the twins' hashes are never equal either:

```
3s: twin floor keys holographic 27, mem0-oss 27, shared 10, equal hashes 0
1s: twin floor keys holographic 27, mem0-oss 27, shared 10, equal hashes 0
```

So the raw hash cannot compare two runs at all. The corrected check below was declared on #388 before it ran.

## The corrected store check

The corrected check ran the base runs at 3 s and then at 1 s on the same host, then a second run at 3 s. It used `surfdiag2.py`, which records per Hermes session every store surface the system declares: each file's path and digest, and for SQLite files each table's row count and a digest per column. Run-specific values are masked first: Hermes session ids, clock times, random UUIDs, the sandbox root and the director port. It records digests and counts only. Each set's verdict lines:

3 s:

```
2026-11-03T22:38:42Z start surf388b-3s: main e687fdb9d7782fc692df3d60d882ac2eb6e81026; three T1 base runs, idle, --turn-wait 3, through surfdiag2
2026-11-03T22:38:47Z pack T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7
2026-11-03T23:43:32Z exit 0 in 3885 s: hermes-native/t1/base
2026-11-03T23:44:46Z exit 0 in 3958 s: holographic/t1/base
2026-11-04T00:09:09Z exit 0 in 5422 s: mem0-oss/t1/base
2026-11-04T00:09:10Z done surf388b-3s: runs_ok=1; T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7; packing receipts, cards, log and load
```

1 s:

```
2026-11-04T00:10:53Z start surf388b-1s: main e687fdb9d7782fc692df3d60d882ac2eb6e81026; three T1 base runs, idle, --turn-wait 1, through surfdiag2
2026-11-04T00:10:58Z pack T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7
2026-11-04T01:01:26Z exit 0 in 3028 s: hermes-native/t1/base
2026-11-04T01:02:43Z exit 0 in 3105 s: holographic/t1/base
2026-11-04T01:25:28Z exit 0 in 4470 s: mem0-oss/t1/base
2026-11-04T01:25:30Z done surf388b-1s: runs_ok=1; T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7; packing receipts, cards, log and load
```

second 3 s:

```
2026-11-04T01:28:38Z start surf388b-3s2: main e687fdb9d7782fc692df3d60d882ac2eb6e81026; three T1 base runs, idle, --turn-wait 3, through surfdiag2
2026-11-04T01:28:43Z pack T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7
2026-11-04T02:33:17Z exit 0 in 3874 s: hermes-native/t1/base
2026-11-04T02:34:34Z exit 0 in 3951 s: holographic/t1/base
2026-11-04T02:58:57Z exit 0 in 5414 s: mem0-oss/t1/base
2026-11-04T02:58:58Z done surf388b-3s2: runs_ok=1; T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7; packing receipts, cards, log and load
```

Printed by `compare-surf388b.py`. Strict items must be equal, with no exception: the same sessions, no store change after the adapter's own hash, the same files, tables and columns, and every table's row count. Masked items (file, table and column digests) must be equal too. The only exception is an item that also differs at the same wait, between the twin floors of one run or between the two 3 s runs, and the output names each such exception.

```
run 3s: 693 rows, 646 keys, same_as_adapter false 0, surface errors 0
run 1s: 693 rows, 646 keys, same_as_adapter false 0, surface errors 0
run 3s2: 693 rows, 646 keys, same_as_adapter false 0, surface errors 0
twin floors in 3s: 10 shared keys; raw items differing 416
  twin strict differences in 3s: 0 items
  twin masked differences in 3s: 7 items
    10 sessions  ('HERMES_HOME/.', 'cache/tool_discovery_cache.json', 'm')
    10 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'sessions', 'set')
    10 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'sessions', 'system_prompt_hash', 'col')
    10 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'system_prompts', 'hash', 'col')
    10 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'system_prompts', 'set')
     6 sessions  ('HERMES_HOME/.', 'cache/mcp_schema_cache.json', 'm')
     6 sessions  ('HERMES_HOME/.', 'spawn-ledger.json', 'm')
twin floors in 1s: 10 shared keys; raw items differing 416
  twin strict differences in 1s: 0 items
  twin masked differences in 1s: 7 items
    10 sessions  ('HERMES_HOME/.', 'cache/tool_discovery_cache.json', 'm')
    10 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'sessions', 'set')
    10 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'sessions', 'system_prompt_hash', 'col')
    10 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'system_prompts', 'hash', 'col')
    10 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'system_prompts', 'set')
     6 sessions  ('HERMES_HOME/.', 'cache/mcp_schema_cache.json', 'm')
     6 sessions  ('HERMES_HOME/.', 'spawn-ledger.json', 'm')
twin floors in 3s2: 10 shared keys; raw items differing 416
  twin strict differences in 3s2: 0 items
  twin masked differences in 3s2: 7 items
    10 sessions  ('HERMES_HOME/.', 'cache/tool_discovery_cache.json', 'm')
    10 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'sessions', 'set')
    10 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'sessions', 'system_prompt_hash', 'col')
    10 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'system_prompts', 'hash', 'col')
    10 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'system_prompts', 'set')
     6 sessions  ('HERMES_HOME/.', 'cache/mcp_schema_cache.json', 'm')
     6 sessions  ('HERMES_HOME/.', 'spawn-ledger.json', 'm')
same-wait pair 3s vs 3s2: raw items differing 13257; key problems 0
  same-wait strict differences: 0 items
  same-wait masked differences: 18 items
   322 sessions  ('HERMES_HOME/.', 'spawn-ledger.json', 'm')
   194 sessions  ('HERMES_HOME/.', 'memory_store.db', 'db', 'meta', 'set')
   194 sessions  ('HERMES_HOME/.', 'memory_store.db', 'db', 'meta', 'value', 'col')
   194 sessions  ('SANDBOX_HOME/.mem0', 'qdrant/collection/mem0/storage.sqlite', 'db', 'points', 'id', 'col')
   194 sessions  ('SANDBOX_HOME/.mem0', 'qdrant/collection/mem0/storage.sqlite', 'db', 'points', 'set')
    40 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'session_model_usage', 'billing_base_url', 'col')
    40 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'session_model_usage', 'cost_source', 'col')
    40 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'session_model_usage', 'cost_status', 'col')
    40 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'session_model_usage', 'input_tokens', 'col')
    40 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'session_model_usage', 'model', 'col')
    40 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'session_model_usage', 'task', 'col')
    37 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'session_model_usage', 'output_tokens', 'col')
    36 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'session_model_usage', 'api_call_count', 'col')
    32 sessions  ('HERMES_HOME/.', 'cache/local_endpoint_probes.json', 'm')
    17 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'messages', 'display_identity', 'col')
    17 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'messages', 'set')
    17 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'messages_fts_data', 'block', 'col')
    17 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'messages_fts_data', 'set')
3s vs 1s: raw items differing 13497
3s vs 1s STRICT differences: 0 items
3s vs 1s masked differences excused by calibration: 18 items
   322 sessions  ('HERMES_HOME/.', 'spawn-ledger.json', 'm')
   194 sessions  ('HERMES_HOME/.', 'memory_store.db', 'db', 'meta', 'set')
   194 sessions  ('HERMES_HOME/.', 'memory_store.db', 'db', 'meta', 'value', 'col')
   194 sessions  ('SANDBOX_HOME/.mem0', 'qdrant/collection/mem0/storage.sqlite', 'db', 'points', 'id', 'col')
   194 sessions  ('SANDBOX_HOME/.mem0', 'qdrant/collection/mem0/storage.sqlite', 'db', 'points', 'set')
    48 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'session_model_usage', 'billing_base_url', 'col')
    48 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'session_model_usage', 'cost_source', 'col')
    48 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'session_model_usage', 'cost_status', 'col')
    48 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'session_model_usage', 'input_tokens', 'col')
    48 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'session_model_usage', 'model', 'col')
    48 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'session_model_usage', 'task', 'col')
    45 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'session_model_usage', 'api_call_count', 'col')
    45 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'session_model_usage', 'output_tokens', 'col')
    33 sessions  ('HERMES_HOME/.', 'cache/local_endpoint_probes.json', 'm')
    17 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'messages', 'display_identity', 'col')
    17 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'messages', 'set')
    17 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'messages_fts_data', 'block', 'col')
    17 sessions  ('HERMES_HOME/.', 'state.db', 'db', 'messages_fts_data', 'set')
3s vs 1s masked differences NOT excused: 0 items
card hermes-native/system: equal 4c832f9263b9642e 4c832f9263b9642e 4c832f9263b9642e
card hermes-native/wiped: equal 6852686b678e952c 6852686b678e952c 6852686b678e952c
card holographic/system: equal 957da6144dc6a98c 957da6144dc6a98c 957da6144dc6a98c
card holographic/wiped: equal 2f068dd5d2802705 2f068dd5d2802705 2f068dd5d2802705
card mem0-oss/system: equal ec675c5ff22475a6 ec675c5ff22475a6 ec675c5ff22475a6
card mem0-oss/wiped: equal ae90459fe2886516 ae90459fe2886516 ae90459fe2886516
receipt 3s hermes-native/system: wait 3.0 late 0 status COMPLETE wall_s 3884
receipt 3s hermes-native/wiped: wait 3.0 late 0 status COMPLETE wall_s 3884
receipt 3s holographic/system: wait 3.0 late 0 status COMPLETE wall_s 3957
receipt 3s holographic/wiped: wait 3.0 late 0 status COMPLETE wall_s 3957
receipt 3s mem0-oss/system: wait 3.0 late 0 status COMPLETE wall_s 5420
receipt 3s mem0-oss/wiped: wait 3.0 late 0 status COMPLETE wall_s 5420
receipt 1s hermes-native/system: wait 1.0 late 0 status COMPLETE wall_s 3027
receipt 1s hermes-native/wiped: wait 1.0 late 0 status COMPLETE wall_s 3027
receipt 1s holographic/system: wait 1.0 late 0 status COMPLETE wall_s 3104
receipt 1s holographic/wiped: wait 1.0 late 0 status COMPLETE wall_s 3104
receipt 1s mem0-oss/system: wait 1.0 late 0 status COMPLETE wall_s 4469
receipt 1s mem0-oss/wiped: wait 1.0 late 0 status COMPLETE wall_s 4469
receipt 3s2 hermes-native/system: wait 3.0 late 0 status COMPLETE wall_s 3873
receipt 3s2 hermes-native/wiped: wait 3.0 late 0 status COMPLETE wall_s 3873
receipt 3s2 holographic/system: wait 3.0 late 0 status COMPLETE wall_s 3950
receipt 3s2 holographic/wiped: wait 3.0 late 0 status COMPLETE wall_s 3950
receipt 3s2 mem0-oss/system: wait 3.0 late 0 status COMPLETE wall_s 5412
receipt 3s2 mem0-oss/wiped: wait 3.0 late 0 status COMPLETE wall_s 5412
VERDICT STORES_EQUAL CARDS_EQUAL LATE_0
```

`compare-surf388b.py` exit status: 0 (0: stores equal, cards equal, no late request).

## Files

| Set | Run | Arm | card.json sha256 |
|---|---|---|---|
| A/B 3 s | hermes-native/base | system | `4c832f9263b9642ee1f43a0bf51bf0e4393140b741e75e0f5a71e776c671a36d` |
| A/B 3 s | hermes-native/base | wiped | `6852686b678e952c139a8f6991dd04b7098d322f66b81fa8358370c87f75cdb2` |
| A/B 3 s | hermes-native/run1 | system | `4a0c7321094aac21155b3384fc8e8ec8c2f85dc3bc7eb3700060f49d8e92a1fe` |
| A/B 3 s | hermes-native/run1 | wiped | `6852686b678e952c139a8f6991dd04b7098d322f66b81fa8358370c87f75cdb2` |
| A/B 3 s | holographic/base | system | `957da6144dc6a98cd78ed206b0131e2ffc82094ae312bc9eaff1b8146cdb68cf` |
| A/B 3 s | holographic/base | wiped | `2f068dd5d2802705423154d647c48029d038cad3294732b37ecff5abb36840ec` |
| A/B 3 s | holographic/run1 | system | `006e9dff7e7b9c1942d1c0d9e0529e1924cb67a3f80f114aba38ee840550818b` |
| A/B 3 s | holographic/run1 | wiped | `2f068dd5d2802705423154d647c48029d038cad3294732b37ecff5abb36840ec` |
| A/B 3 s | mem0-oss/base | system | `ec675c5ff22475a68ec5b9197b82fa3dcbc3ef6f449247802366cc6e99c6a80d` |
| A/B 3 s | mem0-oss/base | wiped | `ae90459fe288651622b420aaa88f35c1a10211f9089325d90dbbfc0518c7cad7` |
| A/B 3 s | mem0-oss/run1 | system | `68749da263b33c45875e080447e70bbf20800320c66c983a6ec6bdb2031f5b09` |
| A/B 3 s | mem0-oss/run1 | wiped | `ae90459fe288651622b420aaa88f35c1a10211f9089325d90dbbfc0518c7cad7` |
| A/B 1 s | hermes-native/base | system | `4c832f9263b9642ee1f43a0bf51bf0e4393140b741e75e0f5a71e776c671a36d` |
| A/B 1 s | hermes-native/base | wiped | `6852686b678e952c139a8f6991dd04b7098d322f66b81fa8358370c87f75cdb2` |
| A/B 1 s | hermes-native/run1 | system | `4a0c7321094aac21155b3384fc8e8ec8c2f85dc3bc7eb3700060f49d8e92a1fe` |
| A/B 1 s | hermes-native/run1 | wiped | `6852686b678e952c139a8f6991dd04b7098d322f66b81fa8358370c87f75cdb2` |
| A/B 1 s | holographic/base | system | `957da6144dc6a98cd78ed206b0131e2ffc82094ae312bc9eaff1b8146cdb68cf` |
| A/B 1 s | holographic/base | wiped | `2f068dd5d2802705423154d647c48029d038cad3294732b37ecff5abb36840ec` |
| A/B 1 s | holographic/run1 | system | `006e9dff7e7b9c1942d1c0d9e0529e1924cb67a3f80f114aba38ee840550818b` |
| A/B 1 s | holographic/run1 | wiped | `2f068dd5d2802705423154d647c48029d038cad3294732b37ecff5abb36840ec` |
| A/B 1 s | mem0-oss/base | system | `ec675c5ff22475a68ec5b9197b82fa3dcbc3ef6f449247802366cc6e99c6a80d` |
| A/B 1 s | mem0-oss/base | wiped | `ae90459fe288651622b420aaa88f35c1a10211f9089325d90dbbfc0518c7cad7` |
| A/B 1 s | mem0-oss/run1 | system | `68749da263b33c45875e080447e70bbf20800320c66c983a6ec6bdb2031f5b09` |
| A/B 1 s | mem0-oss/run1 | wiped | `ae90459fe288651622b420aaa88f35c1a10211f9089325d90dbbfc0518c7cad7` |
| store r1 3 s | hermes-native/base | system | `4c832f9263b9642ee1f43a0bf51bf0e4393140b741e75e0f5a71e776c671a36d` |
| store r1 3 s | hermes-native/base | wiped | `6852686b678e952c139a8f6991dd04b7098d322f66b81fa8358370c87f75cdb2` |
| store r1 3 s | holographic/base | system | `957da6144dc6a98cd78ed206b0131e2ffc82094ae312bc9eaff1b8146cdb68cf` |
| store r1 3 s | holographic/base | wiped | `2f068dd5d2802705423154d647c48029d038cad3294732b37ecff5abb36840ec` |
| store r1 3 s | mem0-oss/base | system | `ec675c5ff22475a68ec5b9197b82fa3dcbc3ef6f449247802366cc6e99c6a80d` |
| store r1 3 s | mem0-oss/base | wiped | `ae90459fe288651622b420aaa88f35c1a10211f9089325d90dbbfc0518c7cad7` |
| store r1 1 s | hermes-native/base | system | `4c832f9263b9642ee1f43a0bf51bf0e4393140b741e75e0f5a71e776c671a36d` |
| store r1 1 s | hermes-native/base | wiped | `6852686b678e952c139a8f6991dd04b7098d322f66b81fa8358370c87f75cdb2` |
| store r1 1 s | holographic/base | system | `957da6144dc6a98cd78ed206b0131e2ffc82094ae312bc9eaff1b8146cdb68cf` |
| store r1 1 s | holographic/base | wiped | `2f068dd5d2802705423154d647c48029d038cad3294732b37ecff5abb36840ec` |
| store r1 1 s | mem0-oss/base | system | `ec675c5ff22475a68ec5b9197b82fa3dcbc3ef6f449247802366cc6e99c6a80d` |
| store r1 1 s | mem0-oss/base | wiped | `ae90459fe288651622b420aaa88f35c1a10211f9089325d90dbbfc0518c7cad7` |
| store r2 3 s | hermes-native/base | system | `4c832f9263b9642ee1f43a0bf51bf0e4393140b741e75e0f5a71e776c671a36d` |
| store r2 3 s | hermes-native/base | wiped | `6852686b678e952c139a8f6991dd04b7098d322f66b81fa8358370c87f75cdb2` |
| store r2 3 s | holographic/base | system | `957da6144dc6a98cd78ed206b0131e2ffc82094ae312bc9eaff1b8146cdb68cf` |
| store r2 3 s | holographic/base | wiped | `2f068dd5d2802705423154d647c48029d038cad3294732b37ecff5abb36840ec` |
| store r2 3 s | mem0-oss/base | system | `ec675c5ff22475a68ec5b9197b82fa3dcbc3ef6f449247802366cc6e99c6a80d` |
| store r2 3 s | mem0-oss/base | wiped | `ae90459fe288651622b420aaa88f35c1a10211f9089325d90dbbfc0518c7cad7` |
| store r2 1 s | hermes-native/base | system | `4c832f9263b9642ee1f43a0bf51bf0e4393140b741e75e0f5a71e776c671a36d` |
| store r2 1 s | hermes-native/base | wiped | `6852686b678e952c139a8f6991dd04b7098d322f66b81fa8358370c87f75cdb2` |
| store r2 1 s | holographic/base | system | `957da6144dc6a98cd78ed206b0131e2ffc82094ae312bc9eaff1b8146cdb68cf` |
| store r2 1 s | holographic/base | wiped | `2f068dd5d2802705423154d647c48029d038cad3294732b37ecff5abb36840ec` |
| store r2 1 s | mem0-oss/base | system | `ec675c5ff22475a68ec5b9197b82fa3dcbc3ef6f449247802366cc6e99c6a80d` |
| store r2 1 s | mem0-oss/base | wiped | `ae90459fe288651622b420aaa88f35c1a10211f9089325d90dbbfc0518c7cad7` |
| store r2 second 3 s | hermes-native/base | system | `4c832f9263b9642ee1f43a0bf51bf0e4393140b741e75e0f5a71e776c671a36d` |
| store r2 second 3 s | hermes-native/base | wiped | `6852686b678e952c139a8f6991dd04b7098d322f66b81fa8358370c87f75cdb2` |
| store r2 second 3 s | holographic/base | system | `957da6144dc6a98cd78ed206b0131e2ffc82094ae312bc9eaff1b8146cdb68cf` |
| store r2 second 3 s | holographic/base | wiped | `2f068dd5d2802705423154d647c48029d038cad3294732b37ecff5abb36840ec` |
| store r2 second 3 s | mem0-oss/base | system | `ec675c5ff22475a68ec5b9197b82fa3dcbc3ef6f449247802366cc6e99c6a80d` |
| store r2 second 3 s | mem0-oss/base | wiped | `ae90459fe288651622b420aaa88f35c1a10211f9089325d90dbbfc0518c7cad7` |
