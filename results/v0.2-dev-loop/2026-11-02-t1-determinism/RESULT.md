# Bicentennial v0.2 Developer loop: T1's determinism on the release commit, idle and under load

Claim class: a determinism check of T1 at one commit on two dedicated Linux hosts, one idle and one under induced load; not a developer-machine measurement; not predictive of the full tier; never certifies.

- Release code commit: `436750ecd900631e38fda99bc28cc6ee464b5f40`. T1 pack hash: `278fb65a975ddfed8f75dde34e6fa9fcfc19ea3b205b408705c98e55900afa5c` (idle host), `278fb65a975ddfed8f75dde34e6fa9fcfc19ea3b205b408705c98e55900afa5c` (loaded host).
- Each host ran three chains at once, one per reference system; each chain ran T1 twice (base, then run1), and the run script compared run1's cards with base's.
- Full run trees (cards, receipts, logs and load samples): the private evidence store, tag `bicentennial/t1-determinism-v02-20261102`. Receipts are not published here: they hold machine-local fields.

## Each host's verdict lines

Printed from each host's own log: the pack it built, the load it held, the run script's run1-against-base card comparison per system (`same` allows only the gate verdict, which differs by design: base is CONFORMANCE_PASS and run1 PASS), and the run's end.

Idle host:

```
2026-11-02T11:34:01Z pack T1=278fb65a975ddfed8f75dde34e6fa9fcfc19ea3b205b408705c98e55900afa5c
2026-11-02T14:26:35Z determinism hermes-native: same
2026-11-02T14:26:35Z determinism holographic: same
2026-11-02T14:26:35Z determinism mem0-oss: same
2026-11-02T14:26:35Z done d10-idle: runs_ok=1; T1=278fb65a975ddfed8f75dde34e6fa9fcfc19ea3b205b408705c98e55900afa5c; packing receipts, cards, log and load
```

Loaded host:

```
2026-11-02T11:34:35Z pack T1=278fb65a975ddfed8f75dde34e6fa9fcfc19ea3b205b408705c98e55900afa5c
2026-11-02T11:34:38Z load: 12 hogs in group 3407590
2026-11-02T18:24:35Z load: 12 of 12 hogs were alive when the last chain ended
2026-11-02T18:24:35Z determinism hermes-native: same
2026-11-02T18:24:36Z determinism holographic: same
2026-11-02T18:24:36Z determinism mem0-oss: same
2026-11-02T18:24:36Z done d10-loaded: runs_ok=1; T1=278fb65a975ddfed8f75dde34e6fa9fcfc19ea3b205b408705c98e55900afa5c; packing receipts, cards, log and load
```

## Idle against loaded, card by card

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

## Gate verdicts

Printed by `gates_d10.py` from each card. The wiped-store control must fail T1's gate in every run; if it passed, the run would be invalid (RING0 §5).

| Host | System | Run | Arm | Gate verdict | Run status |
|---|---|---|---|---|---|
| idle | hermes-native | base | system | `CONFORMANCE_PASS` | `COMPLETE` |
| idle | hermes-native | base | wiped | `FAIL` | `COMPLETE` |
| idle | hermes-native | run1 | system | `PASS` | `COMPLETE` |
| idle | hermes-native | run1 | wiped | `FAIL` | `COMPLETE` |
| idle | holographic | base | system | `CONFORMANCE_PASS` | `COMPLETE` |
| idle | holographic | base | wiped | `FAIL` | `COMPLETE` |
| idle | holographic | run1 | system | `PASS` | `COMPLETE` |
| idle | holographic | run1 | wiped | `FAIL` | `COMPLETE` |
| idle | mem0-oss | base | system | `CONFORMANCE_PASS` | `COMPLETE` |
| idle | mem0-oss | base | wiped | `FAIL` | `COMPLETE` |
| idle | mem0-oss | run1 | system | `PASS` | `COMPLETE` |
| idle | mem0-oss | run1 | wiped | `FAIL` | `COMPLETE` |
| loaded | hermes-native | base | system | `CONFORMANCE_PASS` | `COMPLETE` |
| loaded | hermes-native | base | wiped | `FAIL` | `COMPLETE` |
| loaded | hermes-native | run1 | system | `PASS` | `COMPLETE` |
| loaded | hermes-native | run1 | wiped | `FAIL` | `COMPLETE` |
| loaded | holographic | base | system | `CONFORMANCE_PASS` | `COMPLETE` |
| loaded | holographic | base | wiped | `FAIL` | `COMPLETE` |
| loaded | holographic | run1 | system | `PASS` | `COMPLETE` |
| loaded | holographic | run1 | wiped | `FAIL` | `COMPLETE` |
| loaded | mem0-oss | base | system | `CONFORMANCE_PASS` | `COMPLETE` |
| loaded | mem0-oss | base | wiped | `FAIL` | `COMPLETE` |
| loaded | mem0-oss | run1 | system | `PASS` | `COMPLETE` |
| loaded | mem0-oss | run1 | wiped | `FAIL` | `COMPLETE` |

