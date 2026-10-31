# PREREG-v0.5 freeze record

| Field | Value |
|---|---|
| Version | PREREG-v0.5, the pilot pre-registration (text) for design v2.3. It supersedes PREREG-v0.4. |
| Frozen at | 2026-10-31T17:53:57Z |
| `prereg/PREREG-v0.5.md` sha256 | `2ee155f881c844a58d0412abe6e400147152b301173dab59ef73bf6d667e490a` |
| `docs/DESIGN.md` (design v2.3) sha256 | `a51638c021a6d411e9219493555358a7df5f74679ea385d29528cac4e3c99fdf` |
| What changed from v0.4 | DV48, agent-only validation, at the owner's direction of 2026-10-31: no person grades, annotates, keys, audits, adjudicates or breaks a tie. Gold is computed from the world state; mechanical checks come first (N-version gold, metamorphic relations, contradiction and property tests, the phrase bank's round-trip check, scene-graph legibility floors, seeded image mutants and an exposure check on every scored bundle); cross-family agent panels from new completion slots handle what is left: the validation families (C-16), the image readers (C-17) and the Scoring Veto Panel (C-18). Interpretive disputes count as errors, a factual dispute clears only when the deterministic checker refutes its premise, and nothing clears because a model withdraws after a rebuttal. The audit's sample sizes and clustered bounds stay, with a recall correction and a false-error bar on the auditor pair together; every published table carries an agent-key row; the feasibility-pilot label is computed from the validation receipts; validation spend has its own capped row. See `prereg/CHANGELOG.md`. |
| Decision record | `docs/DECISIONS-v2.md`, DV1-DV48 |
| Evidence | #311, which lists the human steps DV48 removes |
| Tag | `prereg-v0.5`, on the commit that adds this record's final text. The commit SHA is posted on lcm-x #1964. |
| Approved by | the benchmark session, the product and release owner under the owner's grant of 2026-10-26 |
| Owner co-sign | not required. The owner retired it on 2026-10-26. |
| Completion record | pending: slots C-1 to C-18, in `prereg/PREREG-v0-completion.md`, committed before any real memory system's first pilot run; C-16 to C-18 are filled by their rules in that record |
| External scoring veto | the Scoring Veto Panel (C-18), with a quorum of two families, binding from the first freeze after C-18 is filled; every freeze before that, this one included, keeps design v2.2's interim rule, that every adversarial review tests for self-serving construction; the external human reviewer: waived by the owner in writing on 2026-10-31 ([recorded on lcm-x #1964](https://github.com/electricsheephq/lcm-x/issues/1964#issuecomment-6539072295)), so once its rule binds, the panel holds the veto alone |
| Interim review of this freeze | design v2.2's interim rule. Adversarial reviews tested the candidate for self-serving construction: a fresh-context review by Anthropic's claude-opus-5-5, the authoring family, and one by OpenAI's gpt-6-astra (high); a second-pass review bot also spot-checked the gates. Neither Anthropic nor OpenAI may sit on the Scoring Veto Panel: C-18 excludes Anthropic outright, and OpenAI is in LCM-X's public development record, which the LCM-X lane registry must cover. C-18 is not filled yet, so no panel family has reviewed this freeze |

**Verify** (the files as they are at the tag; a later edit to `docs/DESIGN.md` is a design erratum in `prereg/CHANGELOG.md` and does not move these hashes):

```bash
git show prereg-v0.5:prereg/PREREG-v0.5.md | shasum -a 256
git show prereg-v0.5:docs/DESIGN.md | shasum -a 256
```
