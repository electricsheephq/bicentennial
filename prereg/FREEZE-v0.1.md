# PREREG-v0.1 freeze record

| Field | Value |
|---|---|
| Version | PREREG-v0.1, the pilot pre-registration (text). It supersedes PREREG-v0, which was never co-signed. |
| Frozen at | 2026-10-26T02:12:21Z |
| `prereg/PREREG-v0.1.md` sha256 | `b9a7459bc3544b53237decfd6384390e738df6ba51443d2576023ceb68953968` |
| `docs/DESIGN.md` (design v1.4) sha256 | `c0cdce7f12c12ca9af7e14af65965f9e960b86932d5d6ff0f7dcc0573dd9a6a4` |
| What changed from v0 | the **24-hour rule**: the full core board for one system, and the seasonal robustness study for one system, must each finish within 24 h of wall-clock time; about 5 assistant turns per scripted session; completion slot C-11 (permitted concurrency, measured in S6a); the failed-pilot fallback is renamed PREREG-v0-narrowed |
| Approved by | the benchmark session, under the owner's grant of 2026-10-26 |
| Owner co-sign | requested on [lcm-x #1964](https://github.com/electricsheephq/lcm-x/issues/1964); its link is added here once given |
| Completion record | pending: slots C-1 to C-11, in `prereg/PREREG-v0-completion.md`, committed before any real memory system's first pilot run |
| External scoring veto | to be recruited before PREREG-v1 |

**Verify:**

```bash
shasum -a 256 prereg/PREREG-v0.1.md docs/DESIGN.md
```
