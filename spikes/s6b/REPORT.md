# S6b report: the Sol agent lane through the director

**Claim** (`advisory`): Hermes v0.22.2 replays the 10-session micro-life with write turns and probes end to end on `gpt-6.1-sol` through the S6b director under credential model C′: 64 of 64 turns ok, 0 unknown requests, 0 refusals. On Sol, a write turn takes 4.3 s on average, against 6.6 s on GLM with parameters forwarded (r6). The lane's binding limit is not concurrency. A soak at 24 in flight hit a per-account request rate near 200 per minute (an inference from two 429 bursts). With the request-rate bound at the planning rate of 180 per minute on one account, the full board at L = 48 needs 26.2 h of requests alone and does not fit in 24 h at any concurrency. It fits on one account with cuts 1-2 (21.1 h) or at L = 32 (17.4 h), and on two accounts (hypothetical) at L = 48 from C = 20 by lane time. The one-account full-board verdict rests on 4 probe turns and flips at 2.60 probe requests per probe turn (r7b: 3.25), so it is sensitive to that input.

## Method
- **Harness.** As S6a (`spikes/s6a/REPORT.md`): Hermes v0.22.2, unmodified, Python 3.14, a new `HERMES_HOME` per run, built-in memory, ACP toolsets `memory`, `session_search` and `todo`, driven in process by `hermes_worker.py`. r7b ran **one Hermes process at a time**, at the release manager's condition for the bench account. Hermes's background title request can still overlap a main-turn call inside that process.
- **Credential model C′.** Every Hermes home runs the native `openai-codex` provider with a placeholder token (an unsigned JWT-shaped string with a far-future expiry), `auth.adopt_external_logins: false`, an empty `CODEX_HOME`, and its Codex base URL on the director at 127.0.0.1. The director alone reads and refreshes the bench login, replaces the inbound credential, and rebuilds the account headers from the token's claims. No header value and no identity header name is written to any ledger or log; r7b's ledger contains none.
- **Director** (`sol_director.py`). S6a's ledger, budget, classification, write turns and ledger-before-send on the Responses SSE wire. The full upstream stream is buffered, classified and recorded before it is replayed. Upstream 429s and overloads are absorbed with backoff (5, 15 and 45 s) and never passed to Hermes. Inference parameters are forwarded unchanged; the model is pinned to `gpt-6.1-sol` with `reasoning.effort = medium`, and the compression task carries the same pin. **r7b ran on the director at commit 4d9fa0e** (the worktree head at launch). The later round-2 director changes, merged into this branch afterwards, cover failure-path classification, latching and persistence scrubbing; a normal run behaves the same under them.
- **Ramp** (`ramp_sol.py`). Level n sends 2n tiny requests through n workers, using the director's own upstream call in process. Calls are never retried. It stops on 3 consecutive quota refusals (checked as results arrive) and on any 401 or 403.
- **Soak** (`soak_sol.py`). 24 requests in flight for 180 s, with a finished run's forwarded write-turn and compaction bodies in that run's order and mix, never retried. It stops on 3 consecutive quota refusals (checked as results arrive and before each send) and on any 401 or 403, and a call ceiling keeps it under the upstream cap.
- **Machine.** One shared 14-core machine running a release gauntlet alongside. Sol calls do not use the GLM lane, so the busy marker's `glm` field does not pause them. Every live step started at marker exit 0.

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

