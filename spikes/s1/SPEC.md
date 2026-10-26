# S1: request roles

**Question.** Can the director tell a harness's own requests apart (the main turn, compaction, summariser, extraction and title calls) reliably enough that a run fails closed instead of mis-serving one?

## Method
It extends the director from S6a.
- **The rule,** applied in order:
  1. **Cursor match:** on the scripted turn, or on a call id the director issued.
  2. **Model alias,** where the harness lets the run name the model: Hermes' main and auxiliary models, a system's documented summary model, Claude Code's small and fast alias.
  3. **Shape signature,** for whatever is left. It is confirmed after the fact from harness markers: Claude Code's compaction boundary, Codex's compacted rollout items.
  4. **Anything else is unknown.** The cell fails closed.
- **Hermes:** the S6a micro-life's recorded sessions, plus one fresh run with a forced compaction.
- **Claude Code:** 30 turns with inflated reported usage, plus `/compact`, in an isolated configuration with a placeholder key (shared with S4).
- **Codex:** `codex exec --json` in an isolated home, with a provider entry pointing at the director (Responses wire) and a low auto-compact limit. The director serves scripted and stub responses, so no upstream model is needed. No subscription login is used.

## Done when
`spikes/s1/REPORT.md` shows every recorded request classified, with zero compaction false negatives and zero false positives, states whether Codex compacts locally or remotely, pins each harness version, and adds a shape test that CI can run.

## Does not prove
- Stability across harness versions: each new version re-runs the shape test.
- Anything about a memory system's quality.
