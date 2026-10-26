# PREREG-v0.4 freeze record

| Field | Value |
|---|---|
| Version | PREREG-v0.4, the pilot pre-registration (text) for design v2.2. It supersedes PREREG-v0.3. |
| Frozen at | 2026-10-26T17:34:35Z |
| `prereg/PREREG-v0.4.md` sha256 | `4db64d3f7787cafb8a673a6d3d6f0fdc335d5f96e4197961cc23889b37d41ab5` |
| `docs/DESIGN.md` (design v2.2) sha256 | `b0903804ccef74eb5b2709aa5ad09deafeb83671d3068beb1216e203c2d4c650` |
| What changed from v0.3 | DV47, the run-time rule, at the owner's direction of 2026-10-26: a full-tier run of record runs in locked, resumable segments instead of one contiguous 24-hour window. Every replaying (arm, life) finishes within 24 h of its first request, each system's lane work fits a work bound in each of its board, study and Image board runs, a paid run is capped at $100 for all systems together, and the control arms and naive RAG run in every life block on the pinned reader, never swapping, with checkpoint-dispatched probes, so each gate comes from the same blocks as the scores judged against it and its probe times sample the roster's own checkpoint times; a report-only anchor shows the swap route. The pilot's runs of record stay contiguous. DV47 also counts the mid-life swap's lane, which DV42's fit left out. See `prereg/CHANGELOG.md`. |
| Decision record | `docs/DECISIONS-v2.md`, DV1-DV47 |
| Evidence | spike S6c: PR #16 (the paced director) and PR #17 (soak 1) |
| Tag | `prereg-v0.4`, on the commit that adds this record's final text. The commit SHA is posted on lcm-x #1964. |
| Approved by | the benchmark session, the product and release owner under the owner's grant of 2026-10-26 |
| Owner co-sign | not required. The owner retired it on 2026-10-26. |
| Completion record | pending: slots C-1 to C-15, in `prereg/PREREG-v0-completion.md`, committed before any real memory system's first pilot run |
| External scoring veto | to be recruited before PREREG-v1 |

**Verify:**

```bash
shasum -a 256 prereg/PREREG-v0.4.md docs/DESIGN.md
```
