# Fresh-seed follow-up readers

The offline readers in this section implement the [declaration](../DECLARATION.md), sections
3–5. They use no live reader and change no pack or run. Their output is an
exploratory reading, never a rank, certification or prediction of the full tier.

`tasks.py` freezes the ranking pairs and descriptive items before any arm runs.
It checks the edition-3 shape: five G1 lives, five G2 lives, forty target items
in twenty twin pairs and ten descriptive items. The canonical JSON binds the
pack letter, commit, edition, spec hash, draw hash and installed pack tree hash.

```sh
python results/followup/run/tasks.py --pack A --packs PACKS_DIR --spec pack-A.toml --draw DRAW \
       --commit <40 hex> --edition 3 --out TASKS-A.json
python3 -I results/followup/run/cut_cards.py TASKS-A.json OUT_DIR A.F1=RUN_DIR [A.R1=RUN_DIR ...]
```

The cutter uses only the standard library. It refuses an output folder that
already exists, and creates it. It requires canonical full cards and keeps each
frozen ranking or descriptive key exactly once. Over the items it keeps, it
recomputes three outcome counts: `counts.kept_copies` and
`counts.null_citation` by the card builder's rules, and `counts.infra`, the
number of kept items whose `failure_class` is `BLOCKED`, by the runner's, so
no outcome count of a cut card tells anything of an unread item. Every other
field stays as the full card has it: the structural counts (`units`, `lives`,
`floor_cached_units`, `not_scored_live` and the `items.*` counts), `groups`,
`floor` and `controls_broken` describe the full run. A cut card is therefore
not a valid T2 card (`validate_t2_card` refuses it because `not_scored_live`
names items the cut drops), and is checked against the full card through the
printed SHA-256; `floor_cached_units` records where the floor came from (a
cached floor), not a score. It prints one JSON
mapping from labels to full-card SHA-256 hashes. A fault names only its label
(`card` when no label is at fault) and exits nonzero.

`table.py` verifies all three frozen lists against their own installed packs,
recomputes scripted reports and applies the unchanged round-2 rule functions.
It reads system outcomes directly. Every pooled repeat spans all three packs;
comparisons preserve all fifteen G1 lives. System failures remain scored.

```sh
python results/followup/run/table.py \
    --pack A PACKS_A TASKS_A_JSON TASKS_A_SHA256 \
    --pack B PACKS_B TASKS_B_JSON TASKS_B_SHA256 \
    --pack C PACKS_C TASKS_C_JSON TASKS_C_SHA256 \
    --system-hash HEX --harness-hash HEX --route-table-hash HEX \
    --order LABELS --attempts LIST [--reruns LABELS] [--after-reruns] [--checks-only] \
    [--check3 FILE] [--filter-out PATH] \
    LABEL=RUN_DIR ...
```

Supply all thirty-six labels. The declared first-attempt order is:

```text
A.F1 A.R1 A.O1 A.H1 A.H2 A.O2 A.R2 A.F2 A.O3 A.B1 A.G1 A.W1
B.F1 B.R1 B.O1 B.H1 B.H2 B.O2 B.R2 B.F2 B.O3 B.G1 B.W1 B.B1
C.F1 C.R1 C.O1 C.H1 C.H2 C.O2 C.R2 C.F2 C.O3 C.W1 C.B1 C.G1
```

`--attempts` is comma-separated and begins with this exact order. Append any
reruns as `LABEL.rerun`, at most once per label, after all first attempts.
`--reruns` names exactly those labels, comma-separated. `--order` lists their
last attempts in chronological order. Times must not overlap. The three
commitment hashes apply to every H arm. An H arm's commitment hashes are
judged by check 4 for that arm alone. Check 3 is one verbose test receipt
beginning with `commit SHA`, containing only passing outcomes for every test
in round 2's `CHECK3_TESTS`, and ending with `exit 0`.

Sections appear in this order:

1. Header, code hashes, task-list hashes, identity and attempt positions.
2. Checks before any score, including exclusions and their reasons.
3. Scores by kind: arms, pooled repeats and rows, including incomplete rows.
4. Per-kind readings and flags, margins and repeat combinations.
5. Room and Use, with exact life differences, sign-flip p and per-kind differences.
6. The two descriptive kinds, per pack and pooled.
7. H minus F, floor provenance, summariser tokens, each anchor's scripted score
   beside its live score (the pack's row in section 3: its usable repeats,
   pooled) and run metadata.
8. Oracle filter counts by round 2's rule: a trial is unscored when its O arm is
   missing, invalid, mismatched or compacted, and an O arm incomplete on a kind
   keeps its scored items. The optional canonical receipt has a section per
   pack, naming the unscored trials (`o_excluded`) and the O arms left out of
   each kind's readings (`o_excluded_by_kind`).

