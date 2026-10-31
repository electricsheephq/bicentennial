# Bicentennial vision

**The question.** Does an agent that lives for months wake up as itself and act on the right memories? Bicentennial asks it across restarts, compactions, crashes, model swaps and long silences, inside the harness the agent really runs in. The name comes from *The Bicentennial Man*, in which an android becomes a person over two hundred years. The benchmark measures the memory that journey needs: first for today's coding and assistant agents, then for agents that see and hear, then for robots that keep a home in mind.

## Agents run it, end to end
No step needs a person (DV48). An agent can generate a life, run its own system through it, read the scores, take the repro bundle for each failure, fix the system and run again. That is how Bicentennial is meant to be used: agents improving their own memory.
- **Gold is computed, never labelled.** Ground truth comes from the generator's world state, so every answer key is derived from the world the life was rendered from.
- **Mechanical checks come first.** A second gold implementation, written from the plain-language world rules, recomputes every answer. Metamorphic relations, contradiction searches and property tests check each template, render round-trips check the text, and scene-graph floors and seeded mutants check the images. The no-memory floor shows that an item needs memory, and the oracle-evidence ceiling shows that it can be answered.
- **Judgements go to agents.** Where a judgement is still needed, panels of agents from different model families make it, and their own recall is measured on planted errors. When they disagree, a pre-registered rule decides (the item is quarantined, dropped or flagged on the card), never a person, and never a model withdrawing a finding after a rebuttal.
- **There are no human graders, annotators or human answer keys.** Every card says "agent-validated; no human key" and carries the validation receipts, and every published table has an agent-key row.
- **Developer loops stay cheap.** Public packs ship with their validation receipts. A life generated locally gets a lite audit from a model family other than the running agent's own, and lite results never feed a board.

## Built to pull the field forward
- Most memory benchmarks ask whether a stored fact can be found again. Bicentennial asks what long-lived agents need next. Their memory has to:
  - survive a life in the agent's own harness;
  - change what the agent does;
  - obey what the agent was told to keep, to forget and never to do;
  - learn from the agent's own attempts.
- **Scores are expected to be low, and many cells are hard on purpose.** Some test capabilities no surveyed system documents yet. Valid zeros are published.
- **A low score still shows where to improve.** Each failure is attributed to the stage that broke: perceived, stored, retained, retrieved or used. Each comes with a repro bundle.
- **No targets.** Difficulty is frozen from controls only, and no target is set on any system's score.

## Fast loops, not one change a day
A developer, or an agent working on its own system, moves through the tiers:
- T0 probe packs run in seconds, and T1 CI smoke in minutes.
- T2 live smoke and T3 dev each take about an hour.
- The fault finder shrinks a failure to a minimal public life.
- Every cell offers rungs, so a developer sees movement before a verdict changes.
- Ring 1 checks that a gain holds on fresh seeds, and Ring 2 checks transfer to a held-out template family.
- The sealed board certifies each season, and a delta board on a new release when it is powered.

## Where it goes
The release plan is in [`ROADMAP.md`](ROADMAP.md).
1. **Text:** coding and assistant agents (the G1 and G2 genres).
2. **Images and screens** (the Image profile), then audio and video.
3. **World profiles:**
   - **E1,** a robot vacuum in a 2D home. It covers partial observation and a two-vacuum fleet, and the routines it writes for itself count as memory.
   - **E2,** a desk arm in simulation.
   - A physical low-cost desk arm stays a design only.
4. **Later:** a mobile manipulator, a household helper, and the full android: months of continuous multimodal life.

A new profile joins only when it exposes a memory question the earlier ones cannot.

## What it will not do
- Claim firstness, or that any system is better, before the results exist.
- Use raw transcripts, corpus text or personal data.
- Tune toward any system. The benchmark is maintained alongside LCM-X, one of the systems it tests, under the firewall in [`README.md`](README.md): it never tunes, patches or advises on LCM-X, and LCM-X's developers never see held-out seeds or keys. A Scoring Veto Panel of agents from outside families reviews every pre-registration freeze for self-serving construction.
