# PREREG-v0.2 freeze record

**Superseded** by PREREG-v0.3 (`prereg/FREEZE-v0.3.md`) on 2026-10-26. This record is kept unchanged below.

| Field | Value |
|---|---|
| Version | PREREG-v0.2, the pilot pre-registration (text) for design v2.0. It supersedes PREREG-v0.1, which was never co-signed. |
| Frozen at | 2026-10-26T07:05:40Z |
| `prereg/PREREG-v0.2.md` sha256 | `b2940d58bace1e1a4f5314e48cd49ec98eb430e7efc2a4f706af61c90ef886ba` |
| `docs/DESIGN.md` (design v2.0) sha256 | `af005de755dbb84d52a88dccf34399b6521b08ebc8976d1082d016c83b92f9de` |
| What changed from v0.1 | design v2.0's capability map; certification on Act only; developer rings; the Image profile; per-item action accuracy; failure attribution by cause; the five amendments; the 24-hour rule sized on the pinned family's lane (see `prereg/CHANGELOG.md`) |
| Decision record | `docs/DECISIONS-v2.md`, DV1-DV46 (DV42 reserved: the pinned family's model lane, set after spike S6b) |
| Tag | `prereg-v0.2`, on the commit that adds this record's final text; the commit SHA is posted on lcm-x #1964 |
| Approved by | the owner, on 2026-10-26 (design v2.0 and this freeze). The benchmark session froze it under the owner's grant. |
| Owner co-sign | not required. On 2026-10-26 the owner made the benchmark session the product and release owner, deciding freezes on data-backed alignment without co-signs. PREREG-v0.2 binds from its freeze. |
| Completion record | pending: slots C-1 to C-15, in `prereg/PREREG-v0-completion.md`, committed before any real memory system's first pilot run |
| External scoring veto | to be recruited before PREREG-v1 |

**Verify:**

```bash
shasum -a 256 prereg/PREREG-v0.2.md docs/DESIGN.md
```