Source: each card.json's gate_verdict and run_status. Expected by design: the system arm reads CONFORMANCE_PASS on a base run (no baseline yet) and PASS on run1; the wiped-store control must FAIL.

`gates_d10.py` exit status: 0 (0: every verdict and run status as expected by design).

## Wall times

Printed by `t1loop_numbers.py` from the runs' own receipts, with the field each number comes from.

### Per run

| Code | System | Run | W | No-memory arm | System arm | Wiped arm | Outside the arms |
|---|---|---|---|---|---|---|---|
| 436750e-idle | hermes-native | base | 3,712 s | 123 s | 1,297 s | 1,308 s | 983 s (26%) |
| 436750e-idle | hermes-native | run1 | 3,761 s | 126 s | 1,302 s | 1,322 s | 1,012 s (27%) |
| 436750e-idle | holographic | base | 3,768 s | 123 s | 1,315 s | 1,314 s | 1,016 s (27%) |
| 436750e-idle | holographic | run1 | 3,800 s | 123 s | 1,321 s | 1,327 s | 1,029 s (27%) |
| 436750e-idle | mem0-oss | base | 5,174 s | 125 s | 1,512 s | 1,512 s | 2,025 s (39%) |
| 436750e-idle | mem0-oss | run1 | 5,177 s | 125 s | 1,516 s | 1,523 s | 2,012 s (39%) |
| 436750e-loaded | hermes-native | base | 8,991 s | 203 s | 1,679 s | 1,719 s | 5,390 s (60%) |
| 436750e-loaded | hermes-native | run1 | 8,980 s | 201 s | 1,688 s | 1,720 s | 5,371 s (60%) |
| 436750e-loaded | holographic | base | 9,153 s | 199 s | 1,712 s | 1,741 s | 5,501 s (60%) |
| 436750e-loaded | holographic | run1 | 9,134 s | 201 s | 1,724 s | 1,740 s | 5,470 s (60%) |
| 436750e-loaded | mem0-oss | base | 12,346 s | 204 s | 2,003 s | 2,033 s | 8,107 s (66%) |
| 436750e-loaded | mem0-oss | run1 | 12,246 s | 204 s | 2,005 s | 2,023 s | 8,013 s (65%) |

Source: each run's system and wiped receipt.json: wall_end_ms − wall_start_ms, and timings[] (pin_check_ms, sessions[].wall), slower branch per arm and life.

### Critical path (per arm and life, the slower branch; summed)

