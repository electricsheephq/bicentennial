# S6: one generated full-scale G2 life

**Question.** What does one 200-session public life cost on the pinned Sol lane, by request role, including eight long sprints, the inline kill and the wiring-only swap? How do natural store bytes compare with K100 and K10, and what lane work follows under PREREG v0.4 §11?

S6 is an advisory feasibility measurement. It produces no memory-quality score or completion-record value. Part (a) implements offline preparation and tests; the dispatcher owns every live operation in part (b).

**Implementation status.** P06b implements `build`, `run` and `summarise`, continuing the stopped first attempt. Validation is offline only; live measurements remain pending part (b). P06a projection and window files are frozen in this attempt. The P06b stop signal is more than 700 added lines in `run.py`.

## Part A: preparation and accounting (offline, $0)

- Generate G2, life `s6-g2`, seed 6, `named("full")`; never re-pick the seed.
- Compile 200 replay sessions and one two-item QA probe session immediately after replay 200. Earlier checkpoints measure bytes only.
- Use exact rational workload arithmetic, with integers at the canonical JSON boundary. Include every sent retry, hold and integer token count by ledger role.
- Expose R12's optional full-window configuration while preserving the default bytes. W = 131072 is illustrative; C-4 remains open.
- Count recovery spawn/open once, inside recovery time. Never copy probe finals into measurement artifacts.

## Part B: the full life (dispatcher only, pending)

**Arms.** `hermes-native` and `mem0-oss` only, one process and one arm at a time. Mem0 remains `not_run: mem0_blocked` until its registry artifact pin is measured. Extraction and embeddings remain scripted wiring.

**Measures.** Replay and probe cost by role; session job and own time; compactions by sprint; kill/resume and swap; natural store bytes above the initialised empty-store baseline at 20, 60, 120 and 200; K100 verdict and K10 cap without a verdict; responder state, holds, drift, marker readings, egress and credential-scan receipts. Probe finals remain solely in normal harness history and director ledgers.

**Projection.** Report every PREREG §11 term as measured, derived, assumed, missing or not run. C_learn and C_erase are missing, entering arithmetic as zero. Project board and study work separately at R_s = 180 and C = 20 per account, with each work projection times the 1.25 pause allowance bounded by 96 h, for hypothetical one- and two-account lanes. Apply the fixed cut order. Report the replay-plus-probe chain time as a lower bound. Life fit and overall fit are undetermined without an occupancy projection.

## Constraints

- Standard library and benchmark code only; the temporary Responses bridge is loaded from S7 through `runpy`, never promoted into `src`.
- No network, login, credential-store access, model call or real Hermes in part (a). Unit tests may use loopback fakes.
- Live preflight requires the benchmark operator, hash seed 0, nice 19 and background policy, required Sol variables, 150 GB free disk and start marker 0. Refuse after two hours without admission.
- Every live root is isolated in scratch. Never use the reference agent, SSH or LCM-X. No worker-group-external signals.
- The live arm wall ceiling is 24 h. Identity drift, credential refusal, responder stops, quota holds, non-loopback egress and scan hits stop admission under the dispatch packet.
- One shared run Spend, cap 0 and prices 0. No paid API. Required max-output source and send ceiling are recorded.
- Before first ingest, open/end an empty worker session and settle, then measure the baseline for both arms. Initialisation uses the adapter's existing private cold-start/open/end hooks, without delivering any turn; it checkpoints the native WAL and settles Mem0 before measuring the baseline.

## Does not prove

Any memory quality; Learn chains or erasure; images or act items; replication-family or swap-lane performance; K10 under a real cap; twin-measured shares; checkpoint 20–120 probe cost; many concurrent processes/accounts; other times of day or GLM; native-provider behaviour without the bridge; behaviour without scripted placeholder assistant turns; a frozen 128K window; generalisation beyond one seed/life; Mem0 without scripted extraction and embeddings; or a fit under the projected schedule and lane occupancy.

## Lanes

Part (a) is offline code and unit tests only. Part (b) remains the dispatcher's live task after part (a) completes and passes its acceptance checks. The dispatcher owns live execution, credential access, result publication and the README status update. Offline checks include loopback Responses SSE and fake-worker scenarios; sandbox worker-start failures require a dispatcher rerun.

## Commands and outputs

`build --out D` exclusively creates the fixed full-life layout and prints its script hash.
`run --arm {hermes-native,mem0-oss} --life D --scratch S --hermes H --sol-max-output N --sol-max-output-source TEXT --max-sends N [--mem0-source M]` runs a single isolated arm. Blocked Mem0 returns 2 before preflight, login or root construction. All other live starts use ordered preflight. Existing roots refuse reuse.
`summarise --scratch S --life D --out P` exclusively writes canonical aggregate JSON after verifying the ledger and requiring a clean credential scan. It refuses nonzero settled spend. A stopped replay keeps partial accounting but receives no full-life projection.

Exit codes: 0 complete; 1 credential leak/scan hit; 2 arm not run; 3 admission/login, system or summary refusal; 4 run stop or runtime failure (exception type only); 70 incorrect hash seed. No probe final is copied into `arm.json` or `s6.json`. Normal harness histories and ledgers retain their ordinary content.
