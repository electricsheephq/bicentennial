# S1 report: request roles

**Claim** (`advisory`, a feasibility spike): one harness-neutral classifier, `roles.py`, classifies every request recorded in the S6a and S6b ledgers and in fresh stub captures of Hermes, Claude Code and Codex. Across 1,392 requests it has zero compaction false negatives, zero compaction false positives and zero `unknown`. It disagrees with a director's own label once, and there the director was wrong (below). Every deliberately unseen shape classifies as `unknown`, which the caller must refuse. Codex, run against a custom Responses provider, compacts **remotely**: each compaction is a request that reaches the stub.

## Method
- **The rule** (DESIGN §6.2, job 6), applied in order:
  1. **Cursor,** in the main frame only (no marker of an auxiliary role is present). Either a trailing tool result answers a call id the director issued or forwarded, or the last user message carries the scripted turn at the cursor with tools offered. A re-sent current turn (a retry) and a harness continuation marker on the current turn also count.
  2. **Model alias:** a declared per-task base-URL prefix or model name. A marker may narrow the role within the alias's allowed set; a marker outside it is a conflict.
  3. **Shape:** exactly one marker role, or an endpoint that needs no body (count_tokens, a remote compaction endpoint, model-catalog and local-server probes).
  4. **Unknown:** anything else, and any conflict between steps.
- **Roles:** `replay_main`, `write_turn`, `probe_main`, `compaction`, `summariser`, `extraction`, `title`, `aux` and `unknown`. `compaction` is the harness's own context compaction. The S6a and S6b directors call Hermes' compression call `summariser/compression`; S1 maps that label to `compaction` and keeps `summariser` and `extraction` for a memory system's declared summary and extraction models.
- **Two pure steps.** `shape(request)` reduces a request to wire, path, sorted key set, model, the item-role sequence, trailing tool ids, 16-hex hashes of the last user message's text blocks, text lengths and the names of the markers present. `classify_shape(shape, ctx)` applies the rule. `classify(request, ctx)` composes the two. The context holds the cursor's expected turns (as hashes), the call ids issued, and the declared aliases. No header value is read.
- **Markers hold no text.** Each is a (field, prefix length, SHA-256 prefix) triple, derived once from a captured sample. The repository therefore keeps no harness text.

| Marker | Harness | Field, prefix | Role |
|---|---|---|---|
| `hermes_title` | Hermes | system, 23 chars | title |
| `hermes_compression` | Hermes | first user message, 59 chars | compaction |
| `hermes_background_review` | Hermes | last user message, 33 chars | aux |
| `director_write_suffix` | director | last user message, 18 chars | write_turn (a director-originated body) |
| `claude_compact` | Claude Code | last user message, 400 chars | compaction |
| `claude_explore_subagent` | Claude Code | system block, 48 chars | aux |
| `claude_task_notification` | Claude Code | last user message, 55 chars | continuation of the current turn |
| `codex_compact` | Codex | last user message, 50 chars | compaction |

- **Labels.** Each director ledger already records its own role and subrole, and those labels are the expected roles. The fresh Claude Code and Codex captures have no director, so their 6 non-main requests were labelled by hand from the capture (the evidence script lists them by sequence number). Each labelling was then checked against the harness's own compaction markers.
- **Recorded evidence, offline.**
  - S6a `r6-write` (Hermes on the chat-completions wire) and S6b `r7c-write` (Hermes on the Responses wire): every request.
  - S6b `a2`-`a5` live smokes. The `a2`-`a4` ledgers hold only their 6 metadata probes each, because the S6b director's credential guard stopped those runs before any turn was recorded.
  - The S6b soak's 700 director-originated bodies.
  - The director-originated write-turn bodies inside each run's upstream records.
