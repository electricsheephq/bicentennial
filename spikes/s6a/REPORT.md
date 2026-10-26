# S6a report: a micro-life on Hermes' native memory

**Claim** (`advisory`): the synthetic 10-session micro-life replays end to end through unmodified Hermes v0.22.2 with native memory and live write turns. Projected with PREREG-v0.1 §11, a 200-session life's sequential critical path is about 10 h, which fits the 24-hour rule. The total work of the full core board for one system does not fit at the measured lane concurrency of 8, at any latency multiplier tested or after all three §11 cuts. The board needs about 34-52 concurrent jobs, so under §11 the choice goes to the owner.

## Method
- **Harness.** Hermes v0.22.2 (commit d923a5eb), unmodified, Python 3.14. Each run has its own new `HERMES_HOME`. The config enables built-in memory and the user profile with no external `memory.provider`, turns shared metrics and update checks off, and limits the ACP toolsets to `memory`, `session_search` and `todo`. Main, compression and every other auxiliary task point at the director on 127.0.0.1 with a placeholder key.
- **Driving (fallback, disclosed).** The pinned install lacks the optional dependency that `hermes acp`'s JSON-RPC transport needs. So `hermes_worker.py` drives the ACP adapter's own session path in process: `SessionManager`, `AIAgent.run_conversation`, `save_session` and `end_all_sessions`. Each life session is a new Hermes session in a new process.
- **Director** (`director.py`). Requests are classified by the tool-call ids the director issued or forwarded, by per-task base URL, by cursor match against the script, or by Hermes' background-review prefix. Anything else gets a 400 and is logged as `unknown`. The incoming `Authorization` header is dropped. A guard aborts the process if the upstream credential reaches any ledger write. Records are hash-chained JSONL, with bodies stored by SHA-256 (zstd).
- **Write turns** (PREREG §10; the suffix is provisional and labelled so). Before each scripted turn, the director sends the live model Hermes' own request plus one uniform suffix, with tools filtered to the declared write tool `memory`. Any `memory` call goes back to Hermes, which executes it. The scripted turn is then served on the tool-result request. The director executes no tool.
- **Micro-life** (`life.py`, seed 6101). 10 synthetic G1 sessions with 60 scripted turns. It has six facts told in sessions 1-3, a correction in session 5, a commitment due in session 7, a SIGKILL restart after turn 5.2, a three-week gap before session 8 (told in the text only) and a 15-turn log sprint in session 6. Two live probe sessions of two turns each follow the life.
- **Compaction.** Life runs use `context_length` 64000, `compression.threshold_tokens` 12000 and `protect_last_n` 6, so session 6 compacts. The overhead run uses Hermes' defaults: context 131072, no threshold override, default toolsets.
- **Model and machine.** The model is `glm-5.3` (provisional; C-1 is open), and the served model id is recorded per call. Every process ran under `nice -n 19 taskpolicy -b`, gated per session on the busy marker, with at most 2 Hermes processes at a time. Upstream calls pause while the marker reads `glm=true`.
- **Egress.** Hermes' `HTTP(S)_PROXY` points at the director, which logs and refuses any proxied attempt, and `lsof` samples each Hermes process once a second.

**Runs.** The overhead run is 1 session at defaults. `scripted` is the life with no write turns. `write` is the life with write turns and probes. `par-a` and `par-b` are the scripted life run twice at once. `probes` re-runs the two probe sessions on a copy of `write`'s final home (see Results). An earlier write run stopped at turn 10.2 when its lane was halted, and it is not used.

## Results
All timings are wall clock. Load is the 1-minute load average on a 14-core machine shared with a running release gauntlet.

