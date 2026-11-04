# Comparing T2 runs

Run the report from a source checkout with PYTHONHASHSEED=0:

```sh
bicentennial report --current runs/current --previous runs/previous --aa-prime runs/previous-repeat --out report.json
```

`--current` and `--previous` name completed T2 run directories. Optional `--aa-prime` names a second run of the previous version: the noise band compares previous minus A′. Required `--out` names a new file; existing files and symlinks are refused. The command writes canonical JSON and prints a plain-text report. Exit status is 0 on success, 3 for refusals and usage errors, and 70 for unexpected failures.

Only T2 is supported. Each directory must contain a valid COMPLETE receipt.json, a valid T2 card.json, receipts/system.json, units.json with a non-negative integer system arm time and a positive integer slots count, and no_memory.json with exactly the card's units and item identities. Floor rows must carry item_id, cell_id, stage, score_milli, failure_class and base_verdict. Fresh and cached floors have the same representation. Files are read in that order. G2 actions listed in not_scored_live remain excluded even when a crash leaves a numeric score. The same paired exclusion rule governs differences, noise statistics and floor lifts.

Comparability uses the imported BASELINE_FIELDS: system, pack_hash, seed_hash, model, effort, pins.harness_hash, answer_contract_sha256, pins.benchmark_commit, pins.generator_commit, pins.director_commit, pins.scorer_commit and profile. T2 also compares pins.route_table_hash and pins.write_turn_package_hash. These benchmark-side values are equal for any two runs of one system at one clean commit, so a mismatch identifies a benchmark change. A match does not show a clean tree: the commit pins are the checkout's `HEAD`, so an uncommitted edit outside the route table and `director/scripted.py` can leave every compared value equal. A mismatch uses the field in the templates below. The T2 card schema fixes profile, so a differing profile is run_invalid:card. Version pairs may differ in pins.system_hash; previous and A′ must match it. All loaded run and system receipts must share the same decimal-string turn_wait_s.

The seed is the hex SHA-256 of the concatenated current, previous and optional A′ card bytes, in that order. There is no seed option. Identical inputs produce identical output bytes. The per-life table lists contributing lives in life order, scored-item counts, exact mean paired differences and each version's lift with its item count. Each lift pairs its own run with that run's floor and uses items scored in both arms; an empty lift is null with an item count of zero. An item excluded in only one version can count in the other version's lift but not in the contribution. Thus current_lift − previous_lift need not equal the contribution. Fractions are in score units, on the raw penalised scale. Lives with zero contribution do not count as sign changes; a zero or absent estimate has a null sign-change count.

Operating metrics are current minus previous, from system receipts only. T2 wall time uses the system's RING0 §14.8 arm time, excluding the floor whether fresh or cached. Each run's slot count is printed. When current and previous slot counts differ, wall_ms is null and wall_ms_reason is slots_differ; otherwise wall_ms_reason is null. Only wall_ms is suppressed, because the arm time is computed from the slot count itself. The latency percentile deltas are not adjusted for slots: more units at once can lengthen each request through contention at the provider and on the machine, so read them with both slot counts in mind. A′ slots are reported only; the noise band uses no wall time. Per cell and pooled, the text includes the estimate, direction, p, clustered interval or the fewer-than-ten-lives notice, q0 fraction with its Wilson interval and independence assumption, A − A′, approximate sensitivity with the exact test limit, and sign-change counts. Both version hashes, operating deltas, failure taxonomy and the per-life table are printed.

| Code | Cause |
|---|---|
| `run_invalid:receipt` | A run or system receipt is missing, unreadable or invalid. |
| `run_incomplete` | The run receipt does not say COMPLETE. |
| `run_invalid:card` | The card is missing, unreadable or invalid, including a differing profile. |
| `tier_unsupported` | The parsed card's tier is not T2; checked before T2 validation. |
| `run_invalid:units` | units.json is unreadable or lacks a non-negative integer system arm time or a positive integer slots count. |
| `run_invalid:floor` | The floor is missing, unreadable, malformed or does not cover exactly the card's units and items. |
| `baseline_mismatch:<field>` | Current and previous differ on a field listed above. |
| `aa_prime:baseline_mismatch:<field>` | Previous and A′ differ on a field listed above. |
| `aa_prime:system_hash` | Previous and A′ have different system hashes. |
| `turn_wait_mismatch` | Loaded receipts disagree on turn_wait_s. |
| `items_mismatch` | Valid version cards have different item identities. |
| `aa_prime:items_mismatch` | Valid previous and A′ cards have different item identities. |
| `invalid_rows` | Paired item metadata disagree or rows cannot be used by the statistics contract. |
| `out_exists` | The output path already exists, including a symlink. |
| `tool_failure` | An unexpected failure occurred, including an output write failure. |
| `hashseed` | PYTHONHASHSEED is not 0. |
| `source_checkout_required` | Source files are missing or the git top level differs. |
| `usage` | A required argument is missing or a command-line argument is invalid. |

Every report carries this label:

a developer signal; not predictive of the full tier; confirm on Ring 1 before claiming
