# S6a report: a micro-life on Hermes' native memory

**Claim** (`advisory`): the synthetic 10-session micro-life replays end to end through unmodified Hermes v0.22.2 with native memory and live write turns. Projected with PREREG-v0.1 §11, a 200-session life's sequential critical path is about 6.6 h, which fits the 24-hour rule. The total work of the full core board for one system does not fit at the measured lane concurrency of 8 at nominal latency, in either reading, even after all three §11 cuts. At nominal latency it fits by lane time from lane concurrency 16 with L = 24, or 24 with L = 32, so under §11 the choice goes to the owner.

## Method
- **Harness.** Hermes v0.22.2 (commit d923a5eb), unmodified, Python 3.14. Each run has its own new `HERMES_HOME`. The config enables built-in memory and the user profile with no external `memory.provider`, turns shared metrics and update checks off, and limits the ACP toolsets to `memory`, `session_search` and `todo`. Main, compression and every other auxiliary task point at the director on 127.0.0.1 with a placeholder key.
- **Driving (fallback, disclosed).** The pinned install lacks the optional dependency that `hermes acp`'s JSON-RPC transport needs. So `hermes_worker.py` drives the ACP adapter's own session path in process: `SessionManager`, `AIAgent.run_conversation`, `save_session` and `end_all_sessions`. Each life session is a new Hermes session in a new process.
- **Director** (`director.py`). Requests are classified by the tool-call ids the director issued or forwarded, by per-task base URL, by cursor match against the script, or by Hermes' background-review prefix. Anything else gets a 400 and is logged as `unknown`. The incoming `Authorization` header is dropped. Forwarded calls carry every harness key, `reasoning_effort` included; the only adaptations are the model alias and non-streaming transport. Each request record is appended before the response is sent. A guard aborts the process if the upstream credential reaches any ledger write. Records are hash-chained JSONL, with bodies stored by SHA-256 (zstd).
- **Write turns** (PREREG §10; the suffix is provisional and labelled so). Before each scripted turn, the director sends the live model Hermes' own request plus one uniform suffix, with tools filtered to the declared write tool `memory`. Any `memory` call goes back to Hermes, which executes it. The scripted turn is then served on the tool-result request. The director executes no tool. A readback checks that the forwarded body is the harness request plus the suffix, and a failed write turn stops the run.
- **Micro-life** (`life.py`, seed 6101). 10 synthetic G1 sessions with 60 scripted turns. It has six facts told in sessions 1-3, a correction in session 5, a commitment due in session 7, a SIGKILL restart after turn 5.2, a three-week gap before session 8 (told in the text only) and a 15-turn log sprint in session 6. Two live probe sessions of two turns each follow the life.
- **Compaction.** Life runs use `context_length` 64000, `compression.threshold_tokens` 12000 and `protect_last_n` 6, so session 6 compacts. The overhead run uses Hermes' defaults: context 131072, no threshold override, default toolsets.
- **Model and machine.** The model is `glm-5.3` (provisional; C-1 is open), and the served model id is recorded per call. Every process ran under `nice -n 19 taskpolicy -b`, gated per session on the busy marker, with at most 2 Hermes processes at a time. Upstream calls pause while the marker reads `glm=true`.
- **Egress.** Hermes' `HTTP(S)_PROXY` points at the director, which logs and refuses any proxied attempt, and `lsof` samples each Hermes process once a second.

**Runs.** The overhead run is 1 session at defaults. `scripted` is the life with no write turns. `write` (the run of record, r6) is the life with write turns and probes, on the fixed director that forwards the harness's inference parameters. `write-r3` is the same life on the earlier director, which stripped `reasoning_effort`; it is kept as the "parameters stripped" comparison. `par-a` and `par-b` are the scripted life run twice at once. An earlier write run stopped at turn 10.2 when its lane was halted, and it is not used.

## Results
All timings are wall clock. Load is the 1-minute load average on a 14-core machine shared with a running release gauntlet. `write` ran with marker exit 0-10 and `glm` false at every timing, with no upstream pause.

