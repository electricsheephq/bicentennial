# Bicentennial v0.3: the first measured live T2 arm (#391)

Claim class: one live T2 run of Hermes native on the public T2 pack, on a shared developer Mac, with the runner in macOS's background band; a timing and smoke measurement, not a comparison of systems; not predictive of the full tier; never certifies.

- Code commit: `ac81423de4bceda65952cd44a3934e67105becd6`, which is `main` at #472 (`f7238b2`) plus the fix for #476. T2 pack hash: `15141b194ab8abf389af2bfdbb4fd81e4d511fca14c54508d613fbe156628c04`.
- **The run:** 2026-11-04, 12:45:00Z to 14:35:14Z, exit 0, run status COMPLETE. Hermes native at the registry's pinned Hermes (v0.22.2, `systems/registry/hermes-native.toml`); the live model `gpt-6.1-sol` at effort `medium`; 8 parallel slots; a send bound of 1,000. The no-memory floor ran live beside the system arm (every floor unit was a cache miss).
- Full run tree (card, outcomes, floor rows, kept pre-probe copies, `units.json`, receipts, custody, disclosures and spend): the private evidence store, tag `bicentennial/t2-live-arm-20261104`. Receipts are not published here: they hold machine-local fields.
- The first attempt, at 11:04Z on `ca74302` (`main` before #472, which changes only CI files), stopped at 11:34Z in the live act stage (#476) and wrote no card. Nothing from it is used here.

## The arm's time

Printed by `t2live_numbers.py` (beside this file), which reads `card.json`, `units.json`, `spend.json` and `receipt.json` and recomputes each arm's time from `units.json` with the runner's own `calculate_arm_times` (RING0 §14.8 and its 2026-11-04 errata). A unit is one branch of one life, with every attempt it took; times are on the run's monotonic clock from its start. `predicted` is the runner's own `predicted_seconds` (43 s per replay session, 49 s per probe session), which orders the replay.

```
tier T2 system hermes-native pack_hash 15141b194ab8
slots 8 admitted 8
wall 110.2 min monotonic 110.2 min
arm system: arm_time 96.2 min (5771559 ms; recomputed 5771559 ms, equal); replay 95.9 min; outside units 0.3 min; 20 units; over the 1 h target (1.60 h)
floor_replay 26.8 min
units no_memory: 20; span min 6.1 min, median 8.9 min, max 15.2 min; attempts 20; pre_probe 0.0 min; keep 0.0 min
units system: 20; span min 29.1 min, median 31.0 min, max 65.5 min; attempts 22; pre_probe 2.4 min; keep 2.0 min
  no_memory t2-g1-1 B0: span 13.7 min; predicted 245 s; attempts 1; slot 0; pre_probe 0.0 min; keep 0.0 min; start 65.7 min end 79.5 min
  no_memory t2-g1-1 B1: span 8.4 min; predicted 196 s; attempts 1; slot 2; pre_probe 0.0 min; keep 0.0 min; start 94.2 min end 102.6 min
  no_memory t2-g1-2 B0: span 15.2 min; predicted 245 s; attempts 1; slot 3; pre_probe 0.0 min; keep 0.0 min; start 65.9 min end 81.0 min
  no_memory t2-g1-2 B1: span 8.2 min; predicted 196 s; attempts 1; slot 1; pre_probe 0.0 min; keep 0.0 min; start 95.3 min end 103.4 min
  no_memory t2-g1-3 B0: span 13.4 min; predicted 245 s; attempts 1; slot 5; pre_probe 0.0 min; keep 0.0 min; start 78.4 min end 91.8 min
  no_memory t2-g1-3 B1: span 9.4 min; predicted 196 s; attempts 1; slot 4; pre_probe 0.0 min; keep 0.0 min; start 96.1 min end 105.5 min
  no_memory t2-g1-4 B0: span 13.3 min; predicted 245 s; attempts 1; slot 0; pre_probe 0.0 min; keep 0.0 min; start 79.5 min end 92.8 min
  no_memory t2-g1-4 B1: span 8.6 min; predicted 196 s; attempts 1; slot 5; pre_probe 0.0 min; keep 0.0 min; start 100.5 min end 109.1 min
  no_memory t2-g1-5 B0: span 12.5 min; predicted 245 s; attempts 1; slot 3; pre_probe 0.0 min; keep 0.0 min; start 81.0 min end 93.5 min
  no_memory t2-g1-5 B1: span 8.2 min; predicted 196 s; attempts 1; slot 0; pre_probe 0.0 min; keep 0.0 min; start 101.9 min end 110.1 min
  no_memory t2-g2-1 B0: span 8.7 min; predicted 245 s; attempts 1; slot 5; pre_probe 0.0 min; keep 0.0 min; start 91.8 min end 100.5 min
  no_memory t2-g2-1 B1: span 6.6 min; predicted 147 s; attempts 1; slot 6; pre_probe 0.0 min; keep 0.0 min; start 101.9 min end 108.6 min
  no_memory t2-g2-2 B0: span 9.5 min; predicted 245 s; attempts 1; slot 7; pre_probe 0.0 min; keep 0.0 min; start 92.5 min end 102.0 min
  no_memory t2-g2-2 B1: span 6.7 min; predicted 147 s; attempts 1; slot 7; pre_probe 0.0 min; keep 0.0 min; start 102.0 min end 108.6 min
  no_memory t2-g2-3 B0: span 9.1 min; predicted 245 s; attempts 1; slot 0; pre_probe 0.0 min; keep 0.0 min; start 92.8 min end 101.9 min
  no_memory t2-g2-3 B1: span 6.4 min; predicted 147 s; attempts 1; slot 2; pre_probe 0.0 min; keep 0.0 min; start 102.6 min end 109.1 min
  no_memory t2-g2-4 B0: span 9.1 min; predicted 245 s; attempts 1; slot 6; pre_probe 0.0 min; keep 0.0 min; start 92.8 min end 101.9 min
  no_memory t2-g2-4 B1: span 6.5 min; predicted 147 s; attempts 1; slot 3; pre_probe 0.0 min; keep 0.0 min; start 102.9 min end 109.3 min
  no_memory t2-g2-5 B0: span 9.3 min; predicted 245 s; attempts 1; slot 3; pre_probe 0.0 min; keep 0.0 min; start 93.5 min end 102.9 min
  no_memory t2-g2-5 B1: span 6.1 min; predicted 147 s; attempts 1; slot 1; pre_probe 0.0 min; keep 0.0 min; start 103.4 min end 109.5 min
  system t2-g1-1 B0: span 65.5 min; predicted 675 s; attempts 2; slot 0; pre_probe 0.3 min; keep 0.1 min; start 0.2 min end 65.7 min
  system t2-g1-1 B1: span 29.1 min; predicted 626 s; attempts 1; slot 2; pre_probe 0.1 min; keep 0.1 min; start 34.5 min end 63.6 min
  system t2-g1-2 B0: span 34.4 min; predicted 675 s; attempts 1; slot 1; pre_probe 0.1 min; keep 0.1 min; start 0.2 min end 34.6 min
  system t2-g1-2 B1: span 30.3 min; predicted 626 s; attempts 1; slot 1; pre_probe 0.1 min; keep 0.1 min; start 34.6 min end 64.9 min
  system t2-g1-3 B0: span 34.2 min; predicted 675 s; attempts 1; slot 2; pre_probe 0.1 min; keep 0.1 min; start 0.2 min end 34.5 min
  system t2-g1-3 B1: span 30.2 min; predicted 626 s; attempts 1; slot 4; pre_probe 0.1 min; keep 0.1 min; start 35.4 min end 65.6 min
  system t2-g1-4 B0: span 35.6 min; predicted 675 s; attempts 1; slot 3; pre_probe 0.2 min; keep 0.1 min; start 0.2 min end 35.8 min
  system t2-g1-4 B1: span 30.1 min; predicted 626 s; attempts 1; slot 3; pre_probe 0.1 min; keep 0.2 min; start 35.8 min end 65.9 min
  system t2-g1-5 B0: span 35.1 min; predicted 675 s; attempts 1; slot 4; pre_probe 0.1 min; keep 0.0 min; start 0.2 min end 35.4 min
  system t2-g1-5 B1: span 32.7 min; predicted 626 s; attempts 1; slot 5; pre_probe 0.3 min; keep 0.2 min; start 45.7 min end 78.4 min
  system t2-g2-1 B0: span 45.5 min; predicted 675 s; attempts 2; slot 5; pre_probe 0.1 min; keep 0.0 min; start 0.2 min end 45.7 min
  system t2-g2-1 B1: span 31.6 min; predicted 577 s; attempts 1; slot 7; pre_probe 0.1 min; keep 0.1 min; start 60.8 min end 92.5 min
  system t2-g2-2 B0: span 30.9 min; predicted 675 s; attempts 1; slot 6; pre_probe 0.1 min; keep 0.0 min; start 0.2 min end 31.2 min
  system t2-g2-2 B1: span 31.4 min; predicted 577 s; attempts 1; slot 6; pre_probe 0.1 min; keep 0.1 min; start 61.5 min end 92.8 min
  system t2-g2-3 B0: span 31.1 min; predicted 675 s; attempts 1; slot 7; pre_probe 0.4 min; keep 0.0 min; start 0.2 min end 31.3 min
  system t2-g2-3 B1: span 30.7 min; predicted 577 s; attempts 1; slot 2; pre_probe 0.0 min; keep 0.1 min; start 63.6 min end 94.2 min
  system t2-g2-4 B0: span 30.3 min; predicted 675 s; attempts 1; slot 6; pre_probe 0.1 min; keep 0.2 min; start 31.2 min end 61.5 min
  system t2-g2-4 B1: span 30.3 min; predicted 577 s; attempts 1; slot 1; pre_probe 0.0 min; keep 0.0 min; start 64.9 min end 95.3 min
  system t2-g2-5 B0: span 29.5 min; predicted 675 s; attempts 1; slot 7; pre_probe 0.1 min; keep 0.0 min; start 31.3 min end 60.8 min
  system t2-g2-5 B1: span 30.5 min; predicted 577 s; attempts 1; slot 4; pre_probe 0.0 min; keep 0.2 min; start 65.6 min end 96.1 min
```

The run's operating numbers, printed by the same script from `units.json`, `spend.json` and `receipt.json`: the summed unit time per arm; the summed time of the director's requests by role (`probe_main` is the live model; every other role is scripted at T2); tokens by role (input, output); the director's request latency; the load averages when the run ended; background requests per arm (`late`: arrived after the next turn began; `threads_at_turn_start`: turns that started with the system's background threads alive); and the receipt's status fields.

