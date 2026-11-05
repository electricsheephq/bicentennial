# Outside registry entries

Keep an entry file outside the benchmark checkout and select it with `--entry PATH`.
`t0`, `t1`, `t2lite`, `t2` and `pins` each require exactly one of `--system NAME`
and `--entry PATH`. A file is an outside entry exactly when it has a `recipe` table.
The built-in registry files use the existing code tables and cannot contain that table.
An outside entry never resolves a built-in code-table row by its name.

The file uses the system schema and the same admission rules as built-ins, plus the
outside-entry rules below. Its system hash covers both the artifact declaration and
the canonical complete entry after loading (including supplied nullable defaults).
Two versions can therefore be compared at one benchmark commit: changing a recipe
changes the system hash even when the artifact declaration stays the same.

## Entry file

Supply these system fields:

| Field | Value |
|---|---|
| `name` | System name: ASCII letters, digits, `.`, `_` and `-`, starting with a letter or digit; must not shadow any built-in registry or code-table name. |
| `licence` | Provisional OSI licence identifier. |
| `harness` | `hermes` for these runners. |
| `artifact` | `name`, release-tag `version`, and archive `sha256`. |
| `write_tools` | Tool/action rows: the first tool is covered by `recipe.write`, the forget delete tool by `recipe.forget`, and any other tool by `recipe.unscripted`. |
| `read_tools` | Declared read-tool names. |
| `recall` | Tool and `argument_template`, with only `{prompt}` substitution; omit when unused. |
| `surfaces` | Rows with `root`, relative path, and `volatile_paths`; the state to preserve and scan. An outside entry has one HERMES_HOME row at `.`, the whole Hermes home, as every Hermes built-in has, and any SANDBOX_HOME rows. |
| `fresh_install_hash` | Measured install digest. |
| `own_model_routes` | Rows with a role and its served alias. |
| `structured_formats` | Required empty table for an outside entry. |
| `embedding_dim` | Embedding dimension when used; omit when unused. |
| `settle` | `kind` (`none` or `hook`) and integer `bound_s`. |
| `machine_class` | `light` or `heavy`. |
| `benchmark_operator_runs` | Whether benchmark-operator runs are allowed; identity exclusions also apply. |
| `recipe` | The closed recipe table described below. |

TOML has no null. Loading supplies `recall = null` and `embedding_dim = null` when
omitted. The other required system fields must be present. See the [built-in guide](ring0.md)
for the shared tool, surface, model-route and install contracts.

## Recipe fields

| Field | Value |
|---|---|
| `provider` | Memory-provider plug-in ID. Supply exactly one of `provider` and `engine`. It must not name a provider that the pinned Hermes bundles, which Hermes loads first. |
| `engine` | Context-engine ID. `compressor` is forbidden, as is an engine that the pinned Hermes bundles. Engine-only entries have no T0 surface. |
| `plugin_directory` | Optional install directory ID; defaults to provider, otherwise engine. |
| `archive_tree` | Closed table with `ref` and optional `subdirectory`. |
| `archive_tree.ref` | `HEAD` or a full 40-character lowercase hexadecimal commit. |
| `archive_tree.subdirectory` | Relative archive path; no parent component, backslash, absolute path or leading dash. |
| `enabled` | Boolean controlling the enabled plug-in list. Required. |
| `worker_environment` | Required table of isolated worker variables and string values. |
| `file_time_sites` | Required array of file/function sites, such as `provider.py:now`; `[]` when unused. |
| `settle_threads` | Optional array of thread names used by hook settledness. |
| `write` | Optional closed table with `tool`, `fixed` arguments and `content_key`. |
| `forget` | Optional closed table with the fields below. |
| `unscripted` | Required array of mapped, unscripted tools; `[]` when unused. |

Provider, engine and directory IDs follow `[a-z0-9][a-z0-9_-]*`. Worker variables
use the built-in environment rules: reserved names and prefixes are forbidden,
plain values cannot name paths, and `{model_cache}` may select the supplied model cache.
The recipe cannot supply a dependency lock or reference adapter.

A forget mapping supplies `search_fixed`, `query_key`, `listing_key`, `text_key`,
`id_key`, `delete_tool`, `delete_fixed`, and `delete_key`. `search_tool` is optional;
omitting it means no search tool. The fixed fields are argument tables. A provider
requires both write and forget mappings even with `write_tools = []`, because T0
and every tier's fresh-install check use the memory host.

