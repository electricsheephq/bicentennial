# S4: Claude Code headless against the director

**Question.** Can Claude Code run headless against the director, which forwards to a subscription-lane model, with no subscription token ever forwarded? And which model can serve as model B for the mid-life swap?

## Method
- **Setup:**
  - `claude -p` with stream-json output, in an isolated configuration directory;
  - the API base URL points at the director, and the sandbox holds a placeholder key only. The real upstream key lives only in the director's environment;
  - non-essential traffic is disabled, and the sandbox is localhost-only.
- **Test:**
  - five live turns that use Bash, Read and Edit and one tool from a small local MCP fixture;
  - then `--resume`, `--fork-session` and one compaction.
- **Record:** request fields the upstream rejects (stripped and logged), the context window Claude Code assumes, and its behaviour on a 429.
- **Model B** (completion slot C-2): a model from a family other than A, servable through the director. S4 lists the candidate lanes and the cost of each per board, using S6a's token counts, and proposes one. A paid lane counts inside the board's paid ceiling.

## Done when
`spikes/s4/REPORT.md` shows 5 of 5 valid tool turns, zero egress except through the director, a served compaction, `--resume` and `--fork-session` working, and the model-B candidate table.

## Does not prove
- That every Claude Code feature works through the director: only the ones exercised.
- Any memory system's quality inside Claude Code.
