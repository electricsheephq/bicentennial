# S5: memory-system surfaces (desk survey)

**Question.** For each candidate memory system, which public surfaces does it offer, and what would running it on Bicentennial involve?

This part is a desk survey of public documentation; nothing is installed. Timing each surface (p50 latency) is a later part, S5b, which needs installs.

## Method
For Hermes' native memory, for LCM-X (its public plug-in documentation only), and for open-source memory systems found by search, record:
- licence, and whether it can be self-hosted;
- surfaces: a Hermes memory-provider plug-in, an MCP server, a documented ingest and query API, an Add and Search interface compatible with the Agent Memory Leaderboard;
- its **write tools,** from the vendor's documentation, as candidates for completion slot C-6's declared lists;
- the model calls it makes itself (summariser, extraction, embeddings), and whether it needs local embeddings;
- the state paths it keeps, for snapshots;
- public adoption signals (stars, downloads), each with its source and date. The board's competitors are selected later by the frozen rule in completion slot C-9; this survey only lists candidates.

## Done when
`spikes/s5/REPORT.md` and `spikes/s5/candidates.csv` cover at least 12 candidate systems, every row has its sources, and each row says what an adapter would need.

## Does not prove
- Latency or quality of any system.
- The competitor selection, which follows the C-9 rule on the completion date.
