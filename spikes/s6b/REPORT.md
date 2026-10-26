# S6b report: the Sol agent lane through the director

**Claim** (`advisory`): Hermes v0.22.2 replays the 10-session micro-life with write turns and probes end to end on `gpt-6.1-sol` through the S6b director under credential model C′. r7c is the run of record: 64 of 64 turns ok, 0 unknown requests, 0 refusals. On Sol, a write turn takes 4.2 s on average, against 6.6 s on GLM with parameters forwarded (r6), and 49 of 60 matched turns ran faster than on r6 (sign test p = 7.6 × 10⁻⁷). A soak at 24 in flight hit a per-account request rate near 200 per minute (an inference from two 429 bursts). At the planning rate of 180 per minute, one account sustains about 18 requests in flight. On one account the full board at L = 48 does not fit in 24 h at any concurrency: its requests alone take 24.4 h, and its lane time is 25.6 h at C = 20. It fits on one account with cuts 1-2 (lane time 21.6 h at C = 20; requests 20.0 h) or at L = 32. Two accounts (hypothetical until S6c's two-account paced soak) fit the full board at their achievable C = 36 (lane time 14.2 h) but not at C = 20. Every verdict rests on one micro-life, with 2 compaction calls in its one long session and 4 probe turns. The flip points are given below.

## Method
- **Harness.** As S6a (`spikes/s6a/REPORT.md`): Hermes v0.22.2, unmodified, Python 3.14, a new `HERMES_HOME` per run, built-in memory, ACP toolsets `memory`, `session_search` and `todo`, driven in process by `hermes_worker.py`. r7c ran **one Hermes process at a time**, at the release manager's condition for the bench account. Hermes's background title request can still overlap a main-turn call inside that process.
- **Credential model C′.** Every Hermes home runs the native `openai-codex` provider with a placeholder token (an unsigned JWT-shaped string with a far-future expiry), `auth.adopt_external_logins: false`, an empty `CODEX_HOME`, and its Codex base URL on the director at 127.0.0.1. The director alone reads and refreshes the bench login, replaces the inbound credential, and rebuilds the account headers from the token's claims. No header value or identity header name is written to any ledger or log, and r7c's ledger contains none.
- **Director** (`sol_director.py`). S6a's ledger, budget, classification, write turns and ledger-before-send on the Responses SSE wire. The full upstream stream is buffered, classified and recorded before it is replayed. Upstream 429s and overloads are absorbed with backoff (5, 15 and 45 s) and never passed to Hermes. Inference parameters are forwarded unchanged. The model is pinned to `gpt-6.1-sol` with `reasoning.effort = medium`, and the compression task carries the same pin. **r7c ran on the director at commit c4c7e4e**, the worktree head at launch: the director of 19af193, which includes 5704c09, plus a test-only commit. 5704c09 counts the request's `instructions` in the usage the director reports to Hermes. Before it, the director under-reported each scripted turn by about 2,325 input tokens, which delayed Hermes's compaction trigger in r7b (below).
- **Ramp** (`ramp_sol.py`). Level n sends 2n tiny requests through n workers, using the director's own upstream call in process. Calls are never retried. It stops on 3 consecutive quota refusals (checked as results arrive) and on any 401 or 403.
- **Soak** (`soak_sol.py`). 24 requests in flight for 180 s, with a finished run's forwarded write-turn and compaction bodies in that run's order and mix, never retried. It stops on 3 consecutive quota refusals (checked as results arrive and before each send) and on any 401 or 403, and a call ceiling keeps it under the upstream cap.
- **Machine.** One shared 14-core machine running a release gauntlet alongside. Sol calls do not use the GLM lane, so the busy marker's `glm` field does not pause them. Every live step before r7c started at marker exit 0. r7c started and ran at marker exit 10, when a gauntlet row is running and light work is allowed; its gate waited only on exit 11. `glm` read false throughout.

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

**Inference, labelled as an inference: fixed 60 s windows of exactly 200 accepted requests per account.** Counted from the first send, the three 60 s windows hold exactly 200, 200 and 200 accepted calls (with 72, 26 and 2 refusals). Each burst began when its window's 200th call had been accepted, and each `retry-after` expired near a window edge (about +60.6 s and +120.8 s), so the windows look anchored near the first call. A rolling window is contradicted: 220 starts were accepted in 105.5-165.4 s, alongside 27 rate-refused attempts (+112.8 to +120.5 s), and a rolling cap of 200 accepted starts per 60 s cannot explain 220 accepted within about 60 s, whatever refusals also occurred. Likewise, 113 calls after +125.7 s were accepted although the 60 s before each held 200 or more accepted starts. Concurrency does not fit either (24 were held throughout), nor does quota (the headers read 0%). The ramp is consistent: its largest level sent 96 calls in 27 s. The planning rate below is R_s = 180 requests per minute, 90% of that threshold. A token bucket at R_s is not safe by its refill rate alone: any 60 s window can hold up to its burst capacity plus 180 starts (a burst of 24 allows 201 starts within 59 s), so the burst must stay at 19 or below to keep every window at 199 or fewer. S6c's pacer uses a burst of 10, for at most 190; paced refusal-free operation is still to be validated.

**Overload.** The 2 `server_is_overloaded` refusals arrived as `response.failed` events inside an HTTP 200, each after about 20 s. The director that ran the soak classed them `other` (not retryable), because it read only the first 2,000 characters of the terminal event and that event echoes the whole request before its error. The director now classifies an in-stream failure by its error object, so such a failure is retried with backoff.

### r7c-write against S6a's r6 and r3
2026-10-26 09:48:04-10:02:06 UTC (ledger). The run's parameters were the same as r7b's. 64 of 64 turns ok (60 scripted, 4 probe); 167 ledger records; 88 upstream attempts, all budgeted; 0 unknown; 0 non-loopback sockets in 514 egress samples; no identity header name in the ledger or logs; no login-stop file. Matched turns: the same 10-session micro-life, write turns and probes. r6 is GLM with inference parameters forwarded, r3 GLM with them stripped (S6a: n = 60 write turns, 10 life sessions and 4 probe turns each). Conditions: r7c marker exit 10 at every timing, `glm` false, load mean 10.4 (p90 17.9, n = 125 timings); r6 marker exit 0-10, `glm` false, load mean 13.0; r3 marker exit 0-10, `glm` false, load mean 12.3 (n = 125 each).

| Write turn | n | p50 s | p90 s | mean s | prompt tokens, mean | completion tokens, mean | `memory` calls executed | readback |
|---|---|---|---|---|---|---|---|---|
| r7c Sol | 60 | 3.1 | 7.2 | 4.2 | 4,147 (58% cached) | 16 (reasoning 9) | 1 | 60/60 |
| r6 GLM, forwarded | 60 | 6.1 | 9.0 | 6.6 | 4,009 | 80 | 14 | 60/60 |
| r3 GLM, stripped | 60 | 10.4 | 28.6 | 16.0 | 4,087 | 571 | 21 | 60/60 |

| Other measures (n for r7c) | r7c Sol | r6 GLM |
|---|---|---|
| Compaction calls, s (n) | 67.1 and 67.8 (2, both in session 6); prompt mean 8,149, completion mean 3,048 | 79 and 119 (2) |
| Aux (titles), s | mean 4.8, p50 4.2 (n = 15) | mean 5.1 (n = 12) |
| Turn with compaction removed, mean s (n = 60) | 6.7 | 10.0 |
| Session total, mean s (n = 10) | 75.3 | 108.8 |
| Session fixed time, s (n = 10 sessions) | median 20.0; mean 21.4, or 18.7 without session 5 [^close] | mean 28.9 |
| Restart wake, s | 7.0 (n = 1) | 9.3-25.3 (n = 3) |
| Probe turn, mean s | 22.2 (n = 4; 11 upstream calls, mean 6.6 s) | 31.5 |
| Hermes RSS, mean / peak MiB | 185 / 218 (13 processes) | 176 / 215 |
| Requests with the effort pin | 73 of 88: every write turn, probe and compaction | n/a |

- **Refusals and retries in r7c: none.** 0 × 429, 0 × `server_overloaded`, 0 retry waits, so latency with and without retry waits is the same (the director records each attempt's wait).
- **Compaction.** Session 6 made 2 compaction calls, at turns 6.11 and 6.12, as r6 also made 2. Hermes refused the first call's summary because it would have grown the transcript (about 8,824 to 11,515 tokens). Nothing was dropped, and the turn continued unchanged. The second call's summary was committed (about 9,627 to 4,523 tokens). The projection counts both calls, because each costs a request and lane time.
- **Sign test.** 49 of 60 matched life turns were faster on r7c than on r6 (two-sided binomial p = 7.6 × 10⁻⁷).
- **Aux effort.** Both compaction calls carried `reasoning.effort = medium`. All 15 title requests carried no `reasoning` field: the declared limitation below.
- **Behaviour.** Sol wrote memory once in 60 write turns (r6: 14). That is a model difference at the same suffix, not a harness change.

[^close]: Session 5's fixed time was 46.1 s, of which its close took 28.6 s, at a load of 26.5, the highest in the run. It raises the mean fixed time and so the job-time reading (R includes S × session fixed time). The lane-time and request-rate readings do not use it.

### Superseded: r7b-write
r7b ran with the same parameters on the director at commit 4d9fa0e, before 5704c09. **Its compaction count was affected by the director's usage undercount; superseded by r7c.** It is kept as disclosed evidence and is not used in the projection. It ran 2026-10-26 08:22:37-08:37:29 UTC at marker exit 0, load mean 15.3:
- 64 of 64 turns ok; 90 upstream attempts; 0 unknown; 0 refusals.
- Write turns: p50 3.7 s, p90 7.2 s, mean 4.3 s (n = 60), with 4 `memory` calls.
- 1 compaction call (session 6, 70.8 s). Aux mean 5.4 s (n = 16).
- Session fixed time: mean 36.7 s, including a 199.9 s open in session 7. Hermes logged nothing for about 170 s before registering plugins, and the director was idle: a host start-up stall.
- Matched turns faster than r6: 45 of 60 (p = 1.3 × 10⁻⁴).


### Quota readings
Plan and percentages only, from the account's status reader:

| UTC | When | Plan | Weekly free | 5-hour free |
|---|---|---|---|---|
| 08:08:34 | before the soak | pro | 100% | 100% |
| 08:13:51 | after the soak (700 calls) | pro | 100% | 100% |
| 08:18:57 | before r7b | pro | 100% | 100% |
| 08:37:52 | after r7b (90 calls) | pro | 100% | 100% |

The readings are whole percentages. The soak's 700 calls (about 3.0M input tokens) and r7b's 90 moved neither window by one step.

r7c's 88 calls ran after the last reading. No reading was taken around r7c.

### The 24-hour projection (PREREG-v0.2 §11) with a request-rate bound
PREREG-v0.2 §11 binds from its freeze. Its board formula is v0.1's. Its study formula adds two per-study-life terms, C_learn and C_erase (the Learn chains and erasure probes). Both are unmeasured placeholders, set to 0 here (see the break-even below). S6a's assumptions A1-A14 and formulas apply, with r7c's inputs:
- a turn is 6.7 s, 4.2 s of it upstream;
- session fixed time is 21.4 s (the mean, with session 5's slow close);
- each long sprint has 2 compaction calls at 67.5 s each, as in r7c's one long session (80 per life);
- a probe episode is 9.4 s plus a 22.2 s live turn (18.3 s upstream);
- aux is 6.0 s per session;
- each Hermes process uses 185 MiB.

At ×1, R = 4.56 h, P = 2.63 h and the critical path is 4.6 h.

**Concurrency.** C = 20 is the soak's effective concurrency: the floor of 20.6, by Little's law with ok-call service time clipped to the send window. It was measured above the rate threshold. The ramp's burst level of 48 is not a sustained level and is not projected.

**Achievable concurrency on k accounts.** At R_s per account, k accounts sustain about k × C_eff requests in flight, where C_eff = R_s × mean request latency. With R_s = 180 per minute and r7c's mean request of 6.04 s, C_eff is 18.1. Requests in flight beyond C_eff only queue behind the rate limit. The machine caps C too: J × 215 MiB ≤ 16 GiB allows J ≤ 76 Hermes processes, which is C ≤ 53 on the full board. (At r7c's peak of 218 MiB, J ≤ 75.) One account therefore reaches C = 18, and two accounts reach C = 36, with J = 52. Each verdict below is read at C = 20 and at the achievable C. The DV42 rule (DECISIONS §L.1) reads criterion 2 at C = 24. There, every one-account verdict is the same as at C = 20, and the two-account full board fits (lane time 21.4 h), as it does at C = 36.

**Request-rate bound.** r7c's upstream requests per unit, retries included:
- 1.0 per scripted turn (the write turn; the scripted turn itself is served from the script);
- 1.0 per compaction call, at 2.0 compaction calls per long session;
- 1.25 aux per session;
- 2.75 per probe turn (n = 4 probe turns, 11 calls).

Scaled with the same §11 formulas, N_req at L = 48 is 263,700 for the board and 166,488 for the study (215,700 and 70,924 after cuts 1-2). The bound is N_req ÷ R_s, and a cell fits when max(lane time at C, N_req ÷ R_s) ≤ 24 h. At R_s = 180 per minute, C_eff is 18.1 at r7c's 6.04 s mean request (18.4 at the soak's 6.12 s). At 360 per minute it is 36.3 (36.7).

The board's N_req fell from r7b's 282,600 although compaction calls doubled. Changing one input at a time from r7b's value to r7c's: compaction calls (1 → 2 per long sprint) add 3,600, aux (1.33 → 1.25 per session) removes 4,500, and probe requests (3.25 → 2.75 per probe turn) remove 18,000, for −18,900 net.

At ×1 latency, with a write turn before every turn (board; study). Each cell is job h / lane h at C, then N_req ÷ R_s at 180 and 360 per minute. ✓ marks ≤ 24 h. **Fits** means max(lane, rate at 180) ≤ 24 h.

| L, cuts | C = 16 | C = 20 | C = 24 | C = 32 | Rate bound, h (180 / 360) | Fits at 1 account |
|---|---|---|---|---|---|---|
| 48, none, board | 45.4 / 32.0 | 36.3 / 25.6 | 30.3 / 21.4✓ | 22.7✓ / 16.0✓ | 24.4 / 12.2✓ | **no, at any C** (rate 24.4 h, and lane-bound below C = 22; 2 accounts: from C = 24) |
| 48, none, study | 30.0 / 20.8✓ | 24.0✓ / 16.7✓ | 20.0✓ / 13.9✓ | 15.0✓ / 10.4✓ | 15.4✓ / 7.7✓ | from C = 16 |
| 48, cuts 1-2, board | 38.8 / 27.0 | 31.0 / 21.6✓ | 25.9 / 18.0✓ | 19.4✓ / 13.5✓ | 20.0✓ / 10.0✓ | from C = 20 (and at the achievable C = 18, with lane time 23.98 h) |
| 48, cuts 1-2, study | 13.3✓ / 9.1✓ | 10.6✓ / 7.3✓ | 8.9✓ / 6.1✓ | 6.6✓ / 4.6✓ | 6.6✓ / 3.3✓ | from C = 8 |
| 32, none, board | 30.3 / 21.4✓ | 24.2 / 17.1✓ | 20.2✓ / 14.2✓ | 15.1✓ / 10.7✓ | 16.3✓ / 8.1✓ | from C = 16 |
| 32, cuts 1-2, board | 25.9 / 18.0✓ | 20.7✓ / 14.4✓ | 17.2✓ / 12.0✓ | 12.9✓ / 9.0✓ | 13.3✓ / 6.7✓ | from C = 16 |
| 24, none, board | 22.7✓ / 16.0✓ | 18.2✓ / 12.8✓ | 15.1✓ / 10.7✓ | 11.3✓ / 8.0✓ | 12.2✓ / 6.1✓ | from C = 16 |
| 24, cuts 1-2, board | 19.4✓ / 13.5✓ | 15.5✓ / 10.8✓ | 12.9✓ / 9.0✓ | 9.7✓ / 6.7✓ | 10.0✓ / 5.0✓ | from C = 16 |

"From C = n" is the first fitting C in the sampled grid (8, 16, 20, 24, 32). One account reaches only about C = 18 (above), so a column above that is reachable only with more accounts. On two accounts, the L = 48 board's lane time needs C ≥ 22.

**The two-account rows** (R_s = 360 per minute; hypothetical until S6c's two-account paced soak):

| L = 48 | C = 20: lane / rate h, J | Achievable C = 36: lane / rate h, J |
|---|---|---|
| Board, no cuts | 25.6 / 12.2, J 29: **does not fit** | 14.2✓ / 12.2✓, J 52: **fits** |
| Board, cuts 1-2 | 21.6✓ / 10.0✓, J 29: fits | 12.0✓ / 10.0✓, J 52: fits |

**Probe sensitivity.** The probe live-turn calls carry 37.5% of the full board's N_req. The probe input is r7c's 2.75 requests per probe turn, from n = 4 probe turns. On requests alone, the one-account full board would fit at **2.63 or fewer** requests per probe turn. S6a measured 2.25 (r6) and 2.0 (r3) on GLM. Its lane time binds as well, though: 25.6 h at C = 20 and 28.5 h at the achievable C = 18, whatever the probe input. A lower probe input alone does not make it fit. The board's rate bound at probe requests ×1, ×1.5 and ×2 is 24.4, 29.0 and 33.6 h. A larger probe sample is needed before a pilot relies on these rows.

**Flip points.** Each flip point holds every other input fixed (`results/projection.json`, `flip_points`). "None" means no value of that input changes the verdict.

| Cell (L = 48) | Verdict | Probe requests per probe turn | Compaction calls per long sprint | Compaction call, s |
|---|---|---|---|---|
| 1 account, no cuts, C = 20 | no | none (lane-bound) | fits at ≤ 0.75 | none (the rate bound holds) |
| 1 account, cuts 1-2, C = 20 | fits | fails above 4.56 | fails above 2.72 | fails above 91.7 |
| 2 accounts, no cuts, C = 20 | no | none (lane-bound) | fits at ≤ 1.52 | fits at ≤ 51.2 |
| 2 accounts, no cuts, C = 36 | fits | fails above 9.8 | fails above 7.2 | fails above 243 |

Measured: 2.75 probe requests per probe turn, 2 compaction calls per long sprint, and 67.5 s per compaction call.

**The study's added workloads.** C_learn and C_erase are 0 in this grid. At R_s = 180 per minute the study still fits on requests while they stay under about **11,600 upstream requests per study life** at L = 48 (8 study lives), or about **47,000** after cuts 1-2 (4 study lives).

**Latency sensitivity at C = 20** (L = 48, no cuts; board, then study; job / lane h):

| Latency | Board | Study | Critical path |
|---|---|---|---|
| ×0.5 | 25.7 / 12.8 | 17.0 / 8.3 | 3.2 h |
| ×1 | 36.3 / 25.6 | 24.0 / 16.7 | 4.6 h |
| ×1.5 | 46.9 / 38.4 | 31.0 / 25.0 | 5.9 h |

The rate bound does not change with latency. At ×1.5, L = 48 with cuts 1-2 needs C = 27 by lane time.

**Cuts at C = 20, ×1** (board / study, job h): none 36.3 / 24.0; cut 1 31.0 / 21.3; cut 2 31.0 / 10.6; cut 3 15.5 / 10.6. By job time the board needs C = 31 (26 after cuts 1-2, 13 after all three). By lane time it needs C = 22 (18, 9).

**Processes.** The lane reading at C = 20 needs J = 29 concurrent Hermes processes (29-30 with cuts 1-2). That is about 5.3-5.4 GiB at the mean RSS and 6.2-6.4 GiB at peak. At the two-account achievable C = 36 it needs J = 52: 9.4 GiB at the mean and 11.1 GiB at peak. Only one process at a time was tested. The full grid is in `results/projection.json`: ×0.5 and ×1.5 for every row, all three write cadences, both readings and both rates, plus the probe sensitivity, the flip points, the k-account rows and the break-even.

**Quota extrapolation.** This is an upper bound only, from one account at one time of day, assuming burn is linear per served request. Neither window moved by one whole-percent step between 08:08:34 and 08:37:52 UTC. In that span the upstream served 694 requests: the soak's 598, the stopped r7b attempt's 6 and r7b's 90. Refused calls are not counted. That bounds the burn below 1/694 points per request (< 0.00145). The span is unchanged by r7c, whose 88 calls ran later; only the request counts below are r7c's.
- **Weekly window.** A board makes 263,700 requests (215,700 after cuts 1-2), which is under 380 points (< 311). That does not show a board fits the weekly window: the readings are too coarse.
- **5-hour window.** At the board's mean of 183.1 requests per minute, a 5-hour window holds 54,938 requests, which is under 79.2 points of it. The response headers report only the weekly primary window (the secondary window reads 0 minutes), so the 5-hour figure rests on the status reader alone.
- **Rate.** Separately, the board's 183.1 requests per minute, averaged over 24 h, exceed the planning rate: the rate bound's verdict above.

**Verdicts at r7c.** The change from r7b is given in brackets.
- **One account, L = 48, no cuts: does not fit** [unchanged]. Its requests take 24.4 h at 180 per minute. Its lane time is 25.6 h at C = 20 and 28.5 h at the achievable C = 18. Under r7b it was bound by the rate limit only. It is now bound by lane time as well at C = 20 and at the achievable C = 18. It flips only if compaction calls fall to 0.75 per long sprint or below. The probe input alone cannot flip it.
- **One account, L = 48, cuts 1-2: fits** [unchanged]. Lane time is 21.6 h at C = 20, and requests take 20.0 h. At the achievable C = 18, lane time is 23.98 h, a margin of about a minute. It is now lane-bound, and fits from C = 20 in the grid [r7b: from C = 16].
- **One account, L = 32, no cuts: fits from C = 16** [unchanged].
- **Robustness study, L = 48: fits from C = 16** [unchanged], while C_learn + C_erase stay under the break-even.
- **Two accounts (hypothetical), L = 48, no cuts.** At C = 20 it **does not fit**, with lane time 25.6 h [changed: under r7b it fitted at 22.7 h]. At the achievable C = 36 it **fits**: lane time 14.2 h, requests 12.2 h, J = 52 ≤ 76 [a new reading].

Per §11 the choice goes to the owner: a second account (to be validated by S6c's two-account paced soak), cuts 1-2, or L = 32.

### Declared limitation: title requests carry no reasoning field
Hermes's title generator disables reasoning for its request, and Hermes ranks that above the configured auxiliary effort pin. `gpt-6.1-sol` has no "none" effort to pin instead, so title-generation requests reach the upstream with no `reasoning` field, and the upstream default applies to them. Compaction and every other auxiliary task carry `reasoning.effort = medium`.

### Pilot requirement: a director-side pacer
This spike needs no pacer: r7c ran one Hermes process. A board run does. The director should hold each account's request rate under R_s (180 per minute in this plan) with a burst capacity of at most 19, so that no 60 s window exceeds 199 starts, and honour `retry-after`, so that a 429 burst never reaches Hermes as a stall.

### Run conditions
- The disk floor for r7b and r7c was lowered to 20 GB, because a run's peak disk is about 37 MB. This was the benchmark owner's decision under the machine's current light-work rule. An earlier r7b attempt stopped itself after session 1 on the old 150 GB floor (5 turns, 6 upstream calls). It is kept as disclosed partial evidence and not used.
- Upstream budget: S6b made 1,217 Sol upstream calls, under the cap of 1,400 (raised from 400 by the benchmark owner after the burst ramp). By run: live smokes 8, ramp 264, aborted r7-write 61, soak 700, stopped r7b 6, r7b 90, r7c 88 (r7c's stub smoke made no upstream call).
## Footnote: the aborted r7-write
An earlier run, r7-write, ran on the director before its review fixes. A machine-wide hold on the lane's traffic stopped it after scripted turn 8.1. It is disclosed partial evidence, never the run of record. 46 scripted turns completed, all ok, with 61 upstream calls (47 write turns, 13 aux, 1 compaction). Write turns: p50 3.3 s, p90 6.1 s, mean 5.0 s, max 26.2 s (n = 47); prompt mean 4,941 tokens (67% cached), completion mean 19; 2 `memory` calls executed; readback 47/47. Its one compaction took 97 s. Its aux and compaction requests carried no effort pin. Its forwarded bodies are the soak's payloads. Conditions: marker exit 0, `glm` false, load mean 19.8 (6.9-54.5, n = 61 calls). The stopped r7b attempt (5 turns, 6 calls) ran at marker exit 0, load mean 9.1 (n = 10 timings).

## Does not prove
- Any quality or score for any memory system: nothing is scored.
- Sustained behaviour beyond a 3.6-minute soak. The ramp's levels lasted about 25 s each, and burst headroom is not sustained headroom.
- The account's quota windows, which are not published and can change without notice. One account at one time of day is measured, and the quota extrapolation is a coarse upper bound from that alone.
- The rate-limit inference beyond this account and day: it rests on two bursts on one account at one time of day.
- That the rate limit is per account, and so doubles with a second account on the same host. The two-account rows assume it. It is untested here, so those rows stay hypothetical until S6c's two-account paced soak.
- That k accounts reach k × C_eff in flight. The achievable concurrency is derived from R_s and the mean request latency, not measured.
- The verdicts beyond their inputs. Probe requests come from n = 4 probe turns (11 calls), and compaction from one long session (2 calls). The flip points are in the table above. The one-account fit with cuts 1-2 at the achievable C = 18 has a margin of about a minute.
- The quota extrapolation's linearity: it assumes burn is linear per served request, and the readings are whole percentages.
- Behaviour outside a provider-side shedding window. The upstream was shedding load model-wide all day from about 06:21 UTC (`server_overloaded`, and 429s at connect with retries of 60-240 s). As reported for the day, that was about 18 failures per 1,000 requests on `gpt-6.1-sol`. Every measurement here falls inside that window. The soak saw 2.9 in-stream overloads per 1,000, and r7b and r7c saw none.
- The soak's prompt-cache share (83%) for a board: its bodies were each re-sent about 15 times.
- Many Hermes processes at once. Only one was run, while the lane reading needs about 29 at C = 20 and 52 at the two-account achievable C = 36.
- That one micro-life behaves like a board run, or that its 2 compaction calls in one long session are typical.
- Latency on other machines, accounts or times of day.
