# S4 report: Claude Code headless through the director, forwarding to GLM

**Claim** (`advisory`, a feasibility spike): Claude Code 2.1.306 runs headless (`claude -p`, stream-json) against the S4 director, which forwards to GLM (`glm-5.3`) on z.ai's Anthropic-compatible endpoint. Claude Code held only the placeholder key, and the director held the only real one. All 9 scripted steps were valid: 5 of 5 tool turns (Bash, Read, Edit and the fixture MCP tool), `--resume`, `--resume --fork-session`, one served `/compact` and one recall turn after it. No non-loopback endpoint was observed on Claude Code's process tree, the upstream rejected no request field, and the run used 18 upstream calls. GLM is **proposed for C-2**, with one condition this report adds: the swap share of a board does not fit 24 hours on the GLM lane at its measured concurrency of 8 (below).

## Method
- **Director** (`anthropic_director.py`, stdlib only, bound to 127.0.0.1). It store-and-forwards `POST /v1/messages` (streaming or not) and `POST /v1/messages/count_tokens`. Any other method or path gets a logged 404 and is never forwarded.
  - **Credentials.** Every inbound `Authorization`, `x-api-key`, `cookie` and `anthropic-*` header is dropped. Its value is only compared with the placeholder. A credential other than the placeholder gets a 401 and writes the stop file, so nothing more is forwarded. The upstream key comes from the director's environment and is sent as `Authorization: Bearer`, with a fixed `anthropic-version`. A guard aborts the process if the key ever reaches a write.
  - **Ledger.** One JSONL record per request: method, path, query key names, model in and out, stream flag, sorted body key set, status, timing, usage, served model, stop reason, `tool_use` names, the dropped header names and the stripped field names. It holds no body text and no header value.
  - **Stripping.** If the upstream answers 400 naming a top-level body field (except `model`, `messages`, `max_tokens`, `stream`, `system` and `tools`), the director strips that field, retries, and keeps it on a strip list in a file, so every later request is sent clean.
  - **Failures.** `--inject-429 N` answers the N-th `/v1/messages` request with a synthetic 429 and `retry-after`, without calling the upstream. Upstream 429, 503 and 529 are retried after 5, 15 and 45 s. Upstream error text is never forwarded: the harness gets the director's own error body.
  - **Limits.** A call cap (`--max-calls`, default 120) counts every upstream attempt in a file shared across director restarts. There is a stop file, and GLM use pauses while the busy marker's `glm` field is true.
