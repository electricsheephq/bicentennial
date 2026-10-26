# S2 report: simulated clocks

## Claim

**Claim class: `advisory`.** Hermes (0.22.2, in-process `sitecustomize` shim) and Claude Code (the Node build 2.1.112 with `NODE_OPTIONS=--require`, and the pinned native 2.1.306 with `BUN_OPTIONS=--preload`) both see a simulated 3-day gap consistently in the prompt date and in the timestamps they generate from the Python or Node clock. Three kinds of value stay on wall time: kernel-sourced values (file times, including mtimes recorded as data, and process start times), clocks read by non-Python and non-Node children, and engine-internal clock reads. Hermes' wall-time guards behave correctly only while simulated time stays behind wall time. Two of the four guards probed trip when simulated time runs ahead of it.

## Method

- **Clock file.** The director writes `clock.json`, `{"sim_start", "wall_anchor", "rate"}`, before each session. Simulated time is `sim_start + (wall_now - wall_anchor) * rate`, so it ticks normally inside a session. Both shims re-read the file when it changes. Both exit with code 70 instead of falling back to wall time when the file is set but unreadable. With the variable unset, both do nothing.
- **Python shim** (`clockshim/sitecustomize.py`, loaded through `PYTHONPATH`). It patches the functions the spec names, plus the no-argument forms of `ctime`, `asctime` and `strftime`. `datetime.date` and `datetime.datetime` are replaced by subclasses whose metaclass keeps `isinstance` true for C-made instances. Pickle and `repr` keep the stdlib names. Known limit: instances made by the original C classes (for example by a class reference taken before the shim installs) keep `isinstance` but no longer pickle, because `datetime.datetime` is now a different object; instances the shim's classes create pickle and round-trip. A user subclass of `datetime.datetime` keeps ordinary `isinstance` semantics. A self-test asserts all three. The patched time functions do not bind as class attributes, so `logging.Formatter.converter` still works. `time.monotonic`, `perf_counter`, `process_time` and asyncio loop time are deliberately left alone: they measure durations, timeouts depend on them, and the jump happens between processes.
- **Node shim** (`clockshim/clock_shim.cjs`). It patches `Date.now()`, `new Date()` with no arguments, and `Date()` called as a function. The replacement constructor shares `Date.prototype`, so `instanceof` and subclassing still work. `performance.now` is left alone.
- **Model stub** (`stub/recording_stub.py`). It binds 127.0.0.1 only and records every request with credential headers dropped. It answers OpenAI chat completions (JSON or SSE) and Anthropic messages (JSON or SSE) with canned replies. Directive lines in the user turn (`STUB_MEMORY`, `STUB_RUN`, `STUB_TOOL`) become tool calls, so the harness writes memory and runs child processes. Every model response came from the stub.
- **Hermes runs** (`hermes/run_all.sh`). There are four runs, each with two fresh `hermes chat -q` sessions 3 days apart in a fresh `HERMES_HOME`. Outbound HTTP(S) goes to a closed local proxy port.
  - `control`: no shim (wall time).
  - `past-default`: t0 = 2025-03-03T09:00Z, default config.
  - `past`: the same t0, with `terminal.env_passthrough: [BICENTENNIAL_CLOCK_FILE]` in the config.
  - `future`: t0 = 2027-03-01T09:00Z, with the passthrough.

  Session 1 writes a memory entry and runs a terminal probe. Session 2 runs the terminal probe and an `execute_code` probe. `check_hermes.py` then classifies every timestamp in `state.db` (a copy), every text file in the home, every kernel mtime and every captured request against the simulated and wall windows (±180 s). `guard_probe.py` calls four Hermes guards directly, on a clone of the run's home, at sim A, A + 3 d and A + 8 d. `inventory_guards.py` is a line-level static scan of the pinned source.
