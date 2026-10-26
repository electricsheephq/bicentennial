# S6b: the Sol agent lane through the director

**Question.** S6a measured a sustained concurrency of 8 on its model lane, and at 8 one system's full core board does not fit in 24 hours (PREREG-v0.1 §11). Does a second agent lane, `gpt-6.1-sol` on a subscription login held by the director, change that verdict?

S6b is a feasibility and timing measurement. It produces no score for any memory system. Its numbers inform the pinned family's model lane.

## What it builds (spike-grade code, under `spikes/s6b/`)
1. **The director on the Codex Responses wire** (`sol_director.py`, the first PR). It keeps S6a's ledger, budget, classification, write turns and ledger-before-send, and adds credential model C′:
   - Hermes runs its native `openai-codex` provider with a placeholder token, no external-login adoption, an empty `CODEX_HOME`, and its Codex base URL pointing at the director on 127.0.0.1;
   - the director alone reads and refreshes the bench login, replaces the inbound credential, and rebuilds the account headers from the token's claims. No credential, account id or email reaches any log, ledger, commit or PR text;
   - the upstream base URL and token endpoint come from the local environment, never from the repository;
   - an upstream 429 is never passed to Hermes; it is absorbed with backoff, and a usage-limit refusal counts towards the 3-in-a-row stop.
