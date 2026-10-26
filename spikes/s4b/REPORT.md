# S4b report: DeepSeek V4.1 Flash as the swap-model candidate

**Claim** (`advisory`, a feasibility spike): RESULTS_CLAIM

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
RESULTS_TABLE

## Reproduction
From the repository root, with the router URL and key in the environment only, and `S6A_HERMES`, `S6A_SCRATCH`, `S6A_EVIDENCE` and `S6A_BUSY_CMD` set as for S6a:

```sh
nice -n 19 taskpolicy -b python3.14 -B spikes/s4b/run.py ramp --mode live --out "$S6A_EVIDENCE/ramp" --ledger-dir "$S6A_SCRATCH/ramp-ledger" --spend-file "$S4B_SPEND" --provider-only deepinfra/fp8 --served-provider DeepInfra
nice -n 19 taskpolicy -b python3.14 -B spikes/s4b/run.py replay --mode live --out "$S6A_EVIDENCE" --spend-file "$S4B_SPEND" --provider-only deepinfra/fp8 --served-provider DeepInfra --run write --port 8764 --write-turns --probes --context-length 64000 --threshold-tokens 12000 --protect-last-n 6 --min-free-gb 0
python3.14 -B spikes/s4b/run.py analyse --out spikes/s4b/results --spend-file "$S4B_SPEND" --evidence "$S6A_EVIDENCE" --run write --ramp "$S6A_EVIDENCE/ramp/ramp.json"
```

`run.py dryrun --mode stub` runs the same life through the director in process with no network.

## Does not prove
- Anything about the model maker's own endpoint, or about other third-party endpoints of the same model.
- Quality: nothing is scored, and no memory system is compared.
- C-2: it stays a v0 completion-record decision; this spike supplies evidence for it.
- Capacity beyond 32 in flight, or sustained capacity over a long soak.