- **Claude Code runs** (`claude/run_all.sh`). Each run gets a fresh isolated `HOME` and `CLAUDE_CONFIG_DIR`, with `ANTHROPIC_BASE_URL` set to the stub, a placeholder API key, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, and the autoupdater, telemetry and error reporting off. Two `claude -p` sessions run 3 days apart, each with one Bash probe. A socket monitor (`lsof` on the process tree) counts non-loopback endpoints. The five runs:
  - `node-control`: the Node build, no shim;
  - `node-past` and `node-future`: the Node build with `NODE_OPTIONS`, at the same two t0 values as Hermes;
  - `native-node-options`: the native build with `NODE_OPTIONS`;
  - `native-bun-preload`: the native build with `BUN_OPTIONS=--preload`.
- **Shim self-tests.** `tests/test_clockshims.py`, run with `python3 -m pytest spikes/s2/tests`, has 11 cases. In the closeout re-run, all 11 pass on CPython 3.9.6, and all 11 pass again with `S2_CHILD_PYTHON` set to the Hermes interpreter (CPython 3.14.9), so the shim runs in 3.14 children. The saved output stays with the run evidence, outside the repo. The earlier hand smoke on 3.14 left no saved output.

Aggregate numbers are in [`results/summary.json`](results/summary.json). Ledgers, bodies and logs stay out of the repo.

## Results

**Machine state for every run.** The busy marker read exit 10 (light work only, `"glm": false`). The 1-minute load average was between 7.3 and 14.4. Every process ran under `nice -n 19 taskpolicy -b`. Timings are wall seconds per session and are advisory only.

### Prompt date (all sessions; n = 8 Hermes sessions, 10 Claude Code sessions)

| Run | Session 1 prompt date | Session 2 prompt date | Matches sim |
|---|---|---|---|
| Hermes `control` | Monday, October 26, 2026 | Monday, October 26, 2026 | wall, as expected |
| Hermes `past-default` | Monday, March 03, 2025 | Thursday, March 06, 2025 | 2/2 |
| Hermes `past` | Monday, March 03, 2025 | Thursday, March 06, 2025 | 2/2 |
| Hermes `future` | Monday, March 01, 2027 | Thursday, March 04, 2027 | 2/2 |
| CC `node-control` (2.1.112) | 2026-10-26 | 2026-10-26 | wall, as expected |
| CC `node-past` (2.1.112) | 2025-03-03 | 2025-03-06 | 2/2 |
| CC `node-future` (2.1.112) | 2027-03-01 | 2027-03-04 | 2/2 |
| CC `native-node-options` (2.1.306) | 2026-10-26 | 2026-10-26 | 0/2: the native build ignores `NODE_OPTIONS` |
| CC `native-bun-preload` (2.1.306) | 2025-03-03 | 2025-03-06 | 2/2 |

- Hermes puts the date in `Conversation started: …` in the system prompt. Session 2 also carried session 1's memory entry.
- Claude Code puts it in the `currentDate` context, as `Today's date is …`.
- In every shimmed run, the only wall dates in captured requests are in tool results: 1 to 3 per session, from the children listed below.

### Stored timestamps

**Hermes `state.db`** (n = 2 sessions per run, 4 runs). Every Hermes-written timestamp column falls in its session's simulated window, in all 3 shimmed runs:
- `sessions.started_at` and `sessions.ended_at`: 2 + 2;
- `messages.timestamp`: 6 + 6;
- `session_model_usage.first_seen` and `last_seen`: 2 + 2;
- `state_meta.value`: 1 + 1.

The only wall values in `state.db` are in `messages.content`: tool output that quotes the children's clocks. No `CURRENT_TIMESTAMP`, `'now'` or `unixepoch()` appears in any stored schema. No other database was created.

