# S6b: the Sol agent lane through the director

**Question.** S6a measured a sustained concurrency of 8 on its model lane, and at 8 one system's full core board does not fit in 24 hours (PREREG-v0.1 §11). Does a second agent lane, `gpt-6.1-sol` on a subscription login held by the director, change that verdict?

S6b is a feasibility and timing measurement. It produces no score for any memory system. Its numbers inform the pinned family's model lane.

## What it builds (spike-grade code, under `spikes/s6b/`)
1. **The director on the Codex Responses wire** (`sol_director.py`, the first PR). It keeps S6a's ledger, budget, classification, write turns and ledger-before-send, and adds credential model C′:
   - Hermes runs its native `openai-codex` provider with a placeholder token, no external-login adoption, an empty `CODEX_HOME`, and its Codex base URL pointing at the director on 127.0.0.1;
   - the director alone reads and refreshes the bench login, replaces the inbound credential, and rebuilds the account headers from the token's claims. No credential, account id or email reaches any log, ledger, commit or PR text;
   - the upstream base URL and token endpoint come from the local environment, never from the repository;
   - an upstream 429 is never passed to Hermes; it is absorbed with backoff, and a usage-limit refusal counts towards the 3-in-a-row stop.
2. **A concurrency ramp on Responses SSE** (`ramp_sol.py`). S6a's ramp, ported: levels 4, 8, 16, 24 and 32, then 48 only if 32 is clean. Each level sends 2 × level tiny requests through that many workers. It stops at once after 3 consecutive quota refusals, checked as results arrive, and on any 401 or 403. A level is sustained when every call was sent and none got a 429.
3. **r7-write.** S6a's full micro-life with write turns and probes, on Sol through the director, with at most 2 Hermes processes.
4. **The projection** (`analyse_sol.py`). S6a's §11 formulas and grid (`spikes/s6a/analyse.py`), at Sol's measured concurrency and latency.

## What it measures
- Sol's sustained concurrency and the shape of any 429 (completion slot C-11 for this lane).
- Write-turn latency (p50, p90, mean), compaction latency, and tokens, each with its sample size.
- r7 against S6a's r6 (GLM, inference parameters forwarded) and r3 (parameters stripped), on the same quantities.
- The §11 fit table at the measured concurrency: job time and lane time, latency ×0.5, ×1 and ×1.5, board sizes n_L of 24, 32 and 48, with and without the §11 cuts, and the number of Hermes processes J needed, with the memory per process.

Every timing records the busy-marker state and the machine's load average.

## Stop conditions
More than 400 upstream calls in all; any 401 or 403 from the upstream or the token endpoint; a refresh that fails or returns no new refresh token; a credential, email or account id in any log, ledger, commit or PR text.

## Done when
Hermes v0.22.2 replays the micro-life with write turns end to end on Sol through the director, every request classified and none unknown, and `spikes/s6b/REPORT.md` gives every measurement above with its sample size and marker state.

## Does not prove
- Anything about any memory system's quality: nothing is scored.
- Latency or limits on other machines, accounts or times of day. One shared machine, one account and one time of day are measured.
- The account's quota windows, which are not published and can change without notice.
