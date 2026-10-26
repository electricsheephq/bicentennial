# S4b report: DeepSeek V4.1 Flash 1017

Claim: advisory, build-only. Results: **pending the live run**.

## Method
`lane.py` subclasses S6a's director, preserving classification, suffix, write-tool filtering,
script cursor, Guard and hash-chained ledger. The readback allows exactly the declared
`provider` and `usage` additions, besides S6a's model/transport adaptations. No parameter fallback.
`run.py replay` imports S6a's driver, replaces only its child-director launch and bypasses its
helper without executing it. Hermes config, worker, restart, egress sampling, per-session marker
and background scheduling stay S6a's. No S6a source hook. Use pinned Hermes v0.22.2 / d923a5eb.
URL and key come only from BICENTENNIAL_UPSTREAM_OPENAI_URL and BICENTENNIAL_UPSTREAM_KEY.
Every call records declared keys, served provider/model, usage, reasoning tokens when supplied,
and weekday UTC peak (01:00–04:00 / 06:00–10:00, end exclusive) or off_peak; no GLM wait.
Spend file uses flock plus fsync, policy matching and open reservations. Input estimation uses
serialized request length / chars-per-token (default 4); output reserves max_tokens or 32768.
Prices default to $0.30/$1.20 per million. Reservation refusal is spend_cap and never sent.
Router usage.cost takes precedence; token fallback is cost_estimated. Only connection refusals
before a response, or HTTP errors without usage, settle zero. Ambiguous billed responses retain
the full reservation; a charge exceeding its reservation stops. Crash reservations stay open;
never reset the file to regain budget. All participating processes must use the same file/policy.
Ramp reuses S6a run_level: two rounds at 1,2,4,8,16,32, max_tokens=16; any refusal stops expansion.
Analysis reuses S6a measures, adds spend/identity/window/reasoning counts and prints r6 side by side.
No completion slot, quality score or live-provider claim is filled by the stub checks.

## Orchestrator commands (from repository root; environment supplied by orchestrator)
Set S6A_HERMES to the pinned checkout, S6A_SCRATCH to bulk storage and S6A_EVIDENCE to evidence;
set S4B_SPEND to one new shared guard-file path, and S6A_BUSY_CMD / BICENTENNIAL_BUSY_CMD as needed.
Replay launches its own director. The standalone director command below is an alternative entry point.
```sh
nice -n 19 taskpolicy -b python3.14 -B spikes/s4b/lane.py --mode live --port 8764 --life spikes/s6a/micro_life.json --ledger-dir "$S6A_SCRATCH/director-ledger" --spend-file "$S4B_SPEND" --write-turns
python3.14 -B spikes/s4b/run.py replay --mode live --out "$S6A_EVIDENCE" --spend-file "$S4B_SPEND" --run write --port 8764 --write-turns --probes --context-length 64000 --threshold-tokens 12000 --protect-last-n 6 --min-free-gb 0
nice -n 19 taskpolicy -b python3.14 -B spikes/s4b/run.py ramp --mode live --out "$S6A_EVIDENCE/ramp" --ledger-dir "$S6A_SCRATCH/ramp-ledger" --spend-file "$S4B_SPEND"
python3.14 -B spikes/s4b/run.py analyse --out spikes/s4b/results --spend-file "$S4B_SPEND" --evidence "$S6A_EVIDENCE" --run write --ramp "$S6A_EVIDENCE/ramp/ramp.json"
```

## Results
pending the live run

## Limits
Stub checks exercise plumbing with simulated memory acknowledgements, without Hermes or network.
Token estimation is approximate; prices and served identity fields must be checked by the live owner.