Burst concurrency: 48, the ramp's ceiling, with no 429. The weekly quota window (10,080 min) read 0% used throughout.

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
| Effective concurrency | 20.6: ok-call service time clipped to the send window, over that window (Little's law); the sampled in-flight mean over all calls is 20.9. Unclipped ok service over the send window (21.8) counted 209 s of drain and is not used |
| Quota headers | `x-codex-primary-used-percent` 0 on all 598 ok responses |

**The 429 shape.** HTTP 429, body `{"detail": str}`, no quota header on the response, and a `retry-after` header. The 429s came in two bursts: calls 200-272 (+40.6 s to +60.5 s), with `retry-after` counting down from 20 to 1, and calls 473-499 (+112.8 s to +120.5 s), counting down from 8 to 1. None was a quota refusal; the quota stop never fired.

**Inference, labelled as an inference: fixed 60 s windows of exactly 200 accepted requests per account.** Counted from the first send, the three 60 s windows hold exactly 200, 200 and 200 accepted calls (with 72, 26 and 2 refusals). Each burst began when its window's 200th call had been accepted, and each `retry-after` expired near a window edge (about +60.6 s and +120.8 s), so the windows look anchored near the first call. A rolling window is contradicted: 220 calls were accepted in 105.5-165.4 s with no 429, and 113 calls after +125.7 s were accepted although the 60 s before each held 200 or more accepted starts. Concurrency does not fit either (24 were held throughout), nor does quota (the headers read 0%). The ramp is consistent: its largest level sent 96 calls in 27 s. The planning rate below is R_s = 180 requests per minute, 90% of that threshold; a token bucket at R_s is safe under either window model.

**Overload.** The 2 `server_is_overloaded` refusals arrived as `response.failed` events inside an HTTP 200, each after about 20 s. The director that ran the soak classed them `other` (not retryable), because it read only the first 2,000 characters of the terminal event and that event echoes the whole request before its error. The director now classifies an in-stream failure by its error object, so such a failure is retried with backoff.

### r7b-write against S6a's r6 and r3
2026-10-26 08:22:37-08:37:29 UTC, marker exit 0 at every timing, load mean 15.3 (p90 27.9). 64 of 64 turns ok (60 scripted, 4 probe); 172 ledger records; 90 upstream attempts, all budgeted; 0 unknown; 0 non-loopback sockets in 495 egress samples. Matched turns: the same 10-session micro-life, write turns and probes. r6 is GLM with inference parameters forwarded, r3 GLM with them stripped (S6a: n = 60 write turns, 10 life sessions and 4 probe turns each). Conditions: r7b marker exit 0, load mean 15.3 (n = 125 timings); r6 marker exit 0-10, `glm` false, load mean 13.0; r3 marker exit 0-10, `glm` false, load mean 12.3 (n = 125 each).

| Write turn | n | p50 s | p90 s | mean s | prompt tokens, mean | completion tokens, mean | `memory` calls executed | readback |
|---|---|---|---|---|---|---|---|---|
| r7b Sol | 60 | 3.7 | 7.2 | 4.3 | 4,477 (65% cached) | 21 (reasoning 12) | 4 | 60/60 |
| r6 GLM, forwarded | 60 | 6.1 | 9.0 | 6.6 | 4,009 | 80 | 14 | 60/60 |
| r3 GLM, stripped | 60 | 10.4 | 28.6 | 16.0 | 4,087 | 571 | 21 | 60/60 |

| Other measures (n for r7b) | r7b Sol | r6 GLM |
|---|---|---|
| Compaction latency, s (n) | 70.8 (1); prompt 9,441, completion 3,620 | 79 and 119 (2) |
| Compactions in the life | 1 (session 6) | 2 |
| Aux (titles), s | mean 5.4, p50 3.7 (n = 16) | mean 5.1 (n = 12) |
| Turn with compaction removed, mean s (n = 60) | 6.1 | 10.0 |
| Session total, mean s (n = 10) | 80.6 | 108.8 |
| Session fixed time, s (n = 10 sessions) | median 16.8; mean 36.7, or 16.0 without session 7 [^stall] | mean 28.9 |
| Restart wake, s | 9.9 (n = 1) | 9.3-25.3 (n = 3) |
| Probe turn, mean s | 20.1 (n = 4; 13 upstream calls, mean 5.2 s) | 31.5 |
| Hermes RSS, mean / peak MiB | 193 / 230 (13 processes) | 176 / 215 |
| Requests with the effort pin | 74 of 90: every write turn, probe and compaction | n/a |

- **Refusals and retries in r7b: none.** 0 × 429, 0 × `server_overloaded`, 0 retry waits, so latency with and without retry waits is the same (the director records each attempt's wait).
- **Aux effort.** The one compaction carried `reasoning.effort = medium`. All 16 title requests carried no `reasoning` field: the declared limitation below.
- **Behaviour.** Sol wrote memory 4 times in 60 write turns (r6: 14). That is a model difference at the same suffix, not a harness change.

[^stall]: Session 7's open took 199.9 s: Hermes logged nothing for about 170 s after loading its environment and before registering plugins, and the director was idle. It is a host start-up stall, not lane time. It raises the mean fixed time and so the job-time reading (R includes S × session fixed time); the lane-time and request-rate readings do not use it.

### Quota readings
Plan and percentages only, from the account's status reader:

| UTC | When | Plan | Weekly free | 5-hour free |
|---|---|---|---|---|
| 08:08:34 | before the soak | pro | 100% | 100% |
| 08:13:51 | after the soak (700 calls) | pro | 100% | 100% |
| 08:18:57 | before r7b | pro | 100% | 100% |
| 08:37:52 | after r7b (90 calls) | pro | 100% | 100% |

The readings are whole percentages. The soak's 700 calls (about 3.0M input tokens) and r7b's 90 moved neither window by one step.

### The 24-hour projection (PREREG-v0.2 §11) with a request-rate bound
PREREG-v0.2 §11 binds from its freeze. Its board formula is v0.1's. Its study formula adds two per-study-life terms, C_learn and C_erase (the Learn chains and erasure probes), which are unmeasured placeholders set to 0 here (see the break-even below). S6a's assumptions A1-A14 and formulas apply, with r7b's inputs:
- a turn is 6.1 s, 4.3 s of it upstream;
- session fixed time 36.7 s (mean, with the session-7 stall);
- one compaction per long sprint at 70.8 s (40 per life);
- a probe episode of 7.4 s plus a 20.1 s live turn (16.9 s upstream);
- aux 7.2 s per session;
- 193 MiB per Hermes process.

At ×1, R = 4.53 h, P = 2.29 h and the critical path is 4.5 h.

**Concurrency.** C = 20 is the soak's effective concurrency: the floor of 20.6 (Little's law, ok-call service time clipped to the send window). It was measured above the rate threshold. The ramp's burst level of 48 is not a sustained level and is not projected. The DV42 rule (DECISIONS §L.1) reads criterion 2 as max(lane time at C = 24, N_req ÷ R_s). At the measured C = 20 every verdict below is the same as at C = 24, because the request-rate term binds wherever the two differ.

**Request-rate bound.** r7b's upstream requests per unit, retries included:
- 1.0 per scripted turn (the write turn; the scripted turn itself is served from the script);
- 1.0 per compaction;
- 1.33 aux per session;
- 3.25 per probe turn (n = 4 probe turns, 13 calls).

Scaled with the same §11 formulas, N_req is 282,600 for the board and 175,644 for the study at L = 48 (227,600 and 73,705 after cuts 1-2). The bound is N_req ÷ R_s, and a cell fits when max(lane time at C, N_req ÷ R_s) ≤ 24 h. At R_s = 180 per minute, C_eff = R_s × mean request latency is 16.0 at r7b's 5.34 s (18.4 at the soak's 6.12 s). At 360 per minute it is 32.0 (36.7).

