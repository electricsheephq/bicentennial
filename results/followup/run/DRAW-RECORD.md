# The draw's record

`draw_record.py` holds the saved-record rules for the follow-up draw in
[the declaration](../DECLARATION.md), §2. The draw, release, and readers use
these same pure functions. The command layer reads remote responses through
`gh` and `curl` and appends private records. It never edits or deletes a posted
comment. It uses only the Python standard library.

Run `python3 -I results/followup/run/draw_record.py COMMAND --state DIR [args]`.
`DIR` is supplied by the caller and must be private, with one writer at a time.
No command prints bodies, served identities, or relay contents. Published
comment identifiers, rounds, times, commit identifiers and fixed reason labels
are the only identifying output. A refusal prints `refused: <reason>` to stderr
and exits 2; otherwise results go to stdout.

## The maintainers' reading of §2

This is the maintainers' reading of §2, fixed at the run commit before the draw.
The declaration says that a post gives a round and a full commit identifier,
without specifying value lines. One reading must govern the run's own posts
and every other candidate before any round's value is known.

Split the created body at every line feed. Remove one carriage return at the
end of each resulting line. A final line without a line feed is still a line.
A carriage return anywhere else stays in the line. The first line must be
exactly the appropriate first line:

- `Follow-up draw: first post`
- `Follow-up draw: second post`
- `Follow-up draw: task lists`
- `Follow-up draw: stop`

A line gives a round only when it is exactly `round ` followed by a positive
decimal number in ASCII digits, without a sign or a leading zero. A line gives
a commit only when it is exactly `run_commit ` followed by 40 lowercase hex
characters (`0123456789abcdef`). At least one qualifying line must exist for
each value, and every qualifying line for that value must agree. Invalid lines
give nothing. Equal repeated lines give the same value; differing qualifying
lines make that value ambiguous. Missing or ambiguous round or commit lines
make a first post not a commitment post, with the reason retained.

The six frozen identity values are read as `<name> <value>` with no whitespace
in the value: `registry_entry_sha256`, `fresh_install_hash`, `artifact_sha256`,
`system_hash`, `harness_hash`, and `route_table_hash`. They are retained, but
do not decide whether the post counts. Other value lines used for matching
have a lowercase name beginning with a letter and continuing with letters,
digits or underscores, one space, and a nonempty value without whitespace.
Equal repetitions agree; conflicting repetitions have no single value. Round
and commit value lines retain their stricter syntax. All such value lines are
compared for second and task-list posts. Text outside value lines, including
a hidden marker after the final value line, contributes no value.

## Saved facts and pure decisions

`candidates` unions every read and post, by integer comment identifier, in
record-number order. An absent later comment remains present. Only comments
by the merging login, created in a second strictly after the declaration's
merge second, are candidates. The first sight fixes the created body forever:

- A post response supplies its body.
- An unedited read supplies its body.
- An edited read supplies the earliest edit node's `diff` only when
  `includesCreatedEdit` is true and that node's `deletedAt` is null.
- Otherwise the created body is unrecoverable.

Non-candidates need no created body. `evaluate_records` orders candidates by
creation second, then integer identifier. A first post's commitment test uses
the saved declaration hash and length, the pull requests attached to the
named commit, and their comparisons. A qualifying pull request targets main,
is merged, has a merge commit containing the named commit (`identical` or
`ahead`), and merged in a second strictly earlier than the comment. The earliest
qualifying merge decides. Commit dates contribute nothing. A 404 or a 422
saying no commit was found is a failed test; other HTTP failures, rate limits,
and timeouts refuse without new evidence or tests. A full 100-pull-request
page refuses rather than silently truncating the evidence.

A round is due at `1692803367 + (round - 1) * 3`. Creation exactly 600 seconds
before that time is on time. Passing commitments to the same round are one,
carrying the earliest's time, commit and values. The earliest on-time commitment
whose round has no void is counted. Earlier unrecoverable candidates block
the decision; later ones do not. The list retains the provisional selection among
recoverable comments with its `counted` reason, even when an earlier
unrecoverable candidate makes `evaluate` report `blocked`. A blocked selection
cannot be used by any later action. When nothing counts, any unrecoverable
candidate blocks. The public list retains unrecoverable candidates because
their original first line cannot be known. It reports each first post's
round, commit, qualifying pull request, merge time, timing, test, and counting
reason. No saved test is replaced by a later observation.

