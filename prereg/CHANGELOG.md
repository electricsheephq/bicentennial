# Pre-registration changelog

Every change to the pre-registration after a freeze makes a new version, recorded here. Every result discloses the version it used.

## PREREG-v0.4, FREEZE_DATE: frozen (supersedes v0.3)
- **DV47, the run-time rule,** at the owner's direction: locked, resumable segments replace the contiguous 24-hour window. Every life finishes within 24 h, and each system's work, times 1.25 for pauses, fits 96 h on every lane (§11).
- **Validity controls** for segments: the run lock, keyed randomness, the served-identity check, the drift canary (new slot C-16), pause rules with a store-hash proof, attempts, and life-major interleaving of the arms after the controls (§6, §11). The card discloses the segments (§10).
- **DV42's fit corrected:** the swap model's lane is counted, and C-2 pins the swap model's effort.
- **The paid-lane ceiling** is $100 per board run and per study run, down from $300 (§11).

## PREREG-v0.3, 2026-10-26: frozen (supersedes v0.2)
- **DV42 decided after spike S6b:** the pinned agent family is OpenAI (gpt-6.1-sol at medium effort, on dedicated benchmark accounts); GLM is the replication family and the swap model.
- **The blind panel** becomes Anthropic, Zhipu and one paid third family (§4, C-3).
- **C-11** becomes the lane's sustainable capacity per account (concurrency, or a paced request rate), with the account count; the fit rule and director pacing are stated (§11).
- **The tuning disclosure** is generic (§10).
- **The owner co-sign** is removed, as recorded in the process note below.

## Process note, 2026-10-26: no owner co-sign
The owner made the benchmark session the product and release owner. Freezes bind on its own data-backed approval, with no owner co-sign. Text that mentions a co-sign in PREREG-v0.2 and design v2.0 is left unchanged so their hashes hold. It is corrected in the next version.

## PREREG-v0.2, 2026-10-26: frozen (supersedes v0.1)
- **Design v2.0:** the capability map of track rows by evaluation profiles. Its stages are Remember, Survive and Act, and each is reported separately.
- **Certification on Act only:** on the sealed board, by an intersection-union rule on the raw penalised scale. A season left underpowered by a cut issues no certificate, but every result is still published.
- **Developer rings 0-2:** rungs on system-agnostic anchors, and a monthly "transfer gap detected" bit per organisation.
- **Frontier diagnostics:** Learn chains, erasure probes and attestation twins.
- **The Image profile**, admitted through spike S8, with an approved vision budget of about $50 a season.
- **Per-item action accuracy**, defined in full. Failures are attributed by cause, not by the component that reports them.
- **The five amendments to v0.1:** long sprints by count, the Wake claim contract, per-item accuracy reported, added turn latency, and G1 task completion.
- **The 24-hour rule** is now sized on the pinned agent family's model lane (C-11). The lane itself is set by DV42 after spike S6b.
- **Decisions:** DV1-DV46, with DV42 reserved, are in `docs/DECISIONS-v2.md`.

## PREREG-v0.1, 2026-10-26: frozen (superseded by v0.2, never co-signed)
- **The 24-hour rule** (§11):
  - the full core board for one system, and the seasonal robustness study for one system, must each finish within 24 h of wall-clock time;
  - a run that cannot meets the cut order first, and then the owner decides between paid capacity and a narrower design.
- **About 5 assistant turns per scripted session.** This keeps each life's write-turn chain, its critical path, short.
- **New completion slot C-11:** the permitted concurrency, measured in S6a.
- **A rename:** the failed-pilot fallback is now PREREG-v0-narrowed.

## PREREG-v0, 2026-10-26: frozen (superseded, never co-signed)
- **The first frozen text.** It follows three adversarial review rounds, a closure check and a first-principles cost review (`docs/REVIEW-SUMMARY.md`).
- **Completion record pending.** Slots C-1 to C-10 (the pinned models, windows, write-turn package, template tables, analysis code, competitor list and ablation validation) are filled in `prereg/PREREG-v0-completion.md`, before any real memory system's first pilot run.