At ×1 latency, with a write turn before every turn (board; study). Each cell is job h / lane h at C, then N_req ÷ R_s at 180 and 360 per minute. ✓ marks ≤ 24 h. **Fits** means max(lane, rate at 180) ≤ 24 h.

| L, cuts | C = 16 | C = 20 | C = 24 | C = 32 | Rate bound, h (180 / 360) | Fits at 1 account |
|---|---|---|---|---|---|---|
| 48, none, board | 42.7 / 28.4 | 34.1 / 22.7✓ | 28.5 / 18.9✓ | 21.3✓ / 14.2✓ | 26.2 / 13.1✓ | **no, at any C** (probe-sensitive, below; 2 accounts: from C = 20) |
| 48, none, study | 28.5 / 18.0✓ | 22.8✓ / 14.4✓ | 19.0✓ / 12.0✓ | 14.3✓ / 9.0✓ | 16.3✓ / 8.1✓ | from C = 16 |
| 48, cuts 1-2, board | 36.9 / 23.4✓ | 29.6 / 18.7✓ | 24.6 / 15.6✓ | 18.5✓ / 11.7✓ | 21.1✓ / 10.5✓ | from C = 16 |
| 48, cuts 1-2, study | 12.8✓ / 7.7✓ | 10.2✓ / 6.2✓ | 8.5✓ / 5.2✓ | 6.4✓ / 4.5✓ | 6.8✓ / 3.4✓ | from C = 8 |
| 32, none, board | 28.5 / 18.9✓ | 22.8✓ / 15.1✓ | 19.0✓ / 12.6✓ | 14.2✓ / 9.5✓ | 17.4✓ / 8.7✓ | from C = 16 |
| 32, cuts 1-2, board | 24.6 / 15.6✓ | 19.7✓ / 12.5✓ | 16.4✓ / 10.4✓ | 12.3✓ / 7.8✓ | 14.0✓ / 7.0✓ | from C = 16 |
| 24, none, board | 21.3✓ / 14.2✓ | 17.1✓ / 11.3✓ | 14.2✓ / 9.5✓ | 10.7✓ / 7.1✓ | 13.1✓ / 6.5✓ | from C = 16 |
| 24, cuts 1-2, board | 18.5✓ / 11.7✓ | 14.8✓ / 9.3✓ | 12.3✓ / 7.8✓ | 9.2✓ / 5.8✓ | 10.5✓ / 5.3✓ | from C = 8 |