Every tier and `pins` check write-tool coverage: the first write tool must match
`recipe.write`, the forget delete tool is covered by `recipe.forget`, and any other
write tool must appear in `recipe.unscripted`. Missing or undeclared mapped tools,
an undeclared forget search tool, and fixed actions absent from a tool's non-empty declared actions use the
mapping refusal codes below. The check compares the recipe with the entry's own
`write_tools` and `read_tools`, not with the plug-in's tool schemas, and an entry
with no write tools skips it. `forget_mapping_missing` cannot be reached by an
outside entry: a provider recipe requires both mappings, and an engine needs no
forget mapping. Scripted `structured_formats` remain unsupported.

## Measuring and running

Begin with zero digests for the measurements, then run:

```sh
bicentennial pins --entry ENTRY --hermes HERMES --plugin-source PLUGIN
```

`ENTRY` names the outside TOML file; `HERMES` and `PLUGIN` name the pinned clean
checkouts. Pins measures two fresh installs from the recipe's archive tree and
prints `fresh_install_hash`, `artifact.sha256` and the entry name. Copy both digests
into the file. Pins applies all outside rules except the unmeasured-pin check.
Use `--entry ENTRY` in place of `--system NAME` with each runner's usual pack and
output arguments. T0 constructs a seg0 route table for this entry and records its
hash in the run lock. The frozen built-in route table stays unchanged.

A T2-lite comparison's `flips.json` prints each rerun command with `--system NAME`;
for an outside entry, replace it with `--entry ENTRY` and add `--plugin-source` (and
`--model-cache` if the recipe uses one) until #471 prints them.

## Worked example: the benchmark's own baseline

