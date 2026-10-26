# Bicentennial roadmap

Bicentennial is its own product, with its own repository, releases and site. Its versions are independent of LCM-X's.

**What it is for.** Today's memory benchmarks mostly ask whether a stored fact can be found again. Bicentennial asks what long-lived agents will need next:
- whether an agent's memory survives a life inside its own harness: restarts, compactions, crashes, model swaps and long gaps;
- whether it changes what the agent *does*;
- whether it obeys what the agent was told to keep, forget and never do;
- whether it learns from the agent's own attempts.

Many cells are hard on purpose. Some test capabilities that no surveyed system documents yet, and carry the label "undocumented frontier". The label is display only and never decides whether a cell is required: the season-1 frontier cells are diagnostics because of where they sit (Learn, the erasure probes, attestation, the conditional Image board, and the Survive stage for standing rules after compaction and a swap), and a zero there is published like any other result. Difficulty is frozen from controls only, and no target is set on any system's scores. Every cell's developer pack offers rungs, so a developer can measure movement below the board's lever values before a cell's verdict changes.

## Releases

| Release | What ships | Done when |
|---|---|---|
| **v0.1 Kit** (the first weeks after approval) | the public repository; generator core with the G1 and G2 genres; scorer; director; Hermes adapter; spikes S1-S8, with S6a first; **Ring 0 developer packs for the Remember, Survive and Act stages: T0 probe packs and T1 CI smoke** | T0 and T1 run on Hermes native memory and two external systems. T1 is deterministic on stable fields, and the wiped-store positive control fails it. |
| **v0.2 Pilot** (3-week timebox, re-planned after S6 and S8) | **T2 live smoke, T3 dev, rungs per cell, the fault finder, repro bundles with their declared class, the developer report**; the **Image profile** in Ring 0 once spike S8 admits it; the first **Learn** chains (bounded and terminal; a diagnostic); the calibration set; the bar-1 and bar-2 runs of record; the pilot report | Pilot bars 1-6 pass, or the failed-pilot fallback runs. **The developer-loop acceptance bar:** the benchmark team, acting as developer of its own baseline (naive RAG or the raw-archive marker), takes one real-stack public failure, reproduces it from its bundle, fixes it and confirms it on Ring 1, within the declared T2/T3 budgets; no contestant system is involved, and LCM-X is not. The variance inputs are measured on the bar-2 control arms with one A/A′ rerun, and the operating-characteristic simulation of the certification rule (true margins 0, +5, +10 and +15, plus one cell at −10) is run on the penalised scale as PREREG-v1's freeze gate. It passes when certification is issued at most 5% of the time at margin 0 in every cell, at least 80% of the time at +10 in every cell, and at most 20% of the time at +10 in every cell but one that sits at −10; it sets the final certification sizes. An external reviewer with a veto over scoring is recruited and has reviewed the map, the verdicts and the gates, and PREREG-v1 is frozen and its hash posted. |
| **v1.0 Board** (season 1; Phase 1, targeted alongside the LCM-X v0.30.0 milestone but not gated by it) | the sealed board for G1 and G2: the Text profile, plus the Image profile on its own profile board if S8 and the pilot's validity checks pass (otherwise it joins in season 2; at its planning size of 8 lives × 40 image bundles it publishes cell verdicts and diagnostics, issues no certificate, and runs per system separately from the Text board under the 24-hour rule); each profile's required Act cells, baselines and operating metrics, published before submissions; cell gates from the board's own control arms, run on the pinned reader before any real system; the dated capability census, which annotates cells and never selects them; the seasonal robustness study, with the Learn chains and erasure probes as its terminal forks; at least 3 external competitors; the Claude Code adapter; Ring 1 (fresh seeds at each release and at least monthly) and Ring 2 (a held-out template family with fresh seeds every month); the results table with full stack identity (memory × harness × model, plus the vision provider and spend) and a small crossover panel, whose rows render past turns in the pinned reader's voice, run once per season after the sealed board closes, in its own 24-hour window, and once when a new PREREG version is frozen; the raw-archive marker column; the seal; the results card; **the site and leaderboard** (launch timing is set with the owner) | The season-1 board is published with CIs, cell verdicts, certification on Act per declared profile with its stability (no certificate if a cut leaves the season below the powered size), and the operating metrics. The best system's launch measurement, taken on per-item action accuracy (the highest system figure among real systems on the full-tier board), is published beside the penalised score whatever its value: below about 60% is the disclosed expectation, never a release condition, and the test is not tuned toward it. |
| **v1.x** | a sealed slice for model labs, under a seal-preserving design: the benchmark runs the lab's model inside the sealed runner, with no per-item private results and no traces of private items; community templates (executable templates over synthetic worlds, through the validity gates, entering versioned seasons with bridge anchors); audio and video, following the image loop; the Codex adapter (needs a VM clock); an **AML-compatible adapter**, so a system that already serves the Agent Memory Leaderboard's Add and Search endpoints can run Bicentennial's API-mode slice with no new code (API mode never sets the headline); vendor-submitted configurations (when a submission window opens); IRT dev selection; an evaluation of within-life twins; a measured dev-predicts-full chain | as each lands |
| **v2 World and research tier** | **World profiles**, each admitted only when it exposes a memory question the Text and Image profiles cannot, with Hands scored inside them: **E1**, a robot vacuum in an event-sourced 2D home with partial observation and high-level actions, an event scheduler that compresses idle time, optional body programming (agent-written routines count as memory) and a two-vacuum fleet cell, a candidate from the robotics survey confirmed by an E1 spike before any commitment; then **E2**, a desk arm (SO-101) in MuJoCo, also confirmed by a spike before commitment, with the physical low-cost desk-arm path kept as design only. Board-path engines are Mac-feasible and use commercially usable assets only. **The research tier:** a long-horizon run size of at least 10M tokens, and a continuous-stream item; their design is kept now, and capture waits for measured use (per #1719) | research curves first, reporting simulated span, evidence volume, controller steps and real elapsed time separately; a profile joins the board when its pilot shows it discriminates |
| **Later** | a mobile manipulator and a household helper; longer simulated lives; the full android remains a design target | — |

## How Bicentennial differs from other memory benchmarks
- **The [Agent Memory Leaderboard](https://agentmemoryleaderboard.ai/) (AML) is a competitor.** It runs Textual, Coding and Multimodal tracks:
  - systems expose Add and Search endpoints;
  - a fixed platform pipeline answers the questions;
  - results come in seasonal cycles, with separate open-source and commercial rankings.

  Bicentennial follows AML's conventions where they help entrants: a versioned evaluation contract, and a non-scored smoke run before any full run.
- **The claim Bicentennial has to earn with results:** memory inside a real agent harness across a life, judged on actions, covering governance, with a fast diagnostic loop. To that end it:
  - runs the whole system inside a real agent harness, across a life;
  - injects compactions, crashes and swaps;
  - judges actions by their outcomes in the world;
  - tests governance: forgetting through derived copies, consent and revocation, standing rules;
  - returns a repro bundle for every public failure.
- **What we do not claim:** firstness, multimodal novelty, or a better score than any system before the results exist.

## The site and leaderboard
- **Generated from the results.** The site is static and built from the result cards in the public repository, so no score is ever typed by hand.
- **Pages:**
  - **Board:** per season, one results table. For each system:
    - the full stack identity of the row: memory × harness × model, plus the vision provider and spend;
    - the capability map, track rows × profiles, with cell verdicts (CLEAR, UNRESOLVED or FAIL), cause labels such as "unsupported", and the non-results N/A, N/A_READER and BLOCKED. Remember and Survive are shown as diagnostic stages; Act carries the certification. Flatten's row reads "not yet built";
    - certification on Act per declared profile, with its certification stability;
    - the per-item action accuracy beside the penalised score, and twin consistency;
    - the harmful-actions panel, which is also the violations panel;
    - the baselines of each profile (the no-memory floor, the oracle-evidence ceiling, the full-history oracle ceiling where it fits, and naive RAG) and the raw-archive marker column;
    - operating metrics: latency p50 and p95, added turn latency, store growth, time-to-correct, cost and wall time per run;
    - G1 task completion, beside the scores and outside the headline.

    The memory headline holds the reader and harness fixed. A small predeclared crossover panel shows other models and harnesses. Its rows render past turns in the pinned reader's voice, the same text for every model, and a model from the blind-filter panel's family is excluded from it. Systems whose CIs overlap are shown as tied bands, not as ranks.
  - **Stack view:** model-native memories, on a separately labelled view outside board eligibility. It follows the board's eligibility rules except the open-source rule, and each row is vendor-submitted with a disclosed configuration.
  - **Census:** the dated capability census, from public documentation only, and the "undocumented frontier" labels it puts on cells. The labels never change whether a cell is scored, required or included, and no system's results ever set them.
  - **Robustness:** the seasonal study's fault pass^q, Keep curve, swap comparator and replication family, and its Learn-chain and erasure diagnostics. Each result is labelled with the versions it covered.
  - **Method:** the design, the pre-registration versions with their hashes and changelogs, the firewall statement, and the tuning detector (LCM-X at its last release before the public generator).
  - **For developers:**
    - how to run the Ring 0 packs, the rungs and the fault finder on your own system, with loop time published per tier;
    - how rung results are read: per-rung paired deltas with an A/A′ band and the smallest detectable effect, and a pooled curve shift, never a "highest rung cleared";
    - Ring 1 and Ring 2, and what each returns;
    - the pack catalogue, the repro bundle format and its classes, and guarded autonomous loops.
  - **Contribute:** how to contribute an executable template over a synthetic world, with its validity evidence on controls. Admission never depends on any system failing; a failure reproducer may illustrate a template but never qualifies it. No raw transcripts, corpus text or personal data.
  - **Submit:** how a system joins the board. It needs an open-source, self-hostable system with a Hermes memory plug-in or a documented ingest and query API, and an equal configuration budget. Model-native memories join the stack view instead; model labs use the sealed slice (v1.x).
  - **Roadmap:** this page.
  - **Runs:** every scheduled run, published in order, with its result card and spend. Traces are downloadable for public lives only.
- **Board rules shown on the site:**
  - every system's latest version, never its best;
  - every scheduled run is published;
  - delta boards run only on a new GA, with the previous version re-run alongside;
  - certification is issued only on a sealed board at the pre-registered size: a season board, or a delta board when powered. A season cut below the powered size issues no certificate, and its results are still published;
  - no claim of rank without separation.
- **Gate:** the leaderboard is published only after the v1.0 board exists. Until then the site carries the method, the developer packs and the roadmap.

## Papers
- **The Bicentennial paper, in two steps.** Both are written only from published result cards.
  1. **A preprint after the pilot:** the design, the pre-registration and its versions, and the pilot's validity evidence (filters, audits, known-order ablations, the controls).
  2. **The full paper with the season-1 board:** adding the board, the robustness study and the measured dev-predicts-full chain.
- **Papers about memory systems evaluated on Bicentennial,** LCM-X's among them:
  - they cite only published, sealed board runs;
  - a paper by a system's own maintainers also reports independent benchmarks, so Bicentennial is never the only evidence for a system built alongside it;
  - an LCM-X paper discloses that LCM-X and the benchmark share maintainers. The firewall rules apply unchanged.

## Standing rules
- **Firewall:** the benchmark never advises on LCM-X internals. LCM-X runs under the same rules as every system, and its developers never see held-out seeds, templates or keys. LCM-X improves only through outputs every registered system gets on equal terms: the public packs, Ring 1 results, Ring 2 bits per organisation, and published cards. The benchmark session runs nothing on LCM-X beyond the scheduled runs every system gets.
- **Cell inventory:** frozen per release from the ability taxonomy and the track templates, never from any system's documentation or results. The census only annotates it.
- **Difficulty:** frozen from controls only. No target or veto is set on any system's results, and valid zeros are published.
- **Spend:** reported on every run.
