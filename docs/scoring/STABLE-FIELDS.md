# Stable-field partition

Import `bicentennial.contracts.bundle` once to register scoring semantics, then use
`bicentennial.contracts.run.validate(name, obj)`. K13 owns structural validation.
Paths describe schema properties; `[]` denotes each array element. Open envelope
`value` payloads inherit stable status, including every nested key.
All times/latencies are integer milliseconds; load is scaled by 1000.
Pins bind the named artifact bytes; `masks_hash` pins K13's named masks table.

| Property path | Stability | Source |
| --- | --- | --- |
| `card.canary` | stable | RING0 §4 |
| `card.tier` | stable | RING0 §4 |
| `card.system` | stable | RING0 §4 |
| `card.run_status` | stable | RING0 §4 |
| `card.pins` | stable | RING0 §4 |
| `card.pins.benchmark_commit` | stable | RING0 §4 |
| `card.pins.generator_commit` | stable | RING0 §4 |
| `card.pins.director_commit` | stable | RING0 §4 |
| `card.pins.scorer_commit` | stable | RING0 §4 |
| `card.pins.pack_hash` | stable | RING0 §4 |
| `card.pins.seed_hash` | stable | RING0 §4 |
| `card.pins.harness_hash` | stable | RING0 §4 |
| `card.pins.system_hash` | stable | RING0 §4 |
| `card.pins.route_table_hash` | stable | RING0 §4 |
| `card.pins.write_turn_package_hash` | stable | RING0 §4 |
| `card.pins.environment_boundary_hash` | stable | RING0 §4 |
| `card.pins.repository_boundary_hash` | stable | RING0 §4 |
| `card.pins.masks_hash` | stable | RING0 §4 |
| `card.masked_ledger_digest` | stable | RING0 §4 |
| `card.labels` | stable | RING0 §4 |
| `card.labels.signal` | stable | RING0 §4 |
| `card.labels.filters` | stable | RING0 §4 |
| `card.labels.rungs` | stable | RING0 §4 |
| `card.labels.voice` | stable | RING0 §4 |
| `card.labels.act` | stable | RING0 §4 |
| `card.labels.scripted_model` | stable | RING0 §4 |
| `card.items` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].item_id` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].cell_id` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].stage` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].track` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].base_verdict` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].benign_extra` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].failure_class` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].infra_reruns` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].score_milli` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].worst_case_milli` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].accuracy_correct` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].tuesday_class` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].envelope` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].envelope.type` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].envelope.value` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].envelope.confidence_milli` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].envelope.citation` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].envelope.citation.quote` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].envelope.citation.context_offset` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].selected_option` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].competing_present` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].carry_over` | stable | RING0 §4; PREREG §3/§7 |
| `card.items[].stage_attribution` | stable | RING0 §4; PREREG §3/§7 |
| `card.bundles` | stable | RING0 §4; PREREG §3/§7 |
| `card.bundles[].bundle_id` | stable | RING0 §4; PREREG §3/§7 |
| `card.bundles[].cell_id` | stable | RING0 §4; PREREG §3/§7 |
| `card.bundles[].twin_type` | stable | RING0 §4; PREREG §3/§7 |
| `card.bundles[].items` | stable | RING0 §4; PREREG §3/§7 |
| `card.bundles[].score_milli` | stable | RING0 §4; PREREG §3/§7 |
| `card.bundles[].failure_class` | stable | RING0 §4; PREREG §3/§7 |
| `card.aggregates` | stable | RING0 §4 |
| `card.aggregates[].stage` | stable | RING0 §4 |
| `card.aggregates[].track` | stable | RING0 §4 |
| `card.aggregates[].score_milli` | stable | RING0 §4 |
| `card.sensitivity` | stable | RING0 §4; PREREG §3/§7 |
| `card.sensitivity.minus_one_at_zero` | stable | RING0 §4; PREREG §3/§7 |
| `card.sensitivity.minus_one_at_zero[].stage` | stable | RING0 §4; PREREG §3/§7 |
| `card.sensitivity.minus_one_at_zero[].track` | stable | RING0 §4; PREREG §3/§7 |
| `card.sensitivity.minus_one_at_zero[].score_milli` | stable | RING0 §4; PREREG §3/§7 |
| `card.sensitivity.minus_one_at_minus_two` | stable | RING0 §4; PREREG §3/§7 |
| `card.sensitivity.minus_one_at_minus_two[].stage` | stable | RING0 §4; PREREG §3/§7 |
| `card.sensitivity.minus_one_at_minus_two[].track` | stable | RING0 §4; PREREG §3/§7 |
| `card.sensitivity.minus_one_at_minus_two[].score_milli` | stable | RING0 §4; PREREG §3/§7 |
| `card.per_item_accuracy` | stable | RING0 §4; PREREG §3/§7 |
| `card.per_item_accuracy[].cell_id` | stable | RING0 §4; PREREG §3/§7 |
| `card.per_item_accuracy[].correct` | stable | RING0 §4; PREREG §3/§7 |
| `card.per_item_accuracy[].eligible` | stable | RING0 §4; PREREG §3/§7 |
| `card.per_item_accuracy[].accuracy_milli` | stable | RING0 §4; PREREG §3/§7 |
| `card.coverage` | stable | RING0 §4; PREREG §3/§7 |
| `card.coverage.assigned` | stable | RING0 §4; PREREG §3/§7 |
| `card.coverage.scored` | stable | RING0 §4; PREREG §3/§7 |
| `card.coverage.blocked` | stable | RING0 §4; PREREG §3/§7 |
| `card.coverage.na_exposure` | stable | RING0 §4; PREREG §3/§7 |
| `card.coverage.na_clock` | stable | RING0 §4; PREREG §3/§7 |
| `card.coverage.coverage_milli` | stable | RING0 §4; PREREG §3/§7 |
| `card.controls` | stable | RING0 §4; RING0 §1/§6 |
| `card.controls.wiped_store` | stable | RING0 §4; RING0 §1/§6 |
| `card.controls.no_memory_floor` | stable | RING0 §4; RING0 §1/§6 |
| `card.controls.oracle_evidence` | stable | RING0 §4; RING0 §1/§6 |
| `card.controls.full_history` | stable | RING0 §4; RING0 §1/§6 |
| `card.controls.naive_rag` | stable | RING0 §4; RING0 §1/§6 |
| `card.diagnostics` | stable | RING0 §4; RING0 §1/§6 |
| `card.diagnostics[].track` | stable | RING0 §4; RING0 §1/§6 |
| `card.diagnostics[].competing_milli` | stable | RING0 §4; RING0 §1/§6 |
| `card.diagnostics[].carry_over_milli` | stable | RING0 §4; RING0 §1/§6 |
| `card.carry_over_milli` | stable | RING0 §4 |
| `card.gate_verdict` | stable | RING0 §4; RING0 §1/§6 |
| `receipt.canary` | volatile | RING0 §4 |
| `receipt.run_status` | volatile | RING0 §4 |
| `receipt.wall_start_ms` | volatile | RING0 §4 |
| `receipt.wall_end_ms` | volatile | RING0 §4 |
| `receipt.latency_ms` | volatile | RING0 §4 |
| `receipt.load_milli` | volatile | RING0 §4 |
| `receipt.busy_marker_readings` | volatile | RING0 §4 |
| `receipt.tokens` | volatile | RING0 §4 |
| `receipt.tokens.input` | volatile | RING0 §4 |
| `receipt.tokens.output` | volatile | RING0 §4 |
| `receipt.spend_micro_usd` | volatile | RING0 §4 |
| `receipt.store_growth_bytes` | volatile | RING0 §4 |
| `receipt.process_ids` | volatile | RING0 §4 |
| `receipt.ports` | volatile | RING0 §4 |
| `receipt.temporary_paths` | volatile | RING0 §4 |
| `receipt.raw_body_digest` | volatile | RING0 §4 |