`github_clock` uses the HTTP Date header and the machine's whole Unix second.
A skew of 60 seconds either way passes; more refuses. Round selection retains
a saved round only while it is more than 600 seconds ahead, rejects a saved
round more than 3600 seconds ahead, and otherwise saves the smallest round due
at least 900 seconds ahead before posting.

`accept_beacon` requires two equal JSON objects with exactly `round`,
`randomness`, and `signature`; the expected integer round; 64 lowercase hex
randomness characters; nonempty lowercase hex signature bytes; and randomness
equal to the signature bytes' SHA-256. A failed relay is never accepted even
if it returns parseable bytes. The GitHub time taken after both reads decides
the 86400-second cutoff. At the cutoff, agreement cannot rescue the read.
Acceptance records canonical JSON, sorted keys, compact separators, and one
newline. This verifies the two-relay/hash rule, not a beacon signature proof.

## Commands and results

| Command and arguments | stdout | Exit |
|---|---|---|
| `init` | `initialized` | 0 |
| `now` | `github <seconds> skew <seconds>` | 0 |
| `read` | `read <comment-count>` | 0 |
| `evaluate` | `counted <id> round <n> due <seconds> commit <commit>` | 0 |
| `evaluate` | `none` | 1 |
| `evaluate` | `blocked <id> [<id> ...]` | 3 |
| `evaluate --recheck` | `changed <id> <field> <old-json-value> <new-json-value>` per difference, or `unchanged <id>` | 0 |
| `choose-round` | `round <n> due <seconds> kept` or `round <n> due <seconds> new` | 0 |
| `post first FILE`, `post second FILE`, `post tasks FILE`, `post stop FILE` | `posted <id> <created-at>` | 0 |
| `beacon --round n` | `accepted round <n>` | 0 |
| `beacon --round n` | `not-accepted <reason>`; retry after 30 seconds | 1 |
| `beacon --round n` | `cutoff round <n>` | 3 |
| `match second FILE`, `match tasks FILE` | `differs <id>` for differing candidates, then `matched <id>` | 0 |
| `match second FILE`, `match tasks FILE` | `differs <id>` for differing candidates, then `none` | 1 |
| `record-void --round n --receipt-sha256 H` | `void round <n>` | 0 |
| `publish-list` | canonical JSON array and one newline | 0 |

All commands except `init` require a declaration record. After a blocked
evaluation only `evaluate` and `publish-list` remain available: the former
continues to report the block or compare evidence. `publish-list` performs no
remote reads; run `evaluate` first to save missing commitment evidence.
`evaluate --recheck` reports differences without writing any records.

`init` reads the declaration pull request, its merging login, merge second,
merge commit and declaration bytes at that commit. A repeat must agree with
the saved declaration. Every `gh api` includes headers, and the HTTP status is
read even when the tool exits nonzero. Each call has a 60-second timeout.
GraphQL reads complete both comment and edit pagination; failure of any page
leaves no read record. Integer comment identifiers use `fullDatabaseId`.

Before a first post the caller runs `read` and `evaluate`, then `choose-round`
when no draw counts. `post` also refuses a further first post when a saved draw
counts. It checks the first line and authenticated login; a first post must
use the newest saved round, due more than 600 seconds ahead, and a passing
commit with its earliest qualifying merge at least 60 seconds before GitHub's
time. The returned comment is saved before any output or subsequent record.
Its creation time, rather than the pre-post clock, decides its saved test.
A late response remains public evidence; the caller selects a new round and
retries under the same rules.

`match` considers only merging-account candidates after the counted comment
(by second and integer identifier), with the proper kind and counted round.
It records differing comments without halting the run. Its body file is the
run's proposed post; the caller supplies the second-post receipt and task-list
values. `record-void` accepts only the counted round and a receipt hash. The
caller must first confirm that the seed tool at the counted commit reproduces
the placement void; this module does not reproduce placement.

## Records