`naive-rag-dev` v1 is the benchmark team's Hermes memory-provider plug-in, implementing
the pinned naive-RAG control's hashed TF-IDF, top-5 retrieval algorithm in its own code.
The team acts as an outside developer: the entry is kept outside the checkout and its
`recipe` table makes it an outside entry, off every roster and board. See
[RING0 §14.2 and its 2026-11-05 (#390) erratum](../../specs/ring0/RING0.md#142-the-baseline-naive-rag-dev)
for the baseline, version and receipt rules.

Save this v1 entry as `ENTRY`. Its archive digest is measured; its all-zero
`fresh_install_hash` is a placeholder to replace before running a tier.

<!-- entry-example: naive-rag-dev-v1 -->
```toml
name = "naive-rag-dev"
licence = "Apache-2.0"
harness = "hermes"
artifact = {name = "naive-rag-dev", version = "1.0.0", sha256 = "8f991c14d1aee11e846fe7f2c8b9e296f2555d561e729b5a8574cba81fef622e"}
fresh_install_hash = "0000000000000000000000000000000000000000000000000000000000000000"
write_tools = [{tool = "naive_rag_add", actions = []}, {tool = "naive_rag_delete", actions = []}]
read_tools = ["naive_rag_search"]
recall = {tool = "naive_rag_search", argument_template = {query = "{prompt}"}}
surfaces = [{root = "HERMES_HOME", relative = ".", volatile_paths = [".mcp-discovery.lock", "logs"]}]
own_model_routes = []
structured_formats = {}
settle = {kind = "none", bound_s = 0}
machine_class = "light"
benchmark_operator_runs = true

[recipe]
provider = "naive-rag-dev"
archive_tree = {ref = "aa30438e9c3402f6a4e761174694e33b1de1f3aa", subdirectory = "baselines/naive-rag-hermes"}
enabled = false
worker_environment = {}
file_time_sites = []
unscripted = []
write = {tool = "naive_rag_add", fixed = {}, content_key = "content"}
forget = {search_tool = "naive_rag_search", search_fixed = {whole = true}, query_key = "query", listing_key = "results", text_key = "content", id_key = "id", delete_tool = "naive_rag_delete", delete_fixed = {}, delete_key = "memory_id"}
```

The archive embeds the commit id, so its digest names that commit as well as its tree.
The full 40-character ref is public on `main`; `HEAD` would move. This follows erratum
(b), which requires a public commit for each version.

Start with the hash seed below; every `bicentennial` command and the pack install
module refuse with `hashseed` without it. `HERMES` is the pinned clean Hermes checkout.
`PLUGIN` is a clean, full-history clone of this benchmark repository containing the
entry's commit. In a depth-1 clone that lacks it, pins and the receipt refuse
`pin_mismatch`. Measure the fresh install:

```sh
export PYTHONHASHSEED=0
bicentennial pins --entry ENTRY --hermes HERMES --plugin-source PLUGIN
```

Copy the printed `fresh_install_hash` into `ENTRY` and confirm the printed
`artifact.sha256` agrees with the entry. Build and install each tier's packs. The
install command takes source and destination as two positionals; each destination
must not exist. It prints the pack hash on stdout:

```sh
bicentennial build --tier T0 --out BUILD_T0
PACK_HASH_T0="$(python -m bicentennial.packs.install install BUILD_T0/T0 PACKS_T0)"
bicentennial build --tier T1 --out BUILD_T1
PACK_HASH_T1="$(python -m bicentennial.packs.install install BUILD_T1/T1 PACKS_T1)"
```

Choose `PACK_ID` from the installed T0 `index.json`. Run that one pack first: within
minutes it shows whether Hermes loads the plug-in. Then run all T0 packs and T1.
Every run needs its own new output directory (`out_exists` otherwise); the placeholders below name distinct outputs.

```sh
bicentennial t0 --entry ENTRY --pack PACK_ID --packs PACKS_T0 --pack-hash "$PACK_HASH_T0" --hermes HERMES --plugin-source PLUGIN --out OUT_T0_ONE
bicentennial t0 --entry ENTRY --pack all --packs PACKS_T0 --pack-hash "$PACK_HASH_T0" --hermes HERMES --plugin-source PLUGIN --out OUT_T0_ALL
bicentennial t1 --entry ENTRY --packs PACKS_T1 --pack-hash "$PACK_HASH_T1" --hermes HERMES --plugin-source PLUGIN --out OUT_T1
```

For v1, green means all of the following:

- The all-pack T0 command exits 0. No file records that exit status; its written
  equivalent is `gate_verdict = "PASS"` in every `OUT_T0_ALL/pack/<...>/card.json`
  and no `OUT_T0_ALL/refusal.json`. T0 cards can only be `PASS`, `FAIL`, `INVALID`
  or `BLOCKED`.
- T1 exits 0. Its written equivalent for this first run, without a baseline, is
  `OUT_T1/system/card.json` field `gate_verdict` equal to `CONFORMANCE_PASS`, matching
  the `gate.final` property in `OUT_T1/system/junit.xml`. A run with a baseline uses
  `PASS`. The junit `gate` property holds the gate before overrides; its exit code
  is not the command's exit status.
- `OUT_T1/wiped/card.json` field `gate_verdict` is `FAIL`. `PASS` or
  `CONFORMANCE_PASS` makes the system card `INVALID`; `BLOCKED` makes the control
  uninformative; `INVALID` means a honeypot was read.
- `OUT_T1/system/card.json` field `controls.wiped_store` is `FAIL`, rather than
  `PASS` or `uninformative`. The wiped arm's own copy of that field is always
  `FAIL` and provides no evidence about the system's control.

Finally, run the receipt on the same installed T1 packs used above. `RECEIPT` must
be a new file with an existing parent directory. The script imports and runs the
entry's archived code in its own process; use it only for the benchmark's own
baseline entry.

```sh
python scripts/naive_rag_top5.py --entry ENTRY --plugin-source PLUGIN --packs PACKS_T1 --pack-hash "$PACK_HASH_T1" --out RECEIPT
```

Receipt outcomes:

- Exit 0: receipt written, no defect.
- Exit 1: receipt written, a defect.
- Exit 3: refusal or usage error, no receipt. Reasons include `entry_ref_not_commit`,
  `pin_mismatch`, `identity_mismatch`, `pack_hash_mismatch`, `pack_not_t1` (packs are
  not T1), `out_exists` (an existing output is never replaced), and entry loader
  refusals from the [table below](#loader-and-admission-refusals). Usage errors
  print `usage: MESSAGE`.
- Exit 70: unexpected crash, `tool_failure`, no receipt.

The offline path below checks admission and the printed archive pin, scripted writes
through an outside recipe with a fake worker, and retrieval equivalence through v1's
real archived code. It does not prove that Hermes loads the plug-in (T0), real-stack
conformance (T1), or anything live (T2). The T0, T1 and receipt runs above precede the
bar's declaration, as erratum (d) requires. The fresh-clone CI job runs this exact
block, requiring every selected test to run without skips:

<!-- ci-block: entry-offline -->
```sh
set -e
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e .[dev]
export PYTHONHASHSEED=0
python -m pytest -q tests/test_developer_doc_entry.py::test_ci_block_matches_doc tests/test_developer_doc_entry.py::test_entry_example_admitted tests/test_developer_doc_entry.py::test_entry_archive_pin tests/test_naive_rag_top5.py tests/runner/test_entry_write_life.py::test_outside_scripted_write_life --junitxml=build/entry-offline.xml
python -c 'import xml.etree.ElementTree as E; root = E.parse("build/entry-offline.xml").getroot(); assert len(root.findall(".//testcase")) == 37 and not root.findall(".//skipped"), "offline acceptance must pass without skips"'
```

## Operator firewall

The benchmark operator runs only entries it wrote itself, including its baseline.
The firewall prevents accidentally running LCM-X under a different entry filename:
it checks the entry name, artifact name, provider, engine and directory after Unicode
normalization, case folding and punctuation removal, and refuses any of them that
contains `lcm`, so an unrelated name such as `excel-cmd` is refused too; rename such an
entry. It also recognizes registry
identities marked operator-forbidden and their measured, nonzero artifact digests.
T2-lite and T2 apply the same identity check to an operator-marked home and also refuse
an entry whose own `benchmark_operator_runs` is false there. An operator-marked home is
a login home (`--login-home`) holding a `.bicentennial-operator` file, as the
benchmark's own does. A deliberately disguised copy is outside this scope. The entry's own permission flag cannot override
an excluded identity under `BICENTENNIAL_OPERATOR=benchmark`.

## Loader and admission refusals

Refusals exit with code 3. Loader refusals occur before a runner starts. Admission
refusals use each runner's existing output-folder behavior: T2-lite and T2 leave
`refusal.json` in the new output folder, as their other preflight refusals do, so use a
new output folder after fixing the entry. Every refusal comes before any install,
session or live request. `<field>` is replaced
with the offending recipe field, including `archive_tree.ref` or
`archive_tree.subdirectory`; `provider` also names the provider/engine exclusivity rule.
Other install and runner refusals are listed in the [Ring 0](ring0.md),
[T2-lite](t2lite.md) and [T2](t2.md) guides.

| Code | Cause |
|---|---|
| `entry_unreadable` | Entry file cannot be read or parsed as TOML, or its path cannot be resolved. |
| `entry_invalid` | Entry file fails the system schema (including the recipe table's field types, required fields and unknown fields) or the contract. |
| `entry_recipe_missing` | An outside entry file has no recipe table. |
| `entry_name_invalid` | An outside entry's name uses a character other than ASCII letters, digits, `.`, `_` and `-`, or does not start with a letter or digit; published rerun commands carry the name. |
| `entry_recipe_invalid:<field>` | A recipe value breaks an outside-entry rule: both or neither of `provider` and `engine`, an ID that does not match the ID pattern, the `compressor` engine, `archive_tree.ref`, `archive_tree.subdirectory`, `worker_environment`, or an incomplete `forget` table; the code names the field. |
| `entry_shadows_builtin` | Normalized entry name collides with a registry file or a built-in code-table key. |
| `entry_recipe_unsupported:structured_formats` | Outside entries cannot declare scripted structured formats. |
| `write_mapping_missing:<tool>` | First write tool does not match `recipe.write`, or a write tool has no mapping. |
| `write_mapping_unknown:<tool>` | A mapped write or forget delete tool, or an unscripted tool, is not declared in `write_tools`. |
| `forget_search_undeclared:<tool>` | Forget search tool is absent from `read_tools`. |
| `write_mapping_action:<tool>` | A fixed write or forget-delete action is absent from the tool's non-empty declared actions. |
| `embedding_dim_invalid` | An embeddings route has no integer dimension of at least 2. |
| `t0_mapping_missing` | Provider recipe lacks its write or forget mapping, required by the install host. |
| `entry_surfaces_unsupported` | An outside entry's surfaces are not one HERMES_HOME surface at `.` plus any SANDBOX_HOME surfaces. The life runners hash, clone and wipe the whole Hermes home, and run no other root. |
| `entry_shadows_hermes_plugin` | An outside provider or engine has the name of one that the pinned Hermes bundles, which Hermes would load instead of the entry's archive. |
| `recipe_in_builtin` | A built-in registry file contains an outside recipe table. |
| `sandbox_overlap` | The entry file resolves to a sandbox slot's base or below it, where a run's lease would delete it; refused before the file is read; exit 3. |
| `licence_not_osi` | Licence is outside the provisional OSI allow-list. |
| `artifact_unpinned` | Artifact version is not a release tag or its digest is not 64 lowercase hex characters. |
| `route_unroutable` | An own-model alias is outside the served alias vocabulary. |
| `compaction_alias_mismatch` | Compaction does not use bicentennial-summariser. |
| `state_path_undeclared` | Surface path is unsafe, or active state has no surface. |
| `recall_placeholder` | Recall template contains a placeholder other than {prompt}. |
| `schema_invalid` | The declaration fails the system schema without a more specific policy refusal. |
| `benchmark_operator_forbidden` | Benchmark operator requests an excluded identity or an entry forbidding its runs. |
| `unmeasured:artifact.sha256` | Artifact digest is still the all-zero placeholder. |
| `unmeasured:fresh_install_hash` | Fresh-install digest is still the all-zero placeholder. |