```
unit time summed {'no_memory': '188.9 min', 'system': '678.9 min'} total 867.8 min
director request time by role {'aux': '17.6 min', 'probe_main': '76.0 min', 'replay_main': '6.2 min', 'summariser': '0.0 min', 'unknown': '0.0 min', 'write_turn': '3.8 min'} total 103.6 min (12% of the summed unit time)
tokens by role {"aux": [128150, 3950], "probe_main": [5230165, 70392], "replay_main": [14405685, 1481430], "summariser": [35854, 897], "unknown": [0, 0], "write_turn": [15909129, 17031]}
latency_ms {"max": 48668, "n": 6037, "p50": 95, "p90": 4306, "p95": 5247}
load average at the run's end (1, 5, 15 min) [6.546, 12.709, 14.624]
background [{"arm": "no_memory", "late": {"count": 0, "max_delay_ms": null}, "threads_at_turn_start": {"count": 0, "max_alive": 0}, "unattributed": {"count": 368}}, {"arm": "system", "late": {"count": 0, "max_delay_ms": null}, "threads_at_turn_start": {"count": 839, "max_alive": 4}, "unattributed": {"count": 2162}}]
run_status COMPLETE turn_wait_s 3.0 spend_micro_usd 0 store_growth_bytes 39504888
```

