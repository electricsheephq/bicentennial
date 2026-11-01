# Bicentennial roadmap

Bicentennial is its own product, with its own repository, releases and site. Its versions are independent of LCM-X's.

**What it is for.** Today's memory benchmarks mostly ask whether a stored fact can be found again. Bicentennial asks what long-lived agents will need next:
- whether an agent's memory survives a life inside its own harness: restarts, compactions, crashes, model swaps and long gaps;
- whether it changes what the agent *does*;
- whether it obeys what the agent was told to keep, forget and never do;
- whether it learns from the agent's own attempts.

Many cells are hard on purpose. Some test capabilities that no surveyed system documents yet, and carry the label "undocumented frontier". The label is display only and never decides whether a cell is required: the season-1 frontier cells are diagnostics because of where they sit (Learn, the erasure probes, attestation, the conditional Image board, and the Survive stage for standing rules after compaction and a swap), and a zero there is published like any other result. Difficulty is frozen from controls only, and no target is set on any system's scores. Every cell's developer pack offers rungs, so a developer can measure movement below the board's lever values before a cell's verdict changes.

## Releases

From v0.2 the roadmap runs two tracks.
- **Developer releases** ship the tiers and tools a developer runs on their own system. They never certify, and they never wait for the board track.
- **The board track** validates the measurement ladder in the pilot and freezes PREREG-v1. It gates only the v1.0 Board.

Older documents say "v0.2" for work that is now split across v0.2, v0.3 and the Pilot. The rows below are authoritative.

