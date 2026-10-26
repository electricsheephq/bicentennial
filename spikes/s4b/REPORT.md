# S4b report: DeepSeek V4.1 Flash as the swap-model candidate

**Claim** (`advisory`, a feasibility spike): DeepSeek V4.1 Flash, served by the pinned third-party fp8 endpoint, completed S6a's micro-life through the director, with 60 of 60 write-turn readbacks, 18 memory calls executed and both probe sessions answered. It did so only after the director's hold schedule was lengthened. With S6a's own holds (5 s, then 15 s), the endpoint's shared-pool overload refusals stopped the first life at session 6, turn 8. Against GLM-5.3's r6 on the same life, its write turns were about 1.7 times slower (mean 11.2 s against 6.6 s) and wrote about 7 times as many completion tokens, 72% of them reasoning. Its burst ramp was clean to 32 in flight, against GLM's 8. Everything cost $0.031 against the $5 cap, and the router's own usage for the key rose by the same amount.

## Method
- **The lane.** `lane.py` subclasses the S6a director and keeps its request classification, write-turn suffix, write-tool filter, script cursor, credential guard and hash-chained ledger. Only the upstream call changes:
  - every forwarded body gets `model` set to `deepseek/deepseek-v4.1-flash-1017`, non-streaming transport, and two declared additions: `provider` (`only` the pinned endpoint, `allow_fallbacks` false) and `usage` (`include` true). The write-turn readback expects exactly these additions;
  - S6a's parameter-rejection fallback is not used: a rejected parameter is a refusal;
  - there is no GLM pause, since the lane is not GLM; S6a's per-session busy-marker gating, `nice -n 19` and `taskpolicy -b` stay.
