# The draw's record

`draw_record.py` implements the saved-record rules of [the declaration](../DECLARATION.md),
§2, using the standard library under the project's Python 3.14:

```
<the project's Python 3.14> -I results/followup/run/draw_record.py <command> --state DIR [args]
```

The reading is the module at the run commit. Before posting a first post it compares
its own bytes with the public file at that post's `run_commit`. When reporting a
counted post, or acting on it, it compares with that counted commit. A difference
refuses with `reading module differs at <C>` (or `reading module unavailable at <C>`);
the caller moves to that full 40-hex commit. There is no operator-selected reading
commit. Two merged versions of this module could read posts differently. This is
why §2 fixes the reading, reader, controls and placement at the public run commit.
An already accepted beacon is returned from its record without another remote read;
a stopped draw is refused first.

## The maintainers' reading of §2

Split bodies at line feeds; remove one terminal carriage return per line. The last
line need not end in a line feed. A carriage return within a line remains there.
The first line must exactly equal one of:

- `Follow-up draw: first post`
- `Follow-up draw: second post`
- `Follow-up draw: task lists`
- `Follow-up draw: stop`

A value line has a name matching `[a-z0-9_]+`, one space, and a nonempty value
without whitespace. Other lines, such as blanks, hidden markers or prose that does not match this grammar, are not value lines.
Each name must occur once; even equal repeated names fail. A round value matches
`[1-9][0-9]{0,17}`: 1 to 18 ASCII digits, without a sign or leading zero. Any other
round value is read as `missing round`. Every integer read from JSON, a string id
or a command argument is limited to 18 digits (excluding a sign); an invalid or
overlong integer refuses before conversion. A `run_commit` value is exactly
40 hex characters in either case; it is compared and stored in lowercase. A first
post must give both. Invalid or repeated lines make it not a commitment post.
The six H values (`registry_entry_sha256`, `fresh_install_hash`, `artifact_sha256`,
`system_hash`, `harness_hash`, `route_table_hash`) are retained; their contents do not decide whether the post counts.
The unique-name rule still applies to them. Matching second and task-list posts uses exact equality
of the full value-line sets. No missing or extra value is allowed. Prose and blank
lines do not affect a match. The earliest matching comment is used.

## Saved comments and evidence

The comment set is every comment in any saved read or POST response, keyed by its
integer id. The query asks for comment `fullDatabaseId`, converted to an integer,
without the deprecated comment `databaseId`; the author keeps the User `databaseId`. A comment never seen is outside the set. Deleting a comment later
does not remove it from that union. The run's own posts are saved from the POST
response; §2's prohibition on editing or deleting draw posts covers those posts.
A never-seen deletion is a limit of the record, not another stop.

`init` saves the merging account's integer id and login, merge time, declaration
commit, declaration byte length and SHA-256. It requires a merged pull request and
nonempty declaration. Repeated initialization compares the account id, merge time,
declaration commit, SHA-256 and length, retaining the first initialization's login.
Author identity is the integer id, fixed at first sight with the created body, for every comment by that
account, including comments that are not candidates. A rename changes nothing;
a reused login on a different id changes nothing. A null author is not a candidate.

An unedited comment, or the run's POST response, supplies its body directly. For an
edited comment with `includesCreatedEdit`, exactly one edit node must have `editedAt`
equal to the comment's `createdAt`. That node's `diff` supplies the created body
only when `deletedAt` is null. No qualifying node, two qualifying nodes, a deleted
creation revision, or missing creation history makes it unrecoverable. Node order
does not break ties. The public list retains unrecoverable comments by the merging
account, with the creation revision's `deletedAt` when known and the GitHub time
of first sight. No later observation changes the first sight.

A candidate is by the merging id, in a second strictly after the declaration's
merge. A merging-account comment created at or before the merge is `not after the
merge`, checked before body recovery or first-line syntax. For every other comment,
first-line syntax is checked before the author rule, then evidence calls in their order. A passing
commit has the unchanged declaration (hash and length) and a qualifying pull request
to `main` with compare status `identical` or `ahead`. The default branch is read before
and after the pulls call and both settings are recorded; either setting other than
`main` makes that evidence undecided, regardless of fetch time. No mutable setting
decides a post. The earliest qualifying merge must be in an earlier second than the
comment. Commit dates are irrelevant. A full 100-pull-request response refuses.
A 404, or a 422 whose JSON message begins `No commit found for SHA`, can fail a
comment; another status or another 422 refuses.