| Release | What ships | Done when |
|---|---|---|
| **v0.1 Kit** (the first weeks after approval) | the public repository; generator core with the G1 and G2 genres; scorer; director; Hermes adapter; spikes S1-S9, with S6a first and S9 before the first full-tier run; **Ring 0 developer packs for the Remember, Survive and Act stages: T0 probe packs and T1 CI smoke** | T0 and T1 run on Hermes native memory and two external systems. T1 is deterministic on stable fields, and the wiped-store positive control fails it. |
| **v0.2 Developer loop** (about a week after v0.1; re-planned 2026-11-01) | **T1 for every registered system on its own lanes**, LCM-X included, which its maintainers run after their own registry change; **T2-lite**, a developer live smoke on T1's lives: only the probe answers come from the live pinned model, while write turns, compaction, extraction and embeddings stay scripted, so the store at each checkpoint equals T1's. QA answers are scored by the pinned scorer, G1 actions by the action scorer, and G2 actions are not scored live yet; **a per-item flip list** against the developer's own baseline, with a rerun command and a repeat count; **T1's loop time** measured per arm and, since it misses its budget by more than 2×, cut in RING0 §6's order: the probe budget first, then B1's full replay. A flip is a developer signal: a fix is confirmed on Ring 1 (v0.3) before it is claimed | T2-lite runs Hermes native live on the pinned model twice (A and A′), and publishes each card with its flip list, q₀, loop time, requests and spend. Offline tests show a planted flip reproduced by its rerun command every time, a live-upstream failure recorded as infrastructure and never as the system's, and LCM-X refused under the benchmark's operator identity. The developer guide covers T2-lite, and its offline path runs in the fresh-clone CI job. T1's per-arm loop time is published with its breakdown. T1 stays deterministic on stable fields, checked by one A/A′ pair per reference system run in parallel. |
| **v0.3 Developer tools** (about two weeks after v0.2) | **repro bundles with their declared class** (snapshot-probe, replay-from-schedule or live) and a `bicentennial repro` command; **the fault finder**; **the developer report**, with the diff against your previous version, its MDE and an A/A′ band; **Ring 1** (fresh seeds of the public templates); **T2 live smoke** at its PREREG size (about 10 public lives × 8-10 sessions); **T3 dev**; **rungs per cell**, as new template versions whose rung values are taken before any real system runs on them (C-7); action predicates that score a live G2 action by meaning; the T0 Hermes-replay fallback | **The developer-product acceptance bar** (PREREG §8): the benchmark team, acting as developer of its own baseline (naive RAG or the raw-archive marker), takes one real-stack public failure, reproduces it from its bundle, fixes it and confirms it on Ring 1, within the declared T2/T3 budgets; no contestant system is involved, and LCM-X is not. |
| **Pilot** (board track, alongside the developer releases; a 3-week timebox from its first run of record, re-planned after S6 and S8) | the **Image profile** in Ring 0 once spike S8 admits it; the first **Learn** chains (bounded and terminal; a diagnostic); Ring 0's item filters; the calibration set; the bar-1 and bar-2 runs of record; the pilot report. Where a pilot bar needs a developer tier's runner, it runs that runner on fresh seeds as a run of record; the developer tier itself carries no bar. Bars 1 and 2 use the T2 and T3 runners, so their runs of record, and the timebox that starts with them, follow v0.3 | Pilot bars 1-5 pass and bar 6 is measured. A failed bar follows PREREG §8: the failed-pilot fallback when the companion or bar 2 fails, a reported finding escalated to the owner when only bar 1's main test fails, and the redesign, remedy or cut order with a fresh acceptance run when bar 3, 4 or 5 fails. The variance inputs are measured on the bar-2 control arms with one A/A′ rerun, and the operating-characteristic simulation of the certification rule (true margins 0, +5, +10 and +15, plus one cell at −10) is run on the penalised scale as PREREG-v1's freeze gate. It passes when certification is issued at most 5% of the time at margin 0 in every cell, at least 80% of the time at +10 in every cell, and at most 20% of the time at +10 in every cell but one that sits at −10; it sets the final certification sizes. The agent-validation gates pass (PREREG §5, §8): the validation families and image readers filled by rule (C-16, C-17), a passing phrase-bank receipt, the template census, the pilot instance audit with its plant minimums and its procedure-recall, false-error and AUC bars, judge validation, and for Image claims the legibility and verifier gates; otherwise the pilot is labelled a feasibility pilot. The Scoring Veto Panel (C-18) has reviewed the map, the verdicts and the gates on PREREG-v1's candidate hash, with no blocking finding left uncleared; the panel holds the veto alone, since the owner waived the external human reviewer on 2026-10-31. PREREG-v1 is frozen and its hash posted. |
| **v1.0 Board** (season 1; Phase 1, targeted alongside the LCM-X v0.30.0 milestone but not gated by it) | the sealed board for G1 and G2: the Text profile, plus the Image profile on its own profile board if S8 and the pilot's validity checks pass (otherwise it joins in season 2; at its planning size of 8 lives × 40 image bundles it publishes cell verdicts and diagnostics, issues no certificate, and runs per system separately from the Text board under the run-time rule); each profile's required Act cells, baselines and operating metrics, published before submissions; cell gates from the board's own control arms, run on the pinned reader in the same blocks as the real systems; the dated capability census, which annotates cells and never selects them; the seasonal robustness study, with the Learn chains and erasure probes as its terminal forks; at least 3 external competitors; the Claude Code adapter; Ring 2 (a held-out template family with fresh seeds every month), beside Ring 1, which starts in v0.3 and runs at each release and at least monthly; the results table with full stack identity (memory × harness × model, plus the vision provider and spend) and a small crossover panel, whose rows render past turns in the pinned reader's voice, run once per season after the sealed board closes, in its own window, and once when a new PREREG version is frozen; the raw-archive marker column; the seal; the results card; **the site and leaderboard** (launch timing is set with the owner) | The season-1 board is published with CIs, cell verdicts, certification on Act per declared profile with its stability (no certificate if a cut leaves the season below the powered size), and the operating metrics. The best system's launch measurement, taken on per-item action accuracy (the highest system figure among real systems on the full-tier board), is published beside the penalised score whatever its value: below about 60% is the disclosed expectation, never a release condition, and the test is not tuned toward it. |
| **v1.x** | a sealed slice for model labs, under a seal-preserving design: the benchmark runs the lab's model inside the sealed runner, with no per-item private results and no traces of private items; community templates (executable templates over synthetic worlds, through the validity gates, entering versioned seasons with bridge anchors); audio and video, following the image loop; the Codex adapter (needs a VM clock); an **AML-compatible adapter**, so a system that already serves the Agent Memory Leaderboard's Add and Search endpoints can run Bicentennial's API-mode slice with no new code (API mode never sets the headline); vendor-submitted configurations (when a submission window opens); IRT dev selection; an evaluation of within-life twins; a measured dev-predicts-full chain | as each lands |
| **v2 World and research tier** | **World profiles**, each admitted only when it exposes a memory question the Text and Image profiles cannot, with Hands scored inside them: **E1**, a robot vacuum in an event-sourced 2D home with partial observation and high-level actions, an event scheduler that compresses idle time, optional body programming (agent-written routines count as memory) and a two-vacuum fleet cell, a candidate from the robotics survey confirmed by an E1 spike before any commitment; then **E2**, a desk arm (SO-101) in MuJoCo, also confirmed by a spike before commitment, with the physical low-cost desk-arm path kept as design only. Board-path engines are Mac-feasible and use commercially usable assets only. **The research tier:** a long-horizon run size of at least 10M tokens, and a continuous-stream item; their design is kept now, and capture waits for measured use (per #1719) | research curves first, reporting simulated span, evidence volume, controller steps and real elapsed time separately; a profile joins the board when its pilot shows it discriminates |
| **Later** | a mobile manipulator and a household helper; longer simulated lives; the full android remains a design target | — |

**Act in the v0.1 Kit.** T0 and T1 run with no model. Their Act results are the scripted reader's evidence-conditioned actions, executed and scored by the real action scorer. They are labelled "evidence-conditioned scripted action; not an Act judgement", because a scripted policy measures whether the evidence was available, not what a model does with it. The Act stage proper starts with the live tiers: for G1 in v0.2's T2-lite, and for G2 in v0.3, once its action predicates score a live action by meaning (`specs/ring0/RING0.md` §3; `docs/ERRATA-v2.2.md` E12). At T2-lite a G1 action is the live model's decision over a store built from scripted write turns, and its card says which roles were live.

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