Only `DIR/records` is written. Names are `NNNN-<kind>.json`, or `.body` for raw
relay responses. One increasing counter spans both extensions and every kind.
A record is written exclusively to a partial name, flushed, then finalized by
a no-replace rename: link the final name exclusively and unlink the partial
name. This standard-library link/unlink pair cannot replace a competing final
name, unlike the platform's replacing rename operation. An
existing final or partial name refuses. Finalized records are never replaced,
moved or deleted; abandoned partials remain and reserve their counter.

| Kind | Contents |
|---|---|
| `declaration` | merging login, merge time, declaration commit, SHA-256, length |
| `read` | one complete issue read, including complete edit histories |
| `post` | normalized REST response with integer identifier and created body |
| `evidence` | commit, content status/hash/length, pull requests and comparison statuses; any definitive failure label |
| `test` | comment identifier and its fixed commitment result and qualifying merge |
| `round` | saved round number |
| `relay-primary`, `relay-secondary` | raw response bytes, including failed attempts |
| `beacon` | accepted object as canonical JSON |
| `difference` | differing comment identifier, kind and round |
| `void` | void round and caller-confirmed receipt hash |

Newest means the highest record number of a kind; first-sight bodies, evidence
and tests deliberately use the earliest applicable record. Private records
can contain bodies and identity values; command output does not expose them.

## Declaration sentence map

| §2 sentence or rule implemented here | Pure rule; command layer |
|---|---|
| The merging account posts the round, full run commit and frozen identity. | `parse_body`, `initial_declaration`, `validate_first`; `post` |
| Round n is due at the stated epoch plus three-second intervals. | `round_due` |
| Name a round fifteen minutes ahead and save it before posting. | `choose_round`, `validate_first`; `append_record` |
| Retry or restart reuses the round while more than ten minutes ahead. | `choose_round` |
| Read the issue before a first post; make no further first post while an on-time nonvoid draw exists. | `evaluate_records`; `read_issue`, `post`; caller sequences the pre-post read |
| A late post is retried with a new round. | `evaluate_records`, `choose_round`; caller retries |
| A commitment is by the merging account, after merge, with the exact first line and a full commit holding the declaration on main. | `candidates`, `parse_body`, `commitment_test` |
| GitHub creation time and lower integer comment identifier order posts. | `seconds`, `comment_order`, `candidates` |
| A qualifying main merge must precede creation by a whole second; commit dates do not decide. | `commitment_test`; `fetch_evidence` |
| On time is at least ten minutes before the due time; a late post never counts. | `round_due`, `evaluate_records` |
| Later edits and deletions change nothing. | `candidates`; `write_record` |
| Same-round commitments are one with all the earliest's values. | `evaluate_records` |
| The earliest on-time draw counts, proceeding past placement voids. | `evaluate_records` |
| The counted post fixes the run commit. | `evaluate_records`; saved `test` records |
| No draw post is edited or deleted. | `post`, `write_record`; no edit/delete operation exists |
| Read both named relays, requiring equal exact-field objects and the signature hash. | `accept_beacon`; `beacon_attempt` |
| A down, behind or disagreeing relay is read again. | `accept_beacon`; exit 1 tells the caller to retry |
| A late round is waited for; no redraw follows relay delay. | `evaluate_records`, `accept_beacon`; caller waits |
| Stop if no valid read occurs within 24 hours of due time. | `accept_beacon`; `beacon_attempt` gives cutoff, caller posts stop |
| The stop is posted by the merging account with the exact stop first line, using GitHub creation time. | `parse_body`, `rest_comment`; `post` |
| Only a reproduced placement void advances the draw. | `evaluate_records`; `record-void` records the caller's confirmed receipt |
| The second post records the round and drawn-list receipt after the round is read. | `parse_body`, `matching_comments`; `post`; caller supplies receipt and ordering |
| Pack and task-list hashes are posted before the first arm. | `parse_body`, `matching_comments`; `post`; caller supplies hashes and ordering |
| With results, publish every first post's identifier/time, commit, qualifying pull request/merge, and counting decision. | `publish_list`, `evaluate_records`, `commitment_test` |

Seed derivation, tracked-seed exclusion, placement reproduction, build retries,
pack creation, arm ordering, score reading, release publication and live-service
proof are outside this module. Offline synthetic tests prove the local rules
and tool protocol only.
