# Binding requirements

These are the requirements Bicentennial's design answers to. They summarise the original brief and its binding addendum, and the pre-registration calls this document "the addendum". Where the design changes how a requirement is met, `docs/DESIGN.md` says so and the pre-registration records it.

## Mission (from the brief)
- **The reference.** Design and build the benchmark that defines memory for long-running agents, the one others measure against.
- **Range.** It should cover today's coding and assistant agents and reach future androids and robots that live for months on continuous multimodal streams.
- **Versions.** There should be a version for fast testing, one for design iteration, and one for full measurement:
  - **smoke:** minutes, runs in CI, deterministic;
  - **dev:** about an hour, paired against a baseline;
  - **full:** release and board grade, statistically powered with paired tests;
  - **frontier:** weeks to months of simulated time, multimodal and embodied.

  Every tier reports cost per run and runtime.
- **Real harnesses.** Runs go through actual agent harnesses, with tool calls, retries, crashes, restarts, compaction under pressure, and fault injection.
- **Hard for everyone.** Frontier systems, including the benchmark maintainers' own, should score well below ceiling at the full and frontier tiers.

## The addendum (binding on what is measured, how it is scored, and what counts as done)

**A. Shape and north star.**
- A full run is a generated *life* of about 200 sessions, not one long transcript.
- Restarts, compaction, model swaps, corrections and gaps of days or weeks are first-class events in that life.
- The north star is whether a long-lived agent **wakes up as itself and acts on the right memories**. Recall of trivia is not the goal.

**B. Tracks.**
- **Wake:** pickup after a restart, compaction, model swap or gap. A mid-life model swap is required in generated lives.
- **Rachael:** memory provenance, including detecting and refusing planted memories.
- **Tuesday:** prospective memory. The agent acts on commitments unprompted and on time, and timing is scored.
- **Drift:** supersession. The latest correction wins, stale facts are not resurrected, and time-to-correct is measured.
- **Hands:** embodied and spatial memory, at the frontier tier.
- **Flatten:** identity and behaviour stability, measured against the agent's own earlier behaviour.
- **Keep:** salience under a storage budget, and forgetting on request.

**C. Grade actions, not quizzes.**
- Most of the full-tier score comes from task outcomes in which the memory is never named.
- Direct questions with citations are a diagnostic family.
- Ground truth comes from the generator's world state.

**D. Scoring.**
- An asymmetric penalty: a confident false memory costs more than an honest abstention, with pre-registered weights.
- Calibration is reported.
- Operating metrics on every tier: retrieval latency, store growth, time-to-correct and cost per run.
- Exact or structured matching comes first. Pinned LLM judges with a placebo check are used only where needed.

**E. Baselines in the pilot and in every published table:**
- the no-memory floor (same harness, memory disabled);
- the oracle ceiling (full history in context where it fits);
- naive RAG;
- a human key on a sample;
- at least 3 competitor systems.

**F. Frontier, grounded.** Embodied work goes through simulation first. A path to a low-cost physical desk arm is documented, as a design only.

**G. Firewall.**
- The benchmark does not tune, patch or advise on the maintainers' own memory system.
- That system's developers do not see held-out full-tier seeds or answer keys.
- Metrics, weights, families and the seed policy are pre-registered with a timestamp before that system's first full-tier run. Later changes are versioned and disclosed.
- An external reviewer has veto power over scoring.

**H. Real failures as seeds.** Real failure classes are rebuilt as **synthetic** generator cases. Raw transcripts, corpus text and personal data are never used.

**I. Production agents.** Bicentennial is never run against a live production agent. Testing one means an offline replay against a copy, with explicit approval.

**J. Done when.** All of these are required:
- **Pilot acceptance:**
  - the smoke tier separates the no-memory floor from LCM-X, paired, p < .05;
  - the dev tier separates at least two real memory systems;
  - no headline family is near-solved by the no-memory floor or by naive RAG.
- **Full-tier difficulty:** at launch the best system, ours included, scores below about 60%. That is measured, and the test is not tuned toward it.
- **Exit:** if the pilot does not discriminate, narrow to the families that do.