2. **A concurrency ramp on Responses SSE** (`ramp_sol.py`). S6a's ramp, ported: levels 4, 8, 16, 24 and 32, then 48 only if 32 is clean. Each level sends 2 × level tiny requests through that many workers. It stops at once after 3 consecutive quota refusals, checked as results arrive, and on any 401 or 403. A level is clean when every call was sent and none got a 429. Each level lasts about 25 s, so the ramp is a burst test, not a sustained one.
3. **r7b-write, then r7c-write.** S6a's full micro-life with write turns and probes, on Sol through the fixed director, with at most 2 Hermes processes. Every auxiliary request's forwarded body must carry the pinned `reasoning.effort` (title generation excepted, below); if none does, the run stops. An earlier run, r7-write, was aborted part-way by a machine-wide hold and is kept only as disclosed partial evidence. r7b's compaction count was affected by the director's usage undercount (fixed in 5704c09). r7c-write repeats it with the same parameters on the fixed director and is the run of record; r7b is kept as superseded evidence.
4. **A C24 soak** (`soak_sol.py`). 24 requests held in flight for 180 s through the director, with realistic bodies: a finished run's forwarded write-turn and compaction requests (synthetic micro-life content only), replayed in that run's order and mix. The soak ran before r7b, so its bodies came from the aborted r7-write. Calls are never retried. It stops at once after 3 consecutive quota refusals, checked as results arrive and before every send, and on any 401 or 403. A call ceiling keeps it under the upstream cap, and it refuses to start if the planned window would not fit under that ceiling. It records completions and tokens per minute, in-flight samples, the quota headers, and the redacted shape of any refusal.
5. **The projection** (`analyse_sol.py`). PREREG-v0.2 §11 through S6a's formulas and grid (`spikes/s6a/analyse.py`), with the study's C_learn and C_erase as unmeasured placeholders at 0 and their break-even reported, at Sol's measured concurrency (the soak's effective level by Little's law over the send window, with service clipped to it, or the ramp's burst level labelled "burst, not sustained") and the run of record's latency. It adds a request-rate bound: that run's upstream requests per scripted turn, compaction, session (aux) and probe turn, scaled by the same formulas to the board's and the study's N_req. Each grid cell reports N_req ÷ R_s at R_s = 180 requests per minute (one account) and 360 (two accounts, hypothetical), and fits when max(lane time at C, N_req ÷ R_s) ≤ 24 h. It also gives C_eff = R_s × mean request latency, the achievable concurrency on k accounts (C_k = k × R_s × each projected workload's own mean request time, capped by J × 218 MiB ≤ 16 GiB), each headline verdict at C = 20 and at C_k, the flip points of each headline verdict in the probe and compaction inputs, and a quota extrapolation: the quota percentage burned per r7b life and per soak minute, and what that implies for one board run in the 5-hour and weekly windows.

## What it measures
- Sol's burst and sustained concurrency, the shape of any 429, and the binding limit (completion slot C-11 for this lane).
- Every 429 and `server_overloaded` event: its count, which request, how the director handled it, and the retry wait; latency with and without retry waits.
- The account's quota reading (plan and percentages only) before and after r7b and the soak.
- Write-turn latency (p50, p90, mean), compaction latency, and tokens, each with its sample size.
- The run of record against S6a's r6 (GLM, inference parameters forwarded) and r3 (parameters stripped), on the same quantities.
- The §11 fit table at the measured concurrency: job time and lane time, latency ×0.5, ×1 and ×1.5, board sizes n_L of 24, 32 and 48, with and without the §11 cuts, and the number of Hermes processes J needed, with the memory per process.

Every timing records the busy-marker state and the machine's load average.

## Stop conditions
More than 1,400 upstream calls in all (raised from 400 by the benchmark owner after the burst ramp; the soak counts towards it); any 401 or 403 from the upstream or the token endpoint; a refresh that fails or returns no new refresh token; a credential, email or account id in any log, ledger, commit or PR text; a persisted login-stop file beside the login store (never deleted by the lane).

## Done when
Hermes v0.22.2 replays the micro-life (r7c) with write turns end to end on Sol through the director, every request classified and none unknown, and `spikes/s6b/REPORT.md` gives every measurement above with its sample size and marker state.

## Does not prove
- Anything about any memory system's quality: nothing is scored.
- Latency or limits on other machines, accounts or times of day. One shared machine, one account and one time of day are measured.
- The account's quota windows, which are not published and can change without notice. The quota extrapolation is from one account at one time of day.
- Sustained behaviour beyond the soak's window: the ramp is a burst test.
- That one micro-life behaves like a board run.

## Declared limitation
Hermes's title generator disables reasoning for its request, and Hermes ranks that above the configured auxiliary effort pin. `gpt-6.1-sol` has no "none" effort to pin instead, so title-generation requests carry no `reasoning` field and the upstream default applies to them. Compaction and every other auxiliary task carry the pin.


## S6c pacing

Each account's director shares one locked token bucket across HTTP, soak and retry calls:
180 requests/minute, burst 10, acquired immediately before each upstream POST after budget/stop checks.
Per director process, any half-open 60 s window contains at most burst + rate sends: 190 by default, below 200.
Start a paced process only after 60 s with no traffic on that account, and never within 60 s of the unpaced ramp.
`--rate-per-min 0` disables pacing (recorded in the ledger); stub mode bypasses it.
`--burst` defaults to 10; burst + rate >= 200 requires `--allow-over-window`.
The ramp deliberately uses rate 0 to retain its refusal-threshold burst measurement; the soak passes
`--rate-per-min` and `--burst` through to the director. Every attempt records `pace_wait_ms`.
`summary.json` beside the ledger reports counts, recovery outcomes, overload/429/breaker counts,
trailing half-open 60 s request windows ending at each send (p50/max, including start-up), and total pace wait;
service latency excludes pacing. Summaries contain no bodies or headers; older ledgers remain readable.
After a pace wait the director reads the login token again, so a token that expired while it waited is
refreshed before the send. A read that blocks for more than 1 s (on a refresh) admits the request again, so
each send leaves within 1 s of its admission and a 60 s window holds at most burst + 61/60 × rate sends (193). A paced soak's send window (`last_send_s`, and the projection's C_effective window)
ends at the last send after pacing; files without pace waits keep their recorded window.
`summary.json` also records `stop_reason`, a fixed-vocabulary label, and `breaker_stops` counts only
`upstream_failures_3_in_a_row`.
Invalid HTTP 4xx except 401/403/429 stop with `upstream_invalid_request_<code>` and invalidate evidence.
Three served-but-unparsed calls with no forwarded call between them stop with `upstream_unparsed_3_in_a_row`
(failed tries in between neither extend nor reset the count), holding the failure breaker streak and never
forwarding the stream. Neither stop writes the credential sentinel.
Upstream success and HTTP-error bodies are bounded to 8 MiB + 1 byte; oversize yields only `error:oversize`
without decoding, parsing, replaying or persisting the body. Refresh-log draining is atomic, soak slots release
on exceptions, and ledger attempt reconciliation includes refresh, soak and ramp records. On exit the director stops, then
waits up to 2 s for woken pace waiters to release their reservations, so the budget equals the ledger.
The >=10 minute paced soak with no 429 is **pending**, to be run by the orchestrator before the pilot;
this offline implementation does not confirm the sustainable rate.

The live director holds `holder.lock` for its process lifetime and records only lease presence in the ledger. Refresh links a durable `refresh_in_flight` sentinel after the budget check; durable rotated-store write-back clears only that reason, while credential refusals replace it under the login lock. Store, sentinel and home-local `director-pin.json` writes sync the file and parent folder. The account and user pin stays beside the store; `--scan --run RUN` refuses a missing run pin, a changed lease or a changed account before learning needles. These are offline implementation guarantees, not new measured run results.