Evidence records keep GitHub's time from before their first evidence call. The
successfully fetched declaration bytes describe an immutable commit tree and decide
at any fetch time when both default-branch readings are `main`. A 404 or no-commit response does not describe a fetched tree;
it cannot negatively decide a later comment. Those failures decide only at or after the comment's creation. A positive
qualifying main merge before the comment also decides at any fetch time. A negative pull/compare result decides only when that evidence time
is at or after creation. An earlier negative snapshot never rejects a later post.
The first deciding result is frozen in a `test` record for that comment. If no
saved evidence decides, new evidence is fetched. A successful fetch is saved even
when it cannot decide; then evaluation refuses with `post <id> undecided` (exit 2),
never `none`, and `post first` refuses too. A failed fetch keeps its own refusal.
`evaluate --recheck` writes separate `recheck` records for every already tested
comment, including those after the counted post, reports differences or
`undecided <id>` when it cannot decide, and never creates or
replaces deciding evidence or tests. A default-branch flip and restore inside the
pulls call is not detected and could freeze `no qualifying pull request` under the
older GitHub behaviour; a later `evaluate --recheck` exposes that forced failure publicly.

`evaluate` tests in creation-time then integer-id order, stopping at the first
on-time, nonvoid commitment. Exactly 600 seconds before due is on time. Passing
posts of one round are one post with the earliest's values. After a placement
void it continues to the next round. Later candidates are tested only for the
public list; an undecided fetch there is `untested: undecided`, while a failed fetch
is `untested: commitment evidence unavailable`. Every saved record is used even
when that attempt refuses, and no later post can displace the counted post. `evaluate` never blocks. An unrecoverable comment changes no counted
draw, even if discovered later. Only `post first` is gated by an unrecoverable
candidate from after the merge when nothing counts.

## Clocks, posting and stops

GitHub time is the Date header from `gh api -i rate_limit`. Every timed command
refuses a machine skew greater than 60 seconds either way. Within that window,
§2's “its own clock” means the later of GitHub time and the machine clock, for all
900-, 600- and 3600-second rules and first-post margins. Beacon due/cutoff and
stop admission use GitHub's time alone, so public records can check those times.
Round n is due at `1692803367 + (n - 1) * 3`. A saved round more than 600 seconds
ahead is reused; more than 3600 seconds ahead refuses. Otherwise save the smallest
round due at least 900 seconds ahead.

`post` verifies the authenticated account's integer id. `post first` itself reads
all issue pages and edit pages, then evaluates the saved set. It refuses unless
none counts, and prints `blocked <id>...` (13) if an unrecoverable merging-account
candidate created after the merge exists. This gates a further first post; it does not stop the draw. Just
before sending, a fresh GitHub time must leave the read at most 60 seconds old by
GitHub's time, the saved round more than 600 seconds ahead, and the qualifying merge at least
60 seconds old. The module at the named commit must have identical bytes.

Only a 201 POST response with an integer id is success. The `post` record is saved
before another read or success output. It reads the issue back and prints
`posted <id> <created_at>`, exit 0, even if that read fails; stderr then says
`read-back failed`. After a first post it also makes a best-effort evaluation,
testing comments seen in the posting window; evaluation failure does not change
POST success. Any other status, missing status, timeout or exception after sending
writes `post-unknown` and refuses. That record is evidence, published by
`publish-records`, and never gates later second, task-list or stop posts. Only
`post first` refuses with `post outcome unknown` while its own pre-read's GitHub
time is less than the newest unknown first send's GitHub time plus the `gh` timeout
plus 60 seconds. This clears by time alone; the pre-read and evaluation then catch
any landed first post. A kill may leave no POST record, but the next pre-read
still catches a landed first. Duplicate second/task-list posts use the earliest
exact match (skipping an earlier differing one); stops use the earliest qualifying
stop. Duplicate first posts for the same round are `same round as <id>`, and a
later on-time round is `after the counted post`.

A stop post is permitted only with a counted draw at or past its due time:

- `post stop --reason beacon FILE`: no accepted beacon, newest attempt for that
  round says `cutoff`, and time is at least due + 86400 seconds.
- `post stop --reason build --failure-sha256 H FILE`: an accepted beacon and a
  64-character lowercase failure-record SHA-256, saved with the post. The caller
  owns the one fresh-checkout build retry and the truth of that failure receipt.