- **Fresh captures, all against 127.0.0.1 stubs.** No live model call and no login of any kind was used, and every process ran under `nice -n 19` with one harness process at a time, gated on the busy marker (exit 0 or 10 throughout).
  - **Hermes:** the S6a replay with its director in stub mode, sessions 1-10 with write turns and both probe sessions, in a new `HERMES_HOME`, `threshold_tokens` 6000 and `protect_last_n` 4.
  - **Claude Code** (`capture.py claude`): S2's isolation recipe (new `HOME` and `CLAUDE_CONFIG_DIR`, placeholder key, non-essential traffic, autoupdate and telemetry off). It ran 30 `claude -p` turns with stream-json output, then one `/compact`. The stub (`capture_stub.py`) reports 5,500 input tokens per user message. Turns 3 and 17 carry a shell directive, and turn 9 carries one that spawns an Explore subagent.
  - **Codex** (`capture.py codex`): `codex exec --json`, then `exec resume --last`, in a new empty `CODEX_HOME` with no `auth.json`. A custom Responses provider points at the stub, with the key a placeholder in an env var and `requires_openai_auth = false`. `model_auto_compact_token_limit` is 6000, and the stub reports 1,000 input tokens per user message. The run stops 2 turns after the first compaction.
- **Pinned versions:**
  - Hermes v0.22.2 (commit d923a5eb), on Python 3.14.9;
  - Claude Code 2.1.306;
  - Codex CLI 0.164.0.

## Results

| Harness (wire) | Sources | Requests | Agree with label | Compaction (labelled → classified) | FN | FP | Unknown |
|---|---|---|---|---|---|---|---|
| Hermes on GLM lane (chat completions) | r6, fresh stub capture, their write-turn bodies | 389 | 388 | 5 → 5 | 0 | 0 | 0 |
| Hermes on Sol lane (Responses) | r7c, a2-a5, soak, write-turn bodies | 954 | 954 | 16 → 16 | 0 | 0 | 0 |
| Claude Code (Anthropic messages) | fresh capture | 37 | 37 | 2 → 2 | 0 | 0 | 0 |
| Codex (Responses) | fresh capture | 12 | 12 | 3 → 3 | 0 | 0 | 0 |

- **Confusion by role** (labelled → classified):
  - **Hermes on the GLM lane:** replay_main 120 → 120, write_turn 169 → 169, probe_main 13 → 12 + 1 title, title 24 → 24, compaction 5 → 5, and aux 58 → 58 (metadata probes).
  - **Hermes on the Sol lane:** replay_main 61, write_turn 748, probe_main 11, title 16, compaction 16 and aux 102, each classified as labelled.
  - **Claude Code:** replay_main 34 (one of them a background-task continuation), compaction 2, and aux 1 (the subagent).
  - **Codex:** replay_main 9 and compaction 3.
- **Methods used:**
  - Hermes on the GLM lane: cursor 181, model alias 29, shape 179.
  - Hermes on the Sol lane: cursor 73, shape 881.
  - Claude Code: cursor 34, shape 3.
  - Codex: cursor 9, shape 3.
- **Compaction confirmed from the harnesses' own markers.**
  - **Hermes:** one `Compression summary call dispatched` log line per compaction request: r6 2, r7c 2 and the fresh capture 3. The fresh capture logged 4 compression attempts, but one made no progress and sent no request.
  - **Claude Code:** 2 `compact_boundary` events, one `auto` at turn 28 (171,146 reported pre-tokens) and one `manual` (`/compact`). Each matches one compaction request.
  - **Codex:** 3 `compacted` rollout items, each with a replacement history, matching its 3 compaction requests.
- **The one disagreement** is r6 request 128, which the S6a director labelled `probe_main/retry` and forwarded to the probe model. S1 classifies it as `title`, by shape. Hermes' log shows its title call to the title base URL timed out after 30 s, and Hermes fell back to the main client. The fallback request carries the probe's opening message, which matched the S6a director's retry rule, so the director mis-served a title call as a probe turn. S1's cursor applies only in the main frame: it requires tools and no auxiliary marker, and a title request has neither. The fixture expects `title` and records the director's label beside it.
- **Codex compacts remotely.** Each of the 3 compactions is an ordinary `/responses` request to the provider (the stub): no tools, with the compaction prompt as the last user message. It never calls the `/responses/compact` endpoint. The next request opens with Codex's bridge summary, and the rollout gains a `compacted` item. That is the behaviour with a custom provider on 0.164.0; Codex's built-in provider (which needs a login) was not tested. The `/responses/compact` endpoint shape is classified as compaction, but only synthetic requests have exercised it.
- **Claude Code's small-fast alias.** In `-p` mode with non-essential traffic off, 2.1.306 made no small-fast or title call. The Explore subagent ran on the main alias and is classified by its system-prompt marker. So the alias rule (`ANTHROPIC_DEFAULT_HAIKU_MODEL` declared as aux, with title allowed) is exercised only by synthetic shapes. The subagent ran in the background, and Claude Code resumed the turn with a notification as a new user message; S1 classifies that as a continuation of the current scripted turn.
- **Other shapes seen.** Claude Code 2.1.306 sends `system`-role messages inside `messages` (environment and deferred-tool notes); S1 treats them as system context, not turns. Its auto-compaction request carries the scripted turn's text in the same user message as the compaction instruction; the compaction marker takes it out of the main frame, so it is not a cursor match.
- **Egress.** No capture of record reached a non-loopback endpoint. A first Codex capture with the default feature set connected to a public code-hosting address on 3 of 8 runs. It made no model call and used no login. The capture of record turns off Codex's plugin, app and tool-suggestion features, and no such connection recurred. To identify that address, the lane also ran `strings` once on the installed Codex binary. No file-open audit was captured, so the claim that no configuration, auth or session file was read rests on the lane's statement, not on a measurement.

