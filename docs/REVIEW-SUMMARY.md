# Review summary

Design v1 went through several independent adversarial reviews before PREREG-v0 was frozen. Reviewers came from two model families. Every finding received one terminal disposition: fixed, refuted, accepted trade-off, or deferred with a reason. Status posts on [lcm-x #1964](https://github.com/electricsheephq/lcm-x/issues/1964) tracked each step.

| Step | Reviewers | Findings | Result |
|---|---|---|---|
| Round 1 | an OpenAI-family reviewer, plus a six-lens red-team (validity and shortcuts, ground truth, harness realism, statistics, cost and feasibility, self-serving design), with a skeptic re-checking each serious finding | 98 findings in 56 clusters, 6 blocking | every one dispositioned; design v1.1 |
| Round 2 | a targeted readback | 8 new | all fixed; design v1.2 |
| Round 3 | a readback plus a consistency panel | 5 blocking | all fixed; the pre-registration became the only normative source |
| Closure check | two independent checkers, blocking items only, with skeptic votes | 6 confirmed, 3 refuted | all confirmed items fixed |
| First-principles cost review | seven analysis lanes, a blind second opinion from the other model family, and a three-lens red-team (statistics, harness realism, firewall) | 21 decisions | design v1.3 |
| v1.3 readback and closure | an OpenAI-family reviewer | 8 blocking, then 1 regression | all fixed |

## What the reviews changed most
- **Fairness to agent-curated memory.** In *write turns*, the pinned model may call each system's own memory-write tools during the scripted history. Systems that declare no write tools get no write turns, because there the call could change nothing.
- **Scoring that cannot be gamed:**
  - action items score +1 if correct by any route, 0 for abstaining or asking, and −1 for acting on a false, stale or planted memory;
  - each action item is a matched twin pair scored by its minimum;
  - simple shortcut policies must score ≤ 0 on every track before a freeze.
- **Memory the world cannot give back.** The headline counts only items whose answer is not in mail, tickets or code history.
- **Honest statistics.** Tests are life-level sign-flip tests. The confirmatory family tests each system against one neutral reference. The dev bar's family excludes LCM-X, so LCM-X's results cannot loosen the neutral check.
- **A cost that fits.**
  - **Before:** design v1.2 would have needed about 320 whole-life replays per system, several times over its own ceiling.
  - **What v1.3 changed:** it splits a core board from a seasonal robustness study, and fast developer tiers (seconds to about an hour) from the runs of record.
- **Firewall.** The pre-registration freezes before the pilot. Pilot-derived values are computed without LCM-X's data. A pre-public LCM-X release runs on every board as a tuning detector.

## Proposals the reviews overturned
- **Twins inside one life, instead of a forked twin life.** Rejected as the default: a confident prior could pass both items. It is deferred to a later version, after a controls-only comparison.
- **Sequential stopping.** Dropped: with shared lives it saves little, and estimates from stopping early are biased upward.
- **A storage-budget score that would have rewarded systems unable to cap their store.** Replaced with one that matches the old score at both extremes.