Sections 3–8 stay closed while a check is invalid, a rerun is pending or the
run has ended. The three packs' four code pins must each be recorded and equal,
or the run is refused (exit 3), with `--checks-only` too.
With `--after-reruns`, a pending arm is published as it is only
when `--reruns` names it; any other pending arm is still owed its one rerun,
so the reader prints the pending line with those labels and exits 4.
`--checks-only` prints sections 1–2 only.

| Exit | Meaning |
|---|---|
| 0 | Scores printed, or checks-only with no pending arm |
| 3 | Refused inputs, invalid control, order, shared code pins (arms' card pins and the three packs' four code pins), pack or check 3; also no arms after reruns |
| 4 | Pending arms not yet rerun: rerun each once, then use `--after-reruns` |
| 5 | A control rerun fails check 1, 2 or 7, or check 3 still fails after reruns |

The freezer exits 3 on refusal and writes nothing. The reader prints only
counts, public labels, pass/fail and twelve-character hash prefixes. It never
prints task text, answers, item or bundle ids, seeds, served identity values,
life names or paths. Lives in comparisons appear as pack letter and index.
Only frozen rows supply scores; the unread kind and G2 actions supply no
figure. Filter JSON identifies the selected pairs and binds full outcome hashes;
only the receipt's hash prefix is printed.

Run the tests by path, through the environment's shared test slot, with
`PYTHONHASHSEED=0`, `PYTHONPATH=src`, cache disabled, failed-only temporary
retention and a fresh scratch basetemp. Include `tests/test_developer_doc.py`
on every run. Pass this command to the shared slot wrapper, using the designated Python
and a fresh scratch directory:

```sh
PYTHONHASHSEED=0 PYTHONPATH=src python -m pytest -q -p no:cacheprovider \
    -o tmp_path_retention_policy=failed --basetemp=SCRATCH_TEST_DIR \
    results/followup/run/test_table.py results/followup/run/test_cut_cards.py \
    tests/test_developer_doc.py
```

Then run each neighbour separately, again with the developer-document tests:
`results/validity-2/control-trials/test_table.py` and
`results/milestone-1/2026-11-11-separation-table/test_table.py`.
The fixtures use invented packs and runs; one module-scoped test builds and
installs the public T2 spec at edition 3. No test uses a login, network,
socket or live model. This proves offline script logic only, not a real-arm reading.

## Operating the follow-up

`run-followup.sh` implements the declaration's operator steps. The
[draw-record rules](DRAW-RECORD.md) govern how a post is read, which one counts,
and how an unrecoverable created body gates another first post. The script
uses that module at the run commit for every draw operation; it never reads
or changes its record folder.

Supply these environment variables before `prep`, then keep them unchanged:
`FOLLOWUP_STATE`, `FOLLOWUP_REPO`, `FOLLOWUP_HERMES`, `FOLLOWUP_WRAPPER`,
`FOLLOWUP_LOGIN_HOME`, `FOLLOWUP_MARKER`, `FOLLOWUP_PYTHON`, `FOLLOWUP_SLOT`,
and `ORIGIN_MARKER`. `FOLLOWUP_PYTHON` is the project's Python 3.14;
`ORIGIN_MARKER` is the complete hidden agent-origin comment. `prep` records
these settings and the resolved paths of `gh`, `curl`, `git` and that Python
in `private/settings` (0600). Its private folder is 0700. Use `gh`'s stored
login (configuration or keychain): `env -i PATH="$PATH" HOME="$HOME" gh auth
status` must pass, because the draw module removes every inherited `GH_`
variable, including `GH_TOKEN`.

The environment's live-settings wrapper is responsible for live model settings;
none is printed or copied into the public run script. `FOLLOWUP_STANDIN` is
only a test dispatcher: it works solely in a directory already holding
`.followup-test-dir` before `prep`; prep never creates that marker. A real arm
can only run in the official directory named by the record
`.bicentennial-followup-official` in the operator's home. Marking an official
directory permanently disables its steps. After `prep`, a non-official folder runs only through its stand-in.
A failed `prep` leaves an
unrecorded folder that must be moved aside; it posts nothing. After a failed prep,
move its folder aside and re-run `prep` at the same path; prep prunes only missing
worktree registrations before adding its checkout. That prune also forgets any other
unlocked worktree of the repository whose folder is missing, for example one on an
unmounted volume; lock such worktrees first with `git worktree lock`.

Run the steps with `/bin/bash run-followup.sh STEP [ARGUMENTS]`:

| Step, in operating order | Needs; leaves |
|---|---|
| `prep SHA PR [PR ...] [--import none]` | A main commit and merged prerequisites; fixes settings, detached worktree, venv and declaration record. State-directory imports are refused; `none` records lost state. |
| `rehearse` | No real BEACON; places, builds and installs three public-integer packs, prepares H without sends, freezes lists, checks the no-arms reading, check 3, follow-up tests and known-answer derivation. Keeps failed rehearsals. |
| `post-commit` | Rehearsal passed at the run commit; adopts the counted post or posts round, commit and H's six values. Posted values govern H's checks even if they differ from rehearsal. |
| `beacon` | Counted commitment; waits under caffeinate, retries relay reads and only the transient S4 refusals every thirty seconds, saves accepted BEACON or posts the cutoff stop. |
| `draw` | Accepted counted BEACON; fresh clean worktree, recorded draw and exact hash-and-commit verification. |
| `post-draw` | Verified draw; matches or posts round, draw hash, draw time and randomness. |
| `place` | Recorded second post; two independent placements agree, or a reproduced void is confirmed, recorded and archived. |
| `build` | Agreed placements; builds and installs A, B and C through the slot, with logs and hashes. |
| `tasks` | Installed packs, no attempts; validates and freezes all three task lists. |
| `rebuild` | A recorded failed build attempt; repeats draw, two placements, three builds and lists once, from fresh worktrees, preserving the first attempt. Failure posts the build stop. |
| `post-tasks` | Three frozen lists and packs; matches or posts their hashes and the round. |
| `check3` | Task-list post, no arm attempt; keeps one passing attempt or at most two attempts, with commit and exit. A missing or damaged receipt consumes that attempt; retry if one remains, otherwise release. A second failure ends the run. |
| `run LABEL` | All posts still match, passing check 3, preceding first attempts; runs the next of thirty-six arms with the frozen send bound. |
| `table [--after-reruns]` | All first attempts, frozen lists and check 3; preserves each reading, flags, exit and sequence. The flag first recomputes which arms are pending. `table-N.flags` records the reading's arguments with paths relative to the state directory; the command also passes `--filter-out private/FILTER-N.json`. If it refuses `used attempt lacks its sequence`, run `abandon TAG` for that tag, or any `run` or `rerun`, which completes the copy first. |
| `rerun LABEL` | All first attempts and the latest reading naming the label; one whole rerun with the same command and send bound, then another reading. |
| `abandon TAG` | Dead wrapper and no arm process; removes a stale lock and records invocation start and kill times, counting existing output as an attempt. |
| `cards` | Table exit 0; cuts used cards and replaced first attempts per pack, preserving hashes, missing labels, faults and every repeated cut. |
| `stop beacon\|build` | Recorded cutoff, or first failure plus failed rebuild, before any arm; posts only the declaration's reason, exits and log hashes. |
| `release` | Cards complete, stop, blocked first post, unconfirmed void, `counted-not-own`, `state-lost-after-draw`, terminal reading fault or second failed check 3; publishes all extant draw and attempt evidence with versioned exports and recomputation checks. |

Invocations refused before output, or refused by the machine guard before any
unit, are kept but are not attempts; every other invocation that creates output
is the label's attempt. An interrupted build tool is resumed from its exit
record, or, after proving its recorded process dead, its partial output is kept
and it is retried within the declared cutoff budget. A failed build attempt
can proceed only by the one rebuild; no failed attempt changes the draw.

Reruns happen only after all thirty-six first attempts, once per label, when the
latest reading made after every attempt names that label pending or invalid.
After each rerun, read again before another rerun; once scores open, the run
ends, shared pins or order fail, or check 3 fails twice, no rerun is allowed.

Each void is published with its round, DRAW and receipt; at the run commit,
anyone can repeat it with `python scripts/validity_roster.py draw --packs 3
--beacon BEACON --out DRAW` and `python scripts/validity_roster.py place --packs 3
--draw DRAW --work WORK --out-dir OUT`, where BEACON is the public round's
three-field object and WORK and OUT are new. A void that does not reproduce
there leaves the earlier draw standing under §2, which `release` reports.

A counted post naming another commit is recorded as `counted-not-own` and
refused. Once that record exists, `release` is allowed directly and publishes
the records, including unavailable or different reading module status.
`release` also publishes every abandoned invocation's start and
kill times; a killed attempt is rerun once only when the latest reading names
it under the rerun rule. No release step commits or posts results: maintainers
review and commit its publication folder beside the result.

When placement confirms a void, its exit 1 means the next step is `post-commit` for a new round; a failed placement instead requires `rebuild`. Every cutoff keeps its partial logs, and the saved tool PID and process start distinguish a live invocation from a reused PID.

