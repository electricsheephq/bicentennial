# Fresh-seed follow-up readers

These offline scripts implement the [declaration](../DECLARATION.md), sections
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
`floor` and `controls_broken` describe the full run. It prints one JSON
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
commitment hashes apply to every H arm. Check 3 is one verbose test receipt
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
run has ended. With `--after-reruns`, a pending arm is published as it is only
when `--reruns` names it; any other pending arm is still owed its one rerun,
so the reader prints the pending line with those labels and exits 4.
`--checks-only` prints sections 1–2 only.

| Exit | Meaning |
|---|---|
| 0 | Scores printed, or checks-only with no pending arm |
| 3 | Refused inputs, invalid control, order, pins, pack or check 3; also no arms after reruns |
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