## The card

Printed by `t2live_card_summary.py` (beside this file) from `card.json`: pins (first 12 characters), counts, items per genre, mean score per track and genre, failure classes, stages, the items not scored live, and every (track, genre, stage, score, failure class) count. It prints no answers.

```
tier T2 system hermes-native model gpt-6.1-sol effort medium aa_prime False
pack_hash 15141b194ab8 seed_hash 8e28303a4653
pins {"benchmark_commit": "ac81423de4bc", "director_commit": "ac81423de4bc", "generator_commit": "ac81423de4bc", "harness_hash": "dbf03edef301", "route_table_hash": "0490592ab5b0", "scorer_commit": "ac81423de4bc", "system_hash": "dbf03edef301", "write_turn_package_hash": "753f83e1bd00"}
counts {"floor_cached_units": 0, "infra": 0, "items.G1.act": 40, "items.G1.survive": 5, "items.G2.act": 30, "items.G2.survive": 10, "kept_copies": 26, "lives": 10, "not_scored_live": 30, "null_citation": 0, "units": 20}
items 85 lives 10 life x branch 20
items by genre {'G1': 45, 'G2': 40}
track Drift: n=35 mean_score_milli=314.3
track Recall: n=10 mean_score_milli=1000.0
track Wake: n=10 mean_score_milli=100.0
  Drift G1: n=30 mean=466.7
  Drift G2: n=5 mean=-600.0
  Recall G1: n=5 mean=1000.0
  Recall G2: n=5 mean=1000.0
  Wake G1: n=10 mean=100.0
unscored (no integer score_milli) 30
failure_class {'FAIL_TASK': 13, 'None': 72}
stage {'act': 70, 'survive': 15}
infra_reruns total 10
not_scored_live 30 by genre and stage {'G2 act': 30}
controls_broken []
floor units 20 floor identity equals system's True
items by track, genre, stage, score_milli and failure class:
   Drift G1 act -1000 None 3
   Drift G1 act 0 FAIL_TASK 10
   Drift G1 act 1000 None 17
   Drift G2 act None None 20
   Drift G2 survive -1000 None 4
   Drift G2 survive 1000 None 1
   Keep G2 act None None 10
   Recall G1 survive 1000 None 5
   Recall G2 survive 1000 None 5
   Wake G1 act 0 FAIL_TASK 3
   Wake G1 act 0 None 6
   Wake G1 act 1000 None 1
groups 6 labels.t2 "T2: live probe answers only; write turns, compaction, extraction and embeddings scripted; not predictive of the full tier; never certifies"
card counts {"floor_cached_units": 0, "infra": 0, "items.G1.act": 40, "items.G1.survive": 5, "items.G2.act": 30, "items.G2.survive": 10, "kept_copies": 26, "lives": 10, "not_scored_live": 30, "null_citation": 0, "units": 20}
items 85 not_scored_live 30
spend {"estimated": 0, "max_single_call": 0, "next_id": 896, "refused_calls": 0, "settled": 0, "settled_calls": 895}
```

