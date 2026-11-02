# Reading T1's loop-time results: the measurement, and the A/B of a shorter wait

This is the guide to v0.2's measurement of T1's loop time: how long one T1 run takes, arm by arm, and where the time goes. It also covers the A/B run of the first proposed cut, which failed its bar and does not ship. The numbers are in `RESULT.md`, each printed from the runs' own receipts with the field it comes from.

Claim class: timing measurement of T1 on one dedicated host, idle, at two commits, with a same-host card-equivalence check of the second. It is not a loaded measurement, it does not give the loop time on a developer's machine, it is not predictive of the full tier, and it never certifies.

## Why it is measured

T1 is the CI smoke tier: two public lives of 20 sessions each, replayed through the real Hermes harness with a scripted model, plus the regression corpus and a wiped-store control. Its engineering budget is 10 minutes and $0, which is not a bar (PREREG §6). RING0 §6 says loop time is measured and published, idle and busy, and that a miss is disclosed. It also says that if T1 misses its budget by more than 2×, v0.2 cuts the probe budget first, then B1's full replay. The measurement supports a different order ([#267](https://github.com/electricsheephq/bicentennial/issues/267#issuecomment-6571255757)): first the costs that change nothing on T1's cards. The first such cut failed its A/B, below, so the roadmap moves the cut to v0.3, and RING0 §6 changes with the cut that ships.

It misses by far more than 2×. On this host, a T1 run takes about 61-62 minutes for Hermes native and Holographic, and about 85 minutes for Mem0 OSS: 6 to 8.5 times the budget.

## What ran

- **Host:** one dedicated 16-vCPU Linux bench host with nothing else scheduled. The kit and every worker ran at the lowest CPU and I/O priority.
- **Layout:** three chains at once, one per reference system (Hermes native, Holographic, Mem0 OSS). Each chain ran a base run and then a repeat (run1), and the kit compared run1's cards with base's. So each system also gives one determinism pair.
- **The measurement:** main at `c9bf10b`.
- **The A/B:** `047832c` ([#377](https://github.com/electricsheephq/bicentennial/pull/377)). It waits 1 s instead of 3 s after each ordinary turn, checked every 0.25 s instead of every 0.5 s. The wait at each session's end, and the wait after a turn that a scheduled kill or restart follows, stay at 3 s. It ran on the same host, after the measurement. The only other code change between the two commits is in T2-lite's runner, which T1 does not use.
- **Pack:** both built the same T1 pack (`094e7512…`).
- **Egress:** the host's allowlisting proxy is the only route out for the runs' user, and the runs ran with it unset. Its log shows no connection during either set, and the kit's egress sampler recorded no failed sample in any receipt.

## What the numbers measure

- **W** is one run's wall time, from its receipt. Within a run, the arms run one after another (the no-memory floor, the system, the wiped control), and the two branches of an arm (B0 and B1) run side by side.
- **An arm's loop time** sums, over the two lives, the slower branch's time.
- **Outside the arms** is the rest of W: the compile check before the arms, the regression corpus after them, preparation and publication. These steps are not timed separately yet.
- **The critical path** adds, per arm and life, the slower branch's timers: the waits after turns and at session ends, the scripted turns, opening each session, spawning the worker (imports included) and closing it.

## The measurement

- **Per run:** W is 3,664-3,728 s for Hermes native and Holographic, and about 5,090 s for Mem0 OSS. The no-memory arm takes about 122 s, and the system and wiped arms about 1,290-1,300 s each (about 1,500 s for Mem0 OSS).
- **The largest single cost is waiting.** After every scripted turn, the harness waits until nothing has been in flight at the director for 3 s, so that background requests (titles, reviews) finish before the next turn. Those waits add 1,290 s on the critical path for Hermes native and Holographic, 35% of W, and 1,500 s for Mem0 OSS, 29-30%. The waits at session ends add another 330 s.
- **Outside the arms:** 26-39% of W. It is not broken down yet, because its timers go into the receipt, and the receipt code is inside the controls pin: they ship with the next batch of changes that moves packs.
- **Determinism:** each system's repeat gave the same cards as its base run, apart from the base run's gate verdict, which differs by design.

## The A/B of a shorter wait

- **The time it saved:** 849-876 s per run for Hermes native and Holographic (23-24%), and 942-990 s for Mem0 OSS (19%), close to the predictions (about 860 s, or 23%, for the first two, and about 18% for Mem0 OSS).
- **Its own repeat:** within the A/B, each system's repeat again matched its base. On this host, the shorter wait gave the same cards twice.
- **Its bar:** the cut was to ship only if its cards equalled the measurement's for all three systems, apart from the four commit pins.
- **The result:** 0 of 12 cards match. Apart from the four commit pins, each differs in one field only, the masked ledger digest. Scores, items, verdicts and every other card field are identical, and so are the request counts and the token counts per role in the receipts.
- **What the masked ledger digest is:** a hash over the stable fields of every request the director served, including the turn it was filed under and hashes of the masked request and reply. It changes when a request moves to another turn or when the masked content of any request or reply changes.
- **The likeliest cause:** some background requests that Hermes starts after more than 1 s with nothing in flight now arrive after the next turn has started, so the director files them under that turn. With the 3 s wait, they arrived before it. This is inferred, not observed: each run's request ledger is deleted with its sandbox, and the receipts do not yet count late-starting requests.
- **One alternative was ruled out.** The two sets ran from checkout folders with different names, and the open part of [#282](https://github.com/electricsheephq/bicentennial/issues/282#issuecomment-6548982874) says the checkout path still reaches a few worker values: its argv, `PYTHONPATH` and the MCP server's command. These sets' ledgers were deleted, so a unit of a separate run at the A/B's commit was searched instead. In 293 of its decompressed request bodies, the fixed sandbox root appeared in 272, and the checkout and run folder names in none.
- **Why the cut does not ship, even with equal scores:** the cut's own bar failed. And if the inferred cause is right, background work with the shorter wait races the next turn instead of finishing before it. It would then have raced the same way in both of this host's runs, but on a slower or busier host, or for another system, it could race differently from run to run, and T1 must not depend on timing. So the cut is not merged, and v0.2 ships the measurement without a cut.
- **What comes next** ([#378](https://github.com/electricsheephq/bicentennial/issues/378)): first, every T1 receipt counts the background requests that reach the director after the next turn has started. Then, from those counts, a decision on whether the timer should give way to a wait that ends when the worker's background threads have finished and nothing is in flight, which would keep the request order by construction. Another option is a cut that changes no per-turn timing.

## What the results do not show

- **One host, idle.** A loaded run, and a run on a developer's own machine, can take longer. v0.2's determinism check on the release commit runs once idle and once under load, and publishes both runs' wall times.
- **Not the cause directly.** The A/B shows that the shorter wait changes the request ledger. Which requests move, and to which turn, is inferred.
- **Not the time outside the arms.** It is measured as one remainder and is not broken down yet.
- **Card equality is not store equality.** Comparing every card field catches anything a late request changes on the cards. It does not prove that the checkpoint stores are byte-identical, and a late request that changes nothing on the cards leaves no trace.

## Files

`RESULT.md` holds the verdict lines, the tables, the card comparison and each run's card and receipt sha256. The full run trees (cards, receipts, logs and load samples) are in the benchmark's private evidence store, tag `bicentennial/t1-loop-time-20261102`.