"From C = n" is the first fitting C in the sampled grid (8, 16, 20, 24, 32). On two accounts the L = 48 board's lane time needs C ≥ 19.

**Probe sensitivity (the one-account rows depend on it).** Probe episodes carry 58% of the full board's N_req: their live-turn calls (41%) plus their sessions' aux. The probe input is r7b's 3.25 requests per probe turn, from n = 4 probe turns. The one-account L = 48 "no" flips to a fit (rate bound ≤ 24 h) at **2.60 or fewer** requests per probe turn. S6a measured 2.25 (r6) and 2.0 (r3) on GLM. The board's rate bound at probe requests ×1, ×1.5 and ×2 is 26.2, 31.6 and 37.0 h. A larger probe sample is needed before a pilot relies on this row.

**The study's added workloads.** C_learn and C_erase are 0 in this grid. At R_s = 180 per minute the study still fits on requests while they stay under about **10,400 upstream requests per study life** at L = 48 (8 study lives), or about **46,000** after cuts 1-2 (4 study lives).

**Latency sensitivity at C = 20** (L = 48, no cuts; board, then study; job / lane h):

| Latency | Board | Study | Critical path |
|---|---|---|---|
| ×0.5 | 25.5 / 11.3 | 17.2 / 7.2 | 3.6 h |
| ×1 | 34.1 / 22.7 | 22.8 / 14.4 | 4.5 h |
| ×1.5 | 42.8 / 34.0 | 28.4 / 21.6 | 5.5 h |

The rate bound does not change with latency. At ×1.5, L = 48 with cuts 1-2 needs C = 24 by lane time.

**Cuts at C = 20, ×1** (board / study, job h): none 34.1 / 22.8; cut 1 29.6 / 20.5; cut 2 29.6 / 10.2; cut 3 14.8 / 10.2. By job time the board needs C = 29 (25 after cuts 1-2, 13 after all three).

**Processes.** In the lane reading at C = 20, J = 31-32 concurrent Hermes processes (32-34 with cuts 1-2). That is about 5.8-6.0 GiB at the mean RSS, and 6.9-7.2 GiB at peak. Only one process at a time was tested. The full grid is in `results/projection.json`: ×0.5 and ×1.5 for every row, all three write cadences, both readings and both rates, plus the probe sensitivity and the break-even.

**Quota extrapolation** (one account at one time of day, an upper bound only, assuming burn is linear per served request). Neither window moved by one whole-percent step between 08:08:34 and 08:37:52 UTC. In that span the upstream served 694 requests: the soak's 598, the stopped r7b attempt's 6 and r7b's 90; refused calls are not counted. That bounds the burn below 1/694 points per request (< 0.00145).
- **Weekly window.** A board makes 282,600 requests (227,600 after cuts 1-2), which is under 408 points (< 328). That does not show a board fits the weekly window: the readings are too coarse.
- **5-hour window.** At the board's mean of 196.2 requests per minute, a 5-hour window holds 58,875 requests, which is under 85 points of it. The response headers report only the weekly primary window (the secondary window reads 0 minutes), so the 5-hour figure rests on the status reader alone.
- **Rate.** Separately, the board's 196.2 requests per minute, averaged over 24 h, exceed the planning rate: the rate bound's verdict above.

