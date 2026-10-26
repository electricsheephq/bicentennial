# S6b report: the Sol agent lane through the director (draft)

> **Draft.** The ramp and the director are measured. r7b-write, the C24 soak, the quota readings and the projection are not run yet; their tables below are placeholders (`TBD`). Nothing in this draft is a verdict.

**Claim so far** (`advisory`): the S6b director carries Hermes v0.22.2's native `openai-codex` provider to `gpt-6.1-sol` under credential model C′, and a burst ramp through the director's own upstream path saw no refusal at any level up to 48 concurrent requests. A burst level is not a sustained concurrency; the soak decides C-11 for this lane.

## Method
- **Harness.** As S6a (`spikes/s6a/REPORT.md`): Hermes v0.22.2, unmodified, Python 3.14, a new `HERMES_HOME` per run, built-in memory, ACP toolsets `memory`, `session_search` and `todo`, driven in process by `hermes_worker.py`, with at most 2 Hermes processes at a time.
- **Credential model C′.** Every Hermes home runs the native `openai-codex` provider with a placeholder token (an unsigned JWT-shaped string with a far-future expiry), `auth.adopt_external_logins: false`, an empty `CODEX_HOME`, and its Codex base URL on the director at 127.0.0.1. The director alone reads and refreshes the bench login, replaces the inbound credential, and rebuilds the account headers from the token's claims. No header value, and no identity header name, is written to any ledger or log.
- **Director** (`sol_director.py`). S6a's ledger, budget, classification, write turns and ledger-before-send on the Responses SSE wire. The full upstream stream is buffered, classified and recorded before it is replayed. Upstream 429s are absorbed with backoff and never passed to Hermes; an in-stream auth error stops the director. Inference parameters are forwarded unchanged; the model is pinned to `gpt-6.1-sol` with `reasoning.effort = medium`, and the compression task carries the same pin.
- **Ramp** (`ramp_sol.py`). Level n sends 2n tiny requests through n workers, using the director's own upstream call in process. Calls are never retried. It stops on 3 consecutive quota refusals (checked as results arrive) and on any 401 or 403.
- **Soak** (`soak_sol.py`, not yet run). 24 requests in flight for 180 s, with r7b's forwarded write-turn and compaction bodies in r7b's order and mix, never retried. It stops on 3 consecutive quota refusals (checked as results arrive and before each send) and on any 401 or 403, and a call ceiling keeps it under the upstream cap.
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

### C24 soak (TBD)

| Measure | Value |
|---|---|
| Window, in flight (min / mean) | TBD |
| Ended by | TBD |
| Calls sent / ok / refused / 429 | TBD |
| Completions per minute | TBD |
| Write-turn p50 / p90 / mean s under load | TBD |
| Compaction p50 / mean s under load | TBD |
| Input / output / cached tokens | TBD |
| 429 or refusal shape (redacted) | TBD |
| Quota headers, first / last | TBD |

### Quota readings (TBD)
Plan and percentages only, each with a UTC timestamp: before r7b, after r7b, after the soak.

### The 24-hour projection (TBD)
S6a's §11 grid at the measured C and r7b's latency: job and lane time, ×0.5 / ×1 / ×1.5 latency, n_L 24 / 32 / 48, with and without cuts 1-2, plus J and the RSS per process. C is the soak's sustained level if the soak runs, otherwise the ramp's level labelled "burst". The quota extrapolation follows: the percentage burned per r7b life and per soak minute, and what that implies for one board run in the 5-hour and weekly windows.

### Declared limitation: title requests carry no reasoning field
Hermes's title generator disables reasoning for its request, and Hermes ranks that above the configured auxiliary effort pin. `gpt-6.1-sol` has no "none" effort to pin instead, so title-generation requests reach the upstream with no `reasoning` field, and the upstream default applies to them. Compaction and every other auxiliary task carry `reasoning.effort = medium`.

### Upstream budget
333 Sol upstream calls counted so far: live smokes 8, ramp 264, the aborted r7-write 61. The cap for S6b is 1,400, raised from 400 by the benchmark owner after the burst ramp; the soak counts towards it.

## Footnote: the aborted r7-write
An earlier run, r7-write, ran on the director before its review fixes and was stopped after scripted turn 8.1 by a machine-wide hold on the lane's traffic. It is disclosed partial evidence, never the run of record. 46 scripted turns completed, all ok, with 61 upstream calls (47 write turns, 13 aux, 1 compaction). Write turns: p50 3.3 s, p90 6.1 s, mean 5.0 s, max 26.2 s (n = 47); prompt mean 4,941 tokens (67% cached), completion mean 19; 2 `memory` calls executed; readback 47/47. Its one compaction took 97 s. Its aux and compaction requests carried no effort pin, and it stops before the life's later sessions, so it is not compared with r6 or r3.

## Does not prove
- Any quality or score for any memory system: nothing is scored.
- Sustained concurrency: the ramp's levels lasted about 25 s each; burst headroom is not sustained headroom.
- The account's quota windows, which are not published and can change without notice. One account at one time of day is measured, and any quota extrapolation is from that alone.
- Latency on other machines, accounts or times of day.
- That one micro-life behaves like a board run.