| Code | System | Run | Waits after turns | Waits at session ends | Turns | Opening sessions | Spawn and import | Close | Pin checks, gates, resume, workspace |
|---|---|---|---|---|---|---|---|---|---|
| 436750e-idle | hermes-native | base | 1,290 s (35%; 430 waits) | 330 s (9%; 110) | 552 s | 391 s | 75 s | 81 s | 28 s |
| 436750e-idle | hermes-native | run1 | 1,290 s (34%; 430 waits) | 330 s (9%; 110) | 555 s | 401 s | 76 s | 86 s | 29 s |
| 436750e-idle | holographic | base | 1,290 s (34%; 430 waits) | 330 s (9%; 110) | 560 s | 400 s | 74 s | 85 s | 30 s |
| 436750e-idle | holographic | run1 | 1,290 s (34%; 430 waits) | 330 s (9%; 110) | 564 s | 409 s | 76 s | 89 s | 32 s |
| 436750e-idle | mem0-oss | base | 1,500 s (29%; 430 waits) | 330 s (6%; 110) | 588 s | 531 s | 74 s | 114 s | 34 s |
| 436750e-idle | mem0-oss | run1 | 1,500 s (29%; 430 waits) | 330 s (6%; 110) | 591 s | 540 s | 76 s | 116 s | 35 s |
| 436750e-loaded | hermes-native | base | 1,290 s (14%; 430 waits) | 330 s (4%; 110) | 732 s | 910 s | 170 s | 145 s | 66 s |
| 436750e-loaded | hermes-native | run1 | 1,291 s (14%; 430 waits) | 330 s (4%; 110) | 733 s | 917 s | 171 s | 144 s | 67 s |
| 436750e-loaded | holographic | base | 1,290 s (14%; 430 waits) | 330 s (4%; 110) | 754 s | 924 s | 170 s | 153 s | 69 s |
| 436750e-loaded | holographic | run1 | 1,291 s (14%; 430 waits) | 330 s (4%; 110) | 754 s | 935 s | 171 s | 152 s | 69 s |
| 436750e-loaded | mem0-oss | base | 1,495 s (12%; 430 waits) | 330 s (3%; 110) | 797 s | 1,229 s | 169 s | 192 s | 80 s |
| 436750e-loaded | mem0-oss | run1 | 1,495 s (12%; 430 waits) | 330 s (3%; 110) | 794 s | 1,225 s | 167 s | 193 s | 79 s |

Source: receipt.json timings[].sessions[]: drain (the last entry is the session-end wait), turn, open, spawn (which includes import), close, and the remaining timers. Overlapping timers are not added to each other.

### 436750e-loaded against 436750e-idle

| System | Run | W before | W after | Saved |
|---|---|---|---|---|
| hermes-native | base | 3,712 s | 8,991 s | -5,279 s (-142%) |
| hermes-native | run1 | 3,761 s | 8,980 s | -5,219 s (-139%) |
| holographic | base | 3,768 s | 9,153 s | -5,385 s (-143%) |
| holographic | run1 | 3,800 s | 9,134 s | -5,334 s (-140%) |
| mem0-oss | base | 5,174 s | 12,346 s | -7,173 s (-139%) |
| mem0-oss | run1 | 5,177 s | 12,246 s | -7,068 s (-137%) |

## Files