- **MCP fixture** (`mcp_fixture.py`). A stdio JSON-RPC server with one deterministic tool, `fixture_lookup(key)`, over a four-row synthetic table. It is configured with `--mcp-config` and `--strict-mcp-config`.
- **Driver** (`run_s4.py`). S2's isolation recipe:
  - a fresh `HOME` and `CLAUDE_CONFIG_DIR`;
  - a project folder under the system temp directory, outside the home tree;
  - an environment built from a short allow-list, with the base URL on the director, the API key set to a fixed placeholder string, and the model alias `bicentennial-cc-main`;
  - non-essential traffic, the autoupdater, telemetry and error reporting off.

  The director, not Claude Code, starts under the internal helper that supplies the upstream environment. It runs one step at a time, so each request's step is known. Every step is gated on the busy marker, runs one Claude Code process under `nice -n 19`, and is watched by S1's socket monitor (S2's `lsof` sampler on the process tree, about every 0.3 s).
- **Steps.** All content is synthetic:
  - five main turns: `t1` Bash (writes `notes.txt`), `t2` Read, `t3` Edit, `t4` the MCP tool and `t5` Bash, with `t2`-`t5` on `--continue`;
  - `resume` (`--resume <id>`), `fork` (`--resume <id> --fork-session`), `compact` (`/compact` on the resumed session) and `post_compact`, a recall question after the compaction.

  The injected 429 is on `t3`'s first request. A step is valid when the stream's result is `success` and not an error, its expected tool returned at least one non-error result, and its deterministic check passes. The checks are the file content on disk, the answer containing the fixture value or beta's value, or a `compact_boundary` event.
- **Plumbing dry run.** Before the live run, the same driver ran against S2's local recording stub standing in as the upstream (0 upstream calls). Only the live run is reported below.

## Results
Run of record: 2026-10-26, Claude Code `2.1.306`, upstream model `glm-5.3` (served model `glm-5.3` on every reply). The busy marker read exit 10 with `glm` false at every step. The ledger records the request count of every step. `results/summary.json` holds the full minimized record.

| Step | Mode | Tools called (result error?) | Requests (status) | Check | Valid | Wall s |
|---|---|---|---|---|---|---|
| t1 | new | ToolSearch (no), Bash (no) | 3 (200) | file content | yes | 16.6 |
| t2 | `--continue` | ToolSearch (no), Read (no) | 3 (200) | answer has beta = 11 | yes | 7.9 |
| t3 | `--continue` | ToolSearch (no), Edit (no) | 4 (429 injected, then 3 × 200) | file has beta=12 | yes | 17.8 |
| t4 | `--continue` | ToolSearch (no), `mcp__fixture__fixture_lookup` (no) | 3 (200) | answer has the fixture value | yes | 11.3 |
| t5 | `--continue` | Bash (no) | 2 (200) | answer has beta = 12 | yes | 9.5 |
| resume | `--resume` | none | 1 (200) | answer has the fixture value; same session id | yes | 7.2 |
| fork | `--resume --fork-session` | none | 1 (200) | answer has beta = 12; **new session id** | yes | 5.4 |
| compact | `--resume`, `/compact` | none | 1 (200), the compaction | `compact_boundary`, manual | yes | 41.1 |
| post_compact | `--resume` | none | 1 (200) | answer has the fixture value | yes | 7.0 |

- **Tool turns: 5 of 5 valid.** Every tool call returned a non-error result. In `t1`-`t4`, Claude Code 2.1.306 first called `ToolSearch`: it sends 12 tool schemas and defers the rest, including the MCP tool, which appears in the request from `t4` on (13 tools). That is one more request per turn the first time a deferred tool is needed. The MCP server reported `connected` at every step.
- **Resume and fork.** `--resume` continued the same session and recalled a value from `t4`. `--fork-session` produced a new session id that carried the history: it answered from the session's content, and the original session continued afterwards.
- **Compaction served.** `/compact` sent one upstream request, 40.7 s, with usage input 1,347, cache read 6,144 and output 2,863 tokens. Claude Code's `compact_boundary` reports a manual trigger, 6,268 tokens before and 4,116 after. The next turn's request carried 4 messages instead of 30 and recalled the `t4` value correctly.
- **Assumed context window: 200,000 tokens.** Claude Code's own reporting (`modelUsage.contextWindow` in every result) gives 200,000 for the alias, and its stderr flags the alias as an unrecognized model. That is Claude Code's default for a model it does not know, not a property of GLM. S1 saw this build auto-compact at 171,146 reported tokens. An automatic compaction was not exercised here.
- **The 429.** Claude Code emitted one `api_retry` system event (attempt 1, `max_retries` 10, `retry_delay_ms` 3000, `error_status` 429, `error` `rate_limit`). It re-sent the request 3.01 s later, which honours the director's `retry-after: 3`, and the turn then completed normally. The user-visible output was unchanged: the result is `success`, the answer is correct, and the retry shows only as that stream event.
- **Stripped fields: none.** The upstream returned no 400. Every body key Claude Code sent was accepted as is: `context_management`, `max_tokens`, `messages`, `metadata`, `model`, `output_config`, `stream`, `system`, `thinking` and `tools`. Acceptance is not proof that the upstream honours a field. The request query (`beta`) and the `anthropic-beta` header were not forwarded.
- **Credentials.** All 19 inbound requests carried the placeholder (`x-api-key`) and nothing else: 0 foreign and 0 absent. The dropped header names were `anthropic-beta`, `anthropic-dangerous-direct-browser-access`, `anthropic-version` and `x-api-key`. No `Authorization` header and no OAuth or subscription token was ever seen.
- **Egress.** 0 non-loopback endpoints were observed in any step. The director's own upstream connection is outside Claude Code's process tree, and it is the one route out.
- **Requests and calls.** 19 requests, all `POST /v1/messages` (0 `count_tokens`, 0 other paths, 0 404). 18 upstream calls in total, within the cap of 120, with no retry and no upstream refusal. Every request was classified: 17 main-turn requests, 1 injected 429 and 1 compaction. The upstream reported cache reads on every request after the first.

### Model B (completion slot C-2)
**Candidates.** Each candidate is a family other than the pinned family (OpenAI). Anthropic is excluded because it is a pinned judge family (DV42). Each paid candidate documents an Anthropic Messages-compatible endpoint, so this director could serve it with a base URL change. Prices are public list prices read on 2026-10-26.

| Candidate | Family | USD per 1M tokens: cache hit, cache miss, output | Swap share per board, S6a prompt sizes | Swap share per board, full-window prompts | Study comparator (δ_W = 1), S6a / full-window |
|---|---|---|---|---|---|
| `glm-5.3`, z.ai coding plan | Zhipu (the replication family) | subscription, $0 marginal | $0 | $0 | $0 (δ_W = 0: shared with the replication branches) |
| `deepseek-v4-pro`, peak ([price page](https://api-docs.deepseek.com/quick_start/pricing)) | DeepSeek | 0.044, 1.32, 3.96 | $253 | $969 | $53 / $162 |
| `deepseek-v4-pro`, off-peak | DeepSeek | 0.022, 0.66, 1.98 | $126 | $484 | $26 / $81 |
| `MiniMax-M3`, standard, ≤ 512K input ([price page](https://platform.minimax.io/docs/guides/pricing-paygo)) | MiniMax | 0.06, 0.30, 1.20 | $83 | $342 | $17 / $57 |

**Assumptions** (`summarise.py`, `results/model_b.json`):
- **The board formula.** Cost_board = n_L[R(1+f) + 2P] + n_keep[R_cap(1+f) + 2P], with n_L = 48, n_keep = 12, f = 0.5 and R_cap = R.
- **A life.** 200 sessions × 5 turns, one write turn each, at S6a's measured mean of 4,009 prompt and 80 completion tokens. Add 80 compactions at S6a's 9,283 prompt and 7,939 completion tokens.
- **Probes.** b = 150 probe turns × 2.25 calls (S6a), each sized like a write turn, doubled for the resume-only controls.
- **The swap share.** The swap model serves 0.5 of the board's tokens: a mid-life swap moves the alias, summariser and probe model, leaving sessions 101-200 and checkpoints 120 and 200 on the swap model.
- **Caching.** 80% of input tokens are cache hits (S6b measured 83% on write turns).
- **The full-window reading** raises each write-turn and probe prompt to 32K tokens (W/4 at 128K) as a sensitivity. Compaction prompts are held at S6a's size.
- **The study comparator** is costed only when the swap model is not from the replication family: 8 study lives × [R(1+f) + 2P_W], with P_W = 0.1P.
- **Not counted:** title calls, whose tokens S6a did not record. Probe completions are proxied by write-turn completions.

At S6a's prompt sizes, every paid candidate fits the $300 board paid ceiling. At full-window prompts, off-peak DeepSeek ($484) and MiniMax ($342) stay under $500, and none stays under $300. The paid costs scale linearly with the swap share and with prompt size.

**The GLM lane.** GLM costs $0, but the swap share loads the GLM lane. S6a's board needs 676 lane-hours at ×1 latency, and the swap share is 338 lane-hours. At GLM's measured concurrency of 8 that takes about 42 h, which misses the 24-hour rule. The share fits if either of these holds:
- the GLM lane sustains a concurrency of at least 15 (about 14.1 needed), for example two plan accounts at 8;
- the swap's share of the life is at most 0.28, a swap at about session 144 or later;

Running the share in a window of its own does not help: 338 lane-hours at a concurrency of 8 still take about 42 h, and PREREG-v0.3 §11 times the full core board per system. A change to the 24-hour rule itself is a design decision outside this spike.

S6b's projection, behind DV42, puts the whole board on the pinned lane and does not model the swap, so moving the share to GLM lightens the Sol lane by the same amount. The GLM share also pauses whenever the busy marker's `glm` field is true.

**Proposal.** GLM (`glm-5.3` through z.ai's Anthropic-compatible endpoint) is **proposed for C-2**. This run shows it servable to Claude Code through the director with no field stripped. It is the replication family, so δ_W = 0 and the comparator shares lives (PREREG §10, §11), and its marginal cost is $0. The condition is that the 24-hour projection includes the swap share's lane time on GLM and meets one of the two fits above. If none can be met, off-peak `deepseek-v4-pro` or `MiniMax-M3` would serve the share within the paid ceiling at S6a's prompt sizes, but not at full-window sizes.

## Open items
- **The real window.** Claude Code assumes 200K for the alias. If GLM-5.3's served window is smaller than Claude Code's auto-compaction point (about 171K in S1), long sprints would hit upstream refusals before Claude Code compacts. Check the served window before the sub-row runs, and set the alias or the compaction window to match.
- **Unverified fields.** `output_config.effort`, `thinking` and `context_management` were accepted but not shown to be honoured. A behaviour check (as S6a did for `reasoning_effort`) belongs to the sub-row's pilot.
- **`metadata.user_id`.** It is forwarded upstream. In this run it was an id from the fresh, synthetic config. The director could drop it by policy.
- **Lint only.** After the run, the director changed only for lint (regex flag spelling, an explicit `check=False`, a `noqa`, and an equivalent body-type check). The offline tests cover the committed version.

## Does not prove
- That every Claude Code feature works through the director, only those exercised: Bash, Read, Edit, one MCP tool, `ToolSearch`, `--continue`, `--resume`, `--fork-session` and a manual `/compact`. Automatic compaction, subagents, the small-fast alias, title calls, interactive mode and `count_tokens` were not exercised.
- Anything about other Claude Code versions or other upstreams, or about GLM's behaviour at full-scale prompt sizes.
- Any memory system's quality inside Claude Code, or any score: no answer was scored beyond deterministic checks.
- The model-B costs beyond their stated assumptions. They are desk projections from S6a's micro-life token counts and dated list prices, not measured spend.
- That no egress occurred: the socket monitor samples and blocks nothing, so zero means none was observed.
