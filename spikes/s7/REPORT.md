# S7 Part A: write-turn readback, boundary and effect

Claim class: **advisory, offline**. This audits two recorded runs of a public,
synthetic 10-session life. No model, external network, login store, live memory
service, or director modification was used. Part B remains pending.

[Machine-readable counts and id-only item lists](results/partA.json) are the
public evidence summary. Input bodies and store text are excluded. All ledger
records and referenced blobs were hash-verified before analysis.

| Check | r6 (chat completions) | r7c (Responses) |
|---|---|---|
| Input integrity | 136 records; 361 unique blobs; intact | 167 records; 315 unique blobs; intact |
| A1 independent readback | 60/60 forwarded bodies match; 0 mismatches; 0 flag disagreements | 60/60 match; 0 mismatches; 0 flag disagreements |
| A2 literal boundary scan | 7 future-text hits (6 later turns and 1 pending cursor reply), all inherited; 0 introduced; 0 life-id hits | 1 future-text hit, inherited; 0 introduced; 0 life-id hits |
| A3 tool boundary | 60 memory definitions offered; 14 executed calls with valid issued ids; 0 provenance/filter failures; 0 non-write attempts | 60 memory definitions; 1 executed call with valid issued id; 0 failures; 0 non-write attempts |
| A4 effect | 14 applied, 0 refused, 0 staged; 11 original contents in final store; 13 original contents visible next session; 14/14 store and next-session effects satisfied after later patches | 1 applied, 0 refused, 0 staged; 1/1 original content in final store and next session; 0 gaps |
| A5 discard | 60/60 scripted replies match; 0 missing; 46 nonempty write responses checked; 0 whole-content matches later; 137 conversation substring collisions, 0 tool-channel hits and 318 other-field collisions | 60/60 scripted replies match; 0 missing; 59 nonempty write responses checked; 0 whole-content matches later; 215 conversation substring collisions; 0 tool-channel hits; 0 other-field collisions |

## Method and discrepancies

A1 reconstructs each forwarded body from the triggering harness request, using
independent code and the public provisional suffix. Chat changes only the model,
stream and transport keys, appends the suffix, and filters tools. Responses
preserves other fields, sets its declared streaming transport, wraps plain
message strings in role-appropriate typed text parts, and appends the suffix
item. Models are pinned in the checker rather than taken from the observed body.
No director readback function is imported. Each top-level key is compared as
canonical JSON bytes, so a boolean sent as an integer is a mismatch. The recorded
`write_turn_readback` flag is checked in both directions. There are no A1
mismatches to explain.

A2 scans every later scripted user/assistant string, including probe questions,
the cursor turn's own scripted reply (served only after the write turn), and life
id/reference values and event-map keys. The match is an exact, case-sensitive
substring with no minimum length, so two-character ids are needles too. A hit is
inherited only when the forwarded body holds no more copies of the string than the
expected body built from the harness request. Literal matches are retained:
r6 record 43 and r7c record 49 contain the repeated user turn identified as
`8:5:user`; r6 records 90, 92, 93, 94 and 97 contain `8:2:assistant`, the short
branch answer already in the conversation or memory, and record 99 (cursor 8:2)
holds the same text as its pending reply, from the memory snapshot. Each is also
present in that record's triggering harness request. The literal expected-zero condition
is therefore **not met**; the introduced-hit count is zero. The scan is not
silently relaxed to obtain zero.

A3 pairs upstream memory arguments with returned calls in order, checks the
exact monotonic `bcw` ids used by both recorded directors, and finds tool results
in the harness requests that follow under the same cursor, which may split one
turn's results. Newly appearing unissued result ids fail the check, and so does
a tool call on a scripted reply. A non-write attempt counts as blocked only when no served call has its
name, the following request has no new history call with its id or name, and
no later request carries its id as a call or result that was not already in the
triggering request. Both runs attempted only memory
calls, so the blocked and reached-harness paths are exercised by synthetic tests
rather than by these runs.

A4 reads Hermes' explicit success result, and compares content after whitespace
normalisation only. It reads the final target file and only the system prompt
or Responses instructions of the first main request of the next session. The
last r6 call is checked against the first probe session (record 125). Refusals
are separate from applications. A result staged for approval is its own class,
neither applied nor refused. A result that is not a JSON object is unclassified,
and an unclassified result is a gap. A malformed call that Hermes did not apply
is reported as such and is not checked for effects; one it applied stops the
audit. A remove must
be absent, and patch operations propagate the earlier span through later
successful calls in the same target, including a later patch whose old span
encompasses the earlier content, which then becomes that patch's new text.

