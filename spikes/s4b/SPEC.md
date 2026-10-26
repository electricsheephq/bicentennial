# S4b: DeepSeek swap-model candidate (build only)

Issue #21; baseline S6a r6 at commit 1e08e7b. C-2 remains a completion-record decision.
Reuse S6a's seed-6101 life (10 sessions, 60 write turns, 2 probe sessions / 4 turns), director,
replay driver, Hermes worker and two-round ramp. S6a source and results remain unchanged.
Every upstream request adds `provider.only=[deepseek]`, `provider.allow_fallbacks=false` and
`usage.include=true`; record these adaptations, served identities, UTC peak window and usage.
Successful responses outside DeepSeek / `deepseek/deepseek-v4.1-flash*` stop with `pin_failure`.
Reserve estimated prompt tokens plus max_tokens (default 32768) at peak input/output prices
before sending. Share the locked spend file across director and ramp; default cap $4, maximum $5.
Settle router cost, else peak-price token cost; uncertain responses keep the full reserved charge.
No GLM pause; retain per-session marker gating, nice 19 and taskpolicy background priority.
Done: both focused suites, zero-network stub life and ramp through 32, ruff and diff checks.
Stub replay simulates tool results; only the orchestrator's real Hermes run proves memory execution.
