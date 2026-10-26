# PREREG-v0.2 freeze record

| Field | Value |
|---|---|
| Version | PREREG-v0.2, the pilot pre-registration (text) for design v2.0. It supersedes PREREG-v0.1, which was never co-signed. |
| Frozen at | 2026-10-26T06:46:27Z |
| `prereg/PREREG-v0.2.md` sha256 | `453113d4757258dce5efc94934b8fc0eacc5de5a88ecbc252703b1da8d0caac9` |
| `docs/DESIGN.md` (design v2.0) sha256 | `b9b3e6d171a5332358d65d99419805a2e4e9ca014e956395d38590b38ef49a6b` |
| What changed from v0.1 | design v2.0's capability map; certification on Act only; developer rings; the Image profile; per-item action accuracy; failure attribution by cause; the five amendments; the 24-hour rule sized on the pinned family's lane (see `prereg/CHANGELOG.md`) |
| Decision record | `docs/DECISIONS-v2.md`, DV1-DV46 (DV42 reserved: the pinned family's model lane, set after spike S6b) |
| Approved by | the owner, on 2026-10-26 |
| Owner co-sign | requested on [lcm-x #1964](https://github.com/electricsheephq/lcm-x/issues/1964); its link is added here once given |
| Completion record | pending: slots C-1 to C-15, in `prereg/PREREG-v0-completion.md`, committed before any real memory system's first pilot run |
| External scoring veto | to be recruited before PREREG-v1 |

**Verify:**

```bash
shasum -a 256 prereg/PREREG-v0.2.md docs/DESIGN.md
```