A directory runs only the draw it posted: its own S4 `post` record must name
that draw's counted first post. The script reads those records only through
fresh numbered exports under `private/exports/`. Reading or matching #394 never
grants authority. A matching second post or task-list post is adopted only if
its id is also in the directory's own post records; otherwise it posts its own.
An export failure refuses `own post records unavailable`; fix storage or the
export failure and repeat the step. Release exports S4's records independently
and skips these private copies.

`prep SHA --import DIR` is unsupported and refuses before creating or recording
anything. A commit change before or after a void is unsupported, so that run
ends without arms, with readings unresolved under §10's missing-data line.

These fail-closed windows also end the follow-up without arms, and release
publishes the records: GitHub accepts the first post but S4 cannot save the
response (a timeout recorded as `post-unknown`, or a kill or reboot between the
201 and its record); the directory is lost after its first post; or a commitment
post made by hand counts. A `counted-not-own` record permits only release and
abandon. A hand copy of a state directory, on this machine or another, a
hand-edited record, or a gh or network path that alters GitHub's responses is
outside what the script can detect.

`--import none` requires the recorded old directory to be absent and records
`old state lost`. Before any merging-account second-post or task-list marker
after the merge it can prepare normally; after either marker it is permanently
release-only: `state lost after the draw: no arm can run; readings unresolved
(§10, missing data)`. This is missing data, not another §2 stop. Deleting any draw
post (the counted first post, second post or task lists) combined with fresh
draw-record state is §10's disclosed limit: readers
check the published list of posts against their own copies or a public archive.

Beacon waits retry S4's round-not-due, GitHub transport/status/time/header,
GraphQL, relay-timeout, clock-skew and unavailable-reading-module refusals;
`malformed or unavailable record` gets at most two further attempts. Any other
refusal returns immediately; run `beacon` again after fixing its cause. S4 keeps
every attempt, and its 24-hour cutoff is unchanged.

A kill, reboot or full disk either resumes, refuses with a named reason that a
documented step clears, or ends the run; an end can only take kinds out of the
ranking set (§10). After fixing a storage-write failure, repeat the refused step:
checked record partials are rewritten, frozen task hashes are recovered only from a successful
tasks exit and a rechecked list, and an interrupted rebuild finishes its archive
before proceeding. A failed fork record waits for the tool and attempts to save
its exit before refusing; repeat the step after fixing storage. If a failed rebuild
cannot save `rebuild-failed`, `stop build` completes that copy and posts the stop. If a wrapper
was killed, first use `abandon TAG` to clear its dead lock; the next `run` or `rerun` finishes every completed invocation's records
or guard move before it checks attempts. An open invocation of any label requires
`abandon TAG` first; after any rerun attempt, a new `table` is required.
A closed invocation's diagnostics without output move beside its records as
`.orphan-diag`; existing output is kept as its attempt. When the runner refuses after
units ran, it removes its output folder and creates it again; an arm killed in the
instant between those two leaves no output, so that invocation counts as no attempt and
the arm can run again. Its start, end and exit records are published.
An owner or tool without a start record is left alone for sixty seconds by the
recorded clock; a PID alone never proves it live. A tool killed between its start
and its process record is treated as dead after 60 seconds. If it still runs,
its outputs are moved aside and a second copy starts. In the cases traced, the
second copy fails on the first copy's output or on paths the first copy renames
or removes; it could succeed only by finishing before a copy that started at
least 60 seconds earlier. A failure counts as a failed attempt: it uses the one
rebuild, or, after the rebuild, the build stop ends the run. The step below
prevents both outcomes: after any kill, before re-running the step, wait until no
process using the state folder remains (`pgrep -fl -- "$FOLLOWUP_STATE"` prints nothing).
Check 3 runs only
`tests/runner/test_control_arms.py`, verbose, through the slot, at rehearsal and
on each attempt. It passes only when its receipt shows every required test passed, by the reading script's rule.
A failing receipt can still carry local paths in tracebacks; `release` then replaces
it by its sha256 and a note, as D19 requires. Release also accepts a terminal pin/order fault from an
`--after-reruns` pre-run and reports every S4 void round, including missing inputs.

If a sequence write is refused before an arm starts, `abandon LABEL` preserves
that no-output invocation's invalid sequence as `.seq.failed`, then the same
`run` or `rerun` can be retried. A produced arm is never discarded by this recovery.

If every remaining arm is permanently refused before output, for example because
the model endpoint is retired, the run can never reach a release event. It ends
with every reading unresolved, and `release` refuses. The maintainers then
publish the state's records by hand, following D19's list
([#590](https://github.com/electricsheephq/bicentennial/issues/590)). A dead login
is cleared by logging in again and is not this case.