- **The pinned endpoint (a deviation from #21, disclosed).** #21 asked for the model maker's own endpoint. The router refused it for this account: its privacy setting excludes providers that may train on paid prompts, and the first-party endpoint is one of them (2 refused calls, $0, kept as evidence). That filter would apply to any board run on this account too. The run therefore pins `deepinfra/fp8`, a third-party endpoint that states its precision. Its results describe that endpoint, not the model maker's own serving.
- **Served identity.** Every response's `provider` and `model` are recorded. A successful call served by another provider, or by a model id outside `deepseek/deepseek-v4.1-flash`, stops the run (`pin_failure`).
- **Spend.** One locked, fsynced spend file is shared by the director and the ramp. Before each call, its largest cost is reserved: the serialized request length ÷ 4 as input tokens, plus `max_tokens` (32,768 when unset) as output, both at $0.30 and $1.20 per 1M, above the endpoint's list price. A call is refused unsent when settled spend, open reservations and this reservation would pass $4. Each call settles at the router's own `usage.cost`; without it, at its tokens at the reservation prices. A charge above its reservation stops the run. The spike's hard cap is $5.
- **Life and ramp.** S6a's micro-life (seed 6101: 10 synthetic sessions, 60 scripted turns with write turns, a SIGKILL restart, a compaction in session 6, two live probe sessions of two turns), on the pinned Hermes v0.22.2 (d923a5eb) with S6a's life config (`context_length` 64000, compression threshold 12000, `protect_last_n` 6). `run.py replay` reuses S6a's driver and replaces only its director launch. The ramp is S6a's: two rounds at 1, 2, 4, 8, 16 and 32 in flight, `max_tokens` 16; any refusal stops it.
- **Baseline.** S6a's run of record r6 (GLM-5.3 on its subscription lane), from `spikes/s6a/results/measurements.json`.

## Results
Two lives ran, on the same pinned endpoint, life and settings. **Life 1** used S6a's holds (5 s, 15 s). **Life 2**, the run of record, held up to 5, 15, 45, 120 and 300 s (`--hold-schedule`), which only spaces retries of the same request. All 269 calls to the pinned endpoint were off-peak, and every successful call was served by the pinned endpoint and model.

| Measure | S6a r6, GLM-5.3 | S4b life 2 (of record) | S4b life 1 (S6a holds) |
|---|---:|---:|---:|
| Completed the life | yes | yes | no: stopped at session 6, turn 8 |
| Write-turn readbacks passed | 60 / 60 | 60 / 60 | 33 |
| Write-turn latency, mean / p90 / max (s) | 6.6 / 9.0 / 20.9 | 11.2 / 27.2 / 65.2 | 12.2 / 27.9 / 62.9 (n = 32) |
| Write-turn prompt tokens, mean | 4,009 | 4,256 | 3,652 |
| Write-turn completion tokens, mean | 80 | 576 (72% reasoning) | 703 |
| Summariser latency (s) | 99.1 | 153.4 (n = 1) | none reached |
| Auxiliary latency, mean (s) | 5.1 | 1.7 | none succeeded |
| Probe latency, mean (s) | 10.5 | 2.2 | none reached |
| Session total, mean / max (s) | 108.8 / 351.8 | 137.3 / 538.9 | 90.3 / 178.3 (5 sessions) |
| Memory calls executed | 14 | 18 | 14 |
| Overload refusals (HTTP 429, shared pool) | 0 on write turns | 17, all recovered; 220 s held | 16; the life stopped |
| Clean ramp (in flight) | 8 | 32 (two rounds per level, none refused) | (same ramp) |

The refusals were the endpoint's: `engine_overloaded`, with the router naming the provider's shared pool as their source. They came during the life, which sends about one request at a time, after the ramp had run clean at 32 in flight; capacity on this endpoint is therefore not steady. Life 2's 17 refusals fell on 9 write turns, 6 auxiliary calls, 1 summariser call and 1 probe.

Measurements: `results/measurements.json` (life 2) and `results/life1/measurements.json`; each file's spend block is the spike's one shared spend file, read when the file was written.

**Spend.** Every call settled at the router's own `usage.cost`; none was estimated, none was refused by the spend guard, and the largest single call cost $0.0038.

| Part | Calls | Spend |
|---|---:|---:|
| Ramp | 126 | $0.00099 |
| Life 1 | 48 | $0.00891 |
| Life 2 | 95 | $0.02084 |
| First-party endpoint, refused by the account filter | 2 | $0 |
| **Total** | **271 settled** | **$0.03073** |

The key's router-side usage rose by $0.03073 over the spike.

**For C-2.** S4b supplies three facts and makes no choice:
- On this endpoint, DeepSeek sustains far more bursts in flight than GLM's lane, but its throughput during the life is not reliable at one request in flight without long holds.
- It is slower per write turn, because it reasons at the default effort.
- Its marginal cost on this life is about two cents.

A board on this account could not use the model maker's own endpoint; it would face the same privacy filter.

## Reproduction
From the repository root, with the router URL and key in the environment only, and `S6A_HERMES`, `S6A_SCRATCH`, `S6A_EVIDENCE` and `S6A_BUSY_CMD` set as for S6a:

```sh
nice -n 19 taskpolicy -b python3.14 -B spikes/s4b/run.py ramp --mode live --out "$S6A_EVIDENCE/ramp" --ledger-dir "$S6A_SCRATCH/ramp-ledger" --spend-file "$S4B_SPEND" --provider-only deepinfra/fp8 --served-provider DeepInfra
nice -n 19 taskpolicy -b python3.14 -B spikes/s4b/run.py replay --mode live --out "$S6A_EVIDENCE" --spend-file "$S4B_SPEND" --provider-only deepinfra/fp8 --served-provider DeepInfra --hold-schedule 5,15,45,120,300 --run write-hold --port 8765 --write-turns --probes --context-length 64000 --threshold-tokens 12000 --protect-last-n 6 --min-free-gb 0
python3.14 -B spikes/s4b/run.py analyse --out spikes/s4b/results --spend-file "$S4B_SPEND" --evidence "$S6A_EVIDENCE" --run write-hold --ramp "$S6A_EVIDENCE/ramp/ramp.json"
```

`run.py dryrun --mode stub` runs the same life through the director in process with no network.

## Does not prove
- Anything about the model maker's own endpoint, or about other third-party endpoints of the same model.
- Quality: nothing is scored, and no memory system is compared.
- C-2: it stays a v0 completion-record decision; this spike supplies evidence for it.
- Capacity beyond 32 in flight, or sustained capacity over a long soak.
