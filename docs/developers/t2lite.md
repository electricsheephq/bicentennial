# T2-lite: the v0.2 developer loop

## What T2-lite is and is not

`bicentennial t2lite` runs T1's two public lives and their B0/B1 twins, sending only the probes to a live model. It produces a developer card and, against your earlier run, a flip list. It is not predictive of the full tier and never certifies. It has no gate verdict or decision bar.

## What you need

Use a source git checkout, Python 3.14, a virtual environment with the package installed, and `PYTHONHASHSEED=0`. Install `nice` and, on macOS, `taskpolicy`; the CLI re-executes at niceness 19 and background QoS. Build and install a T1 pack with the [Ring 0 guide](ring0.md#7-run-t1-as-a-merge-gate), keeping the printed pack hash. Use the registered system's pinned Hermes checkout and dependencies, including its `mcp` extra. Plug-ins also need `--plugin-source`; only `omega` needs `--model-cache`. The system's registration and artifact measurements must pass T1 preparation.

Set these privately; this page supplies no values:

| Setting | Purpose |
|---|---|
| `BICENTENNIAL_SOL_TOKEN_URL` | Token refresh service used by login custody. |
| `BICENTENNIAL_SOL_CLIENT_ID` | Client identifier used for that refresh. |
| `BICENTENNIAL_SOL_BASE_URL` | Live model service base used by the Responses bridge. |
| Login home's `auth.json` | Login tokens; custody can refresh this file. Point `--login-home` at its directory. |

Use a separate developer login home. The operator identity cannot run `lcm-x`; another run holding the account lock refuses. Keep login material private and outside outputs, packs, cache and sandbox slots.

## Run it

Run from the clone root. In these examples, set `PACK_HASH` to the installed T1 pack's hash, and replace the relative checkout and login directories with your own. Each output directory must be new. Run A first, then repeat the same system and pins as A′ with `--aa-of A --baseline A`. A′'s flips are noise, and its q₀ is the noise rate. Both references must name the same directory, which is checked before the first send: a symlink to A, or another spelling of A on a case-insensitive disk, counts; a copy at another path does not supply this band. Then run a change B with `--baseline A --aa-prime A′` to compare it with A using that measured noise.

```sh
export PYTHONHASHSEED=0
bicentennial t2lite --system hermes-native --packs runs/ring0-t1-packs --pack-hash "$PACK_HASH" --hermes checkouts/hermes --login-home developer-login --max-sends 10000 --cache runs/t2lite-cache --out runs/A
bicentennial t2lite --system hermes-native --packs runs/ring0-t1-packs --pack-hash "$PACK_HASH" --hermes checkouts/hermes --login-home developer-login --max-sends 10000 --cache runs/t2lite-cache --aa-of runs/A --baseline runs/A --out runs/A-prime
bicentennial t2lite --system hermes-native --packs runs/ring0-t1-packs --pack-hash "$PACK_HASH" --hermes checkouts/hermes --login-home developer-login --max-sends 10000 --cache runs/t2lite-cache --baseline runs/A --aa-prime runs/A-prime --out runs/B
```

The send limit is an example, not a promised budget. Earlier cards must match system, pack, seed, model, effort, answer contract, profile and all code/harness pins. A candidate can change its implementation while keeping those comparability fields fixed. Checkpoint reruns use `--only LIFE:B0:CHECKPOINT` (or B1) and optionally `--repeat N`, a positive integer. They replay the whole branch and keep all items at that checkpoint. Repeats above one require a checkpoint; checkpoint runs cannot take references. `--aa-prime` requires `--baseline`; `--aa-of` cannot accompany `--aa-prime`. `--sandbox-slot` chooses an available slot from 0 through 9.

To see a complete run offline, use this acceptance with a fake upstream and fake worker. It exercises real preparation, director, shadow, scoring, cards and checkpoint replay, without a live login. The final check makes a socket-related skip fail this path. The fresh-clone CI job runs these exact lines after T0:

<!-- ci-block: t2lite-offline -->
```sh
set -e
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .[dev]
export PYTHONHASHSEED=0
python -m pytest -q tests/runner/test_t2lite.py::test_full_fake_worker_and_rerun_store_hashes --junitxml=build/t2lite-offline.xml
python -c 'import xml.etree.ElementTree as E; root = E.parse("build/t2lite-offline.xml").getroot(); assert len(root.findall(".//testcase")) == 1 and not root.findall(".//skipped"), "offline acceptance must pass without skips"'
```

## What a run costs

Only `probe_main` goes live; replay, write, extraction, compaction and every other role stay scripted as at T1. The model is pinned to `gpt-6.1-sol`, effort `medium`. No-memory probes also go live. With `--cache`, the floor runs once per cache key: pack hash, model, effort, answer-contract hash, harness hash and benchmark commit. A missing, damaged or incomplete entry runs the floor again; without a cache it always runs. An uncacheable floor is not saved. A cached floor contributes no sends or tokens to this run's receipt. Do not reuse the cache while editing benchmark code: uncommitted edits do not change HEAD's cache key.

`--max-sends` is a required nonnegative limit on upstream sends, including retries and the uncached floor; zero permits no sends. This is the practical bound, not a dollar estimate. The current stack uses zero-price spend accounting and the receipt reports zero spend; that does not promise free service. The token reservation bound is not sent as a model output cap. Read tokens and runtime in the receipt and live state in disclosures. Infrastructure items retry twice before becoming BLOCKED.

## How a run ends

| End | What remains |
|---|---|
| Complete | Card, records, custody and a COMPLETE receipt; BLOCKED items can remain. |
| Credential or spend stop | No card; `refusal.json` with `credential_stop` or `spend_stop`, an INFRA_FAILURE receipt and custody, only if secret-free. |
| INVALID | Isolation breach, canary in a live body or credential scan: only `refusal.json`. Canary outranks a stop. |
| Refused before anything runs | Argument, live-setting and login-home checks create nothing. Later preparation/reference refusals send nothing but can leave `refusal.json`. |
| Tool failure | Cleanup removes outputs and writes `refusal.json` with `tool_failure`; stderr has a traceback. If cleanup itself fails, an exception can escape with partial files and no card. |

A card is published only after scanning all outputs for login secrets. A refusal can therefore replace an otherwise complete run. Inspect stderr when no output directory was created.

## The outputs

Paths below are relative to the output directory; `<life>` and `<branch>` stand for each life and B0/B1. A new run without a baseline omits the flip file; a cached floor omits its per-branch probe files. Probe repeats use numbered repetition directories, beginning at 0.

### Complete

| File | Meaning |
|---|---|
| `card.json` | Verdict-free T2-lite card: pins, labels, item rows, counters, and `not_scored_live`, the ids of G2 action rows that carry no score. |
| `outcomes.json` | Joined per-item outcomes from the last repetition. |
| `repetitions.json` | Joined outcomes for every repetition. |
| `no_memory.json` | Floor outcomes and per-unit stops, possibly reused. |
| `custody.json` | Drained login custody events, without login secrets. |
| `disclosures.json` | Live stack state, including `live.holds` (`waits`, `held_ms`, sorted `reasons`), and transforms disclosed per arm. Holds count waits across every arm that sent live; each wait's time counts once even with multiple reasons. With no holds these are 0, 0 and []. |
| `spend.json` | Locked reservation and settlement accounting. |
| `receipt.json` | COMPLETE status, actual work, tokens, latency and runtime. |
| `flips.json` | Comparison against the baseline, if supplied. |
| `no_memory/<life>/<branch>/t2lite_probes.json` | Uncached floor probe, envelope and shadow diagnostics. |
| `repetitions/0/<life>/<branch>/t2lite_probes.json` | System probe diagnostics for repetition 0 (and similarly each later number). |

### Credential stop

| File | Meaning |
|---|---|
| `refusal.json` | Stop code; spend stops retain the same file set. |
| `receipt.json` | INFRA_FAILURE receipt for work actually performed. |
| `custody.json` | Secret-free custody records explaining the stop. |

## Reading the flip list

`rows` lists items whose `(score_milli, failure_class)` changed between baseline and current, sorted by life, branch, checkpoint and item id. Each row has `item_id`, `baseline`, `current`, `unstable`, `twin_flip` and `rerun`; each excluded entry has `item_id`, `reason`, `baseline`, `current` and `twin_flip`. Each side carries `item_id`, `score_milli`, `failure_class`, `base_verdict`, `life`, `branch`, `probe_point`, `probe_session`, `cell_id`, `track`, `stage`, `template_ref`, `genre`, `twin_bundle`, `in_context`, `stage_attribution`, `envelope`, `value_match`, `citation_match`, `crosses_cold_restart` and `swap_position`. Envelopes here are `parsed` or `missing`; the full envelope is in outcomes. Shadow selection and context diagnostics are distinct from the live answer; match flags do not replace its score.

`score_milli` expresses score in thousandths; `failure_class` and `base_verdict` explain failures and non-results. Life, branch, checkpoint and session locate the probe; cell, track, stage, template and genre classify it. `twin_bundle` identifies its paired bundle. `in_context` and `stage_attribution` describe the shadow reader's evidence, not a causal explanation of the live model. Value and citation matches are answer diagnostics of the scored envelope; they are null when the outcome has no scored envelope, as when an item has a failure class instead of a scored answer, and the probe file keeps the live answer's own parse and matches. Cold-restart and swap fields describe the probe's position in the life.

`excluded` carries both sides and a `reason`: INFRA, INFRA_FAILURE, BLOCKED or `not_scored_live` for G2 actions. These do not appear as flips. `counts` reports items, flips, exclusions, scored comparisons, `aa_prime_scored` and `unstable`. `q0` is the fraction of scored A/A′ items that changed score or failure class, independent of the candidate: exact numerator/denominator plus a milli rendering. It is null for an empty scored intersection or absent A′. Without A′, labels include "no A/A′ band". A row's `unstable` is true when its A/A′ outcomes differ, false when they agree, and null without A′ or when either side is excluded. It is a diagnostic, not a significance test or bar. `twin_flip` is true when the bundle partner's own score or failure class changed between baseline and current and false when it did not; it is null without a bundle, for a bundle that is not a pair, or when the partner is excluded. It is a diagnostic that never changes which answers are flips or any count. `served_identity` discloses baseline/current identities and whether they changed; identity drift does not silently suppress flips.

`rerun` is a shell command for three checkpoint repetitions. Fill every literal placeholder: `<packs>` is the installed pack directory, `<hermes checkout>` the pinned checkout, `<plugin checkout>` the plug-in source when present, `<model cache>` the staged model cache when present, `<login home>` the private login directory, `<max sends>` your send bound and `<new dir>` a fresh output directory. Quote paths as needed. It carries the system, pack hash, `--only` checkpoint and `--repeat 3`; it needs the same private live settings. The developer's flip list and rerun commands are their own regression set.

## Refusal codes

The table includes the shared T1 preparation vocabulary (including inherited T0/install/compare codes), not a promise that every inherited code is reachable in this profile. System reasons may be sorted and comma-joined. `<dist>` names a dependency; `<side>` names a compared card/outcome side; `<field>` is a comparability field listed above, including dotted pin names.

| Code | Cause |
|---|---|
| `<field>` | Baseline comparability field differs. |
| `SpendRefused` | Receipt has positive spend. |
| `aa_of:<field>` | A-of comparability field differs. |
| `aa_of_items` | A-of item ids differ. |
| `aa_prime:<field>` | A′ comparability field differs. |
| `aa_prime:flag` | Earlier A′ card is not marked aa_prime. |
| `aa_prime:no_card` | A′ outcomes have no card. |
| `aa_prime:no_outcomes` | A′ card has no outcomes. |
| `aa_prime_items` | A′ item ids or locations differ. |
| `account_busy` | Another run holds the login account lock. |
| `artifact_unpinned` | Registered artifact lacks a pin. |
| `baseline_invalid` | Earlier reference structure is malformed. |
| `baseline_items` | Baseline item ids or locations differ. |
| `baseline_mismatch` | T1 baseline identity, acceptance or bundle set differs. |
| `baseline_missing` | T0 fault-free baseline pack/item missing. |
| `baseline_unreadable` | An earlier card or required outcomes cannot be read. |
| `benchmark_commit` | Cannot read the benchmark commit. |
| `benchmark_operator_forbidden` | Benchmark operator identity is forbidden. |
| `c7_changed` | Template C-7 hash changed. |
| `c7_missing` | Template has no C-7 entry. |
| `canary` | Canary body reached the live guard: INVALID. |
| `catalogue_changed` | T0 catalogue hash changed. |
| `check_compile` | Script compilation check failed. The runner writes a per-branch summary to stderr. |
| `compaction_alias_mismatch` | Registered compaction alias differs. |
| `credential_scan` | Output contains login material: INVALID. |
| `credential_stop` | Login custody or upstream credentials stopped the run. |
| `egress_unobserved` | Worker egress sampling could not establish isolation. |
| `gate_refused` | Host machine gate refused a spawn. |
| `harness_artifact_mismatch` | Pack harness artifact differs from registry pin. |
| `harness_extra_missing:mcp` | Pinned Hermes environment cannot import mcp. |
| `harness_not_hermes` | Registry harness is not Hermes. |
| `hashseed` | Seed is not 0. |
| `invalid_card:<side>` | Compared card fails T2-lite validation. |
| `invalid_card:aa_of` | A-of card fails validation. |
| `invalid_card:aa_prime` | A′ card fails validation. |
| `isolation` | Worker egress or a non-probe live role: INVALID. |
| `items:<side>` | Card does not vouch for its outcomes. |
| `licence_not_osi` | Registration lacks an accepted licence. |
| `live_config` | A required live setting is missing. |
| `lock_mismatch` | Current run lock differs from expected lock. |
| `login_home` | No auth.json in the supplied login home. |
| `missing_input` | Required checkout/cache missing, or unused model cache supplied. |
| `mode_unavailable:hermes` | T0 fallback unavailable. |
| `model_cache_changed` | Model-cache digest changed during the run. |
| `model_cache_invalid` | Model cache is not a real directory of regular files and directories. |
| `no T0 mapping` | A T0 host detects no write/forget mapping; coverage is not universal. |
| `no_t0_surface:context_engine` | Engine-only system has no T0 memory-provider surface. |
| `only` | No matching checkpoint items. |
| `operator_identity` | Operator-marked login cannot run lcm-x. |
| `out_exists` | Output already exists, including a symlink. |
| `output_overlap` | Output overlaps login, packs or cache. |
| `pin_mismatch` | Checkout does not match its pin. |
| `pinned_artifact_changed` | Pinned pack, code or artifact changed. |
| `plugin_deps_check_failed` | Worker inspection cannot start, times out, lacks marker support, or returns invalid output. |
| `plugin_deps_lock_invalid` | Dependency map or lock is invalid (including a marker the worker's `packaging` cannot parse or evaluate), or applicable pins conflict. |
| `plugin_deps_missing:<dist>` | Worker lacks a locked dependency. |
| `recall_placeholder` | Recall mapping is still a placeholder. |
| `refused` | Install CLI filesystem or value error. |
| `rerun_arguments` | Incompatible references, checkpoint or repetition arguments. |
| `route_unroutable` | Registered model route cannot be resolved. |
| `sandbox_busy` | The selected slot is locked; exit 3. |
| `sandbox_overlap` | An input, login, reference, output or cache overlaps a destructive sandbox slot. |
| `sandbox_root_untrusted` | The parent traverses a symlink, or the base is symlinked, foreign-owned or not mode 0700; exit 3. |
| `sandbox_slot` | Slot is an integer outside 0 to 9; exit 3. A value that is not an integer is a usage error (`usage`, exit 3). |
| `schedule_mismatch` | Packed schedule differs from reconstructed schedule. |
| `schema_invalid` | Registration fails its schema. |
| `scratch_exists` | T1 arm scratch path already exists. |
| `settle_unmapped` | Hook settle has no `SETTLE_THREADS` mapping. |
| `source_checkout_required` | Missing source files or a different git top level. |
| `spend_stop` | Live spend/send guard stopped the run. |
| `state_path_undeclared` | A state path is undeclared. |
| `surface_not_empty` | A sandbox-home memory surface already holds files before install. |
| `telemetry_lock_unreadable` | Telemetry lock cannot be read. |
| `tier` | Installed tier differs from requested runner. |
| `tier_composition` | T1 does not contain exactly G1 and G2. |
| `tool_failure` | Unexpected exception, including failure while refusing. |
| `unknown_pack` | Selection absent from the pack index. |
| `unknown_system` | Unknown or inconsistent system name. |
| `unmeasured:artifact.sha256` | Artifact digest has not been measured. |
| `unmeasured:fresh_install_hash` | Fresh installation has not been measured. |
| `upstream_record` | Isolation audit found a forbidden upstream record or egress. |
| `usage` | Invalid or missing CLI argument; stderr includes usage. |
| `visible_canary` | Canary found in agent-visible input. |
| `visible_pack_overlaps_surface` | The agent-visible pack directory overlaps the workspace or a memory surface. |
| `visible_path_escape` | An agent-visible file would be written outside the pack directory. |

## Exit codes

0 means complete, including cards with BLOCKED rows. 3 means refusal or stop; malformed CLI usage also exits 3. 70 means unexpected tool failure, normally with a traceback and refusal. A cleanup double fault can escape as exit 1 with partial files and no card. Pre-output refusals leave no refusal file.

## Limits

T2-lite is not predictive of the full tier. Only `probe_main` is live; everything else is scripted as at T1. Entity matching is strict, not semantic. G2 actions are not scored live ([#358](https://github.com/electricsheephq/bicentennial/issues/358)): their card and outcome rows carry no score, and the card lists their ids in `not_scored_live`. A G2 action that fails for a system or infrastructure reason keeps that failure class instead. The card's `act` label reads "Act: G1 actions are the live model's, scored by T1's action predicates".

Probes can write memory; isolation is per checkpoint, not per question. The window W = 16K is provisional. Results never feed boards, gates, admission, rungs or the public regression corpus. The flip list is the developer's own regression set, never public-corpus stock ([erratum](../ERRATA-v2.2.md#design-text-where-prereg-governs)). This offline acceptance proves the guide matches the code; it proves no live run.
