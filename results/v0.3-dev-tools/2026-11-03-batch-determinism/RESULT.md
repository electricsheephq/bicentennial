# Bicentennial v0.3 kit batch: T1's determinism on the rebuilt packs, idle and under load

Claim class: a determinism check of T1 at one commit on two dedicated Linux hosts, one idle and one under induced load; not a developer-machine measurement; not predictive of the full tier; never certifies.

- Release code commit: `e687fdb9d7782fc692df3d60d882ac2eb6e81026`. T1 pack hash: `475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7` (idle host), `475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7` (loaded host).
- Each host ran three chains at once, one per reference system; each chain ran T1 twice (base, then run1), and the run script compared run1's cards with base's.
- Full run trees (cards, receipts, logs and load samples): the private evidence store, tag `bicentennial/kit-batch-determinism-20261103`. Receipts are not published here: they hold machine-local fields.

## Each host's verdict lines

Printed from each host's own log: the pack it built, the load it held, the run script's run1-against-base card comparison per system (`same` allows only the gate verdict, which differs by design: base is CONFORMANCE_PASS and run1 PASS), and the run's end.

Idle host:

```
2026-11-03T08:58:57Z pack T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7
2026-11-03T11:52:26Z determinism hermes-native: same
2026-11-03T11:52:26Z determinism holographic: same
2026-11-03T11:52:26Z determinism mem0-oss: same
2026-11-03T11:52:26Z done b10-idle: runs_ok=1; T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7; packing receipts, cards, log and load
```

Loaded host:

```
2026-11-03T08:59:29Z pack T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7
2026-11-03T08:59:32Z load: 12 hogs in group 339237
2026-11-03T15:50:33Z load: 12 of 12 hogs were alive when the last chain ended
2026-11-03T15:50:33Z determinism hermes-native: same
2026-11-03T15:50:33Z determinism holographic: same
2026-11-03T15:50:34Z determinism mem0-oss: same
2026-11-03T15:50:34Z done b10-loaded: runs_ok=1; T1=475a8403952fc5dd5bd2e6c4ed2b76edf326ff6da3d1bc559433d3c5a30292b7; packing receipts, cards, log and load
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

Printed by `gates_b10.py` from each card. The wiped-store control must fail T1's gate in every run; if it passed, the run would be invalid (RING0 §5).

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

`gates_b10.py` exit status: 0 (0: every verdict and run status as expected by design).

## Wall times

Printed by `t1loop_numbers.py` from the runs' own receipts, with the field each number comes from.

### Per run

| Code | System | Run | W | No-memory arm | System arm | Wiped arm | Outside the arms |
|---|---|---|---|---|---|---|---|
| e687fdb-idle | hermes-native | base | 3,713 s | 122 s | 1,294 s | 1,309 s | 988 s (27%) |
| e687fdb-idle | hermes-native | run1 | 3,709 s | 124 s | 1,294 s | 1,306 s | 985 s (27%) |
| e687fdb-idle | holographic | base | 3,775 s | 122 s | 1,309 s | 1,318 s | 1,026 s (27%) |
| e687fdb-idle | holographic | run1 | 3,776 s | 124 s | 1,314 s | 1,315 s | 1,024 s (27%) |
| e687fdb-idle | mem0-oss | base | 5,205 s | 124 s | 1,509 s | 1,512 s | 2,060 s (40%) |
| e687fdb-idle | mem0-oss | run1 | 5,201 s | 125 s | 1,505 s | 1,515 s | 2,055 s (40%) |
| e687fdb-loaded | hermes-native | base | 8,911 s | 197 s | 1,668 s | 1,701 s | 5,344 s (60%) |
| e687fdb-loaded | hermes-native | run1 | 8,915 s | 198 s | 1,668 s | 1,708 s | 5,341 s (60%) |
| e687fdb-loaded | holographic | base | 9,078 s | 197 s | 1,694 s | 1,724 s | 5,463 s (60%) |
| e687fdb-loaded | holographic | run1 | 9,085 s | 197 s | 1,703 s | 1,729 s | 5,455 s (60%) |
| e687fdb-loaded | mem0-oss | base | 12,283 s | 200 s | 1,994 s | 2,020 s | 8,069 s (66%) |
| e687fdb-loaded | mem0-oss | run1 | 12,372 s | 201 s | 1,999 s | 2,025 s | 8,148 s (66%) |

Source: each run's system and wiped receipt.json: wall_end_ms − wall_start_ms, and timings[] (pin_check_ms, sessions[].wall), slower branch per arm and life.

### Critical path (per arm and life, the slower branch; summed)

| Code | System | Run | Waits after turns | Waits at session ends | Turns | Opening sessions | Spawn and import | Close | Pin checks, gates, resume, workspace |
|---|---|---|---|---|---|---|---|---|---|
| e687fdb-idle | hermes-native | base | 1,290 s (35%; 430 waits) | 330 s (9%; 110) | 552 s | 390 s | 74 s | 80 s | 28 s |
| e687fdb-idle | hermes-native | run1 | 1,290 s (35%; 430 waits) | 330 s (9%; 110) | 552 s | 388 s | 74 s | 81 s | 28 s |
| e687fdb-idle | holographic | base | 1,290 s (34%; 430 waits) | 330 s (9%; 110) | 559 s | 399 s | 75 s | 84 s | 31 s |
| e687fdb-idle | holographic | run1 | 1,290 s (34%; 430 waits) | 330 s (9%; 110) | 560 s | 400 s | 74 s | 86 s | 30 s |
| e687fdb-idle | mem0-oss | base | 1,499 s (29%; 430 waits) | 330 s (6%; 110) | 588 s | 530 s | 75 s | 112 s | 34 s |
| e687fdb-idle | mem0-oss | run1 | 1,500 s (29%; 430 waits) | 330 s (6%; 110) | 587 s | 528 s | 75 s | 112 s | 36 s |
| e687fdb-loaded | hermes-native | base | 1,290 s (14%; 430 waits) | 330 s (4%; 110) | 721 s | 896 s | 166 s | 140 s | 66 s |
| e687fdb-loaded | hermes-native | run1 | 1,290 s (14%; 430 waits) | 330 s (4%; 110) | 725 s | 896 s | 168 s | 142 s | 65 s |
| e687fdb-loaded | holographic | base | 1,290 s (14%; 430 waits) | 330 s (4%; 110) | 744 s | 907 s | 168 s | 146 s | 69 s |
| e687fdb-loaded | holographic | run1 | 1,290 s (14%; 430 waits) | 330 s (4%; 110) | 751 s | 912 s | 168 s | 148 s | 71 s |
| e687fdb-loaded | mem0-oss | base | 1,492 s (12%; 430 waits) | 330 s (3%; 110) | 791 s | 1,215 s | 168 s | 189 s | 80 s |
| e687fdb-loaded | mem0-oss | run1 | 1,496 s (12%; 430 waits) | 330 s (3%; 110) | 792 s | 1,219 s | 168 s | 191 s | 81 s |

Source: receipt.json timings[].sessions[]: drain (the last entry is the session-end wait), turn, open, spawn (which includes import), close, and the remaining timers. Overlapping timers are not added to each other.

### e687fdb-loaded against e687fdb-idle

| System | Run | W idle | W loaded | Idle minus loaded |
|---|---|---|---|---|
| hermes-native | base | 3,713 s | 8,911 s | -5,198 s (-140%) |
| hermes-native | run1 | 3,709 s | 8,915 s | -5,206 s (-140%) |
| holographic | base | 3,775 s | 9,078 s | -5,304 s (-141%) |
| holographic | run1 | 3,776 s | 9,085 s | -5,308 s (-141%) |
| mem0-oss | base | 5,205 s | 12,283 s | -7,078 s (-136%) |
| mem0-oss | run1 | 5,201 s | 12,372 s | -7,172 s (-138%) |

A negative value is the extra time the loaded host took.

## Files

| Host | Run | Arm | card.json sha256 | receipt.json sha256 |
|---|---|---|---|---|
| idle | hermes-native/base | system | `4c832f9263b9642ee1f43a0bf51bf0e4393140b741e75e0f5a71e776c671a36d` | `589e5e43af7e05b4356422454b6d85d3746e89b2b6e6556dcc0ce86965690815` |
| idle | hermes-native/base | wiped | `6852686b678e952c139a8f6991dd04b7098d322f66b81fa8358370c87f75cdb2` | `63ac15cb4d4241a6a50f16f200f2004304f4b82ea815a9ceab06e5f1da199f52` |
| idle | hermes-native/run1 | system | `4a0c7321094aac21155b3384fc8e8ec8c2f85dc3bc7eb3700060f49d8e92a1fe` | `145cf18b9f43887e84d6d8b5d42aefc4a0ad95ccd97eec0e9038dccdfd1076bc` |
| idle | hermes-native/run1 | wiped | `6852686b678e952c139a8f6991dd04b7098d322f66b81fa8358370c87f75cdb2` | `6695348a616262b436e6a8e8b334cc8d5d48b31fcdd4b587d3af155f85b1ebf8` |
| idle | holographic/base | system | `957da6144dc6a98cd78ed206b0131e2ffc82094ae312bc9eaff1b8146cdb68cf` | `0698741472b35afde1634dae8fe3ff11c13ff177a20bd84316dba78168fad363` |
| idle | holographic/base | wiped | `2f068dd5d2802705423154d647c48029d038cad3294732b37ecff5abb36840ec` | `8b62c17428f226226777861d9e32a074f1e78aa2012109c6d7ff966802d0cd69` |
| idle | holographic/run1 | system | `006e9dff7e7b9c1942d1c0d9e0529e1924cb67a3f80f114aba38ee840550818b` | `a1a2cad8143a22a132bd0877e41d6af00950db64cb5bba5433c682ffe7ff35a5` |
| idle | holographic/run1 | wiped | `2f068dd5d2802705423154d647c48029d038cad3294732b37ecff5abb36840ec` | `7e58bed6f5b87a030d1ea8f110ad50745176e9dde50485352ca5711823edee88` |
| idle | mem0-oss/base | system | `ec675c5ff22475a68ec5b9197b82fa3dcbc3ef6f449247802366cc6e99c6a80d` | `e5ce911cddea76fd87eaf04562a26daaf1f423a0cdd55b0bdb07f2e8deb4c781` |
| idle | mem0-oss/base | wiped | `ae90459fe288651622b420aaa88f35c1a10211f9089325d90dbbfc0518c7cad7` | `93e7273ca285070546a27620f29c1e97be38397291e407e4409f3dc76ff70d46` |
| idle | mem0-oss/run1 | system | `68749da263b33c45875e080447e70bbf20800320c66c983a6ec6bdb2031f5b09` | `cf21750cc12278b682507ca32c24974bb60020d5b6c9969e90e41b936f54b431` |
| idle | mem0-oss/run1 | wiped | `ae90459fe288651622b420aaa88f35c1a10211f9089325d90dbbfc0518c7cad7` | `99d2e57e94a622415b4c5fa92754fdba52c1304f22221fd864628217343421ae` |
| loaded | hermes-native/base | system | `4c832f9263b9642ee1f43a0bf51bf0e4393140b741e75e0f5a71e776c671a36d` | `98664b68f959872f8e05db812f253453f2e94fcd9bd898cd4fcabfc99771b9a9` |
| loaded | hermes-native/base | wiped | `6852686b678e952c139a8f6991dd04b7098d322f66b81fa8358370c87f75cdb2` | `6ba2e10e61df79ab15a21f934e50eb85d6284c6e41337ab8c8f88de70466f0ac` |
| loaded | hermes-native/run1 | system | `4a0c7321094aac21155b3384fc8e8ec8c2f85dc3bc7eb3700060f49d8e92a1fe` | `6e1255fee4baebd6780636b86e4be3b120b173d91181bf4272f216d154034557` |
| loaded | hermes-native/run1 | wiped | `6852686b678e952c139a8f6991dd04b7098d322f66b81fa8358370c87f75cdb2` | `a173a4e505d662a6e8cf78b7999cf0b5ad90701a1fb440e477406e7fbe1fbff0` |
| loaded | holographic/base | system | `957da6144dc6a98cd78ed206b0131e2ffc82094ae312bc9eaff1b8146cdb68cf` | `32bd17f87a3ee99a20e21c6796964ffff920bc88edda31a9eed29cfe05869386` |
| loaded | holographic/base | wiped | `2f068dd5d2802705423154d647c48029d038cad3294732b37ecff5abb36840ec` | `9ac21ee733754c2cd44b0a948574ff23dbb82bcaff964731071cd668db30c8c3` |
| loaded | holographic/run1 | system | `006e9dff7e7b9c1942d1c0d9e0529e1924cb67a3f80f114aba38ee840550818b` | `f7e03a7be79dcbf514a4bc8d213b0ccacbac49f948c815b9fcd4911f981505f8` |
| loaded | holographic/run1 | wiped | `2f068dd5d2802705423154d647c48029d038cad3294732b37ecff5abb36840ec` | `f3fd9d6bff6907c81261535d221314cb36f5913b1909b67dc5ec99de266e837c` |
| loaded | mem0-oss/base | system | `ec675c5ff22475a68ec5b9197b82fa3dcbc3ef6f449247802366cc6e99c6a80d` | `bba61bd0e13e1acf3b5fba3a7139f2779fbc0f17e14f977a3c6ccf1c2355f47d` |
| loaded | mem0-oss/base | wiped | `ae90459fe288651622b420aaa88f35c1a10211f9089325d90dbbfc0518c7cad7` | `032cf3e773c5a7e26150651dd9b3fc95a5b75615b2d569a5480c833fdee62dc1` |
| loaded | mem0-oss/run1 | system | `68749da263b33c45875e080447e70bbf20800320c66c983a6ec6bdb2031f5b09` | `e739259d272c7d94674ec5aaa07fc0e8dfbe0d7067c6957a7dc0fa30f26a91b5` |
| loaded | mem0-oss/run1 | wiped | `ae90459fe288651622b420aaa88f35c1a10211f9089325d90dbbfc0518c7cad7` | `34aed68972591ba0b8560e7695780acd16170f63e6ee1c547cba033996428fb5` |
