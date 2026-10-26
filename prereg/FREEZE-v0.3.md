# PREREG-v0.3 freeze record

| Field | Value |
|---|---|
| Version | PREREG-v0.3, the pilot pre-registration (text) for design v2.1. It supersedes PREREG-v0.2. |
| Frozen at | 2026-10-26T10:46:20Z |
| `prereg/PREREG-v0.3.md` sha256 | `298915674f127c124d89cdb873394abb76f678b2a2996e2ce07d61a0fe296e6a` |
| `docs/DESIGN.md` (design v2.1) sha256 | `3244f3d507626f951bffc0ce4133d5d00bf380b88aed6af210b57b3906011fc3` |
| What changed from v0.2 | DV42, the pinned agent family (OpenAI, with GLM as the replication family and the swap model), decided after spike S6b. Its consequences are the blind panel (Anthropic, Zhipu and one paid third family), C-11 as sustainable capacity per account with its fit rule and director pacing, and a generic tuning disclosure. The owner co-sign is removed. See `prereg/CHANGELOG.md`. |
| Decision record | `docs/DECISIONS-v2.md`, DV1-DV46, with DV42 decided |
| Evidence | spike S6b: PR #8 (the director) and PR #9 (the measurements) |
| Tag | `prereg-v0.3`, on the commit that adds this record's final text. The commit SHA is posted on lcm-x #1964. |
| Approved by | the benchmark session, the product and release owner under the owner's grant of 2026-10-26 |
| Owner co-sign | not required. The owner retired it on 2026-10-26. |
| Completion record | pending: slots C-1 to C-15, in `prereg/PREREG-v0-completion.md`, committed before any real memory system's first pilot run |
| External scoring veto | to be recruited before PREREG-v1 |

**Verify:**

```bash
shasum -a 256 prereg/PREREG-v0.3.md docs/DESIGN.md
```