**Verdict.** On one account, the rate limit, not concurrency, decides the full board. At L = 48 its 282,600 requests take 26.2 h at 180 per minute, so it does not fit at any C. This verdict is sensitive to the probe input (above). The board fits with cuts 1-2 at C ≥ 16 by lane time, or at L = 32 (C ≥ 16 by lane time, C ≥ 20 by job time). The robustness study fits from C = 16, while C_learn + C_erase stay under the break-even. Two accounts at 360 per minute (hypothetical, and assuming a per-account limit) bring the full L = 48 board to 13.1 h of requests, and it fits from C = 20 by lane time. Per §11 the choice goes to the owner: a second account, cuts 1-2, or L = 32. No fit verdict changed with the corrected C = 20.

### Declared limitation: title requests carry no reasoning field
Hermes's title generator disables reasoning for its request, and Hermes ranks that above the configured auxiliary effort pin. `gpt-6.1-sol` has no "none" effort to pin instead, so title-generation requests reach the upstream with no `reasoning` field, and the upstream default applies to them. Compaction and every other auxiliary task carry `reasoning.effort = medium`.

### Pilot requirement: a director-side pacer
This spike needs no pacer: r7b ran one Hermes process. A board run does. The director should hold each account's request rate under R_s (180 per minute in this plan) and honour `retry-after`, so that a 429 burst never reaches Hermes as a stall.

### Run conditions
- The disk floor for r7b was lowered to 20 GB, because its peak disk is about 37 MB: the benchmark owner's decision under the machine's current light-work rule. An earlier r7b attempt stopped itself after session 1 on the old 150 GB floor (5 turns, 6 upstream calls). It is kept as disclosed partial evidence and not used.
- Upstream budget: 1,129 Sol upstream calls in S6b, under the cap of 1,400 (raised from 400 by the benchmark owner after the burst ramp). By run: live smokes 8, ramp 264, aborted r7-write 61, soak 700, stopped r7b 6, r7b 90.

## Footnote: the aborted r7-write
An earlier run, r7-write, ran on the director before its review fixes. A machine-wide hold on the lane's traffic stopped it after scripted turn 8.1. It is disclosed partial evidence, never the run of record. 46 scripted turns completed, all ok, with 61 upstream calls (47 write turns, 13 aux, 1 compaction). Write turns: p50 3.3 s, p90 6.1 s, mean 5.0 s, max 26.2 s (n = 47); prompt mean 4,941 tokens (67% cached), completion mean 19; 2 `memory` calls executed; readback 47/47. Its one compaction took 97 s. Its aux and compaction requests carried no effort pin. Its forwarded bodies are the soak's payloads. Conditions: marker exit 0, `glm` false, load mean 19.8 (6.9-54.5, n = 61 calls). The stopped r7b attempt (5 turns, 6 calls) ran at marker exit 0, load mean 9.1 (n = 10 timings).

## Does not prove
- Any quality or score for any memory system: nothing is scored.
- Sustained behaviour beyond a 3.6-minute soak: the ramp's levels lasted about 25 s each, and burst headroom is not sustained headroom.
- The account's quota windows, which are not published and can change without notice. One account at one time of day is measured, and the quota extrapolation is a coarse upper bound from that alone.
- The rate-limit inference beyond this account and day: two bursts on one account at one time of day.
- That the rate limit is per account, and so doubles with a second account on the same host. The two-account rows assume it; it is untested here (S6c's two-account paced soak tests it).
- The one-account full-board verdict beyond its probe input: probe requests come from n = 4 probe turns (13 calls), and the verdict flips at 2.60 per probe turn (S6a measured 2.25 and 2.0 on GLM).
- The quota extrapolation's linearity: it assumes burn is linear per served request, and the readings are whole percentages.
- Behaviour outside a provider-side shedding window. The upstream was shedding load model-wide all day from about 06:21 UTC (`server_overloaded`, and 429s at connect with retries of 60-240 s), at about 18 failures per 1,000 requests on `gpt-6.1-sol` as reported for the day. Every measurement here falls inside that window. The soak saw 2.9 per 1,000 in-stream overloads, and r7b saw none.
- The soak's prompt-cache share (83%) for a board: its bodies were each re-sent about 15 times.
- Many Hermes processes at once: only one was run, while the lane reading at C = 20 needs about 31-32.
- That one micro-life behaves like a board run, or that its single compaction is typical.
- Latency on other machines, accounts or times of day.
