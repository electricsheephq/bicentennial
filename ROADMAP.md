# Bicentennial roadmap

Bicentennial is its own product, with its own repository, releases and site. Its versions are independent of LCM-X's.

## Releases

| Release | What ships | Done when |
|---|---|---|
| **v0.1 Kit** (the first weeks after approval) | the public repository; generator core with the G1 and G2 genres; scorer; director; Hermes adapter; spikes S1-S7, with S6a first; **developer tiers T0 (probe packs) and T1 (CI smoke)** | T0 and T1 run on Hermes native memory and two external systems. T1 is deterministic on stable fields, and the wiped-store positive control fails it. |
| **v0.2 Pilot** (3-week timebox) | **T2 live smoke, T3 dev, the fault finder, repro bundles and the developer report**; the calibration set; the bar-1 and bar-2 runs of record; the pilot report | Pilot bars 1-6 pass, or the failed-pilot fallback runs. An external reviewer with a veto over scoring is recruited, and PREREG-v1 is frozen and its hash posted. |
| **v1.0 Board** (Phase 1, inside the LCM-X v0.30.0 milestone) | the sealed full core board for G1 and G2 (season 1); the seasonal robustness study; at least 3 external competitors; the Claude Code adapter; the seal; the results card; **the site and leaderboard** (launch timing is set with the owner) | The season-1 board is published with CIs and the operating metrics. The best system is measured below about 60, and the test is not tuned toward that number. |
| **v1.x** | the Codex adapter (needs a VM clock); an **AML-compatible adapter**, so a system that already serves the Agent Memory Leaderboard's Add and Search endpoints can run Bicentennial's API-mode slice with no new code (API mode never sets the headline); vendor-submitted configurations (when a submission window opens); IRT dev selection; an evaluation of within-life twins; a measured dev-predicts-full chain | as each lands |
| **v2 Frontier** | the ≥ 10M-token horizon; images and screen recordings (after measured use, per #1719); Hands in simulation; a design-only path to a low-cost desk arm | research tier; curves rather than a single score |

## The site and leaderboard
- **Where it fits.** The [Agent Memory Leaderboard](https://agentmemoryleaderboard.ai/) (AML) already ranks memory systems:
  - systems expose Add and Search endpoints;
  - a fixed answer pipeline runs over established recall datasets;
  - results come in seasonal cycles, with separate open-source and commercial rankings.

  Bicentennial measures something AML does not: what an agent *does* inside its own harness across a life of restarts, compactions, model swaps and long gaps. The two are complements. Bicentennial follows AML's conventions where they help entrants: a versioned evaluation contract, and a non-scored smoke run before any full run.
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

## Papers
- **The Bicentennial paper, in two steps.** Both are written only from published result cards.
  1. **A preprint after the pilot:** the design, the pre-registration and its versions, and the pilot's validity evidence (filters, audits, known-order ablations, the controls).
  2. **The full paper with the season-1 board:** adding the board, the robustness study and the measured dev-predicts-full chain.
- **Papers about memory systems evaluated on Bicentennial,** LCM-X's among them:
  - they cite only published, sealed board runs;
  - a paper by a system's own maintainers also reports independent benchmarks, so Bicentennial is never the only evidence for a system built alongside it;
  - an LCM-X paper discloses that LCM-X and the benchmark share maintainers. The firewall rules apply unchanged.

## Standing rules
- **Firewall:** the benchmark never advises on LCM-X internals. LCM-X runs under the same rules as every system, and its developers never see held-out seeds or keys.
- **Spend:** reported on every run.
