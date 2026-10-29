# Run Ring 0 on your system (v0.1 kit)

## 1. What the v0.1 kit is

The kit ships T0 probe packs and T1 CI smoke only. T0 runs micro-lives through the memory-layer adapter; T1 drives two public lives through the harness with a scripted model, regression corpus and controls. See [RING0 §§6–7](../../specs/ring0/RING0.md#6-t1-composition-and-the-probe-budget).

The v0.1 feedback is stage attribution per failed item (`items[].stage_attribution`) and, at T1, comparison against your own previous accepted card through `--baseline`, without an MDE or A/A′ band. The broader [DESIGN §9.1 feedback list](../DESIGN.md#91-developer-rings-and-tiers-no-decision-bar) is a roadmap. This kit does not provide:

- T2, T3, the fault finder, Ring 1 or Ring 2;
- the per-item trace page or `bicentennial repro`;
- the failure taxonomy card or MDE diff;
- rung results or operating-metric deltas.

No result ever carries advice on any system's internals ([DESIGN §9.1](../DESIGN.md#91-developer-rings-and-tiers-no-decision-bar)).

## 2. Limits, stated plainly

Every card carries these labels verbatim from `card_ring0`:

- "Ring 0 developer signal; not predictive of the full tier; never certifies";
- "filters: not run (v0.2)";
- "rungs: uncalibrated (v0.2)";
- "voice: template";
- "Act: evidence-conditioned scripted action; not an Act judgement";
- at T1, "scripted model: wiring-only".

Nothing in a developer ring certifies ([PREREG §6](../../prereg/PREREG-v0.4.md#6-tiers-rings-subsets-and-branches)). The reader measures evidence availability at probe time, not a model's judgement. It selects among options whose locked tokens are present, preferring gold when competing evidence is also present. Act at T0/T1 is evidence-conditioned scripted action ([RING0 §§1–3](../../specs/ring0/RING0.md#1-the-scripted-reader)).

Forgetting is exercised at T0 only. KEEP-FORGET and KEEP-NEIGH read "not exercised at T1" and sit outside its gate. The ≤ 60 s per pack T0 target and ≤ 10 min T1 target are engineering targets, not bars; the T1 figure is not measured. Disclose target misses ([RING0 §6](../../specs/ring0/RING0.md#6-t1-composition-and-the-probe-budget), [PREREG §8 bar 5](../../prereg/PREREG-v0.4.md#8-pilot-acceptance-bars-all-required)). Determinism is claimed only per machine and pin set ([RING0 §4](../../specs/ring0/RING0.md#4-stable-and-volatile-result-fields)).

LCM-X's developers use this public kit on equal terms. The benchmark never runs LCM-X: the runners refuse it under the benchmark operator's identity ([RING0 §12](../../specs/ring0/RING0.md#12-lcm-x)).

## 3. What a source checkout needs

v0.1 runs only from a source checkout. Use a git clone: both runners read `git rev-parse HEAD` and refuse with `benchmark_commit` when that fails. `bicentennial` exits 3 with `source_checkout_required` if `schemas/` or `pyproject.toml` is missing, or if git reports a different repository top level after resolving paths. A worktree passes; a source copy nested inside an unrelated repository does not. If git itself fails, the runners retain their `benchmark_commit` check.

Use Python 3.14, a venv at `.venv`, and `PYTHONHASHSEED=0`. The CLI exits 3 `hashseed` without that seed; a library process started without it exits 70 ([RING0 §8](../../specs/ring0/RING0.md#8-exit-codes)). Install `nice` and, on macOS, `taskpolicy`: the CLI re-executes at niceness 19 and background QoS. `.venv/`, `build/` and `runs/` are git-ignored.

The optional `BICENTENNIAL_BUSY_CMD` shell command returns a JSON object with optional boolean `glm` and string `state`. Exit 0 admits work; 10 admits light work with fewer roots and refuses heavy work; 11 refuses work. Unset means idle. Unreadable output or an unexpected exit refuses work. These are machine-admission checks in `runner/guard.py`, separate from the result gate.

## 4. Build and install a pack

The build command below pins the registered Hermes-native artifact, so these packs can also serve registry systems. The output is a parent directory, which may already exist; the tier directory and its `.staging` and `.work` siblings must not exist, or the command exits 3 with `out_exists`. Success is silent; unexpected build failures exit 70 with `tool_failure` first on stderr (section 8).

```sh
bicentennial build --tier T0 --out build/ring0
```

Install with `python -m bicentennial.packs.install install SRC DEST`. DEST must not exist; its parent must exist. Installation prints the pack hash and makes files 0444 and directories 0555. Verify with `python -m bicentennial.packs.install verify ROOT --pack-hash H`. The install CLI exits 0, or 3 with `hashseed`, `pinned_artifact_changed`, `lock_mismatch` or `refused`; malformed usage also exits 3. An edit to a pinned artifact voids the run ([PREREG §6](../../prereg/PREREG-v0.4.md#6-tiers-rings-subsets-and-branches)).

`visible/` is the agent-visible pool, not a sandbox image. Never copy it wholesale into a harness sandbox. A harness gets only `answer_key.json` with the canary stripped and, per probe point, that checkpoint's repo state or env seed and the events up to the cut. The pool holds later checkpoints and future events too.

## 5. Run T0 in your own CI

These are the commands this repository's own `ring0-doc` workflow runs. Run them from the clone's root with fresh build and output paths. The final line reports each receipt's loop time and the maximum; it imposes no timing gate.

<!-- ci-block: ring0-t0-reference -->
```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .
export PYTHONHASHSEED=0
bicentennial build --tier T0 --out build/ring0
mkdir -p runs
PACK_HASH="$(python -m bicentennial.packs.install install build/ring0/T0 runs/ring0-t0-packs)"
python -m bicentennial.packs.install verify runs/ring0-t0-packs --pack-hash "$PACK_HASH"
bicentennial t0 --system reference_store --pack all --packs runs/ring0-t0-packs --pack-hash "$PACK_HASH" --out runs/ring0-t0-reference_store
python -c 'import json, pathlib; from bicentennial.report.receipt import loop_time; times = [(loop_time(json.loads(p.read_bytes()))[0], p.parent.as_posix()) for p in sorted(pathlib.Path("runs/ring0-t0-reference_store").rglob("receipt.json"))]; [print(ms, "ms", pack) for ms, pack in times]; print("maximum per-pack loop_time:", max(ms for ms, pack in times), "ms")'
```

| T0 flag | Meaning |
|---|---|
| `--system` | Required reference or registry name. |
| `--pack` | Required, repeatable pack id or relative path; `all` selects the index. |
| `--packs` | Required installed tier root. |
| `--pack-hash` | Required hash printed by install. |
| `--out` | Required output path; must not exist. |
| `--mode api\|hermes` | Default `api`; `hermes` exits 3 `mode_unavailable:hermes` in v0.1. |
| `--workers N` | Integer ≥ 1, default 1; results do not depend on it. |
| `--hermes` | Pinned Hermes checkout for registry systems. |
| `--plugin-source` | Pinned source for a plug-in system. |
| `--cache` | Optional control cache; default `<out>/cache`. |

The Hermes-replay fallback ships in v0.2 ([RING0 §13 E5](../../specs/ring0/RING0.md#13-v01-errata)). Reference names are `reference_store`, `bm25`, and seven mutants: `wipe_on_restart`, `truncate_after_compaction`, `orphan_tool_result`, `forget_ignored`, `stale_wins`, `forget_cached_output`, `reset_cached_output`. Each mutant is a reference store with one deliberate defect. A registry name selects a declared system. T0's budget is ≤ 60 s per pack, $0, no upstream credential ([RING0 §7](../../specs/ring0/RING0.md#7-t0-surfaces)).

For Hermes native, the memory-layer host calls `memory` and `session_search` and also reads the session-start memory snapshot rendered by pinned Hermes's own code at session open. Enabled, non-empty memory and user-profile blocks appear in that order, before recall and prefetch context. The snapshot stays frozen through mid-session writes and adds no recall citations. T1's regression corpus uses the same host. The `t0.injection` JUnit property says: "The session-start memory snapshot is read; other harness prompt injection is not exercised." ([RING0 §13 E7](../../specs/ring0/RING0.md#13-v01-errata)).

The adapter conformance checks are `reset_empty`, `duplicate_id_idempotent`, `citations_are_event_ids`, `checkpoint_restore`, `maintain_lossless`, `tool_grouping`, `forget_removes`, `supersession_current`, `settle_returns`, `text_full_length`, and `actor_stored`. Each uses a fresh adapter and settles before every probe or checkpoint. `text_full_length` queries a distinct tail token and requires the entire long event text byte for byte, citing only that event. `actor_stored` requires a sentinel actor in the checkpoint. The long fixture is at least 8,192 characters and a pack-building test keeps it longer than every public T0 and T1 event.

An adapter whose system API cannot carry the actor declares `UNSUPPORTED_FIELDS = frozenset({"actor"})`; no other field can be declared yet. `conformance.run()` returns `True` for the skipped `actor_stored`, while `conformance.declared()` reports `{"actor_stored":"declared"}` separately. Disclose that declaration; it is not a storage pass. The Hermes memory host declares actor unsupported because it delivers no actor, although its checkpoint includes the benchmark's full event copies. Exact `NoMemory` and `OracleEvidence` classes are exempt from the three retrieval checks and both new checks. ReferenceStore and BM25 pass all checks. Naive RAG deliberately fails exactly `supersession_current` and `text_full_length` because it returns chunks. The conformance-only mutants `clip_text_silently` and `drop_actor` fail exactly their respective new checks ([RING0 §13 E12](../../specs/ring0/RING0.md#13-v01-errata)).

Read per-pack loop times again, for reporting only:

```sh
python -c 'import json, pathlib; from bicentennial.report.receipt import loop_time; [print(loop_time(json.loads(p.read_bytes()))[0], "ms", p.parent.as_posix()) for p in sorted(pathlib.Path("runs/ring0-t0-reference_store").rglob("receipt.json"))]'
```

This deliberately defective reference is expected to exit 1:

```sh
bicentennial t0 --system stale_wins --pack all --packs runs/ring0-t0-packs --pack-hash "$PACK_HASH" --out runs/ring0-t0-stale_wins
```

To repeat the main block, first remove its generated trees. These commands delete the named outputs; preserve any results you need first.

```sh
chmod -R u+w runs/ring0-t0-packs
rm -rf build/ring0 runs/ring0-t0-packs runs/ring0-t0-reference_store
```

## 6. Add a registry entry

Use `systems/registry/<name>.toml` and `schemas/system.schema.json`. The schema allows no extra fields. Supply `name`, `licence`, `harness`; `artifact` with `name`, `version`, `sha256`; `write_tools` with `tool` and `actions`; `read_tools`; nullable `recall` with `tool` and `argument_template`; `surfaces` with `root`, sandbox-relative `relative`, and `volatile_paths`; `fresh_install_hash`; `own_model_routes` with `role` and `alias`; `structured_formats` by role with `kind` and nullable `schema`; nullable `embedding_dim`; `settle` with `kind` and `bound_s`; `machine_class`; and `benchmark_operator_runs`.

Admission reasons are:

| Reason | Trigger |
|---|---|
| `licence_not_osi` | Licence outside the provisional OSI allow-list. |
| `artifact_unpinned` | Version is not a release tag or digest is not 64 lowercase hex characters. |
| `route_unroutable` | Own-model alias does not match `bicentennial-…`. |
| `compaction_alias_mismatch` | Compaction route names an alias other than `bicentennial-summariser`, the one the director serves for compaction. |
| `state_path_undeclared` | Unsafe surface path, or write tools/model routes without surfaces. |
| `recall_placeholder` | Recall template has a placeholder other than `{prompt}`. |
| `schema_invalid` | Schema validation fails without a more specific policy reason. |
| `benchmark_operator_forbidden` | Benchmark operator requests an entry forbidding its runs. |
| `unmeasured:artifact.sha256` | Artifact hash is the all-zero placeholder. |
| `unmeasured:fresh_install_hash` | Fresh-install hash is the all-zero placeholder. |

Unmeasured pins are declarations, never runnable. Admission refuses them. The pinned-artifact check compares the installed artifact with `artifact.sha256`; verified empty compares each surface with the unmasked tree hash taken earlier in the same run, never with a registry value ([RING0 §5 and E4](../../specs/ring0/RING0.md#5-verified-empty-and-the-wiped-store-control)).

The artifact digest is sha256 of `git archive --format=tar HEAD` from the clean pinned checkout. For plug-ins use `systems/hermes_plugin.py`'s `TREES` recipe: Holographic uses `HEAD`; Mem0 OSS adds `integrations/hermes-plugin-mem0` after `HEAD`.

The fresh-install hash is a canonical tree listing of relative path, mode, size and content hash, excluding only declared volatile paths. E1 places the v0.1 snapshot before configuration for native memory and after install-time files for plug-ins. E4 masks the director port in root `config.yaml` and `mem0.json` for the reported pin. v0.1 has no public measurement command; measure and review the pin in the registry change ([RING0 §13](../../specs/ring0/RING0.md#13-v01-errata)).

Runners require `harness = "hermes"` (`harness_not_hermes`). A new system needs a reviewed benchmark mapping before it runs: `WRITE_ARGS`, `FORGET`, and plug-in `PROVIDERS`/`TREES`. Optional `ENGINES` selects the `context.engine` id. Optional `PLUGIN_DIRS` overrides the installed directory. Optional `ENABLED` lists systems whose directory goes in `plugins.enabled`. Optional `WORKER_ENV` supplies reviewed worker environment values. Its names may not shadow a variable the harness sets or start with `BICENTENNIAL_`, `HERMES_`, `PYTHON`, `LD_` or `DYLD_`. A value is either `{model_cache}`, optionally followed by `/` and one relative path of `A-Za-z0-9._-` segments, or a plain value of `A-Za-z0-9._,=+-` only, which can never name a path. A cache directory whose resolved path has any character outside `A-Za-z0-9._/-` (a separator or whitespace) refuses `model_cache_invalid`. Systems needing a staged model cache require `--model-cache DIR`; its file-tree digest is disclosed and checked again after the run. This is the same reviewed change for every system. Missing mappings can become infrastructure failures rather than clean refusals; do not assume an exit code.

`DEPENDENCIES` maps a plug-in system to an existing repository-relative POSIX path under `systems/locks/` (no `..` or backslashes); locks allow comments and continuations, require exact `name==version` pins with SHA-256 hashes and optional environment markers, and reject extras, URLs, editables, includes, duplicate normalised names with identical marker text, and empty locks.

## 7. Run T1 as a merge gate

Set `HERMES_CHECKOUT` to a clean git checkout of the release pinned in `systems/registry/hermes-native.toml`, whose `.venv` must include Hermes's `mcp` extra, prepared from the checkout's own lockfile with `uv sync --frozen --extra mcp`. T1's G2 environment tools reach Hermes over MCP. The pin hashes the source checkout only, so the extra does not change it. Set `PLUGIN_CHECKOUT` to the plug-in's pinned source when needed. These are source checkouts you prepare separately. The shipped `hermes-native`, `holographic` and `mem0-oss` entries carry measured pins; an entry that still holds a zero pin is refused with `unmeasured:` before any run (section 6).

A system with a dependency lock gets its own clone of the pinned Hermes checkout at the same commit, prepared with that checkout's own `uv sync --frozen --extra mcp`; install its dependencies with `uv pip install --python <copy>/.venv/bin/python --require-hashes -r systems/locks/<system>.txt`, then pass that copy as `--hermes` for that system only. The shared checkout stays as Hermes's lockfile plus the `mcp` extra make it. Prepare verifies applicable locked versions in the worker and records the lock digest and applicable count as `<tier>.plugin_deps`; every real-worker run records the canonical distribution list as `<tier>.worker_dists` and its digest and count as `<tier>.worker_dists_sha256` in JUnit.

The normaliser reads the pinned Hermes untrusted-content fence around environment-tool results.

The T1 adapter writes three scripted-tier settings:
- `tools.tool_search.enabled: "off"`. By default the pin hides `session_search` and every plug-in and MCP tool behind its `tool_call` bridge, which would leave the scripted write and recall turns without their tools. With the bridge off, every offered tool is eager.
- `agent.api_max_retries: 1` and `agent.auto_recovery_cycles: 0`. The simulated clock is frozen inside a turn, and the pin's retry and auto-recovery waits loop on `time.time()`, so a failed main call would otherwise stall until the turn timeout.

The harness record lists all three under `config_deviations`, and cards disclose them as `t1.tool_search`. Install-time configuration is unchanged, so fresh-install hashes are too. Live tiers keep the pin's defaults.

The pin's empty-reply retries wait on the same clock, and no setting turns them off. So a scripted main reply is never empty: an action probe ends its turn with `Noted.` after the plan's last step, and at once for a refrain plan ([RING0 §2](../../specs/ring0/RING0.md#2-the-scripted-model-t1)).

A plug-in that prefetches memory changes the user text the director sees. The pin appends the prefetched block to the turn's user text, after a blank line, inside a `<memory-context>` fence that opens with its system note. If the exact text matches no turn, the director matches the text before that block. A script whose user text holds the wrapper is refused. A scripted write stores only the text before it. The block stays in the request the reader reads ([RING0 §2](../../specs/ring0/RING0.md#2-the-scripted-model-t1)).

Build and install the T1 tier, then run native memory twice:

```sh
bicentennial build --tier T1 --out build/ring0
PACK_HASH_T1="$(python -m bicentennial.packs.install install build/ring0/T1 runs/ring0-t1-packs)"
bicentennial t1 --system hermes-native --packs runs/ring0-t1-packs --pack-hash "$PACK_HASH_T1" --hermes "$HERMES_CHECKOUT" --out runs/ring0-t1-first
bicentennial t1 --system hermes-native --packs runs/ring0-t1-packs --pack-hash "$PACK_HASH_T1" --hermes "$HERMES_CHECKOUT" --baseline runs/ring0-t1-first/system/card.json --out runs/ring0-t1-next
```

Use a fresh output and that plug-in's own accepted card for its next run. Holographic has a dependency lock, so `HOLOGRAPHIC_HERMES` is its own copy of the pinned checkout, prepared as above with `systems/locks/holographic.txt`:

```sh
bicentennial t1 --system holographic --packs runs/ring0-t1-packs --pack-hash "$PACK_HASH_T1" --hermes "$HOLOGRAPHIC_HERMES" --plugin-source "$PLUGIN_CHECKOUT" --out runs/ring0-t1-holographic-first
bicentennial t1 --system holographic --packs runs/ring0-t1-packs --pack-hash "$PACK_HASH_T1" --hermes "$HOLOGRAPHIC_HERMES" --plugin-source "$PLUGIN_CHECKOUT" --baseline runs/ring0-t1-holographic-first/system/card.json --out runs/ring0-t1-holographic-next
```

T1 requires `--system`, `--packs`, `--pack-hash`, `--out`; optional flags are `--baseline`, `--hermes`, `--plugin-source`, `--cache`. Plug-ins require `--plugin-source`; cache defaults to `<out>/cache`.

The gated arms are system and wiped-store positive control. The wiped gate must FAIL: if it passes, the system card is INVALID, exit 1. Wiped `uninformative` is not a pass. The cached no-memory floor appears as `controls.no_memory_floor` and the `no_memory` JUnit suite ([RING0 §§5–6](../../specs/ring0/RING0.md#5-verified-empty-and-the-wiped-store-control)).

A first run satisfying the other conditions is labelled `CONFORMANCE_PASS`. `--baseline` takes your previous accepted `system/card.json`: canonical, schema-valid, T1, `gate_verdict` PASS or CONFORMANCE_PASS, with the same system, `pins.pack_hash` and `pins.seed_hash`. A mismatch exits 3 `baseline_mismatch`; malformed bytes use `baseline_invalid`. A restart-crossing bundle below baseline is a regression. The gate also requires the gated invariants and corpus cases to pass ([RING0 §6](../../specs/ring0/RING0.md#6-t1-composition-and-the-probe-budget)). Exit 0 passes; any other code blocks the merge.

## 8. Exit codes

Use the process exit as the gate ([RING0 §8, E3](../../specs/ring0/RING0.md#8-exit-codes)):

| Exit | Meaning |
|---|---|
| 0 | PASS or labelled CONFORMANCE_PASS. |
| 1 | FAIL or INVALID; an invariant or corpus failure. |
| 2 | BLOCKED after infrastructure reruns, with no known failure. |
| 3 | Guard or precondition refused; no result. |
| 70 | Tool failure: a runner's unexpected exception (stderr starts with `tool_failure`), or a library process started without `PYTHONHASHSEED=0`; no result file exists. |

INVALID exits 1, BLOCKED exits 2, and a known failure wins over a blocked entry. T0 evaluates each pack: honeypot read → INVALID; any FAIL invariant or SYSTEM_FAILURE item → FAIL; otherwise a BLOCKED run → BLOCKED; otherwise PASS. Across packs, exit 1 wins, then 2, then 0. Item scores below 1000 fail JUnit cases but do not gate T0 in v0.1. Those item failures are diagnostics.

Exit-3 codes and causes, including registry reasons above:

| Code | Cause |
|---|---|
| `source_checkout_required` | Missing source files or a different git top level. |
| `hashseed` | Seed is not 0. |
| `usage` | Invalid or missing CLI argument; stderr includes usage. |
| `mode_unavailable:hermes` | T0 fallback unavailable. |
| `benchmark_commit` | Cannot read the benchmark commit. |
| `unknown_system` | Unknown or inconsistent system name. |
| `unknown_pack` | Selection absent from the pack index. |
| `tier` | Installed tier differs from requested runner. |
| `tier_composition` | T1 does not contain exactly G1 and G2. |
| `schedule_mismatch` | Packed schedule differs from reconstructed schedule. |
| `harness_not_hermes` | Registry harness is not Hermes. |
| `missing_input` | Required Hermes, plug-in source or model cache omitted, or an unused model cache supplied. |
| `no_t0_surface:context_engine` | Engine-only system has no T0 memory-provider surface. |
| `model_cache_invalid` | Model cache is not a real directory of regular files and directories. |
| `model_cache_changed` | Model-cache digest changed during the run. |
| `settle_unmapped` | Hook settle has no `SETTLE_THREADS` mapping. |
| `surface_not_empty` | A sandbox-home memory surface already holds files before install. |
| `harness_extra_missing:mcp` | The pinned Hermes checkout's `.venv` cannot import `mcp`, or the 60 s import check could not start or timed out; install the extra, or rerun on a less loaded machine. |
| `plugin_deps_lock_invalid` | Dependency map or lock is invalid (including a marker the worker's `packaging` cannot parse or evaluate), or applicable pins conflict. |
| `plugin_deps_missing:<dist>` | Worker lacks an applicable locked version; stderr lists every mismatch. |
| `plugin_deps_check_failed` | Worker inspection cannot start, times out, lacks marker support, or returns invalid output. |
| `harness_artifact_mismatch` | Pack harness artifact differs from registry pin. |
| `c7_missing` | Template has no C-7 entry. |
| `c7_changed` | Template C-7 hash changed. |
| `baseline_missing` | T0 fault-free baseline pack/item missing. |
| `catalogue_changed` | T0 catalogue hash changed. |
| `visible_canary` | Canary found in agent-visible input. |
| `no T0 mapping` | A T0 host detects no write/forget mapping; coverage is not universal. |
| `scratch_exists` | T1 arm scratch path already exists. |
| `check_compile` | Script compilation check failed. The runner writes a per-branch summary to stderr. |
| `pinned_artifact_changed` | Pinned pack, code or artifact changed. |
| `lock_mismatch` | Current run lock differs from expected lock. |
| `gate_refused` | Host machine gate refused a spawn. |
| `pin_mismatch` | Checkout does not match its pin. |
| `SpendRefused` | Receipt has positive spend. |
| `upstream_record` | Isolation audit found a forbidden upstream record or egress. |
| `out_exists` | Output exists, including a symlink. |
| `baseline_unreadable` | T1 baseline cannot be read. |
| `baseline_invalid` | T1 baseline is malformed or noncanonical. |
| `baseline_mismatch` | T1 baseline identity, acceptance or bundle set differs. |
| `refused` | Install CLI filesystem or value error. |

Busy-marker messages are `machine guard refused: marker exit N` for a refusing/unreadable marker and `machine busy: heavy work refused` for heavy work at exit 10. The code is on stderr. If this invocation created `--out` before refusal, `refusal.json` holds `{code, fields}`; for `upstream_record`, a non-empty `detail` list names each non-loopback endpoint, with the pid and command that showed it and its sample count, and each record that broke isolation; it is not a result. An already-existing output path is refused without overwriting it. An unexpected exception inside a runner exits 70, prints `tool_failure` first on stderr, and leaves no result file: results are staged and moved into place only when every file is written ([RING0 §8, E6](../../specs/ring0/RING0.md#8-exit-codes)). Any other code also means the tool failed and no result exists. Before a runner starts, for example when the CLI's niceness re-exec finds no `nice` or `taskpolicy`, Python can still exit 1 on an uncaught exception with no result; confirm result files exist before reading exit 1 as a gate.

## 9. Failure classes and stages

Card `failure_class` values are FAIL_TASK, SYSTEM_FAILURE, BLOCKED, N/A_EXPOSURE and N/A_CLOCK. Attribution follows cause, not reporter. A benchmark-owned INFRA_FAILURE gets at most 2 reruns, then BLOCKED, never charged to the system; `infra_reruns` counts reruns ([PREREG §7](../../prereg/PREREG-v0.4.md#7-statistics)).

The `engine_inactive` HarnessFailed stop label means the configured context engine is not active, so Hermes fell back.

Invariant statuses are PASS, FAIL, INCONCLUSIVE, NOT_EXERCISED, INFRA_FAILURE. Corpus statuses are PASS, FAIL (`mismatch`, `system_failure`, `stale_case`) and INFRA_FAILURE. Unsettled checkpoints still execute probes on clones, but every item becomes SYSTEM_FAILURE `unsettled`, regardless of reader result ([RING0 E2](../../specs/ring0/RING0.md#13-v01-errata)).

`stage_attribution`, the reader's `failing_stage`, is stored, retained, retrieved, used or unknown. The reader uses whatever is present, so "used" never fails at Ring 0 ([RING0 §1](../../specs/ring0/RING0.md#1-the-scripted-reader)). Remember, Survive and Act are reported separately; never sum them.

## 10. Reading the outputs

T0 writes `<out>/<pack relpath>/{card.json, receipt.json, junit.xml, invariants.json, controls.json}` plus `<out>/adapter_invariants.json`, `relations.json`, `relations.xml` and optional `cache/`. Relations never change the exit code. T1 writes `<out>/{system,wiped}/{card.json, receipt.json, junit.xml, invariants.json, corpus.json, controls.json}`.

Everything in `card.json` is stable. `receipt.json` holds volatile wall times, latency, load, busy readings, tokens, spend, store growth, process ids, ports and temporary paths. `junit.xml` holds no volatile value. `loop_time = wall_end_ms − wall_start_ms`. Positive spend refuses with `SpendRefused`. T1's system receipt pools the `system` and `no_memory` runs plus the system arm's corpus hosts; the wiped receipt pools the `wiped` runs plus the wiped arm's corpus hosts, including retries and clones. Per-role tokens come from ledger response usage or SSE frames, growth is declared-surface bytes at close minus bytes after install and verified-empty before the first session, and process ids are the recorded worker pids ([RING0 §4](../../specs/ring0/RING0.md#4-stable-and-volatile-result-fields)).

Disclosures ride as JUnit properties until a card field exists. T0 names are `t0.entrypoint`, `t0.event_mapping`, `t0.crash`, `honeypot.hits`, `invariants.forget_inconclusive`, `t0.pair`, and conditionally `t0.injection`, `t0.baseline`, `t0.engine`, `t0.model_cache`, and, on a real-worker run, `t0.worker_dists`, `t0.worker_dists_sha256` and, for a system with a lock, `t0.plugin_deps`. A registry entry with an `own_model_routes` role of `embeddings` adds `t0.embeddings`; an `extraction` key in `structured_formats` adds `t0.extraction` ([RING0 §13 E10–E11](../../specs/ring0/RING0.md#13-v01-errata)). API-mode INV-PAIR covers call and result survival; linkage requires Hermes mode.

Memory-host delivery disclosures are `t0.write_clipped`, `t0.write_max_length`, `t0.fields`, and, for T1's corpus hosts, `t1.write_clipped`, `t1.write_max_length`, `t1.fields`. T0 sums the count over every host built by the invocation, including adapter invariants, baselines, retries and probe clones, and reports the same total on each selected pack. T1 sums every corpus host per gated arm, including retries and clones. The count records successful ingests whose written text differs from the event text; duplicate delivery, reset, restore and forgetting do not erase or inflate it. `write_max_length` appears only when the write tool declares `maxLength`. `fields` is canonical JSON: `{"actor":"not_delivered","text":"full","time":"session_clock"}`, with `text` changed to `clipped:<limit>` when a limit is declared, even when no event exceeds it. Hermes native, Holographic and Mem0 OSS declare no such limit: the count is 0 and the limit property is absent. Reference systems and the no-memory floor receive none of these properties. No card or schema field changes ([RING0 §13 E12](../../specs/ring0/RING0.md#13-v01-errata)).

T1 names in `compare.DISCLOSURES` are `t1.assistant_turns`, `t1.baselines`, `t1.corpus`, `t1.corpus_crash`, `t1.estimator`, `t1.fresh_install`, `t1.isolation`, `t1.key_matching`, `t1.terminal`, `t1.tool_search`, `t1.tuesday`, `t1.unsettled`, `t1.verdicts`, `t1.verified_empty`, `t1.window`. `PLUGIN_DISCLOSURES` adds `t1.a4`, `t1.plugin_snapshot`, `t1.reclassify`, `t1.fresh_install_mask`. Engine/cache disclosures add `t1.engine`, `t1.engine_window`, `t1.corpus_engine`, and `t1.model_cache` when applicable. A real-worker run adds `t1.worker_dists` and `t1.worker_dists_sha256`, and a system with a lock adds `t1.plugin_deps`. Both gated arms add `t1.embeddings` when the registry entry has an `own_model_routes` role of `embeddings`, and `t1.extraction` when `structured_formats` has an `extraction` key; the no-memory suite gets neither ([RING0 §13 E10–E11](../../specs/ring0/RING0.md#13-v01-errata)). Also inspect `isolation.unknown_requests`, `isolation.forwarded`, `no_memory.gold_in_context`, `controls.floor_mismatches`, `controls.wiped_store`, `gate`, `gate.final`, `gate.wiped_blocked` (system arm only: the wiped gate's blocked entries as canonical sorted JSON, `[]` when none), `wiped.label`, `t1.not_exercised`, `t1.transforms`, `t1.reclassified`, `honeypot.hits`, and conditional `t1.a4_gaps`. The corpus is memory-layer mode; probe isolation is per checkpoint, not per item; naive RAG is not run in v0.1. Read these disclosures before interpreting a card.

Compare stable cards after a second run:

```sh
bicentennial t0 --system reference_store --pack all --packs runs/ring0-t0-packs --pack-hash "$PACK_HASH" --out runs/ring0-t0-reference_store-2
python -m bicentennial.report.determinism runs/ring0-t0-reference_store/<pack relpath>/card.json runs/ring0-t0-reference_store-2/<pack relpath>/card.json
```

Replace both `<pack relpath>` placeholders with the same index path before running. The determinism tool names the first stable difference. Its own exits are 0 identical, 1 different, 2 unreadable/invalid input; they are not the Ring 0 exit table ([RING0 §4](../../specs/ring0/RING0.md#4-stable-and-volatile-result-fields)).