**Hermes files**: the files below carry simulated timestamps in every shimmed run. `.skills_prompt_snapshot.json` (`mtime_ns`) and `spawn-ledger.json` `create_time` carry wall values (see the table below).
- `logs/agent.log` and `logs/errors.log`: 134 and 5 timestamps;
- `source-checks/*.json` (the source-update check's `ts`);
- `cache/local_endpoint_probes.json` (a TTL cache);
- `installs/*/bootstrap/default.json`;
- `spawn-ledger.json` `registered_at`;
- session IDs (`20250303_…`, `20250306_…`).

Memory (`memories/MEMORY.md`) holds no timestamp in its content.

**Claude Code transcripts** (`projects/<cwd>/<session>.jsonl`, n = 2 per run). In the shimmed runs, every record `timestamp` is simulated. Top-level record `timestamp` fields number 7 + 7 per Node-build run and 21 + 21 in the native build. The checker's scan also counts nested dates, such as quoted child records, giving the 9 + 9 and 22 + 22 simulated values (session 1 window + session 2 window) in `results/summary.json`. The native build also records `attachment.date` and its own `api-request` records. `.claude.json` (`firstStartTime` and similar) is simulated as well. The wall values in transcripts are the quoted tool output only. In `native-node-options` the transcripts and `.claude.json` are on wall time (48 wall values).

### Timestamps the shims cannot reach

| Value | Where seen | Clock | Proposed handling |
|---|---|---|---|
| Kernel file times (mtime, ctime, birthtime) | Every file. Hermes: 27 files written in the run, all wall; 327 bundled skill files keep their source mtimes. Claude Code: all 4 files, wall | wall | Generator or director sets times with `os.utime` from simulated time where a reader compares them. Card discloses the rest. |
| Mtimes recorded as data | Hermes `.skills_prompt_snapshot.json` manifest (68 `mtime_ns` values), used as a cache key by equality | wall | Harmless, since it is equality, not age. Disclose. |
| Kernel process start time | Hermes `spawn-ledger.json` `create_time` (from the process table); its `registered_at` is simulated | wall | Harmless: compared with the same kernel clock. Disclose. |
| Non-Python and non-Node children | `date` in the terminal or Bash tool, every run (2/2 per run). The same applies to `git commit` author dates and any binary | wall | Director rewrites dates in requests (fallback). Set `GIT_AUTHOR_DATE` and `GIT_COMMITTER_DATE` and `TZ` in the child environment. A libfaketime-style preload is untested and blocked for signed binaries. |
| Hermes `execute_code` sandbox, default config | The sandbox's env scrub drops `BICENTENNIAL_CLOCK_FILE` (`PYTHONPATH` survives) | wall in `past-default` (1/1) | Add `terminal.env_passthrough: [BICENTENNIAL_CLOCK_FILE]` to the life's config. With it, the reading is simulated in `past` and `future` (2/2). |
| Python children | Hermes terminal tool, local backend: `PYTHONPATH` and the clock variable are inherited | simulated (2/2 per run) | None needed for the local backend. Docker, SSH and other backends were not tested. |
| Node children of Claude Code | `node -e` in the Bash tool | simulated under `NODE_OPTIONS` (2/2). Wall in `native-bun-preload` (2/2), where only `BUN_OPTIONS` was set | Set both `NODE_OPTIONS` and `BUN_OPTIONS`. |
| SQLite `'now'` | One site in the pinned Hermes source: `hermes_cli/session_recovery.py:956` (`CAST(strftime('%s','now') AS REAL)`), on the out-of-window repair path only; not reached in any run | wall if reached | The shim can override `strftime`, `datetime`, `julianday`, `date`, `time` and `unixepoch` per connection with `create_function`. Checked: this also covers `DEFAULT (strftime(…))`. The `CURRENT_TIMESTAMP`, `CURRENT_DATE` and `CURRENT_TIME` keywords can be overridden the same way, by zero-argument functions of those names (checked on SQLite 3.54.0). No measured schema uses any of them. |
| Engine-internal clock reads in Node | `Intl.DateTimeFormat#format()` with no date, and `performance.timeOrigin` | wall | Disclose. Not seen in a captured prompt. |
| Peer timestamps | The stub's own `created` fields (wall) | wall | Not stored by either harness in these runs. A real provider's dates are out of scope (stub only). |

### Wall-time guards

**Probed directly** (`guard_probe.py`, one probe per run on a cloned home; A = the run's t0):

| Guard (Hermes) | Compares | Control (wall) | Sim behind wall (`past`, −14,442 h) | Sim ahead of wall (`future`, +3,030 h) |
|---|---|---|---|---|
| `curator.should_run_now`, 7-day interval | sim now vs stored sim `last_run_at` | seeds, false | A false, A+3d false, A+8d true | A false, A+3d false, A+8d true |
| `curator._claim_run`, stale-lock takeover after 1 h | sim now vs a fresh lock's kernel mtime | not taken over | not taken over (a crashed lock would never be reclaimed) | **fresh lock taken over** (A and A+3d): two passes could run at once |
| `prune_scratch_dir`, 24 h idle | sim now vs kernel mtimes | fresh entry kept; backdated entry pruned | fresh entry kept; entry backdated with sim-based `utime` pruned | **fresh entry deleted** (A and A+3d) |
| model-metadata cache age | sim now vs kernel mtime | 0.0 s | negative, so `None` (freshness unknown) | 11,167,071 s (129 days): always stale |

- **A 3-day jump alone trips none of the four guards probed.** The 7-day curator interval sees the jump correctly. Only the curator interval was called before and after a jump in one process (A, A+3d, A+8d). Lock takeover and scratch pruning were called at A and A+3d with fresh fixtures each time. The metadata cache age was called once, after the last jump, so it has no before/after pair. Trips depend on the sign of (sim − wall), because these guards mix simulated time with kernel file times.
- **Static inventory.** The pinned Hermes source has 31 lines in 28 files that compare a kernel file time with a wall reader on the same line. Among them are the curator, model-metadata, models.dev, plugin-catalog, skills-hub, update-lock and runtime-state caches and locks. Comparisons split across lines, such as the scratch prune, are not counted, so this is a lower bound. All 1,142 monotonic-clock lines (timeouts, in-process idle timers) are unaffected by design: they never see a jump between processes.
- **Not exercised dynamically:** the rest of the static inventory above, every Claude Code guard, and (the gateway was not run) gateway session reset, the cron ticker, and the terminal and browser inactivity reapers. The gateway guards each read `time.time()` or `hermes_time.now()` against simulated stored values, so in a long-lived gateway a jump would act as real elapsed time.

**Claude Code (static, from the shipped Node bundle; not probed function by function):**
- Transcript retention (`cleanupPeriodDays`, default 30) computes its cutoff from `Date.now()`.
- The update lock and the deep-link registration cooldown compare `Date.now()` with file `mtimeMs`.
- In `node-future` (sim 126 days ahead) both transcripts survived the second session (2/2). The retention cleanup did not delete the 3-day-old session in `-p` mode.
- **One non-loopback endpoint observed.** In `node-future` session 2 only, the socket monitor observed one non-loopback endpoint on port 443, even with non-essential traffic disabled. Its address block was read as an Anthropic front end at run time; the endpoint string stays in the local run evidence and is not in the committed aggregate. Every other session showed 0 (9/10). The monitor samples `lsof` about every 0.3 s and blocks nothing, so a zero means no endpoint was observed, not that none opened. The stub recorded the 4/4 expected message requests, and the only key present was the placeholder. The trigger was not identified: a cache or cooldown judged stale under the simulated-ahead clock is the likely class.

### Recommendations for the director (advisory)

1. Keep simulated time behind wall time for the whole life: choose t0 so that t0 plus the life's span is earlier than the run's wall start minus 1 day. Mixed-clock guards then fail safe: they keep files and do not take over locks. They do not fail destructively.
2. Have the generator set file times from simulated time (`os.utime`) for any file the harness will age-check, and disclose kernel times on the card.
3. For Hermes, add `terminal.env_passthrough: [BICENTENNIAL_CLOCK_FILE]`. For Claude Code, set both `NODE_OPTIONS` and `BUN_OPTIONS`, and run the working directory outside any directory tree that holds a real `.claude/CLAUDE.md`.
4. Keep the request-date rewriting fallback for tool output from non-Python and non-Node children (`date`, `git`).
5. Run Claude Code inside a network sandbox. `HTTPS_PROXY` breaks the 2.1.112 build even for a loopback base URL (`UND_ERR_INVALID_ARG`).

## Deviations and incidents

- **The pinned 2.1.306 is not a Node build.** On npm, `@anthropic-ai/claude-code@2.1.306` ships `bin/claude.exe`, a native executable built on Bun 1.4.4, plus a Node wrapper that only spawns it. The last version whose `bin` is `cli.js` is **2.1.112**, so the Node-shim runs use 2.1.112 and the native 2.1.306 runs test `NODE_OPTIONS` (ignored) and `BUN_OPTIONS=--preload` (works).
- **The Hermes child environment was not an allow-list.** `run_hermes.py` passed the parent environment minus `HERMES_`, `OPENAI_`, `ANTHROPIC_` and `OPENROUTER_` variables, with the real `HOME`; only `HERMES_HOME` was fresh. The model was the stub, so the only tool calls were its scripted ones (a memory write, the `date` and Python probes, and one `execute_code`). The Claude Code runner already used an allow-list and an isolated `HOME`. A future Hermes runner should do the same; the measured runner is left as run.
- **Runner and shim corrections after the runs.** The closeout bounded the wait after a killed Claude Code session, recorded a Hermes session timeout in `run.json` instead of aborting, and stopped the stub on a startup failure. No session timed out (18/18 exited 0), so the measured runner path is unchanged. It also made the Python shim's clock reload all-or-nothing (a bad rewrite keeps the last reading) and limited the metaclass `isinstance` shortcut to the two shim classes. The measured runs used the earlier shim; neither change was re-measured in a harness run.
- **Hermes outbound traffic was blocked differently.** Hermes reached the outside only through a blackhole proxy. Claude Code could not use one, because `HTTPS_PROXY` makes it fail to reach even the loopback stub. It ran with the socket monitor instead.
- **A debug run read the real memory file.** An early debug run had its working directory under the user's home directory. Claude Code loads `<ancestor>/.claude/CLAUDE.md` for every ancestor of the working directory, whatever `HOME` and `CLAUDE_CONFIG_DIR` say, so the real user memory file was read and reached only the local stub's ledger. That ledger and the debug evidence were deleted. No credential was involved.
  - All reported runs use a working directory under the per-user temporary directory, whose ancestors hold no `.claude` directory.
  - The checker counts loaded context files: 0 outside isolation in all 10 sessions.

## What is deferred

- Gateway-mode guards (session reset, cron ticker, inactivity reapers), and a long-lived process that spans a jump in place. The shim supports one: it re-reads `clock.json`, and the probe exercises the re-read.
- The SQLite function override is not built into the shim, because Hermes has no reachable `'now'` and no measured schema uses the `CURRENT_*` keywords.
- Docker, SSH and other terminal backends. The Hermes desktop and TUI (Node) front ends.
- The cause of the one outbound Claude Code connection under a sim-ahead clock, and Claude Code guards probed function by function.
- Codex (needs a VM). Every memory plug-in's own clocks, which are checked when each plug-in is onboarded.

## Does not prove

- Anything about live model behaviour: every response came from the stub.
- That any memory plug-in honours the shim.
- Anything about Codex.
- That the guard list is complete: the static scan is a line-level heuristic and a lower bound, and only four Hermes guards were called.
- That a sim-behind-wall life is free of guard effects: it only avoids the destructive direction measured here. A crashed lock is never reclaimed, and "unknown freshness" caches refetch.
- Anything at life scale. The sample is 8 Hermes sessions and 10 Claude Code sessions, each two sessions long.
