# PREREG-v0 freeze record

| Field | Value |
|---|---|
| Version | PREREG-v0, the pilot pre-registration (text) |
| Frozen at | 2026-10-26T01:54:50Z |
| `prereg/PREREG-v0.md` sha256 | `c942ba9d130a2c0c65091a3d2925fca0db7f2d136030ea55d71045ef809cc818` |
| `docs/DESIGN.md` (design v1.3) sha256 | `8e0cd70c83c28dff80ce5de4b6cd97175612506c51c0c6f26f04ff63b8de929d` |
| Approved by | the benchmark session, under the owner's grant of 2026-10-26 |
| Owner co-sign | requested on [lcm-x #1964](https://github.com/electricsheephq/lcm-x/issues/1964); its link is added here once given |
| Completion record | pending: slots C-1 to C-10, in `prereg/PREREG-v0-completion.md`, committed before any real memory system's first pilot run |
| External scoring veto | to be recruited before PREREG-v1 |

**Verify:**

```bash
shasum -a 256 prereg/PREREG-v0.md docs/DESIGN.md
```

The frozen text never changes in place. A correction makes a new version, recorded in `prereg/CHANGELOG.md`.
