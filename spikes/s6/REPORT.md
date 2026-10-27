# S6 report skeleton

## Claim

Pending part (b). Intended claim: advisory, live, $0 plan lane (Sol, one account, one process); one generated public G2 life, 200 sessions, 8 sprints; Hermes native measured; Mem0 OSS not run: mem0_blocked.

P06b implements all three CLI commands and offline operational acceptance. The dispatcher must rerun sandbox-blocked worker tests before live part (b). No login, credential-store read, model call or real Hermes run occurred in this lane.

## Inputs and pins

Pending part (b). Fixed life `s6-g2`, G2 seed 6; script SHA-256 `78f85667be31e1840caec345816689c2507a6089d5010daed8b81b0c9ec1f442`. Window 131072: illustrative; C-4 open. Base commit `85f40375be0e89f1d253b5d6b7d30ea73bff9941`.

## R by role

Pending part (b). Include requests, tokens, upstream/held ms, session job/own time, compactions by sprint/ordinary session, kill/resume and wiring-only swap.

## Probes

Pending part (b). Checkpoint 200 only, two QA items. Report e_probe and sample counts; never copy finals.

## Bytes

Pending part (b). Measure above the initialised empty store after empty open/end/settle, before ingest. Report natural bytes, K100 verdict, and K10 cap without verdict at all four checkpoints.

## Terms

Pending part (b). R measured; R_cap derived = R; P from e_probe × b × (1 + ctrl), ctrl = 1 assumed; f = 1/2, r_c = 3R/20, p_c = P/4, P_K = P/5, P_W = P/10 assumed. Report measured sessions 110–120 beside r_c. R_B = R, P_B = P, delta_W = 1 assumed. C_learn/C_erase missing; C_image not run; C_cross/C_marker/C_aa/C_ctrl/C_ring1/C_ring2 shared and unmeasured. Label every term with value and source.

## Projection

Pending part (b). Per arm/life/lane, disclose the cut order, work-bound readings, first fitting work cut and bar-5 inputs at n_L = 48. The chain time is `critical_path_lower_bound_ms`; life fit and overall fit read `undetermined: no occupancy projection`. First overall fitting cut remains unknown.

## The missing Learn-chain term

Pending part (b). C_learn is missing (ERRATA E9). Report its break-even under the v0.4 bound and S6b's former rule. S6b request-only goldens are 11,589 uncut and 47,069 after cuts 1–2 under the former rule; 82,869 uncut under v0.4. Measured in v0.2, before any Learn chain enters a run of record.

## Operating data

Pending part (b). Include sends, holds/pauses, drift/flagged sessions, spend (0), egress, scan, wall time, marker readings and RSS peak.

## Decisions taken

- The Files list controls: do not edit `spikes/README.md` in part (a). This skeleton remains separate from the lane's external evidence report.
- Amendment A1 overrides the original life-fit acceptance: a chain lower bound cannot establish occupancy fit. `Terms.critical_path_ms` preserves the specified constructor name, while output labels the lower bound explicitly. `first_work_fit` is separate from unknown `first_fit`.
- Amendment A2 requires initialisation before the baseline. The runner opens and ends an empty cold worker session using the existing adapter hooks, checkpoints the native WAL, settles Mem0, then measures all surfaces before ingest. The baseline receipt is retained separately from replay cost.
- Amendment A3 is applied during aggregation: preserve initial spawn/open entries, count each recovery once under `resume`.
- Amendment A4 sets the live disk floor to 150 GB, interpreted as 150,000,000,000 bytes. Start admission records every marker poll and refuses after two hours.
- Amendment A5 tests price mismatch on Upstream directly.
- Nearest-rank percentiles follow Decision 11's explicit rule; S6a's older index-rounding implementation is not reused.
- One replay supplies both byte readings. K10 stays unjudged in v0.1. Probes run only at checkpoint 200; two-item episode cost would be disclosed as an upper-bound reading for earlier checkpoints.
- Amendment 2 separates P06b from the frozen P06a files. The stop signal is more than 700 added lines in `run.py`; documentation and tests are outside that count. No P06a file was edited in this attempt.
- Session start times come from the specified deterministic full schedule; rendered session rows omit these times and IDs. Stream session IDs are mapped through the verified history manifest in replay order.
- Both arms have one replay: K10 is a byte-cap comparison without a verdict, not a real-cap run.
- A stopped/incomplete life retains partial roles and the failed attempt's roles separately; its projection is `not_run: incomplete_life`, rather than extrapolating an incomplete R.
- Bridge mapping failures latch the credential responder's underlying stop state so boundary admission sees the bridge label. A NeedleGuard receipt also forces credential exit 1.
- Empty-session initialisation is excluded from replay/probe costs. The arm wall budget includes initialisation and all session-boundary pauses.
- Statistics use integer nearest ranks. Probe wall cost is mean fixed session overhead plus mean own turn cost per item, with two items in the single checkpoint-200 episode. Earlier checkpoint use remains an assumed upper-bound reading.
- Runtime results record hashes, labels and counts; endpoint strings observed by the egress sampler are hashed on a stop. The original response bodies and probe finals remain in normal ledgers only.

## Does not prove

Pending part (b). Any memory quality; Learn chains, erasure probes or Image profile; replication-family R_B/P_B and swap lane (DV47); K10 under a real cap; twin-measured f/r_c/p_c/P_K/P_W; checkpoint 20–120 and act-item probe cost; many processes/accounts; other times of day; GLM (S6d); native-provider behaviour without the bridge; behaviour without scripted placeholder assistant turns; frozen W = 128K; generalisation beyond one seed/life; Mem0 without stubbed extraction/embeddings; a fit under the projected schedule and lane occupancy.

## Reproduction commands

Offline build: `env PYTHONHASHSEED=0 <venv>/bin/python spikes/s6/run.py build --out <scratch>/life`.

Pending part (b). Set the required environment through the local helper, never a repository file, and run one arm/process at a time after offline acceptance passes outside the sandbox.

```sh
env PYTHONHASHSEED=0 <venv>/bin/python spikes/s6/run.py run --arm hermes-native --life <scratch>/life --scratch <scratch> --hermes "$BICENTENNIAL_HERMES" --sol-max-output <N> --sol-max-output-source "<documented source>" --max-sends 2000
env PYTHONHASHSEED=0 <venv>/bin/python -m bicentennial.director.upstream.login --scan --run <run> <scratch>/p06-hermes-native
env PYTHONHASHSEED=0 <venv>/bin/python spikes/s6/run.py summarise --scratch <scratch> --life <scratch>/life --out spikes/s6/results/s6.json
<venv>/bin/python scripts/public_check.py
```

Mem0 stays blocked until its registry artifact pin is measured; then use the same run command with `--arm mem0-oss --mem0-source <checkout>`. The 5–10 h duration is an estimate, not a measurement. Every live result section above remains pending part (b).