| Measurement | n | Value | Marker, load |
|---|---|---|---|
| Harness overhead, defaults (19 tools) | 1 | 10,260 prompt tokens on a minimal first turn; system 5,810 chars, tool schemas 36,770 chars | exit 10, glm false, load 5.5 |
| Harness overhead, life config (4 tools) | 3 | 2,647, 2,610 and 2,643 prompt tokens; system about 5,300 chars, schemas 5,482 chars | exit 0-10 |
| **C-5** | | 2 × 10,260 = 20,520, so the rule selects **24K** at defaults (16K for the 4-tool config) | |
| Scripted turn (harness only) | 60 | p50 0.74 s, mean 8.4 s (including two compactions); 2.26 s with compaction removed | exit 10, load mean 14.5 |
| Session fixed time, scripted | 10 | mean 31.9 s: spawn 3.4, open 19.0, drain 7.2, close 1.4 | as above |
| Session total, scripted | 10 | mean 82.5 s, p50 29.2 s, max 402 s (session 6) | as above |
| Session total, with write turns | 10 | mean 108.8 s, p50 58.1 s, max 352 s (session 6); fixed time mean 28.9 s | exit 0-10, load mean 13.0 |
| Turn with write turn | 60 | mean 13.3 s, p50 7.4 s; mean 10.0 s with compaction removed | as above |
| Write-turn calls | 60 | 1 call per turn, 0 refused; latency mean 6.6 s, p50 6.1 s, p90 9.0 s, max 20.9 s | as above |
| Write-turn tokens | 60 | prompt mean 4,009 (p50 2,674, max 12,953); completion mean 80 (p50 61, max 316) | as above |
| Write-turn effect | 60 | 14 `memory` calls executed by Hermes; forwarded-body readback 60/60; `reasoning_effort` accepted (0 rejections) | as above |
| Summariser (compaction) | 2 in `write`, 10 in all runs | `write`: 79 s and 119 s, prompt 7,990 and 10,575, completion 5,958 and 9,920 (mostly reasoning); both inside turns | as above |
| Aux (titles) | 12 | mean 5.1 s; 5.1 s of upstream time per session | as above |
| Restart wake (SIGKILL, respawn, resume) | 3 | 9.3 s, 11.1 s and 25.3 s; resumed history 6 messages | exit 0-10 |
| Probe turn (live agent) | 4 | mean 31.5 s, min 5.6 s, max 54.0 s; 9 upstream calls, mean 10.5 s; session fixed mean 26.3 s (n = 2) | exit 0-10 |
| Hermes process memory | 13 processes | RSS mean of per-process means 176 MiB, peak 215 MiB | as above |
| Parallel roots | 2 × 10 sessions | both completed with 0 unknown, 10 sessions and 126 messages per home, identical to the single run. Session mean is 0.85× and 0.87× the single run, turn p50 1.04× and 0.97×. No slowdown is detectable at n = 1 per arm. | exit 0-10, load 12.2, 13.0 |
| Concurrency ramp | 62 calls | levels 1, 2, 4 and 8 clean (16 at level 8, p50 1.8 s). Level 16: 14 of 32 refused, all 429 concurrency. Every level was fully funded. | exit 10, glm false, load 19-26 |
| **C-11** | | sustained concurrency **8**; the binding limit is **concurrency** (no rate or quota refusal); the 24-hour rule is **not met** at 8 (below) | |
| Egress | 731 samples in `write`; every run | 0 non-loopback sockets and 0 proxied attempts | |
| Classification and ledger | all runs | 0 unknown in `write`, `scripted` and the parallel runs. `write`: 136 records, 0 chain breaks, 84 upstream attempts recorded = 84 budgeted | |
| Bundles a short life can host | | 53 (fact, probe point) pairs over the 10 boundaries; 8 at end of life only | |

**Parameters forwarded (r6) against parameters stripped (r3).** Same life, director, model and machine; only the forwarding differs. Each value is r6 / r3, n = 60 write turns per run.

| Write turn | p50 | p90 | mean | prompt tokens, mean | completion tokens, mean | `memory` calls executed |
|---|---|---|---|---|---|---|
| Latency, s | 6.1 / 10.4 | 9.0 / 28.6 | 6.6 / 16.0 | 4,009 / 4,087 | 80 / 571 | 14 / 21 |

With `reasoning_effort: medium` forwarded, the upstream reasons far less than at its own default, so latency falls by 59% at the mean and completions by 86%. Hermes also made fewer memory writes. That is a behaviour change from one parameter, which is why r3 is not the run of record. Turns with compaction removed went from 19.3 s to 10.0 s; compaction calls from 140 s to 99 s.

- **Two harness events in `write`, both classified.** One title call hit Hermes' 30 s auxiliary timeout (34.8 s upstream). Its record was kept and flagged `client_disconnected`, the case the review's first finding covers. Hermes then sent its fallback title request on the main route, and the director, matching the current probe turn's text, classified it as a probe retry and forwarded it (2.2 s). That adds about 0.5 s per probe turn.
- **The earlier unknown.** In r3, at probe P2.2, Hermes split a batched `tool_call` into two results under an id of its own; the director refused it fail-closed. The director now matches any trailing result or the call it answers, and `write` had 0 unknown.
- **Upstream refusals.** 4 of 5 attempts at the default-toolset overhead request got 429 code 1305 ("temporarily overloaded"). A 21-call diagnostic found no content trigger, and the identical request then succeeded. No quota refusal was seen in any run.
- **Upstream budget.** 439 calls in all: 355 before the fixes (ramp 62, diagnostics 21, overhead runs 12, halted write run 72, `scripted` 32, `write-r3` 83, parallel 64, re-run probes 9), then 84 for `write`.

