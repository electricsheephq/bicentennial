# Bicentennial roadmap

Bicentennial is its own product, with its own repository, releases and site. Its versions are independent of LCM-X's.

## Releases

| Release | What ships | Done when |
|---|---|---|
| **v0.1 Kit** (the first weeks after approval) | the public repository; generator core with the G1 and G2 genres; scorer; director; Hermes adapter; spikes S1-S7, with S6a first; **developer tiers T0 (probe packs) and T1 (CI smoke)** | T0 and T1 run on Hermes native memory and two external systems. T1 is deterministic on stable fields, and the wiped-store positive control fails it. |
| **v0.2 Pilot** (3-week timebox) | **T2 live smoke, T3 dev, the fault finder, repro bundles and the developer report**; the calibration set; the bar-1 and bar-2 runs of record; the pilot report | Pilot bars 1-6 pass, or the failed-pilot fallback runs. PREREG-v1 is frozen and its hash posted. |
| **v1.0 Board** (Phase 1, inside the LCM-X v0.30.0 milestone) | the sealed full core board for G1 and G2 (season 1); the seasonal robustness study; at least 3 external competitors; the Claude Code adapter; the seal; the results card; **the site and leaderboard** (launch timing is a maintainer decision) | The season-1 board is published with CIs and the operating metrics. The best system is measured below about 60, and the test is not tuned toward that number. |
| **v1.x** | the Codex adapter (needs a VM clock); vendor-submitted configurations (when a submission window opens); an external reviewer with a scoring veto; IRT dev selection; an evaluation of within-life twins; a measured dev-predicts-full chain | as each lands |
| **v2 Frontier** | the ≥ 10M-token horizon; images and screen recordings (after measured use, per #1719); Hands in simulation; a design-only path to a low-cost desk arm | research tier; curves rather than a single score |

## The site and leaderboard
- **Generated from the results.** The site is static and built from the result cards in the public repository, so no score is ever typed by hand.
- **Pages:**
  - **Board:** per season, for each system:
    - the headline with its CI, and the normalised score from no-memory (0) to oracle evidence (100);
    - per-track scores, the budgeted row and the worst-case row;
    - operating metrics: latency p50 and p95, store growth, time-to-correct, and cost and wall time per run.

    Systems whose CIs overlap are shown as tied bands, not as ranks.
  - **Robustness:** the seasonal study's fault pass^k, Keep curve, swap comparator and family-B replication. Each result is labelled with the versions it covered.
  - **Method:** the design, the pre-registration versions with their hashes and changelogs, the firewall statement, and the tuning detector (LCM-X at its last release before the public generator).
  - **For developers:** how to run T0-T3 and the fault finder on your own system, the probe-pack catalogue, and the repro bundle format.
  - **Submit:** how a system joins the board: an open-source, self-hostable system with a Hermes memory plug-in or a documented ingest and query API, and an equal configuration budget.
  - **Roadmap:** this page.
  - **Runs:** every scheduled run, published in order, with its result card and spend. Traces are downloadable for public lives only.
- **Board rules shown on the site:**
  - every system's latest version, never its best;
  - every scheduled run is published;
  - delta boards run only on a new GA, with the previous version re-run alongside;
  - no claim of rank without separation.
- **Gate:** the leaderboard is published only after the v1.0 board exists. Until then the site carries the method, the developer docs and the roadmap.

## Standing rules
- **Firewall:** the benchmark never advises on LCM-X internals. LCM-X runs under the same rules as every system, and its developers never see held-out seeds or keys.
- **Spend:** reported on every run.
