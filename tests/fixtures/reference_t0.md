The adjacent `reference_t0.json` pins the published `card.json` item outcomes
and aggregates for the installed fixture shared with
`tests/runner/test_t0.py::test_reference_whole_run`, plus one test-local row.
That row adapts `g2-keep-forget-inv-1` to a prompt with no event-word overlap:
restraint passes at 1000 and its action twin omits at 0. This exposes a
maximum-for-minimum bundle regression without changing retrieval or scoring.
The file uses the repository's canonical JSON serializer. Pack paths and item IDs
are sorted, as are JSON keys and aggregate stage/track pairs. Scores are
integer milli-points; no outcome is re-scored by the golden test.

Regenerate from the repository root:

```sh
PYTHONHASHSEED=0 BICENTENNIAL_REGEN_GOLDEN=1 PYTHONPATH=src pytest -q tests/runner/test_reference_golden.py::test_reference_t0_golden
```

The runner refuses without `PYTHONHASHSEED=0`. A regeneration run rewrites
the file and skips instead of passing. Review every changed item and
aggregate. A PR changing the golden JSON must explain why in its body. A
change caused by scoring, retrieval or item generation cites its
`prereg/CHANGELOG.md` entry (and its erratum if it touches the design);
otherwise the PR states that the change is test-only.

For release comparison over every pack in two full T0 output directories:

```sh
python3 scripts/compare_reference_t0.py OLD_RUN NEW_RUN
```

It compares each pack's aggregates, gate verdict and run status. Exit
codes: 0 when all are equal, 1 for differences (including missing packs or
aggregate rows), and 2 for unreadable or malformed input.
