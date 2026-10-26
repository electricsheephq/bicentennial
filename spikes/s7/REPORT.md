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
| A2 literal boundary scan | 6 future-text hits, all inherited; 0 introduced; 0 life-id hits | 1 future-text hit, inherited; 0 introduced; 0 life-id hits |
| A3 tool boundary | 60 memory definitions offered; 14 executed calls with valid issued ids; 0 provenance/filter failures; 0 non-write attempts | 60 memory definitions; 1 executed call with valid issued id; 0 failures; 0 non-write attempts |
| A4 effect | 14 applied, 0 refused; 11 original contents in final store; 13 original contents visible next session; 14/14 store and next-session effects satisfied after later patches | 1 applied, 0 refused; 1/1 original content in final store and next session; 0 gaps |
| A5 discard | 60/60 scripted replies match; 0 missing; 46 nonempty write responses checked; 0 whole-content matches later; 137 substring collisions and 318 configuration-value collisions | 60/60 scripted replies match; 0 missing; 59 nonempty write responses checked; 0 whole-content matches later; 215 substring collisions; 0 configuration collisions |

## Method and discrepancies

A1 reconstructs each forwarded body from the triggering harness request, using
independent code and the public provisional suffix. Chat changes only the model,
stream and transport keys, appends the suffix, and filters tools. Responses
preserves other fields, sets its declared streaming transport, wraps plain
message strings in role-appropriate typed text parts, and appends the suffix
item. Models are pinned in the checker rather than taken from the observed body.
No director readback function is imported. There are no A1 mismatches to explain.

A2 scans every later scripted user/assistant string, including probe questions,
and life id/reference values and event-map keys. Literal matches are retained:
r6 record 43 and r7c record 49 contain the repeated user turn identified as
`8:5:user`; r6 records 90, 92, 93, 94 and 97 contain `8:2:assistant`, the short
branch answer already in the conversation or memory. Each is also present in
that record's triggering harness request. The literal expected-zero condition
is therefore **not met**; the introduced-hit count is zero. The scan is not
silently relaxed to obtain zero.

A3 pairs upstream memory arguments with returned calls in order, checks the
exact monotonic `bcw` ids used by both recorded directors, and finds tool results
in the following harness request. Newly appearing unissued result ids fail the
check. Both runs attempted only memory calls, so rejection of a model's
non-write attempt is exercised by synthetic tests rather than by these runs.

A4 reads Hermes' explicit success result, and compares content after whitespace
normalisation only. It reads the final target file and only the system prompt
or Responses instructions of the first main request of the next session. The
last r6 call is checked against the first probe session (record 125). Refusals
are separate from applications; an unclassified result is a gap. A remove must
be absent, and patch operations propagate the earlier span through later
successful calls in the same target.

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

A5 checks scripted response contents and scans later conversational text for
write-response substrings. A separate scan retains equal values in configuration.
Every conversation hit is the same four-character no-write reply occurring in
unrelated compression material: r6 has 53 write-record/request pairs in
compression instructions and 84 in summary tool-use annotations; r7c has 69 and
146 respectively. All 318 r6 configuration collisions are reasoning-setting
values. The full pair lists are retained in the JSON; complete conversational
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
| `python3.14 -m unittest` in S7 | 10 tests, OK; both wire formats, mismatch keys, future/id/probe leaks, non-write attempts, unissued execution, effect gaps, patch/remove, discard and integrity |
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
on the final checker. New non-test code is 328 lines, above the approximate
250-line target and below the 400-line stop signal; the extra scope is wire
response decoding and the observed patch/batch effect trace.

## Does not prove

- Write-turn behaviour at full scale (S6), or under the frozen suffix text
  (C-6). The suffix stays provisional.
- That another passive system responds to pacing as this one does. Part B is
  not run here and will cover one system on one short life.
- Any memory-system quality: nothing is scored.
- A live write execution, general remove/refusal coverage, or behaviour on any
  other system. These are offline observations from two recorded runs.
