# Feasibility spikes

The spikes de-risk the build before the pilot. They run at $0 on subscription lanes, under `nice`, and they never touch a production agent. Each spike lives in its own directory with a `REPORT.md` that gives the claim, the evidence, and what the result does **not** prove.

Spikes measure mechanics, cost, timing and harness overhead. None produces a score for any memory system, and no completion-record value (PREREG-v0, slots C-1 to C-10) is taken from any system's score.

| Spike | Question | Done when | Status |
|---|---|---|---|
| **S1** request roles | Can the director, a model-API proxy, tell the harness's own requests apart: the main turn, compaction, summariser, extraction and title calls? It tries cursor match first, then model alias, then shape signature, and fails closed on anything unknown. | Every request in a recorded Hermes session is classified correctly, and an unknown shape is refused | not started |
| **S2** clocks | Can each harness run on simulated time? Hermes uses an in-process time shim. Claude Code uses its Node build with a preloaded `Date` shim. The fallback is director-side date rewriting with disclosure. | A 3-day simulated gap is seen consistently by the harness and its memory plug-in, with no wall-time guard tripped | not started |
| **S3** clones | One copy-on-write store clone per probe item, including parallel per-worker sandbox roots instead of serial placement | Clone time and isolation are measured, and probe throughput per hour is measured at 1, 4 and 8 workers | not started |
| **S4** Claude Code | Can Claude Code run headless against the director, which forwards to a subscription-lane model? A subscription token is never forwarded. Model B for the swap is also named here (completion slot C-2). | A scripted 5-turn session completes through the director, with every request classified | not started |
| **S5** surfaces | What are the entry points of each memory system's public surface (plug-in, MCP, API), and how long do they take to run? | A per-system table of ingest, query and compaction entry points with p50 latency | not started |
| **S6a** micro-life | One 10-session micro-life on Hermes' native memory | Replay time, write-turn and summariser calls, probe latency, sustained lane concurrency, harness overhead (for slot C-5), and bundles per short life are measured | not started |
| **S6** full-scale life | One full-scale life of about 200 sessions on Hermes' native memory and one extraction competitor, uncapped and at the 10% cap. A dense ~2M-token life and the same seed at ~5M. | Every cost term is measured by role, and pilot bar 5's projection can be computed | not started |
| **S7** write turns | Agent-curated memory works in replay. Each write-turn request equals the harness's own request plus the uniform suffix, checked by readback. A passive-pacing check is included. | The readback matches on every write turn, and the passive-pacing effect is measured on one public life | not started |
