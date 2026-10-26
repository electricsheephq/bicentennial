# Bicentennial

**A benchmark of memory for long-lived agents.** Does an agent wake up as itself and act on the right memories? The test runs across restarts, compaction, model swaps and weeks of silence, inside the harness the agent really runs in, and nobody asks it what it remembers.

A full run is a generated *life* of about 200 sessions in one evolving world. The headline comes from what the agent **does** in later sessions, checked against the world's state. Questions with citations stay as diagnostics. A confident false memory costs more than an honest "I don't remember".

> **Status: pre-pilot.**
> - Design v1.4 is done.
> - **PREREG-v0.1 was frozen on 2026-10-26.** The hash is in [`prereg/FREEZE-v0.1.md`](prereg/FREEZE-v0.1.md) and posted on [lcm-x #1964](https://github.com/electricsheephq/lcm-x/issues/1964).
> - **The 24-hour rule:** the hardest run, the full board for one system, finishes within a day.
> - Spikes S1-S7 are under way.
> - There is no benchmark code and there are no results yet.

## Tracks

| Track | What it measures |
|---|---|
| **Wake** | After a restart, compaction, model swap or long gap, the agent picks up its open loops, commitments, preferences and conventions |
| **Rachael** | Provenance: which memories were observed, told, inferred or planted, and refusing false ones |
| **Tuesday** | Acting on earlier commitments unprompted and on time, without falling for lures |
| **Drift** | The newest correction wins, history stays answerable, and nothing stale resurfaces |
| **Keep** | What is retained under a storage budget, and real forgetting on request |
| **Flatten** | Staying itself under pressure (a diagnostic until it can be measured against each agent's own behaviour) |
| **Hands** | Embodied and spatial memory (frontier tier, simulation first) |

## Two ladders

**For developers** of memory systems and agent harnesses. These tiers carry no pass/fail bar, and none is presented as predicting the full tier until that has been measured.

| Tier | Time | What you get |
|---|---|---|
| T0 probe packs | seconds | per-ability micro-tests, with no model calls |
| T1 CI smoke | minutes | a deterministic merge gate with a regression corpus |
| T2 live smoke, T3 dev | about an hour | a paired diff against your own previous version, with its uncertainty |
| Fault finder | about 15 + 15 minutes | a failure shrunk to a minimal public life, with a one-command repro |

Every failure is attributed to the stage that broke: stored, survived, retrieved or used.

**For measurement:**
- runs of record for the pilot bars;
- a sealed full core board once per season;
- a seasonal robustness study: fault reruns, the storage-budget curve, a model-swap comparator, and a second agent family.

## Documents
- [`docs/DESIGN.md`](docs/DESIGN.md): the design (v1.4).
- [`prereg/PREREG-v0.1.md`](prereg/PREREG-v0.1.md): the pre-registration (the superseded v0 is kept beside it). It is the only normative source for frozen quantities.
- [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md): the binding requirements the design answers to.
- [`docs/REVIEW-SUMMARY.md`](docs/REVIEW-SUMMARY.md): the adversarial reviews and what they changed.
- [`docs/genres/`](docs/genres/): the life generators, G1 software partner and G2 personal assistant.
- [`ROADMAP.md`](ROADMAP.md): releases, the site and the leaderboard.
- [`spikes/`](spikes/): the feasibility spikes that come before the build.

## Credibility rules
- The pre-registration is frozen before any real memory system's first pilot run. Every later change is versioned and disclosed.
- Full-tier seeds and answer keys are held out and sealed.
- The benchmark is maintained alongside [LCM-X](https://github.com/electricsheephq/lcm-x), a memory system that will be one of the systems tested. Firewall rules apply:
  - the benchmark never tunes, patches or advises on LCM-X;
  - LCM-X's developers never see held-out seeds or keys;
  - LCM-X at its last release before the public generator runs on every board, to detect tuning to the public lives;
  - LCM-X gets the same configuration budget as every other system.
- An external reviewer with a veto over scoring is recruited before the full-tier pre-registration.

## Licence
- **Code:** Apache-2.0 ([`LICENSE`](LICENSE)).
- **Documents and public lives:** CC-BY-4.0 ([`LICENSE-DATA`](LICENSE-DATA)).
- See [`NOTICE`](NOTICE) and [`CANARY`](CANARY).
