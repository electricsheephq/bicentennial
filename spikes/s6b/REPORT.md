# S6b report: the Sol agent lane through the director (draft)

> **Draft.** The ramp and the director are measured. r7b-write, the C24 soak, the quota readings and the projection are not run yet; their tables below are placeholders (`TBD`). Nothing in this draft is a verdict.

**Claim so far** (`advisory`): the S6b director carries Hermes v0.22.2's native `openai-codex` provider to `gpt-6.1-sol` under credential model C′, and a burst ramp through the director's own upstream path saw no refusal at any level up to 48 concurrent requests. A burst level is not a sustained concurrency; the soak decides C-11 for this lane.

## Method
- **Harness.** As S6a (`spikes/s6a/REPORT.md`): Hermes v0.22.2, unmodified, Python 3.14, a new `HERMES_HOME` per run, built-in memory, ACP toolsets `memory`, `session_search` and `todo`, driven in process by `hermes_worker.py`, with at most 2 Hermes processes at a time.
- **Credential model C′.** Every Hermes home runs the native `openai-codex` provider with a placeholder token (an unsigned JWT-shaped string with a far-future expiry), `auth.adopt_external_logins: false`, an empty `CODEX_HOME`, and its Codex base URL on the director at 127.0.0.1. The director alone reads and refreshes the bench login, replaces the inbound credential, and rebuilds the account headers from the token's claims. No header value, and no identity header name, is written to any ledger or log.
- **Director** (`sol_director.py`). S6a's ledger, budget, classification, write turns and ledger-before-send on the Responses SSE wire. The full upstream stream is buffered, classified and recorded before it is replayed. Upstream 429s are absorbed with backoff and never passed to Hermes; an in-stream auth error stops the director. Inference parameters are forwarded unchanged; the model is pinned to `gpt-6.1-sol` with `reasoning.effort = medium`, and the compression task carries the same pin.
- **Ramp** (`ramp_sol.py`). Level n sends 2n tiny requests through n workers, using the director's own upstream call in process. Calls are never retried. It stops on 3 consecutive quota refusals (checked as results arrive) and on any 401 or 403.
- **Soak** (`soak_sol.py`). 24 requests in flight for 180 s, with a finished run's forwarded write-turn and compaction bodies in that run's order and mix, never retried. It stops on 3 consecutive quota refusals (checked as results arrive and before each send) and on any 401 or 403, and a call ceiling keeps it under the upstream cap.
- **Machine.** One shared 14-core machine running a release gauntlet alongside. Sol calls do not use the GLM lane, so the busy marker's `glm` field does not pause them; marker exit 11 still holds every live step.

## Results

### Concurrency ramp (burst)
264 calls, 2026-10-26 07:24:14-07:27:02 UTC. Every level fully funded, all 200, served model `gpt-6.1-sol`, 5 output tokens per call. Each level's window was about 25 s, so this is a **burst** test, not a sustained one.

| Level | Calls | Refused | 429 | p50 s | p90 s | max s | Window s | ok / min | Marker, load |
|---|---|---|---|---|---|---|---|---|---|
| 4 | 8 | 0 | 0 | 3.9 | 4.4 | 13.5 | 20.1 | 23.8 | exit 0, glm false, load 32.2 |
| 8 | 16 | 0 | 0 | 2.5 | 7.7 | 22.2 | 22.2 | 43.3 | exit 0, load 21.9 |
| 16 | 32 | 0 | 0 | 2.5 | 5.0 | 24.2 | 25.6 | 74.9 | exit 0, load 21.7 |
| 24 | 48 | 0 | 0 | 2.8 | 5.1 | 24.0 | 29.6 | 97.3 | exit 0, load 24.8 |
| 32 | 64 | 0 | 0 | 2.7 | 13.3 | 22.7 | 24.5 | 156.7 | exit 0, load 24.9 |
| 48 | 96 | 0 | 0 | 2.7 | 5.1 | 23.3 | 27.4 | 210.0 | exit 0, load 21.1 |

- **Burst concurrency: 48, the ramp's ceiling.** No binding limit was reached. No 429 was seen, so there is no 429 shape to record yet.
- **Quota headers.** The responses carried a primary window of 10,080 minutes (one week) at 0% used throughout the ramp, and a secondary window reported as 0 minutes at 0%.

