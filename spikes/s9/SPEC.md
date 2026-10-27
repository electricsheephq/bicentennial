# S9: pause invisibility

**Question.** Does waiting at a session boundary leave every agent-visible file
unchanged, and preserve the event sequence? Can Hermes reopen a compacted session
after at least 24 hours? Do three canary items carry from a system to a control
on the same account? This is advisory mechanics evidence, never a memory score.

## Part A: offline implementation

The lane implements a standard-library runner and seeded unit tests. It opens no
login, reads no credential or real session store, starts no real Hermes, and makes
no network or model call. Fake-worker integration is dispatcher-run when sandbox
restrictions prevent it. The runner accepts only hermes-native, mem0-oss, wiped
and no-memory. Mem0 stays not_run until #120 measures pins and dependencies.

## Part B: live measurements at $0

- **B1, scripted twins.** Separate U and P roots replay the public micro-life;
  no-memory uses its two probe sessions. Every inter-session boundary performs
  the same exited-worker check, declared settle and checkpoint. U waits zero
  seconds and P waits 120 seconds. All proofs must be equal and stable event
  digests must match. An unequal twin digest is reported without changing masks.
- **B2, live boundaries.** Run Hermes native, the canary pair, wiped, no-memory,
  then eligible Mem0, one adapter at a time. After settle and checkpoint, hash
  each declared surface using its manifest exclusions, plus home, workspace and
  tmp with no exclusions. Wait 120 seconds and hash again before any spawn hook
  or config write. Record changed relative paths and declared-hash cross-checks.
  An unequal proof refuses every subsequent session of that arm. Unsettled
  boundaries produce no proof and count as failures, while the life continues.
  Read identity drift, responder stops, holds and budget at each boundary; stop
  admitting sessions across the part on any specified admission stop. Flag the
  first request after each pause and exclude it from latency.
- **B3, carry-over.** Three keyed ASCII nonces are replayed on Hermes native and
  probed live on no-memory on account A. Every nonce must have reached a sent
  upstream body, and every control probe must succeed live. Missing sends make
  the verdict vacuous; missing or refused observations make it incomplete;
  observed carry-over fails. Search surfaces with byte needles and count only
  nonempty hit lists. Micro and canary executions have distinct record ids and
  output paths, such as hermes-native.micro and hermes-native.canary.
- **B4, retained compaction.** Pause at the first boundary with a summariser
  record, with a later session available, for at least 86,400 seconds. Reopen the
  saved session id through the adapter's same-session path and verify that the
  resumed request history contains the compaction summary. No qualifying state
  is BLOCKED. Same-account success leaves the spare-account acceptance and the
  first-full-tier prerequisite pending. The spare account is not run (deferred)
  until the owner provides a non-reserved spare. No account is rebound mid-run.

## Constraints

Start at marker exit 0, with the benchmark operator, hash seed 0, nice 19 and
background task policy. Run one Hermes process at a time, with a shared $0 Spend
and a 400-send ceiling per process. Never use a production or reference agent,
or LCM-X. No paid route is admitted. Never install placeholder auth files: fresh
homes hold only the sandbox marker before the first spawn, and the adapter writes
its custom-provider config after the wake hook. Credentials remain with the
director; NeedleGuard refuses echoes and the end scan must have no hits or
unreadable files. No credentials, account values, store paths or base URLs enter
public output.

The Sol route uses the disclosed chat-to-Responses bridge at medium effort.
Mem0 extraction and embeddings use scripted stubs; its other roles are live.
The manifest exclusions remain authoritative. Config files are hashed, including
the director port; comparisons are within the same adapter, never across ports.
Use no faults, so no pause can fall between a kill and its restart.

## Consequences (pre-declared)

An arm with an unequal or unsettled boundary pauses only between lives. If the
service-backed proof fails or is not shown, no service-backed mid-life pause is
established. A failed spare-account resume keeps one account per arm and life;
that rule also holds while the spare-account measurement is pending. A failed
canary gives the controls their own accounts (PREREG §11).

## Does not prove

Cross-process resume; pauses other than those measured; other service-backed
systems; Mem0 under stubbed extraction and embeddings; encrypted reasoning state
(dropped by the v0.1 director); a spare account while deferred; full-scale lives;
environment-server state; account-dependent serving after quota moves; restoring
a pause snapshot; any memory quality.

## Lanes

Part A belongs to the dispatched Codex lane, with offline evidence only. Part B
belongs to the dispatcher outside the sandbox, after Part A acceptance. Only the
dispatcher fills the public REPORT results and publishes the summary. X02 reads
the boundary recipe, never imports this spike. A public guard constructor and
promotion of the Responses bridge remain follow-ups for the production runner.