### The 24-hour projection (PREREG-v0.1 §11)
**Assumptions** (all inputs measured in `write` unless noted):
- **A1.** S = 200 sessions with 5 assistant turns each, one write turn per turn.
- **A2.** A turn is 10.0 s, of which 6.6 s is upstream. The latency multiplier scales only the upstream share.
- **A3.** Session fixed time is 28.9 s.
- **A4.** 20% of sessions are long sprints, each compacting twice as the micro-life's did, at 99 s each: 80 compactions per life.
- **A5.** A probe episode is a new session (26.3 s) plus one live turn (31.5 s, of which 23.5 s is upstream), with b = 150.
- **A6.** R_cap = R, and the fault and swap add nothing.
- **A7.** f = 0.5.
- **A8.** r_c = 0.15R, p_c = P/4, P_W = 0.1P and P_K = 0.2P.
- **A9.** R_B = R, P_B = P and δ_W = 1.
- **A10.** Resume-only controls double P.
- **A11.** Critical path = R plus one probe episode, since B1 and the checkpoint probes fork and run alongside B0.
- **A12.** Total work is read two ways. Job time ÷ C assumes every second of a job holds a lane slot. Lane time ÷ C counts upstream seconds only, auxiliary calls (5.1 s per session, probe sessions included) counted.
- **A13.** In the lane reading, keeping C lane slots busy needs J = ⌈C × job time ÷ lane time⌉ concurrent jobs, one Hermes process each, at 176 MiB per process (215 MiB peak). In the job reading J = C. Only 2 processes at once were tested.
- **A14.** The write-cadence rows are hypothetical design options, not a recommendation. A turn without a write turn takes the scripted run's 2.26 s.

At ×1 latency this gives R = 6.59 h, P = 4.82 h and a critical path of 6.6 h. With L = 48 and L_keep = 12, the board is 1,171 job-hours (676 lane-hours) and the robustness study is 755 (448).

| Latency | C = 8 | 16 | 24 | 32 | Critical path | C needed (job / lane) |
|---|---|---|---|---|---|---|
| ×0.5, board | 109 h / 42 h | 54 / 21 | 36 / 14 | 27 / 11 | 4.6 h | 37 / 15 |
| ×0.5, robustness | 69 / 28 | 35 / 14 | 23 / 9 | 17 / 7 | 4.6 h | 24 / 10 |
| ×1, board | **146 h / 85 h** | 73 / 42 | 49 / 28 | 37 / 21 | **6.6 h** | **49 / 29** |
| ×1, robustness | **94 h / 56 h** | 47 / 28 | 31 / 19 | 24 / 14 | 6.6 h | **32 / 19** |
| ×1.5, board | 184 h / 127 h | 92 / 63 | 61 / 42 | 46 / 32 | 8.6 h | 62 / 43 |
| ×1.5, robustness | 120 / 84 | 60 / 42 | 40 / 28 | 30 / 21 | 8.6 h | 40 / 29 |

Each cell is job-time wall ÷ lane-time wall, in hours. **Cuts at C = 8, ×1** (board / robustness, job time): cut 1 (b = 100) 122 h / 82 h; cut 2 (L_rob = 4) 122 h / 41 h; cut 3 (L = 24) 61 h / 41 h. After all three cuts the board needs C = 21 by job time (13 by lane time) and the study 14 (9). Variants at C = 8, board: 134 h with one compaction per sprint, 110 h without resume-only controls, 171 h at f = 1; δ_W = 0 changes only the study, to 84 h.

**Board size, lane concurrency and job concurrency** (write turn before every turn; cuts 1-2 are b = 100 and L_rob = 4). Each cell is board job / lane hours; study job / lane hours. ✓ marks ≤ 24 h.

