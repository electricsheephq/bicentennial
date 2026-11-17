# Project status

**Reconciled on 17 November 2026 (UTC).** Each line below is checked against the repository and its
issues on that date. A line that is older than the newest result it names is out of date: trust the result.

This page reports state only. The plan, what comes next and in what order, is
[ROADMAP.md](../ROADMAP.md): its "Now" section and its release rows are the canonical plan.

## In one sentence

Bicentennial is pre-pilot (the Pilot, the board track's first scored runs, has not started): the
developer kit is released, Milestone 1 and validity rounds 1 and 2 are
published, and the fresh-seed follow-up started its run on 17 November; no board has run and nothing is
certified.

## One line per proof plane

A proof plane is one kind of evidence the project can show. Each line says where that plane stands and
links its newest result or source.

- **Kit tags** (released versions of the developer kit, as git tags): `v0.1`, the kit, released
  1 November, and `v0.2`, the developer loop, released 2 November. Newest result:
  [v0.2 developer loop results](../results/v0.2-dev-loop/README.md).
- **Main** (the default branch, where every merged change lands): at commit `0dabe3c0` on 17 November,
  which is also the follow-up's run commit. Newest change: the follow-up's run tools under
  [results/followup/run](../results/followup/run/README.md).
- **The developer tier** (the tiers a developer runs on their own system: signals, never certificates):
  v0.3, developer tools, and v0.4, search and sensitivity, are paused since 11 November; part of v0.3 has
  landed, and v0.4 has not started. Newest result: the first measured live T2 arm, 4 November, in
  [v0.3 developer tools results](../results/v0.3-dev-tools/README.md).
- **Validity rounds** (control-only runs that check whether a kind of task can rank memory systems at
  all): round 1 published 13 November and round 2 published 14 November, with four ranking candidates.
  Newest result: [round 2's page](../results/validity-2/2026-11-14-control-trials/RESULT.md).
- **Runs of record** (scored runs that are published as results; in the design, the Pilot's bar-1 and
  bar-2 runs): none yet, because the Pilot has not started. The nearest published scored runs are
  Milestone 1, the first run comparing memory systems through one live reader, published 12 November
  as a developer-tier result with no bar ([its page](../results/milestone-1/2026-11-11-separation-table/RESULT.md)),
  and the fresh-seed follow-up, an exploratory run
  ([declaration](../results/followup/DECLARATION.md),
  [#394](https://github.com/electricsheephq/bicentennial/issues/394)): its declaration merged
  15 November, its seed draw and task lists were posted on that issue on 17 November, and its 36 arms
  began that day. Its results have not been read.
- **The sealed board** (the v1.0 Board, season 1: the only run that can certify a system): not started.
  It follows the Pilot, the board-track step after the validity work, whose first bar will not run
  before December. The board has no date until that bar has run. Source: the Pilot and v1.0 Board rows
  of [ROADMAP.md](../ROADMAP.md).

## Rules in force

- **The pre-registration** (the frozen rules every scored run follows):
  [PREREG-v0.5](../prereg/PREREG-v0.5.md), frozen on 31 October 2026 for DV48; its hash is in
  [FREEZE-v0.5](../prereg/FREEZE-v0.5.md) and was posted on
  [lcm-x#1964](https://github.com/electricsheephq/lcm-x/issues/1964). It binds from its freeze and supersedes
  PREREG-v0.4.
- **Agents run the benchmark end to end, with no human graders** (DV48, in [DECISIONS-v2](DECISIONS-v2.md)):
  gold comes from the world state, mechanical checks come first, agent panels from different model families judge
  what is left, and pre-registered rules settle every disagreement.
- **The run-time rule** (DV47): full-tier runs execute in locked, resumable segments from one commit, each
  replaying arm's run of a life finishes within a day, and paid-lane spend is capped at $100 per full-tier run, all
  systems together, unless the owner raises it. The pre-registration holds the full rule.

## What this page does not say

- It does not plan: dates and order of future work are in [ROADMAP.md](../ROADMAP.md).
- It does not restate results: each linked page carries its own numbers and its own limits.
- Developer-tier results are labelled "not predictive of the full tier", and neither they nor exploratory
  results certify a system.
