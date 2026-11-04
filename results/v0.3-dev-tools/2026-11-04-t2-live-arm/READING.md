# Reading the first measured live T2 arm (#391)

This is the guide to v0.3's first full-size live T2 run. It says how long one T2 arm takes on Hermes's own memory, against the 1-hour target per arm, and what the run scored. The lines and tables are in [`RESULT.md`](RESULT.md), each printed from the run's own files.

Claim class: one live T2 run of Hermes native on the public T2 pack, on a shared developer Mac, with the runner in macOS's background band. It is a timing and smoke measurement, not a comparison of systems. It is not predictive of the full tier, and it never certifies.

## Why it is measured

T2 is the developer loop's full-size tier: 10 public lives, 5 software-partner lives (G1) and 5 personal-assistant lives (G2). Each runs on both branches against the live model. PREREG §6 sets its budget at 1 hour per arm for the 10 lives, against cached controls (RING0 §14.8).

An arm's time is how long its own units would take alone on the run's parallel slots, plus the run's time when no unit runs. The no-memory floor counts in no arm's time.

Until this run, no T2 arm had been measured at full size, and the T2 guide said so. RING0 §14.8 also says what follows from the measurement: if T2's first measured arm shows the target cannot be met, the bar is re-planned before the declaration. A budget is never re-declared.

## What ran

- **Commit:** `ac81423`, which is `main` at #472 (`f7238b2`) plus the fix for #476, which has since landed on `main` as #480. The first attempt ran at 11:04Z on `ca74302` (`main` before #472, which changes only CI files). It stopped at 11:34Z, when the live act stage rebuilt T2's own act templates from the catalogue (#476), and it wrote no card.
- **Pack:** T2 `15141b194ab8abf389af2bfdbb4fd81e4d511fca14c54508d613fbe156628c04`, byte-equal to the 11-03 build: 85 items in 10 lives, 20 units per arm (a unit is one branch of one life).
- **System:** Hermes native, at the registry's pinned Hermes (v0.22.2, `systems/registry/hermes-native.toml`). The no-memory floor ran live beside it, because its cache was empty.
- **Live model:** the pinned `gpt-6.1-sol` at effort `medium`, through the benchmark's own model login, with a send bound of 1,000.
- **Machine:** a Mac mini (M4 Pro: 10 performance and 4 efficiency cores, 64 GB), shared with another project's work (see "What else ran"). The runner re-executes itself under `nice 19` and `taskpolicy -b`, and starts every Hermes worker the same way, so it yields to everything else on the machine. The guard admitted 8 parallel slots, T2's maximum.
- **Command:** the one in the T2 guide, with these values: `bicentennial t2 --system hermes-native ... --max-sends 1000 --cache <floor cache>`.

## What else ran on the machine

- Before the start, the benchmark's own test processes had stopped (at 12:40Z). The start script, which is in the evidence bundle, starts the run only when the machine's busy marker reads idle. The runner itself was not given the marker command, so its receipt holds no marker readings.
- The other project's release work, as it stated: at most one focused test run of a file or two at a time, at `nice 10`; one read-only code-review lane; and merges whose CI ran on GitHub. Its timed jobs were asleep until 16:00Z.
- The benchmark's own maintainer session ran no test processes and no code-writing lanes. From 12:46Z and from 12:55Z it ran two read-only review jobs, which read one checkout with git, grep and sed. It also edited files and read and posted on GitHub.

## What the results show

1. **The arm missed the 1 h target.** The system arm's time is 96.2 min (1.60 h): 95.9 min for the replay of its 20 units on 8 slots, and 0.3 min of the run's time outside its units. The run took 110.2 min from start to end. The floor's own replay, which counts in no arm's time, was 26.8 min. The runner's recomputation from `units.json` equals the stored arm time, and the monotonic and wall clocks agree.
2. **Most of the time was local work, not the model.** Each system unit that ran once took 29-36 min, about three times the runner's own prediction (577-675 s per unit, from T2-lite's receipts). Two units took a second attempt, after infrastructure failures, and ran 45.5 and 65.5 min with both attempts.
   - The director's requests add up to 104 of the 868 summed unit-minutes (12%). The live model's probe answers are 76 of those minutes.
   - The rest is the harness's local work: Hermes starting and running each session, the 3 s wait after each turn, a store copy before each probe, and scoring.
