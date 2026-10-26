# S7: write turns

**Question.** Do write turns work in replay? Agent-curated memory should be written by the harness's own tools, and each write-turn request should equal the harness's own request plus the uniform suffix and nothing else. Separately: does pausing for write turns change the state of a passive system that ingests asynchronously?

## Method
It extends the director and micro-life from S6a.
- **Readback.** For every write turn in the ledger, the request must equal the harness's own request plus the uniform suffix, compared byte for byte after removing the suffix.
- **The store is used.** On Hermes' native memory, the agent-curated store must be non-empty after the life, and a planted fact that only a write turn could have stored must be retrievable in a probe session. A replay without write turns must not contain it. This is a mechanics check of the write path, not a score.
- **File tools.** An edit outside a system's declared memory or instruction files must be rejected and logged, never executed.
- **Passive pacing.** On one public life, one asynchronous passive memory system from the S5 survey (one that runs at $0 with no local embeddings) is replayed twice: with the per-turn write-turn pause, and without it. The spike compares the stores' contents by a schema-blind span search.

## Done when
`spikes/s7/REPORT.md` shows readback equality on every write turn, the planted-fact check, the file-tool rejection, and the passive-pacing comparison.

## Does not prove
- That any system writes *good* memories: nothing is scored.
- The final write-turn text, which is frozen in completion slot C-6.