## Shape test
`test_s1.py` is offline, deterministic and stdlib-only beyond pytest, and runs in under 0.1 s: 77 tests, all passing.
- The fixtures, `fixtures/shapes.json`, are minimized shapes: no harness or life text, only paths, key sets, model aliases, role sequences, marker names, lengths and hashes. A test asserts that no fixture string can hold text.
- Every recorded request must classify to its expected role. Where a source records the harness's own compaction count, the classified compactions must equal it.
- Unseen shapes must be `unknown`: an unscripted main turn, the scripted turn with no tools, an unissued call id, an unknown wire, an unknown GET, and fresh Responses and Anthropic shapes.
- Conflicting evidence (two marker roles, or a marker outside an alias's allowed set) must fail closed.
- **Fail-closed rules added after the first review.** Each has regressions on all three wires, and each fails on the reviewed head.
  - A trailing tool result must answer a call id the director issued or forwarded. There is one exception. Hermes can add a call of its own beside a forwarded call, in the same assistant message (r6 request 136 and r7c request 165). A result answering that call is accepted only when the same message holds an issued call and its result is also present. Otherwise any unmatched result is `unknown`.
  - A supplied wire must agree with the request's method and path.
  - An alias match on a body with no messages or input is `unknown`.
- **Added after the bot review of the PR.**
  - On the Responses wire, system and developer messages inside `input` are read as system text, like `instructions`. Codex sends its instructions that way, so its recorded system length is now 19,325 characters; no recorded role changes.
  - A malformed body is `unknown`. Before any feature is extracted, every container the rule reads must have its documented type: `model` a string; `tools`, `messages` and a list `input` lists of objects; content a string or a list of objects; `instructions` a string; every call id a string. Otherwise the extractors would drop the bad element and classify the rest.
- Each wire's cursor, retry, issued-id, alias and endpoint rules are tested on synthetic bodies.
- The repository has no CI workflow. The test is ready for one: `python -m pytest spikes/s1 -q`.

## Proposal: integration after S6c
This proposal is not implemented here, because S6c owns both directors.
- Replace each director's `classify` with `roles.classify` on the request. Keep the director's own bookkeeping through `roles.advance`: the cursor, forwarded call ids, and its write ids issued as `write_turn`.
- Route by S1 role. `compaction` goes to the summariser route. `summariser` and `extraction` are for a memory system's declared aliases.
- Keep the existing 400 for `unknown`.
- This fixes the r6 title-fallback mis-serve, and gives the S6a and S6b directors one rule in place of two orders (cursor first in S6a, shape first in S6b).
- Rerun the shape test whenever a harness version changes; a new version's markers are derived the same way.

## Does not prove
- Stability across harness versions. Each marker and capture is pinned to the versions above, and a new version reruns the shape test.
- Behaviour on live lanes beyond the recorded S6a and S6b requests. The fresh captures used stubs, so their reply content and timing are not a model's.
- Claude Code's small-fast and title calls, and Codex's `/responses/compact` endpoint: none were observed, so only synthetic shapes cover them.
- Codex's built-in provider, which needs a login. Interactive Claude Code, which may make background calls that `-p` mode does not.
- Anything about a memory system's quality.