A candidate comment (the merging account's, created after the merge: the set
`candidates` returns, the same set `stopped_comment` reads) whose first line is
`Follow-up draw: stop` counts as the stop only when it is created at or after the
counted round's due time and no candidate comment comes before it in comment order
(`comment_order`: created second, then id) whose first line is
`Follow-up draw: task lists`, that is created at or after the counted round's due
time, whose created body has no repeated value name, and whose `round` value is the
counted round. A missing `run_commit` does not matter
here: task-list bodies carry `round` and the six hashes, never a `run_commit`.
A task-list comment with a repeated value name, with no round, or naming another
round hides nothing. Any other stop comment is a marker: listed by `publish-list`,
never a stop. `post stop` refuses once such a task-list comment exists.
A qualifying saved stop makes `evaluate` print `stopped <id>` (14). Once stopped, first posting, beacon acceptance and voiding refuse.
These implement §2's two stops; unrecoverable comments are never another stop.

## Beacon, matching and export

A beacon attempt reads both relays and saves both raw bodies, then takes time
again. Both must return the same JSON object, with exactly `round`, `randomness`
and `signature`, agreeing by canonical JSON bytes (so `5` and `5.0`, or `true` and
`1`, differ), the expected integer round, lowercase hex signature bytes, and
64 lowercase hex randomness equal to the signature bytes' SHA-256. An attempt
writes its outcome, before/after GitHub times, after-read machine time, and raw-body
record names. On acceptance the `beacon` record is saved before `beacon-attempt`,
so a crash between them cannot lose an in-time acceptance. At or
past due + 86400 it is `cutoff`, regardless of relay agreement. Accepted objects
are canonical JSON (sorted keys, compact separators, one newline). A later beacon
call returns the saved acceptance, including after that round is void, without cutoff or any remote read, after
checking for a stopped draw. `beacon --round n --out FILE` requires `--out` and
links exactly the accepted record's canonical three-field JSON bytes to FILE
without replacement, for a new or saved acceptance. An existing FILE succeeds
only if its bytes are identical and is never rewritten. A not-accepted or cutoff
result creates no FILE. These checks are not signature verification.

`beacon --rehearsal [--fixture FILE]` uses the tracked known-answer round by default.
It needs no counted post, omits the cutoff and retries up to three times 30 seconds
apart. It passes only on an accepted object equal to the fixture, writes a
`rehearsal-beacon` outcome/attempt count, and never writes a `beacon` record.

`match second|tasks FILE` records matches and differences, prints every difference
and uses the earliest match. It considers only comments after the counted post
in comment order (creation second, then integer id). `publish-list` includes both,
all first posts by the
merging id, unrecoverable comments, H's values and every other draw marker by that
account, including before the merge. Markers carry boolean `after_merge` (strictly
after the merge second). Other authors' comments are counted as `other_comments`,
never printed. After an untested first-post row, no later row is counted; later
rows say `undecided: an earlier post is untested`.
`record-void` requires the counted round, its accepted beacon and a receipt hash;
the caller must reproduce the placement void at that commit first.

`publish-records OUT` creates a new folder and copies every finalized record kind
and raw relay body. Reads retain GitHub time and the merging account's comment ids,
author ids, bodies, `includesCreatedEdit` and complete edit nodes; other comments
are replaced by a count. No other author's body is exported. The exported folder
is itself a state folder: the same `evaluate` gives the same result. OUT is the
exception, together with beacon `--out`, to writing exclusively beneath `DIR/records`.

## Commands and results

All except `init` require a declaration record. Every refusal prints
`refused: <reason>` on stderr and exits 2. Result exit 1 is never used.

| Command | Output | Exit |
|---|---|---|
| `init` | `initialized` | 0 |
| `now` | `github <seconds> skew <seconds>` | 0 |
| `read` | `read <count>` | 0 |
| `evaluate` | `counted <id> round <n> due <seconds> commit <C>` | 0 |
| `evaluate` | `none` | 10 |
| `evaluate` | `stopped <id>` | 14 |
| `evaluate --recheck` | `changed <id> <field> <old-json> <new-json>` or `unchanged <id>` or `undecided <id>` | 0 |
| `choose-round` | `round <n> due <seconds> kept|new` | 0 |
| `post first|second|tasks FILE` or guarded `post stop ... FILE` | `posted <id> <created_at>` | 0 |
| `post first FILE` | `blocked <id>...` | 13 |
| `beacon --round n --out FILE` | `accepted round <n>` | 0 |
| `beacon --round n --out FILE` | `not-accepted <reason>` | 10 |
| `beacon --round n --out FILE` | `cutoff round <n>` | 13 |
| `beacon --rehearsal [--fixture FILE]` | `rehearsal-beacon pass` or `rehearsal-beacon fail <reason>` | 0 or 10 |
| `match second|tasks FILE` | `differs <id>` lines, then `matched <id>` or `none` | 0 or 10 |
| `record-void --round n --receipt-sha256 H` | `void round <n>` | 0 |
| `publish-list` | canonical JSON with `first_posts`, `markers` and `other_comments` | 0 |
| `publish-records OUT` | `published records` | 0 |