r6's three differences between original and final content are accounted for:
`bcw00002` (record 8) is patched by `bcw00010` (record 46);
`bcw00008` (record 30) is patched by `bcw00011` (record 87), then `bcw00012`
(record 90); and `bcw00011` is itself superseded by `bcw00012` before the next
session. The first two original contents were visible next session, while the
third's replacement was visible. The final replacement spans are present.
There are no unexplained store or next-session gaps. The offered Hermes schema
uses `patch`, including `new_text` and atomic `operations` forms; these are
reported as such, rather than relabelled as unobserved replace calls. Neither
recorded run exercises remove or refusal.

A5 checks scripted response contents (in Responses streams, the text deltas as
well as the completed items), checks that a response serving write calls
to the harness carries no assistant text (0 in both runs), and scans every
string of every later
request for write-response substrings (exact, case-sensitive, no minimum length),
labelled by channel: conversation text, tool-call arguments and tool outputs
outside it, and every other field. Every write draft in both runs is the literal
four-character no-write reply (46 in r6, 59 in r7c), so A5 here tests one short
token and substring identity carries no provenance. Every conversation hit is
that reply inside unrelated compression material. Classified by hand from local
evidence (these splits are not emitted by the checker): r6 has 53
write-record/request pairs in compression instructions and 84 in summary tool-use
annotations; r7c has 69 and 146. All 318 r6 other-field collisions are
reasoning-setting values. The full pair lists are retained in the JSON; complete conversational
content matches are zero. These counts are pairs, not distinct requests or
occurrences. Script equality and returned response envelopes show no observed
write-text forwarding, but the literal substring expected-zero condition is
**not met**, and substring identity alone cannot establish provenance.

## Reproduction and validation

With the preserved ledger and post-run home supplied as arguments, from the
repository root:

```sh
nice -n 10 python3.14 spikes/s7/readback.py LEDGER HOME --wire chat --life spikes/s6a/micro_life.json
nice -n 10 python3.14 spikes/s7/readback.py LEDGER HOME --wire responses --life spikes/s6a/micro_life.json
```

The checker prints one JSON object; its item lists contain ids, field keys and
reason codes, never memory or conversation content. A malformed chain or blob
fails closed. The input ledger SHA-256 values are:

- r6: `cbab9d5ad491eb39c4afb2f28183e7447f48ec093d4ef72e7cc777ec4fc11b90`
- r7c: `c163b2077b324b55ea18e012225634e0e3da9fa25c47946d32ffb5a3ada7f6f2`

Validation ran serially at inherited priority 10 with the designated scratch
temporary directory. The sandbox warns when `nice` attempts to increase the
already inherited priority again; the effective priority was verified as 10.

| Validation | Observed result |
|---|---|
| `python3.14 -m unittest` in S7 | 22 tests, OK; both wire formats: mismatch keys per kind (a type-coerced value included), the flag in both directions, future, pending-reply, extra-copy, id and probe leaks, non-write attempts blocked, reaching the harness, and inherited from older history, unissued execution, effect gaps, staged and unparseable results, patch/remove, a patch encompassing earlier writes, text served beside write calls, a tool call on a scripted reply, results split across continuation requests, a refused malformed write, streamed text disagreeing with its items, discard in conversation, tool channels and other fields, and integrity |
| `python3.14 -m unittest` in S6a | 9 tests, OK |
| `python3.14 -m unittest` in S6b | 76 tests, OK; one existing HTTPError resource warning |
| `python3.14 -m pytest spikes/s1 -q` with installed pytest on `PYTHONPATH`, plugin autoload disabled, scratch basetemp | 97 passed |
| Ruff diagnostic multiset against base `1e08e7b` | 56 baseline, 56 candidate; 0 added, 0 removed |
| `git diff --check`; public-check on each changed file | pass |

The standalone pytest command was absent, and the default Python 3.9 runner
failed because the existing S1 tests require strict zip. The final run used
Python 3.14 and the already installed pytest 8.4.2 package, without installation
or download. After S7's last passing test, Ruff's dictionary-literal-only edits
were verified by equal normalised ASTs for both files. Readback was then run
on the final checker. New non-test code is 371 lines, above the approximate
250-line target and below the 400-line stop signal; the extra scope is wire
response decoding, the observed patch/batch effect trace, and the review
round's channel and absence checks.

## Does not prove

- Write-turn behaviour at full scale (S6), or under the frozen suffix text
  (C-6). The suffix stays provisional.
- That another passive system responds to pacing as this one does. Part B is
  not run here and will cover one system on one short life.
- Any memory-system quality: nothing is scored.
- A live write execution, general remove/refusal coverage, or behaviour on any
  other system. These are offline observations from two recorded runs.