### r7b-write against S6a's r6 and r3 (TBD)
Matched turns: the same 10-session micro-life, write turns and probes. r6 is GLM with inference parameters forwarded, r3 GLM with them stripped (S6a, n = 60 write turns each).

| Write turn | n | p50 s | p90 s | mean s | prompt tokens, mean | completion tokens, mean | `memory` calls executed | readback |
|---|---|---|---|---|---|---|---|---|
| r7b Sol | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| r6 GLM, forwarded | 60 | 6.1 | 9.0 | 6.6 | 4,009 | 80 | 14 | 60/60 |
| r3 GLM, stripped | 60 | 10.4 | 28.6 | 16.0 | 4,087 | 571 | 21 | 60/60 |

| Other measures | r7b Sol | r6 GLM |
|---|---|---|
| Compaction latency, s (n) | TBD | 79 and 119 (2) |
| Aux (titles) mean s | TBD | 5.1 |
| Turn with compaction removed, mean s | TBD | 10.0 |
| Session fixed time, mean s | TBD | 28.9 |
| Probe turn, mean s | TBD | 31.5 |
| Hermes RSS, mean / peak MiB | TBD | 176 / 215 |
| Aux requests with the effort pin | TBD | n/a |

### C24 soak
2026-10-26 08:08:47-08:12:23 UTC, marker exit 0 and `glm` false at start and end, load 12.7-13.2. r7b had not run yet, so the payloads are the **aborted r7-write's** forwarded bodies: 47 write turns and 1 compaction, replayed in that run's order and mix, about 15 times each. Calls are never retried.

