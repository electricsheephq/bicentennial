# Bicentennial v0.2 Developer loop: T2-lite live runs A and A′, Hermes native

Claim class: live acceptance of the T2-lite developer loop on one system (Hermes native) and one pinned model; not predictive of the full tier; never certifies.

- Benchmark commit: `c9bf10b7f56b0727fc4f018d664f364886c4db39`
- T1 pack hash: `b00461736678eae27d494f8bd54a95f12d1b47dc6382eb5440f4c2771d84625a`
- Commands: `bicentennial t2lite --system hermes-native --packs <T1 install> --pack-hash <hash> --hermes <registry pin> --login-home <login home> --max-sends 410 --cache <cache> --out A`, then the same with `--aa-of A --baseline A --out A-prime`.
- Receipts here drop three machine-local fields (`temporary_paths`, `process_ids`, `ports`); every other field is as written.
- Full run trees: the private evidence store, tag `bicentennial/t2lite-l6b-20261102`.

Every number below is printed by `l6b_numbers.py` from the runs' own files, with the file and field it comes from.

### A

| Number | Value | Source |
|---|---|---|
| tier, system | `T2-lite, hermes-native` | card.json tier, system |
| model, effort | `gpt-6.1-sol, medium` | card.json model, effort |
| served identity | `{"gpt-6.1-sol":"gpt-6.1-sol"}` | card.json served_identity |
| benchmark commit | `c9bf10b7f56b0727fc4f018d664f364886c4db39` | card.json pins.benchmark_commit |
| pack hash | `b00461736678eae27d494f8bd54a95f12d1b47dc6382eb5440f4c2771d84625a` | card.json pack_hash |
| marked as a repeat (A′) | `false` | card.json aa_prime |
| items | `17` | card.json items |
| items with a score | `11` | card.json items[].score_milli not null |
| failure classes | `{"FAIL_TASK": 3}` | card.json items[].failure_class |
| G2 actions not scored live | `6` | card.json not_scored_live |
| no-memory floor reused from the cache | `false` | card.json counts.floor_cached |
| run status | `COMPLETE` | receipt.json run_status |
| wall time | `89.5 min (5369146 ms)` | receipt.json wall_end_ms − wall_start_ms |
| director requests (every role, both arms) | `1958` | len(receipt.json latency_ms) |
| tokens by role (input, output) | `{"aux": [34560, 1140], "probe_main": [868566, 12161], "replay_main": [4182645, 287082], "write_turn": [4600564, 5142]}` | receipt.json tokens_by_role[].role, input, output |
| tokens in all (input, output) | `[9686335, 305525]` | receipt.json tokens |
| spend | `0 micro-USD (zero-price accounting on a plan lane, not a free-service claim)` | receipt.json spend_micro_usd |
| live sends | `163` | disclosures.json live.sends |
| holds (waits, held_ms, reasons) | `{"held_ms": 0, "reasons": [], "waits": 0}` | disclosures.json live.holds |
| live stop reason (`closed` is a run's normal end) | `closed` | disclosures.json live.stop_reason |
| served-identity drift | `null` | disclosures.json live.identity_drift |

### A′

| Number | Value | Source |
|---|---|---|
| tier, system | `T2-lite, hermes-native` | card.json tier, system |
| model, effort | `gpt-6.1-sol, medium` | card.json model, effort |
| served identity | `{"gpt-6.1-sol":"gpt-6.1-sol"}` | card.json served_identity |
| benchmark commit | `c9bf10b7f56b0727fc4f018d664f364886c4db39` | card.json pins.benchmark_commit |
| pack hash | `b00461736678eae27d494f8bd54a95f12d1b47dc6382eb5440f4c2771d84625a` | card.json pack_hash |
| marked as a repeat (A′) | `true` | card.json aa_prime |
| items | `17` | card.json items |
| items with a score | `11` | card.json items[].score_milli not null |
| failure classes | `{"FAIL_TASK": 3}` | card.json items[].failure_class |
| G2 actions not scored live | `6` | card.json not_scored_live |
| no-memory floor reused from the cache | `true` | card.json counts.floor_cached |
| run status | `COMPLETE` | receipt.json run_status |
| wall time | `72.2 min (4333224 ms)` | receipt.json wall_end_ms − wall_start_ms |
| director requests (every role, both arms) | `1737` | len(receipt.json latency_ms) |
| tokens by role (input, output) | `{"aux": [29482, 970], "probe_main": [600139, 6654], "replay_main": [4182645, 287082], "write_turn": [4600564, 5142]}` | receipt.json tokens_by_role[].role, input, output |
| tokens in all (input, output) | `[9412830, 299848]` | receipt.json tokens |
| spend | `0 micro-USD (zero-price accounting on a plan lane, not a free-service claim)` | receipt.json spend_micro_usd |
| live sends | `90` | disclosures.json live.sends |
| holds (waits, held_ms, reasons) | `{"held_ms": 0, "reasons": [], "waits": 0}` | disclosures.json live.holds |
| live stop reason (`closed` is a run's normal end) | `closed` | disclosures.json live.stop_reason |
| served-identity drift | `null` | disclosures.json live.identity_drift |
| flip list counts | `{"aa_prime_scored": 11, "excluded": 6, "flips": 0, "items": 17, "scored": 11, "unstable": 0}` | flips.json counts |
| q₀ (a reduced fraction, as written) | `0/1 (0 milli)` | flips.json q0 |
| q₀ unreduced: changed / items scored in both A and A′ | `0/11 (equals q₀: yes)` | flips.json counts.unstable, counts.aa_prime_scored |
| “no A/A′ band” label | `false` | flips.json labels |
| excluded, by reason | `{"not_scored_live": 6}` | flips.json excluded[].reason |

## Files

| File | sha256 |
|---|---|
| `A/card.json` | `4fe33bbba64ae657df0802026be37a6a382106128ddeae9715a1c9c9e1aa584d` |
| `A/disclosures.json` | `d22b1d30338c98052f4b521abe3f525a3508e20b523465750500580d961ec948` |
| `A/receipt.json` | `515d083acbd2f8a28ccf63fb940f26b35700aa8b815bbbb1fab0604642f76c52` |
| `A-prime/card.json` | `30fc57604b519ce4ce28eff16a10c6efd88ae64452d7cc2306da12ccd5e9d411` |
| `A-prime/disclosures.json` | `56977da64ef3470f855e1662392ae159fa37a38495677c0cc59b6f556be6ada9` |
| `A-prime/flips.json` | `94274f928bc1ff952c6d846ce34adba2ddfa87c2a0c0fd5c89d6ba2113b9ad15` |
| `A-prime/receipt.json` | `d26f24226cbf8d8974092c120b1d67edc2e29aa00b583d65797839dfb78819e6` |

Unedited receipts (sha256 of the files in the evidence store): A `774d1de812864e806350f2d2bd6e65555b871ed49d7fdd47d128b0c15544f8b7`, A′ `7e6977fc96a4fb1ab8e8b843f92e767db1c2d034af2f4a612c7493d01dca51ea`.
