# PREREG-v0.5 freeze record

| Field | Value |
|---|---|
| Version | PREREG-v0.5, the pilot pre-registration (text) for design v2.3. It supersedes PREREG-v0.4 once frozen; until then PREREG-v0.4 binds. |
| Frozen at | pending (set at freeze, after review) |
| `prereg/PREREG-v0.5.md` sha256 | pending (set at freeze, after review) |
| `docs/DESIGN.md` (design v2.3) sha256 | pending (set at freeze, after review) |
| What changed from v0.4 | DV48, agent-only validation, at the owner's direction of 2026-10-31: no person grades, annotates, keys, audits, adjudicates or breaks a tie. Gold is computed from the world state; mechanical checks come first (N-version gold, metamorphic relations, contradiction and property tests, the phrase bank's round-trip check, scene-graph legibility floors, seeded image mutants and an exposure check on every scored bundle); cross-family agent panels from new completion slots handle what is left: the validation families (C-16), the image readers (C-17) and the Scoring Veto Panel (C-18). Interpretive disputes count as errors, a factual dispute clears only when the deterministic checker refutes its premise, and nothing clears because a model withdraws after a rebuttal. The audit's sample sizes and clustered bounds stay, with a recall correction and a false-error bar on the auditor pair together; every published table carries an agent-key row; the feasibility-pilot label is computed from the validation receipts; validation spend has its own capped row. See `prereg/CHANGELOG.md`. |
| Decision record | `docs/DECISIONS-v2.md`, DV1-DV48 |
| Evidence | #311, which lists the human steps DV48 removes |
| Tag | `prereg-v0.5`: pending (set at freeze, after review), on the commit that adds this record's final text. The commit SHA is posted on lcm-x #1964. |
| Approved by | the benchmark session, the product and release owner under the owner's grant of 2026-10-26 |
| Owner co-sign | not required. The owner retired it on 2026-10-26. |
| Completion record | pending: slots C-1 to C-18, in `prereg/PREREG-v0-completion.md`, committed before any real memory system's first pilot run; C-16 to C-18 are filled by their rules in that record |
| External scoring veto | the Scoring Veto Panel (C-18), with a quorum of two families, binding from the first freeze after C-18 is filled; this freeze keeps design v2.2's interim rule, that every adversarial review tests for self-serving construction; the owner's waiver of the external human reviewer: asked 2026-10-31, pending |

**Verify:**

```bash
shasum -a 256 prereg/PREREG-v0.5.md docs/DESIGN.md
```
