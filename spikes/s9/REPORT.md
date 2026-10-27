# S9: pause invisibility

**Claim class: advisory, live at $0 on public lives.**

## Claim

pending: Part B

## Setup

| Field | Value |
|---|---|
| Harness pin | pending: Part B |
| Lane and model | pending: Part B |
| Accounts A and B | pending: Part B |
| Arms and lives | pending: Part B |
| Pause lengths | pending: Part B |
| Marker readings and niceness | pending: Part B |

## Results

### B1

| Arm | Boundaries | Proofs equal | U digest = P digest | Unknown | Non-loopback |
|---|---|---|---|---|---|
| hermes-native | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B |
| mem0-oss | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B |
| wiped | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B |
| no-memory | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B |

### B2

| Arm | Boundaries n | Proofs equal | Unsettled | Changed roots | Declared matches | Drift | Holds | Sends |
|---|---|---|---|---|---|---|---|---|
| hermes-native | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B |
| mem0-oss | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B |
| wiped | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B |
| no-memory | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B | pending: Part B |

Mem0 execution: not_run until #120. Service-backed pause invisibility: not shown.

### B3

| Items | Sent | Carried | Verdict |
|---|---|---|---|
| pending: Part B | pending: Part B | pending: Part B | pending: Part B |

### B4

| Field | Value |
|---|---|
| pause_after | pending: Part B |
| holds_compaction | pending: Part B |
| summariser_before | pending: Part B |
| wait_s | pending: Part B |
| equal | pending: Part B |
| changed | pending: Part B |
| resumed_ok | pending: Part B |
| resumed_total | pending: Part B |
| post_resume.tries | pending: Part B |
| post_resume.forwarded | pending: Part B |
| post_resume.refused | pending: Part B |
| post_resume.credential_stop | pending: Part B |
| dropped_items | pending: Part B |
| encrypted_bodies | pending: Part B |
| drift | pending: Part B |
| account_switched | pending: Part B |
| Spare account | not run (deferred); pending: Part B |

Spare-account acceptance and the first-full-tier prerequisite remain pending.
Same-account success cannot complete them. Without a qualifying compaction, B4 reads BLOCKED.

## Spend and guards

| Settled µ$ | Refused | Sends | Scan hits |
|---|---|---|---|
| pending: Part B | pending: Part B | pending: Part B | pending: Part B |

## Decisions taken

- Declared surfaces retain manifest exclusions; additional roots have none.
- Config and plug-in config remain hashed, with comparisons inside one adapter.
- Interpret the micro-life's empty probes as filtering the input projection;
  the validated script schema has no `probes` property.
- No placeholder auth installation; custom-provider config holds no login.
- Each micro and canary execution has its own record id and output path.
- A guard constructor and bridge promotion for later live tiers are follow-ups.

## Consequences (pre-declared)

Unequal or unsettled arms pause only between lives. Unshown service-backed
evidence does not establish mid-life pauses. One account per arm and life holds
until the spare-account acceptance is met. Canary failure gives controls their
own accounts.

## Does not prove

Cross-process resume; pauses other than those measured; other service-backed
systems; Mem0 under stubbed extraction and embeddings; encrypted reasoning state
(dropped by v0.1's director); a spare account if deferred; full-scale lives;
environment state; account-dependent serving after quota moves (PREREG §11);
the restore path; any memory quality.