| Measure | Value |
|---|---|
| Window | sends 0-167.8 s, then a 47.6 s drain; it ended on the 700-call ceiling before 180 s, because 429s return in about 0.2 s |
| In flight | target 24; mean 20.9, max 24 while sends were starting |
| Calls | 700 sent, 598 ok, 102 refused: 100 × 429, 2 × in-stream `server_is_overloaded` (2.9 per 1,000) |
| Completions per minute | 196, 194, 203, then 5 in the drain; 205 ok per minute over the send window |
| Latency of ok calls, s | p50 3.53, p90 8.76, p95 23.7, mean 6.12 (n = 598) |
| Write turn under load, s | p50 3.49, p90 8.19, p95 13.9, mean 5.0 (n = 585) |
| Compaction under load, s | p50 57.5, mean 56.8 (n = 13) |
| Tokens, write turns | input 2,921,245 (2,416,256 cached, 83%), output 11,645, reasoning 7,123 |
| Tokens, compactions | input 122,733 (101,376 cached), output 41,247 |
| Effort pin | 686 of 700 sent bodies carry `reasoning.effort = medium` (the 14 compaction bodies predate the aux pin) |
| Effective concurrency | 21.8: ok-call seconds over the send window (Little's law) |
| Quota headers | `x-codex-primary-used-percent` 0 on all 598 ok responses; weekly window 10,080 min |

**The 429 shape.** HTTP 429, body `{"detail": str}`, no quota header on the response, and a `retry-after` header. The 429s came in two bursts: calls 200-272 (+40.6 s to +60.5 s), with `retry-after` counting down from 20 to 1, and calls 473-499 (+112.8 s to +120.5 s), counting down from 8 to 1. None was a quota refusal; the quota stop never fired.

**Inference, labelled as an inference: a per-account request rate near 200 per minute.** The first burst began when 200 calls had started within 40.6 s, and its `retry-after` expired about 60 s after the first call. Calls 273-472, exactly 200 more, ran clean from +60.6 s until the second burst at +112.8 s. A rolling window of about 200 requests per 60 s fits both bursts; concurrency (24 held throughout) and quota (headers at 0%) do not. The ramp is consistent with this: its largest level sent 96 calls in 27 s. The planning rate below is R_s = 180 requests per minute, 90% of that threshold.

**Overload.** The 2 `server_is_overloaded` refusals arrived as `response.failed` events inside an HTTP 200, each after about 20 s. The director classed them `other` (not retryable), because it read only the first 2,000 characters of the terminal event and that event echoes the whole request before its error. The director now classifies an in-stream failure by its error object, so such a failure is retried with backoff.

### Quota readings
Plan and percentages only, from the account's status reader:

| UTC | When | Plan | Weekly free | 5-hour free |
|---|---|---|---|---|
| 08:08:34 | before the soak | pro | 100% | 100% |
| 08:13:51 | after the soak (700 calls) | pro | 100% | 100% |
| 08:18:57 | before r7b | pro | 100% | 100% |
| R7B_AFTER_ROW |

The readings are whole percentages. The soak's 700 calls and about 3.0M input tokens moved neither window by one step, so they bound its burn below 1 point of each.

### The 24-hour projection (TBD)
S6a's §11 grid at the measured C and r7b's latency: job and lane time, ×0.5 / ×1 / ×1.5 latency, n_L 24 / 32 / 48, with and without cuts 1-2, plus J and the RSS per process. C is the soak's sustained level if the soak runs, otherwise the ramp's level labelled "burst". The quota extrapolation follows: the percentage burned per r7b life and per soak minute, and what that implies for one board run in the 5-hour and weekly windows.

### Declared limitation: title requests carry no reasoning field
Hermes's title generator disables reasoning for its request, and Hermes ranks that above the configured auxiliary effort pin. `gpt-6.1-sol` has no "none" effort to pin instead, so title-generation requests reach the upstream with no `reasoning` field, and the upstream default applies to them. Compaction and every other auxiliary task carry `reasoning.effort = medium`.

### Upstream budget
333 Sol upstream calls counted so far: live smokes 8, ramp 264, the aborted r7-write 61. The cap for S6b is 1,400, raised from 400 by the benchmark owner after the burst ramp; the soak counts towards it.

### Pilot requirement: a director-side pacer
This spike needs no pacer: r7b runs one Hermes process. A board run does. The director should hold each account's request rate under R_s (180 per minute in this plan) and honour `retry-after`, so that a 429 burst never reaches Hermes as a stall.

### Run conditions
- The disk floor for r7b was lowered to 20 GB, because its peak disk is about 37 MB: the benchmark owner's decision under the machine's current light-work rule. An earlier r7b attempt stopped itself after session 1 on the old 150 GB floor (5 turns, 6 upstream calls); it is kept as disclosed partial evidence and not used.
- r7b ran one Hermes process at a time, at the release manager's condition for the bench account. Hermes's background title request can still overlap a main-turn call inside that process.

## Footnote: the aborted r7-write
An earlier run, r7-write, ran on the director before its review fixes and was stopped after scripted turn 8.1 by a machine-wide hold on the lane's traffic. It is disclosed partial evidence, never the run of record. 46 scripted turns completed, all ok, with 61 upstream calls (47 write turns, 13 aux, 1 compaction). Write turns: p50 3.3 s, p90 6.1 s, mean 5.0 s, max 26.2 s (n = 47); prompt mean 4,941 tokens (67% cached), completion mean 19; 2 `memory` calls executed; readback 47/47. Its one compaction took 97 s. Its aux and compaction requests carried no effort pin, and it stops before the life's later sessions, so it is not compared with r6 or r3.

## Does not prove
- Any quality or score for any memory system: nothing is scored.
- Sustained concurrency: the ramp's levels lasted about 25 s each; burst headroom is not sustained headroom.
- The account's quota windows, which are not published and can change without notice. One account at one time of day is measured, and any quota extrapolation is from that alone.
- Latency on other machines, accounts or times of day.
- That one micro-life behaves like a board run.
- Behaviour outside a provider-side shedding window. The upstream was shedding load model-wide all day from about 06:21 UTC (`server_overloaded`, and 429s at connect with retries of 60-240 s), at about 18 failures per 1,000 requests on `gpt-6.1-sol` as reported for the day. Every measurement here falls inside that window; the soak saw 2.9 per 1,000 in-stream overloads.
- The soak's prompt-cache share (83%) for a board: its bodies were each re-sent about 15 times.
- The rate-limit inference beyond this account and day: two bursts on one account at one time of day.