| Host | Run | Arm | card.json sha256 | receipt.json sha256 |
|---|---|---|---|---|
| idle | hermes-native/base | system | `18e6011b1f3005155c4c0d57c370ed877a31e93a7a6bd1920045d7c5bffce08f` | `bdc468811ed5c76006330447e1c9d55d6e720bfeb6fd7a03321b5b79f2b7e0da` |
| idle | hermes-native/base | wiped | `42629388a53c52e0d9426eda10736bf705f263b1219517b63e896dab68475ce2` | `41f26b6852588c815803557f599046e24a8bd613055b61c21588108d207d7d9d` |
| idle | hermes-native/run1 | system | `60eff0c2e5fc36aa450c2f196d47c276c3f44811a6bb8556785a1a60e368ea54` | `8728b6d3f2901908e9720bc26aa34a0b5c27d3a66a86c4095a5ee99515b610e0` |
| idle | hermes-native/run1 | wiped | `42629388a53c52e0d9426eda10736bf705f263b1219517b63e896dab68475ce2` | `13c0815ecd217cb602526c2b6cc6df28ba75558ae17a682fcb9fad84e2025654` |
| idle | holographic/base | system | `44cda9773feccba1d2af0b52aca76b1f895d9714699f4d17864d2eb02e75fd2e` | `daf0b9daa933f697efea9b78929e81cd3941b47fa2e799c073f04fa2fae464ed` |
| idle | holographic/base | wiped | `0497765596ea02c9a55ca6db1b99c7ad28bdf01fd8eacc193346bf35f651903f` | `6a952f846b7cc17c1835f92b40444e57febccd586ebd269a910b8052fdf5ad25` |
| idle | holographic/run1 | system | `1a4d4a903c326190c24763114418d0075031d64e390dcacc13c9aa19259b8ffe` | `b3fe39eebd8b7c9af2246cdf46ae5bd694ee4e46c1cf7dbf747fc3b1aa841d84` |
| idle | holographic/run1 | wiped | `0497765596ea02c9a55ca6db1b99c7ad28bdf01fd8eacc193346bf35f651903f` | `099a197ded0d27dff2ee0dc9262761fdaaacf1495e5dde05eff47cb75daa7644` |
| idle | mem0-oss/base | system | `200d37fbcc03fcbb87298796e66fa81c2b549f141c575981c90a982ab08405e6` | `96394b09bc75929dba223395080564a873212bca1a33a4b6c713f2c6cf8d743f` |
| idle | mem0-oss/base | wiped | `f681e3a4c89be0721f3c621508149fddf826b2bebbf28c030aa237cbd27cc43e` | `c873a194e0ea11c6fb996e8253d0c7f7a6c7ec999eb8119e6a2807eb5a292452` |
| idle | mem0-oss/run1 | system | `65bdbd4ef7c5e71477353cac2db356703647e51cb6c89a91ba55af32c24a6a84` | `d7c110017117806902cac0ca1173487c7b91093ec0293d64f304e489e3ec9cd1` |
| idle | mem0-oss/run1 | wiped | `f681e3a4c89be0721f3c621508149fddf826b2bebbf28c030aa237cbd27cc43e` | `63db3c2ada8717e5d671d4878036a81a3110ab795a266d59491e65d785ede7a3` |
| loaded | hermes-native/base | system | `18e6011b1f3005155c4c0d57c370ed877a31e93a7a6bd1920045d7c5bffce08f` | `f64d1d3b9d76e748a1b25d8ba6b987f76499e3bb3acac800e626ab9d16ef4049` |
| loaded | hermes-native/base | wiped | `42629388a53c52e0d9426eda10736bf705f263b1219517b63e896dab68475ce2` | `21e9c49a14a4ff5668bb2381d677c3e4b5de6d8e4dab5a169be258a6c22861a1` |
| loaded | hermes-native/run1 | system | `60eff0c2e5fc36aa450c2f196d47c276c3f44811a6bb8556785a1a60e368ea54` | `b32cee69750fb4012165f9d0fae865e9ac804fd6368b43877f34b713eb3ba426` |
| loaded | hermes-native/run1 | wiped | `42629388a53c52e0d9426eda10736bf705f263b1219517b63e896dab68475ce2` | `36ff91fee396f8e7d095c338b2545809666d4e3c5aa8b7058b92c09ccf7d1e10` |
| loaded | holographic/base | system | `44cda9773feccba1d2af0b52aca76b1f895d9714699f4d17864d2eb02e75fd2e` | `e94d9a63ce721961b2282dac92783dabb564986e0c3611433c56dd26d3786c65` |
| loaded | holographic/base | wiped | `0497765596ea02c9a55ca6db1b99c7ad28bdf01fd8eacc193346bf35f651903f` | `0f25e6821052b359b044771398654d59c686becf1882ae65dc51dd19586ca522` |
| loaded | holographic/run1 | system | `1a4d4a903c326190c24763114418d0075031d64e390dcacc13c9aa19259b8ffe` | `d6c1ba787bd35938d0a23383c0f675fd81b4a0d3e8ab5a82b8a9490674c51ef8` |
| loaded | holographic/run1 | wiped | `0497765596ea02c9a55ca6db1b99c7ad28bdf01fd8eacc193346bf35f651903f` | `3b369f9b813f040fca4e0980eb691b168f76e5b6f04719278383e6067502ffb8` |
| loaded | mem0-oss/base | system | `200d37fbcc03fcbb87298796e66fa81c2b549f141c575981c90a982ab08405e6` | `09393c3ab58541d6332dfbd21273e0dbd7e3a7026fc753a791bc3263d7c01fd1` |
| loaded | mem0-oss/base | wiped | `f681e3a4c89be0721f3c621508149fddf826b2bebbf28c030aa237cbd27cc43e` | `27e10e3db33021a46554fa1db93769ed2165117464fe1bacd69acf3775059fc7` |
| loaded | mem0-oss/run1 | system | `65bdbd4ef7c5e71477353cac2db356703647e51cb6c89a91ba55af32c24a6a84` | `4efbd612f6887b69f11b1a308b27ebfabcd88168f3e60bea18e07d2948fd5318` |
| loaded | mem0-oss/run1 | wiped | `f681e3a4c89be0721f3c621508149fddf826b2bebbf28c030aa237cbd27cc43e` | `f27550f94730e24ef6c9726b8051a27df440beb0fdb5b294c0f40ed524cbb197` |
