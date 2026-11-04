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
| `write_tools` | Tool/action rows; must be `[]` for an outside entry in this PR. |
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

Every tier refuses outside entries with nonempty `write_tools` until the next PR
routes the scripted responder through recipes. Scripted `structured_formats` are
also unsupported. A recipe's memory-host mappings do not lift either restriction.

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

## Operator firewall

The benchmark operator runs only entries it wrote itself, including its baseline.
The firewall prevents accidentally running LCM-X under a different entry filename:
it checks the entry name, artifact name, provider, engine and directory after Unicode
normalization, case folding and punctuation removal, and refuses any of them that
contains `lcm`, so an unrelated name such as `excel-cmd` is refused too; rename such an
entry. It also recognizes registry
identities marked operator-forbidden and their measured, nonzero artifact digests.
T2-lite and T2 apply the same identity check to an operator-marked home. A deliberately
disguised copy is outside this scope. The entry's own permission flag cannot override
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
| `entry_scripted_writes_unsupported` | Outside entries cannot declare write tools until the responder uses recipes. |
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