3. **The leading explanation is oversubscription: eight units at once in the runner's background band.** Apple says the system may place background work on the efficiency cores. Independent tests report that the background band keeps it there even when performance cores are idle; those tests used an earlier chip. This Mac has 4 efficiency cores of 14. The runner's prediction comes from T2-lite, which runs in the same band but one unit at a time. Here, all 8 slots were busy for the whole of every system unit's span. Each unit is a Hermes worker with up to 4 background threads alive at a turn start, and the director and scoring run beside them.
   - On this Mac, a single-thread Python loop took 0.82 s at the default priority and 4.6-6.0 s at the runner's priority. Two test runs in the same band were going at the time (1-minute load about 5), so the slower figure includes their contention.
   - The load averages when the run ended were 6.5, 12.7 and 14.6 (1, 5 and 15 minutes).
   - This is a hypothesis until a run at another slot count tests it. Whether T2's sessions also do more work than T2-lite's is not yet separated.
4. **What follows.** Under RING0 §14.8, the bar is re-planned before the declaration, and the 1 h budget stays. #478 holds the re-plan, in this order:
   - the scaling probe: the system arm at 4 slots, one per efficiency core, run as #391's A/A′ pair so it is measured twice. It reuses this run's floor from the cache, so no floor unit runs beside it, as in this run's first 65.7 min. To meet 1 h at 4 slots, units must run near their prediction: this run's unit times, replayed on 4 slots, give 189 min;
   - then #391's pre-declared cuts: the loop-time cut at T2, then B1's replay at T2 only, then the probe budget.
5. **The live act stage worked.** All 70 action items ran from the pack's sealed cases, the stage that stopped the first attempt (#476). The 40 G1 actions were scored. The 30 G2 actions (20 Drift, 10 Keep) carry no score: G2 actions are not scored live until #118, as the T2 guide says.
6. **The scores, as a smoke check:**
   - Recall: all 10 questions right.
   - Drift, G1 actions: 17 right, 10 task failures and 3 disqualified, which scores −1000: a wrong state change driven by a false, stale or planted memory, or a harmful extra action (mean 466.7 on the −1000 to 1000 scale).
   - Drift, G2 questions at the survive stage: 1 right and 4 scored −1000, a confident wrong or missing answer (mean −600).
   - Wake, G1 actions: 1 right, 6 scored 0 without a failure class, and 3 task failures (mean 100).
   - No control broke, the floor's served model identity equals the system's, and no item stayed INFRA.
7. **Spend:** 895 live calls through the benchmark's model login, at $0 (a subscription login; the pacer's bound was 1,000 sends). The live model read 5.2 million input tokens and wrote 70 thousand output tokens. The other token counts in `RESULT.md` belong to scripted roles, which the director serves itself.

## What the numbers measure, and what they do not

- **One run on one machine:** this is one run of one system on one machine, under the runner's background band, at 8 slots, with another project's light work beside it. It does not say what T2 takes on another machine, at another slot count or at the default priority; #478's probe measures the slot count.
- **A smoke check, not a comparison:** the scores have no second system and no A/A′ band yet (#391's A/A′ pair gives the band). T2's own label applies: live probe answers only; write turns, compaction, extraction and embeddings scripted; not predictive of the full tier; never certifies. Entity matching is strict, not semantic.
- **What the run's files do not record:** the machine's hardware, the loop test and the other project's work on the machine come from the maintainers' own notes.
- **Kept copies:** 26 failed items' pre-probe copies were kept for #393. A kept copy is a sound starting state, not an exact replay, until the restored-probe test passes.
- **Unexplained log entries:** the run's error log holds 17 connection-reset tracebacks from the director's local HTTP server, each raised while the server was reading a request line, so a reset may have come between two requests (the first attempt's log held 7). The run completed, and the two units that took a second attempt count both attempts in their time. Whether the resets caused those attempts is not established.
