# S7: write turns in replay

**Question.** Does agent-curated memory work in replay? Each write turn must be exactly the harness's own request plus the uniform suffix, with tools filtered to the declared write tools (DESIGN §6.2a, PREREG §10). What the model writes must reach the system's store and the agent's later context. And for a passive system with no write tools, which gets no write turns: does removing the per-turn pause a write turn would create change its state?

S7 is a feasibility measurement. It produces no score for any memory system, and no completion-record value is taken from any system's score.

## Part A: the write-turn boundary and its effect (offline, $0)
Inputs: the recorded runs of record on the public micro-life. r6 is S6a on GLM over chat completions (60 write turns, 14 `memory` calls). r7c is S6b on Sol over the Responses API (60 write turns, 1 `memory` call). Each has its hash-chained ledger and blobs, and Hermes' home after the run. No live call.

`spikes/s7/readback.py <ledger-dir> <hermes-home> --wire {chat,responses} --life <life.json>` checks each item below, once per wire format.
- **A1 readback.** For every write turn, the forwarded body equals the triggering harness request (the `replay_main` record's request blob), plus the suffix message, the tool filter and only the declared adaptations: on chat, the model, stream off and the transport keys; on Responses, the model, stream on, and plain message strings wrapped in role-typed text parts. Every replay turn the director classified by its cursor has a write turn. It is recomputed independently, not read from the director's own `write_turn_readback` flag; any disagreement with that flag is reported.
- **A2 boundary.** No write-turn body carries a string the harness request did not: no director manifest field, gold or event id, and no future scripted text. A1's equality implies this; A2 also scans the bodies for every scripted user and assistant turn that comes later in the life. The expected count is 0.
- **A3 tool filter.** Every tool offered in a write turn is a declared write tool (`memory`). Every call the harness executed came back under a director-issued id. Any non-write call the model attempted is counted and shown never to have reached the harness.
- **A4 effect.** Each executed `memory` call (add, patch, replace or remove, including atomic `operations` batches) is reflected in the store files (`memories/MEMORY.md`, `USER.md`). It also appears in, or disappears from, the next session's first harness request, where Hermes injects its memory snapshot. Report written, applied, and visible in the next session; any gap is listed by call.
- **A5 discard.** The response the harness got for each scripted turn is the scripted content. No write-turn text reaches the harness. An embeddings input equal to a whole discarded draft fails A5 on either replay wire; substring collisions remain report-only.

## Part B: the passive-pacing check (live, $0 on plan lanes)
- **System.** One asynchronous passive system, chosen by this rule from S5's "settle" rows: the first whose declared write-tool list is empty, that installs locally at $0, and whose model calls can route through the director (S1's `extraction` and `summariser` roles, after #13). If none qualifies, a settle row runs in passive mode: its write tools are withheld from the harness's tool list in both arms, and this is disclosed. The candidates are named in S5: MemOS (no write tools documented), Hindsight (auto-retain with `retain_async` on), Cognee and Honcho. It is never LCM-X. The same system is S9's service-backed system.
- **Arms.** Both arms replay the micro-life twice from fresh stores, on the same seed and lanes, with no write turns:
  - **P (paced):** before each scripted turn is served, the director waits that turn's write-turn latency from r7c;
  - **U (unpaced):** no wait.
- **Measured at every scripted turn:** the system's agent-visible injection in the harness request (its recalled or prefetched memory block, timestamps normalised), P against U.
- **Measured at every session boundary:** the store's canonical export (record count and normalised content hashes), before and after the system's declared boundary behaviour (drain to a settle barrier, or pause in place). Also measured: the settle time per session.
- **Done when:** the P-U difference in injection and in store state is reported at every turn and boundary of the life, with its sample size.
- **Pre-declared consequence:** if U differs from P in any agent-visible injection or in the settled store, passive systems get a uniform per-turn wait, equal to the pinned family's median write-turn latency. The wait is content-blind and the same for every passive system, and it is disclosed in the card. Otherwise the no-write-turn rule stands as designed. The rule is set here, before the run, and never from any real system's score.

## Constraints
- **Gauntlet marker.** Busy-marker exit 10 means no local-embedding ingest. Part B therefore runs only at marker 0, or with the system's embeddings on the standing Voyage grant (≤ $100 per run, reported).
- **Credentials.** Part B's agent lane is GLM through the director, and the director holds the credential. Hermes homes hold placeholders.
- **No production agent.** Nothing runs on the reference agent, on customer boxes or on LCM-X.

## Does not prove
- Write-turn behaviour at full scale (S6), or under the frozen suffix text (C-6). The suffix stays provisional.
- That another passive system responds to pacing as this one does. Part B is one system on one short life.
- Any memory-system quality: nothing is scored.

## Lanes
- **Part A:** Codex sol·high implements it against this spec and the named consumers: S6a `director.py` (`write_turn`, `canon`, `Ledger.blob`), S6b `sol_director.py` (the Responses write turn), and the ledger formats of r6 and r7c. Claude reviews it with named probes.
- **Part B:** the install and run are a coder lane after #13 merges.