| Measurement | n | Value | Marker, load |
|---|---|---|---|
| Harness overhead, defaults (19 tools) | 1 | 10,260 prompt tokens on a minimal first turn; system 5,810 chars, tool schemas 36,770 chars | exit 10, glm false, load 5.5 |
| Harness overhead, life config (4 tools) | 2 | 2,647 and 2,610 prompt tokens; system about 5,300 chars, schemas 5,482 chars | exit 0-10 |
| C-5 input | | 2 × 10,260 = 20,520, so the rule selects **24K** at defaults (16K for the 4-tool config) | |
| Scripted turn (harness only) | 60 | p50 0.74 s, mean 8.4 s (including two compactions) | exit 10, load mean 14.5 |
| Session fixed time, scripted | 10 | mean 31.9 s: spawn 3.4, open 19.0, drain 7.2, close 1.4 | as above |
| Session total, scripted | 10 | mean 82.5 s, p50 29.2 s, max 402 s (session 6) | as above |
| Session total, with write turns | 10 | mean 210.6 s, p50 106.5 s; session 6 is 1,146 s, including a 360 s marker pause | exit 0-10, load mean 12.3 |
| Turn with write turn | 60 | mean 24.0 s and p50 14.9 s with the pause removed; mean 19.3 s with compaction also removed | as above |
| Write-turn calls | 60 | 1 call per turn, 0 refused; latency mean 16.0 s, p50 10.4 s, p90 28.6 s, max 111 s | as above |
| Write-turn tokens | 60 | prompt mean 4,087 (p50 2,802, max 12,590); completion mean 571 (p50 281, max 5,441) | as above |
| Write-turn effect | 60 | 21 `memory` calls executed by Hermes; suffix readback 60/60 | as above |
| Summariser (compaction) | 2 in `write`, 8 in all single and parallel runs | `write`: 113 s and 167 s, prompt 8,160 and 9,872, completion 7,752 and 11,630 (mostly reasoning); all 8: 99-196 s. Both `write` calls fell inside turns | as above |
| Aux (titles) | 12 | mean 4.9 s | as above |
| Restart wake (SIGKILL, respawn, resume) | 2 | 9.3 s and 11.1 s; resumed history 6 messages | exit 10 |
| Probe turn (live agent) | 4 | mean 15.7 s, p50 12.4 s, max 33.6 s; 6 upstream calls, mean 8.3 s; session fixed mean 16.9 s (n = 2) | exit 10, load mean 12.4 |
| Parallel roots | 2 × 10 sessions | both completed with 0 unknown, 10 sessions and 126 messages per home, identical to the single run. Session mean is 0.85× and 0.87× the single run, turn p50 1.04× and 0.97×. No slowdown is detectable at n = 1 per arm. | exit 0-10, load 12.2, 13.0 |
| Concurrency ramp | 62 calls | levels 1, 2, 4 and 8 clean (16 at level 8, p50 1.8 s). Level 16: 14 of 32 refused, all 429 concurrency. **Sustained concurrency 8; concurrency is the binding limit** | exit 10, glm false, load 19-26 |
| Egress | 3,175 samples over the 6 runs used | 0 non-loopback sockets and 0 proxied attempts in every run | |
| Classification | all runs | 0 unknown, except 1 in `write` (below) | |
| Bundles a short life can host | | 53 (fact, probe point) pairs over the 10 boundaries; 8 at end of life only | |

- **The one unknown.** At probe P2.2 the model batched two `session_search` reads into one call of Hermes' `tool_call` meta-tool. Hermes split it into two results under an id of its own, and the director, which matched only the last result's id, refused it fail-closed. The director now matches any trailing result or the call it answers. It also serves a re-sent current turn from the script, which this run did not need. The `probes` run used the fixed director, on a copy of the home, with 0 unknown. The parallel roots also ran the fixed director.
- **Upstream refusals.** 4 of 5 attempts at the default-toolset overhead request got 429 code 1305 ("temporarily overloaded"). A 21-call diagnostic found no content trigger, and the identical request then succeeded. No quota refusal was seen.
- **Upstream budget.** 355 of 400 calls: ramp 62, diagnostics 21, overhead runs 12, halted earlier write run 72, `scripted` 32, `write` 83, parallel 64, `probes` 9.