| L, cuts | Latency | C = 8 | C = 16 | C = 24 |
|---|---|---|---|---|
| 48, none | ×0.5 | 109 / 42; 69 / 28 | 54 / 21✓; 35 / 14✓ | 36 / 14✓; 23✓ / 9✓ |
| 48, none | ×1 | 146 / 84; 94 / 56 | 73 / 42; 47 / 28 | 49 / 28; 32 / 19✓ |
| 48, none | ×1.5 | 184 / 127; 120 / 84 | 92 / 63; 60 / 42 | 61 / 42; 40 / 28 |
| 48, cuts 1-2 | ×0.5 | 90 / 36; 30 / 12✓ | 45 / 18✓; 15✓ / 6✓ | 30 / 12✓; 10✓ / 5✓ |
| 48, cuts 1-2 | ×1 | 122 / 73; 41 / 25 | 61 / 36; 20✓ / 12✓ | 41 / 24; 14✓ / 8✓ |
| 48, cuts 1-2 | ×1.5 | 155 / 109; 52 / 37 | 77 / 54; 26 / 19✓ | 52 / 36; 17✓ / 12✓ |
| 32, none | ×1 | 98 / 56; 94 / 56 | 49 / 28; 47 / 28 | 32 / 19✓; 32 / 19✓ |
| 32, cuts 1-2 | ×1 | 82 / 48; 41 / 25 | 41 / 24; 20✓ / 12✓ | 27 / 16✓; 14✓ / 8✓ |
| 24, none | ×1 | 73 / 42; 88 / 52 | 37 / 21✓; 44 / 26 | 24 / 14✓; 30 / 17✓ |
| 24, cuts 1-2 | ×1 | 61 / 36; 41 / 25 | 31 / 18✓; 20✓ / 12✓ | 20✓ / 12✓; 14✓ / 8✓ |

At ×1, J is 14 at C = 8, 27-28 at C = 16 and 40-42 at C = 24, so the lane reading at C = 24 needs about 42 Hermes processes, about 7.2 GiB at the mean RSS (8.8 GiB at peak). The full grid, ×0.5 and ×1.5 for every row and both readings, is in `results/projection.json`.

**Write-turn cadence** (hypothetical design options, never a recommendation; L = 48, ×1, board / study, job then lane hours):

| Cadence | Write turns per life | C = 8 | C = 16 | C = 24 |
|---|---|---|---|---|
| before every scripted turn (current) | 1,000 | 146 / 94, lane 85 / 56 | 73 / 47, lane 42 / 28 | 49 / 31, lane 28 / 19✓ |
| before every 2nd turn | 600 | 137 / 87, lane 76 / 50 | 68 / 44, lane 38 / 25 | 46 / 29, lane 25 / 16✓ |
| once per session plus before compaction | 280 | 129 / 81, lane 70 / 44 | 64 / 40, lane 35 / 22✓ | 43 / 27, lane 23✓ / 15✓ |

The cadence moves the critical path from 6.6 h to 5.7 h and 5.1 h, but total work only by 6-12% in job time, since session start-up, compaction and probes dominate. With cuts 1-2 at C = 24 the study fits in both readings at every cadence, and the board fits by lane time only with the two reduced cadences.

**Verdict.** Each life's sequential critical path fits within 24 h at every latency multiplier tested. At the measured C = 8 the full board at L = 48 fits in neither reading at any latency, cadence or cut tested, and at ×1 with the current cadence nothing fits. At C = 8 only lane-time readings fit, at ×0.5 or with a reduced cadence (for example the study after cuts 1-2). At ×1 the board fits by lane time from C = 16 at L = 24 and from C = 24 at L = 32, but not at L = 48 even with cuts 1-2 (24.2 h); by job time it fits only at L = 24 with cuts 1-2 and C = 24. The lane reading at C = 24 needs about 40 concurrent Hermes processes. Per §11 this goes to the owner: for the full board at L = 48, paid model capacity of about C ≥ 29 by lane time or 49 by job time (13 and 21 after all three cuts), or a narrower design. Compaction is 33% of R and per-session Hermes start-up is 24%, so those are the cheapest places to look.

## What is deferred
- C-1, the measurement model, and C-6, the write-turn text and tool lists.
- S6: a full-scale life at about 2M tokens, with real prompt sizes. Here a write-turn prompt averages 4.0K tokens, so latency at full scale is likely higher (see ×1.5).
- A sustained-concurrency soak at levels between 8 and 16, and at other times of day. The ramp's quota stop and funding check were added after the recorded ramp, which was fully funded and saw no quota refusal; it was not re-run.
- Machine capacity for C parallel Hermes processes.
- JSON-RPC `hermes acp` driving, once its transport dependency is in the pin.

## Does not prove
- Any quality or score for Hermes native memory or any other system: the probe answers are not scored.
- Latency on other machines, lanes or times of day. One shared machine, one shared model lane and one morning were measured.
- Simulated time: this spike ran on wall time.
- That a generated life behaves like this micro-life.
- The final write-turn text (C-6) or the measurement model (C-1).
