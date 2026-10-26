# S6a: a micro-life on Hermes' native memory

**Question.** How long do the mechanics of one life take, and can the hardest run (the full core board for one system) finish within 24 hours of wall clock, as PREREG-v0.1 §11 requires?

S6a is a feasibility measurement. It produces no score for any memory system, and no completion-record value is taken from any system's score.

## What it builds (spike-grade code, under `spikes/s6a/`)
1. **A minimal director.** A local HTTP proxy that speaks OpenAI chat completions, the wire Hermes uses for a custom provider. For every request it:
   - classifies the role: `replay_main`, `write_turn`, `summariser`, `probe_main`, `aux` or `unknown`. An unknown request fails closed: it is refused and logged;
   - serves scripted assistant turns locally, matched by cursor to the life script;
   - forwards live roles to an upstream model named only by environment variables;
   - drops any incoming `Authorization` header, sets its own upstream credentials, and never writes a credential to any log or ledger;
   - appends one record per request to a hash-chained JSONL ledger, with request and response bodies stored by content hash, and timing and reported usage per call.
2. **A synthetic micro-life.** 10 sessions in the G1 software-partner genre, about 5 assistant turns each, written from templates. It contains no real transcripts and no personal data. It includes at least:
   - six facts told early and needed later;
   - one correction, where the newest value must win;
   - one commitment due in a later session;
   - one restart wake, and one long gap;
   - one session long enough to force compaction at the window used.
3. **A replay driver.** It runs the life through a real, pinned Hermes (v0.22.2) with Hermes' native memory (its built-in memory tool and session search), in an isolated Hermes home with no other memory plug-in enabled. Each session is a fresh Hermes session. Auxiliary calls (titles, compression) are routed to the director too, so nothing leaves the machine except director-forwarded calls.
4. **Write turns** (PREREG §10). Before each scripted assistant turn is served, the director runs a write turn: the harness's own request plus a uniform suffix, served by the live model, whose memory-tool calls Hermes really executes. The suffix text is provisional and labelled so; it is frozen later in completion slot C-6.
5. **Probes.** A few probe sessions after the life, with the live model as the agent. They measure probe latency only; nothing is scored.
6. **A concurrency ramp** on the agent's model lane. It sends short, bounded requests at concurrency 1, 2, 4, 8 and 16 (24 only if 16 is clean), and stops at the first sustained refusal. It records which limit binds: concurrency, request rate, or a usage quota.
7. **Parallel roots.** Two replays of the life run at once in separate homes, to check isolation and measure the slowdown.

## What it measures
- Replay wall time per session: scripted only (harness overhead), and with write turns.
- Write turns: model calls per turn, latency per call, tokens in and out.
- Summariser and compaction calls: count, latency, tokens.
- Probe latency.
- **Harness fixed overhead** (system prompt plus tool schemas), in tokens on the measurement model. It is the input to completion slot C-5's rule: the smallest of 16K, 24K, 32K, 48K and 64K that is at least twice this overhead.
- **Sustained concurrency** of the model lane and the binding limit. It is the input to completion slot C-11.
- **Bundles a short life can host:** the distinct (fact, probe point) pairs where the fact was told at least two sessions before the probe.
- **The 24-hour projection.** Using PREREG §11's formulas, it gives each life's sequential critical path (its write-turn chain) and the total work divided by the measured concurrency, for the full board and the robustness study of one system. It states whether each fits in 24 h, and if not, the concurrency that would.

Every timing records the machine's load at the time it was taken.

## Done when
`spikes/s6a/REPORT.md` gives every measurement above with its sample size, the projection, and the verdict on the 24-hour rule, and the micro-life replays end to end through real Hermes with every request classified and none unknown.

## Does not prove
- Anything about any memory system's quality: nothing is scored.
- Latency at other times of day, on other machines or on other model lanes. The model lane is shared, and so is the machine.
- That a generated life behaves like the micro-life. The generator does not exist yet; S6 measures a full-scale life.
- Simulated time: S6a runs on wall time. S2 covers clocks.
- The final write-turn text (C-6) or the measurement model (C-1).