### The 24-hour projection (PREREG-v0.1 §11)
**Assumptions:**
- **A1.** S = 200 sessions with 5 assistant turns each, one write turn per turn.
- **A2.** A turn is 19.3 s, of which 16.0 s is upstream. The latency multiplier scales only the upstream share.
- **A3.** Session fixed time is 30.6 s.
- **A4.** 20% of sessions are long sprints, each compacting twice as the micro-life's did, at 140 s each: 80 compactions per life.
- **A5.** A probe episode is a new session (16.9 s) plus one live turn (15.7 s, of which 12.4 s is upstream), with b = 150.
- **A6.** R_cap = R, and the fault and swap add nothing.
- **A7.** f = 0.5.
- **A8.** r_c = 0.15R, p_c = P/4, P_W = 0.1P and P_K = 0.2P.
- **A9.** R_B = R, P_B = P and δ_W = 1.
- **A10.** Resume-only controls double P.
- **A11.** Critical path = R plus one probe episode, since B1 and the checkpoint probes fork and run alongside B0.
- **A12.** Total work is read two ways. Job time ÷ C assumes every second of a job holds a lane slot. Lane time ÷ C counts upstream seconds only. Neither checks whether the machine can host C Hermes processes (only 2 were tested).

This gives R = 10.19 h, P = 2.71 h and a critical path of 10.2 h. With L = 48 and L_keep = 12, the board is 1,242 job-hours (804 lane-hours) and the robustness study is 876 (589).

| Latency | C = 8 | 16 | 24 | 32 | Critical path | C needed (job / lane) |
|---|---|---|---|---|---|---|
| ×0.5, board | 105 h / 50 h | 53 / 25 | 35 / 17 | 26 / 13 | 6.4 h | 36 / 17 |
| ×0.5, robustness | 73 / 37 | 36 / 18 | 24 / 12 | 18 / 9 | 6.4 h | 25 / 13 |
| ×1, board | **155 h / 100 h** | 78 / 50 | 52 / 34 | 39 / 25 | **10.2 h** | **52 / 34** |
| ×1, robustness | **110 h / 74 h** | 55 / 37 | 37 / 25 | 27 / 18 | 10.2 h | **37 / 25** |
| ×1.5, board | 206 h / 151 h | 103 / 75 | 69 / 50 | 51 / 38 | 14.0 h | 69 / 51 |
| ×1.5, robustness | 146 / 111 | 73 / 55 | 49 / 37 | 37 / 28 | 14.0 h | 49 / 37 |

Each cell is job-time wall ÷ lane-time wall, in hours. **Cuts at C = 8, ×1** (board / robustness, job time):
- cut 1 (b = 100): 142 h / 103 h;
- cut 2 (L_rob = 4): 142 h / 51 h;
- cut 3 (L = 24): 71 h / 51 h. After all three cuts the board needs C = 24 by job time (16 by lane time) and the study needs 18 (12).

Variants at C = 8, board: 138 h with one compaction per sprint, 135 h without resume-only controls, 194 h at f = 1. δ_W = 0 changes only the study, to 94 h.

**Verdict.** Each life's sequential critical path fits within 24 h at every latency multiplier tested. Total work does not fit at the measured C = 8. The 24-hour rule fails for the full core board and for the robustness study, even after all three cuts. Per §11 this goes to the owner: paid model capacity of about C ≥ 34-52 (C ≥ 16-24 after the cuts), or a narrower design. Compaction is 31% of R and per-session Hermes start-up is 17%, so those are the cheapest places to look.

## What is deferred
- C-1, the measurement model, and C-6, the write-turn text and tool lists.
- S6: a full-scale life at about 2M tokens, with real prompt sizes. Here a write-turn prompt averages 4.1K tokens, so latency at full scale is likely higher (see ×1.5).
- A sustained-concurrency soak at levels between 8 and 16, and at other times of day.
- Machine capacity for C parallel Hermes processes.
- JSON-RPC `hermes acp` driving, once its transport dependency is in the pin.

## Does not prove
- Any quality or score for Hermes native memory or any other system: the probe answers are not scored.
- Latency on other machines, lanes or times of day. One shared machine, one shared model lane and one morning were measured.
- Simulated time: this spike ran on wall time.
- That a generated life behaves like this micro-life.
- The final write-turn text (C-6) or the measurement model (C-1).