## Disclosures and the run's log

From `disclosures.json`: no honeypot hits; 895 live sends; no hold, no identity drift, no login or spend stop; the live leg closed normally; no transforms; turn wait 3.0 s; every floor unit a cache miss. The run's error log holds 17 `ConnectionResetError: [Errno 54] Connection reset by peer` tracebacks, printed by the director's local HTTP server when a client closed its connection during a request. Two units (`t2-g1-1` B0 and `t2-g2-1` B0) took a second attempt; the card counts 10 items with an infrastructure rerun, and no item stayed INFRA.

## Files

sha256 of the run's outputs. The receipts are listed but not published.

```
7700c41cacc61caf9b07ea5412a7d7acb070732268effb07f614d3423e6e8e9d  card.json
2d2c2469d08aa1418fa1b1b9f0fe73734e95243f10cec44a4e8deafc8c64e7a3  outcomes.json
030344e7606cdd1204ff63707cf20e5377b49b7df3497d68f95a7ecaf46d4b7a  no_memory.json
1fd639e4b0f90dec3b15bb8e2c60b9ed798aa5fc84f6ec8dacdaa0fc52d190b4  units.json
8dfa9b37c8ca4e1fe0b629fd0dd1e3f10b06939cb17119a706a5a66617a4fecb  disclosures.json
e1e2e41eb3c8e1527cdbb602b2aa74504fdc111fdfa3c32e79e389fe2565d924  custody.json
a540f9a637832b8f1f67f78cfe41e0dc667d1bc47fc1809a5240434da199f0c9  spend.json
8fb8bbd403c4575b797e6dddc1d5686f02a937c3198ddfcd5599c2b419f5cfff  receipt.json
c986b07a0b3ec191ff1a5a2cad0fccd6b60f0b70b712b48684c352ea478e55ed  receipts/system.json
122738951db9f01fbc54ed3d5d30d45415c902fa81b5cbb93dc6945c66ec911b  receipts/no_memory.json
```