`gh api -i` output is split at the first blank line, supporting LF and CRLF, and
its status is used regardless of the process exit code. Missing status, malformed
records, missing tools and unexpected exceptions refuse. The test entry point is
`main(argv, clock=..., sleep=..., gh_timeout=...)`. Tool stdin is the null device;
the tool environment contains only PATH and HOME. Every inherited `GH_` variable
is removed. `curl` starts with `-q`, so it never reads a curl configuration file.

## Crash-safe records

Each command takes a blocking exclusive flock on the records folder. The next
number is the maximum prefix matching `^\d{6}-`, including partial or otherwise
unfinished names, plus one; unrelated names are ignored. Names are
`NNNNNN-<kind>.json` or `.body`. A record is written with exclusive creation to its
`.partial` name, flushed, fsynced (also `F_FULLFSYNC` where available), hard-linked
to the final name without replacement, then the folder is fsynced. The partial
file is retained and readers ignore it. Nothing is overwritten, moved or deleted.

Kinds include `declaration`, `read`, `round`, `post`, `post-unknown`, `evidence`,
`test`, `recheck`, `relay-primary`, `relay-secondary`, `beacon`, `beacon-attempt`,
`rehearsal-beacon`, `void` and `match`. Newest means highest record number, except
first sightings and first deciding tests, which are frozen at their earliest record.

## Declaration sentence map

| §2 rule implemented | Pure rule / command |
|---|---|
| Merging account posts round, full run commit and H identity | `initial_declaration`, `parse_body`, `post` |
| Epoch and three-second due time | `round_due` |
| Save round at least fifteen minutes ahead; reuse while over ten minutes ahead | `choose_round`, `validate_first` |
| Read before first post; no further first while a nonvoid on-time post exists | `read_issue`, `evaluate_saved`, `post` |
| Retry a late post with a new round | `evaluate_records`, `choose_round`; caller retries |
| Commitment author, after-merge time, first line and unchanged declaration on main | `candidates`, `parse_body`, `commitment_test` |
| Creation-time and integer-id ordering | `comment_order`, `comment_set` |
| Earlier qualifying merge second; own commit dates irrelevant | `commitment_test`, `fetch_evidence` |
| At least ten minutes before due is on time | `first_row`, `round_due` |
| Edits and deletions change nothing | `created_body`, `comment_set` |
| Same-round posts share the earliest's values | `first_row`, `evaluate_records` |
| Earliest on-time nonvoid draw counts; proceed after placement void | `evaluate_records`, `record-void` command |
| Counted commit never changes; reading fixed there | `saved_test`, `verify_reading` |
| No draw post edited or deleted | `post` exposes POST only; append-only `write_record` |
| Two exact-field agreeing relays with signature hash | `accept_beacon`, `relay_attempt` |
| Down, behind or disagreeing relay retried; late round waited for | `accept_beacon`, `beacon_attempt`; caller retries |
| Only unread-after-24-hours or build-after-retry stops | `stop_admission`, `stopped_comment`; caller proves build retry |
| Stop author, first line and creation time | `candidates`, `parse_body`, `stopped_comment`, `post` |
| Only reproduced placement void advances | `evaluate_records`; `record-void` requires beacon and receipt; caller reproduces |
| Second post records drawn list, time and randomness after reading | `matching_comments`, `post`; caller supplies receipt and ordering |
| Packs/task-list hashes before first arm | `matching_comments`, `post`; caller supplies hashes and ordering |
| Public list of first comments with commit, PR, merge and counting reason | `publish_list`, `prepare_list`, `publish_records` |

Synthetic tests prove these local rules and the tool protocol. They do not prove
live issue reads/posts, live relay reads, the calling run script, seed derivation,
placement reproduction, build retries, arm sequencing, scores or publication.
