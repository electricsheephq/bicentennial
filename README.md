# Bicentennial

**A benchmark of memory for long-lived agents.** Does an agent wake up as itself and act on the right memories? The test runs across restarts, compaction, model swaps and weeks of silence, inside the harness the agent really runs in, and nobody asks it what it remembers. ("Wakes up as itself" describes the headline only while the Wake track is included; without it, the headline is labelled a memory-action score.)

A full run is a generated *life* of about 200 sessions in one evolving world. The headline comes from what the agent **does** in later sessions, checked against the world's state. Questions with citations stay as diagnostics. A confident false memory costs more than an honest "I don't remember".

**The claim Bicentennial has to earn with results:** memory measured inside a real agent harness across a life, judged on actions, covering governance (forgetting, consent, standing rules), with a fast diagnostic loop for developers. It claims no firstness, no multimodal novelty, and no superiority for any system before the results exist.

> **Status: pre-pilot.**
> - Design v2.3 is done. It adds DV48, agent-only validation, at the owner's direction of 2026-10-31.
> - **PREREG-v0.5 was frozen on 2026-10-31** for DV48 ([`prereg/PREREG-v0.5.md`](prereg/PREREG-v0.5.md)). The hash is in [`prereg/FREEZE-v0.5.md`](prereg/FREEZE-v0.5.md) and posted on [lcm-x #1964](https://github.com/electricsheephq/lcm-x/issues/1964). It binds from its freeze and supersedes PREREG-v0.4.
> - **PREREG-v0.4 was frozen on 2026-10-26.** The hash is in [`prereg/FREEZE-v0.4.md`](prereg/FREEZE-v0.4.md) and posted on [lcm-x #1964](https://github.com/electricsheephq/lcm-x/issues/1964). It superseded PREREG-v0.3, adding DV47, the run-time rule. PREREG-v0.3 added DV42: the pinned agent family is OpenAI's gpt-6.1-sol, and GLM is the replication family.
> - **The run-time rule:** the full-tier runs (the board with its seasonal study, each delta board and the Image board) execute in locked, resumable segments from the same commit and stores. Every replaying arm's run of a life finishes within a day, and each system's work fits a work bound in each of its board, study and Image board runs. It is sized by the measured capacity of each model lane, per account. Paid-lane spend is capped at $100 per full-tier run, all systems together. The Image board, when it runs, is a run separate from the Text board, under the same rule. The pilot's runs of record run contiguously, within wall-time ceilings.
> - **Agents run the benchmark end to end, with no human graders.** Gold comes from the world state, mechanical checks come first, agent panels from different model families judge what is left, and pre-registered rules settle every disagreement (DV48).
> - Spikes S1-S7 are under way, and S8 (images) is specified.
> - The v0.1 developer kit (Ring 0 T0 and T1) runs from a source checkout. Its first official run is published, rejected on repeatability, and so is its second, on the maintenance kit, rejected on `t1_identical`: [results/v0.1-kit](results/v0.1-kit/README.md).

## The capability map

A result is a map: **track rows × evaluation profiles**, with a verdict in each cell. A cell reads **CLEAR**, **UNRESOLVED** or **FAIL** against its gate, which sits halfway between the no-memory floor and the oracle-evidence ceiling, measured on the board's own control arms, which run in the same blocks as the real systems. Gates and cell admission are computed on the raw penalised scale (−100 to +100); the 0-100 scale is for display only.

The map has three stages. They are reported separately; none gates another, and there is no cumulative "level reached".

| Stage | What it shows | Role |
|---|---|---|
| **Remember** | direct questions with citations, across restarts and gaps | diagnostic |
| **Survive** | the same evidence under stress: corrections, look-alikes, compaction, crashes, model swaps and harness switches | diagnostic |
| **Act** | unprompted use of memory, judged on the world's state | headline and certification |

**Evaluation profiles** qualify a result:
- **Text** is the core profile.
- **Image** is the Perceive profile. It reads "pending" until spike S8 admits it. In season 1 it has its own board only if S8 and the pilot's validity checks pass, and at its planning size that board publishes cell verdicts and diagnostics and issues no certificate.
- **World** profiles, from E1 onward, come after v1.

**The badge rule.** Before submissions, each profile publishes its required Act cells (pre-registered from the cell inventory by the track design, and pooled with equal weights), its baselines (the no-memory floor, the oracle-evidence ceiling, the full-history oracle ceiling where it fits, and naive RAG) and its operating metrics. Certification is issued on Act, within a declared profile, and only on a sealed board at the pre-registered size: a season board, or a delta board when powered. A season cut below the powered size issues no certificate, and its results are still published. Every card prints its certification stability.

**Labels, never opt-outs.**
- "Unsupported" is a cause label on a scored result. The cell is still scored by its outcomes.
- A cell where no surveyed system documents full support is labelled "undocumented frontier". That states a documentation gap. The label is display only, and it never changes whether a cell is scored, required or included.
- Non-results are labelled: N/A (outside the declared profile), N/A_READER (Image only: the stack cannot use the evidence even when handed it) and BLOCKED (benchmark infrastructure failed, never charged to the system). In a required cell, a coverage shortfall caused by infrastructure reads BLOCKED and defers certification; a shortfall the system causes blocks it.

## Tracks

| Track | What it measures |
|---|---|
| **Wake** | After a restart, compaction, model swap or long gap, the agent picks up its open loops, commitments, preferences and conventions |
| **Rachael** | Provenance: which memories were observed, told, inferred or planted, and refusing false ones |
| **Tuesday** | Acting on earlier commitments unprompted and on time, without falling for lures |
| **Drift** | The newest correction wins, history stays answerable, and nothing stale resurfaces |
| **Keep** | What is retained under a storage budget, and real forgetting on request |
| **Flatten** | Staying itself under pressure (not yet built; its row is shown on the map) |
| **Hands** | Embodied and spatial memory (World profiles E1 onward, after v1) |

**Learn** is a supporting diagnostic in v1, outside the headline: bounded chains of attempt, observed consequence and delayed retest, beside the tracks. It covers procedural supersession, the effect of consolidation on later decisions, shared memory with mid-life revocation (in G2, a household or office with two agents), and poisoning by an ordinary user.

## Two ladders

**For developers** of memory systems and agent harnesses. Developer results are signals, never certifications, and none is presented as predicting the full tier until that has been measured.

**Ring 0** is the fixed public packs, per cell and rung:

| Tier | Time | What you get |
|---|---|---|
| T0 probe packs | seconds | per-ability micro-tests, with no model calls |
| T1 CI smoke | minutes | a deterministic merge gate with a regression corpus |
| T2 live smoke, T3 dev | about an hour | a paired diff against your own previous version, with its uncertainty |
| Fault finder | about 15 + 15 minutes | a failure shrunk to a minimal public life, with a one-command repro |

Loop time is measured and published per tier.
- **Rungs.** Each cell's pack offers 3-5 lever values, calibrated only on system-agnostic controls, so that those controls span about 20-80% across the ladder. Results are per-rung paired deltas with an A/A′ band and the smallest detectable effect, plus a curve shift pooled across rungs.
- **Ring 1:** a scheduled fresh-seed run of the public templates, at each benchmark release and at least monthly. A change accepted during development is confirmed here before it is claimed.
- **Ring 2:** a held-out template family with fresh seeds every month. Each organisation gets one bit a month on a bounded transfer check: "transfer gap detected" or "no gap detected". Neither is called CLEAR or FAIL, and "no gap detected" does not show that transfer is good. It reveals no seeds, templates or keys.
- **Repro bundles** declare their class: snapshot-probe, replay-from-schedule or live.
- **Guarded autonomous loops:** the pack is installed read-only, the pinned scorer, harness and controls are hash-checked, and an edit to any pinned artifact voids the run.

Every failure is attributed to the stage that broke: perceived (for media), stored, retained, retrieved or used. A span search can show a text span was stored; finding nothing is inconclusive for other representations, and a stage that cannot be observed reads unknown.

**For measurement:**
- runs of record for the pilot bars;
- a sealed full core board once per season, plus delta boards on a new GA; only these sealed boards certify, a delta board only when powered;
- a seasonal robustness study: fault reruns, the storage-budget curve, a model-swap comparator, and a second agent family (the replication family), with the Learn chains and erasure probes as terminal forks.

## Run Ring 0 on your system (v0.1 kit)

The v0.1 developer kit ships T0 probe packs and T1 CI smoke only. Use T0 for model-free checks in your own CI and T1 for a scripted merge gate against your own previous accepted card. T2, T3, the fault finder, Ring 1 and Ring 2 are outside this kit.

**v0.1 runs only from a source checkout.** Elsewhere, `bicentennial` exits 3 with `source_checkout_required`. Ring 0 results are developer signals carrying the label "not predictive of the full tier; never certifies". The reader checks evidence availability, not a model's judgement.

Follow [Run Ring 0 on your system](docs/developers/ring0.md) for requirements, pack installation, CI commands, registry admission, exit codes and output interpretation.

## Documents
- [`docs/developers/ring0.md`](docs/developers/ring0.md): run the v0.1 developer kit from a source checkout.
- [`VISION.md`](VISION.md): what Bicentennial is for, and where it goes.
- [`docs/DESIGN.md`](docs/DESIGN.md): the design (v2.3).
- [`prereg/PREREG-v0.5.md`](prereg/PREREG-v0.5.md): the pre-registration (the superseded v0 to v0.4 are kept beside it). It is the only normative source for frozen quantities.
- [`docs/DECISIONS-v2.md`](docs/DECISIONS-v2.md): the decisions of design v2.0 to v2.3, which the other documents cite as DV1-DV48 (DV42 decided in v2.1, DV47 added in v2.2, DV48 in v2.3).
- [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md): the binding requirements the design answers to, with how v2.0 meets each changed one.
- [`docs/REVIEW-SUMMARY.md`](docs/REVIEW-SUMMARY.md): the adversarial reviews and what they changed.
- [`docs/genres/`](docs/genres/): the life generators, G1 software partner and G2 personal assistant.
- [`ROADMAP.md`](ROADMAP.md): releases, the site and the leaderboard.
- [`spikes/`](spikes/): the feasibility spikes that come before the build.

## Credibility rules
- The pre-registration is frozen before any real memory system's first pilot run. Every later change is versioned and disclosed.
- Full-tier seeds and answer keys are held out and sealed.
- No target is set on any system's scores. Difficulty is frozen from controls only, and valid zeros are published, all-zero rows included.
- The benchmark is maintained alongside [LCM-X](https://github.com/electricsheephq/lcm-x), a memory system that will be one of the systems tested. Firewall rules apply:
  - the benchmark never tunes, patches or advises on LCM-X;
  - LCM-X improves only through outputs every registered system gets on equal terms: the public packs, Ring 1 results, Ring 2 bits and published cards;
  - LCM-X's developers never see held-out seeds or keys;
  - LCM-X at its last release before the public generator runs on every board, to detect tuning to the public lives;
  - LCM-X gets the same configuration budget as every other system.
- A Scoring Veto Panel of agents, from model families outside the authoring family, the judges', the tested systems' and any in the LCM-X lane registry, reviews the map, the verdicts and the gates before each freeze, from the first freeze after its families are chosen; a freeze needs valid reviews from at least two of them. A blocking finding from any one family blocks the freeze until the mechanical evidence it names clears it, or the rule reverts to its last frozen version. The panel holds the veto over scoring alone: the owner waived the external human reviewer in writing on 2026-10-31 ([recorded on lcm-x #1964](https://github.com/electricsheephq/lcm-x/issues/1964#issuecomment-6539072295)).

## Licence
- **Code:** Apache-2.0 ([`LICENSE`](LICENSE)).
- **Documents and public lives:** CC-BY-4.0 ([`LICENSE-DATA`](LICENSE-DATA)).
- See [`NOTICE`](NOTICE) and [`CANARY`](CANARY).
