# S3: copy-on-write store clones

## Claim

**advisory** — APFS fixture-store clones isolated every measured probe; this is a mechanics spike with no memory-system score.

## Method

Synthetic shapes: a native-home shape (markdown memory, SQLite state in WAL mode, and opaque session files) and a plug-in shape (SQLite plus blobs). Measured fixture labels: home-10, home-100, home-400, plugin-10, plugin-100. Sizes in labels are decimal MB. SQLite is checkpointed with TRUNCATE and closed before the ordinary snapshots. Payloads contain only synthetic bytes.

Cells run 20 probes (see each row), distributed across separate worker roots. Workers are threads in one process, using ThreadPoolExecutor, with one sandbox root per worker. Each probe clones A with the native clonefile call, commits a fresh nonce to SQLite and appends it to a file, then clones B from the original. It checks the original whole-tree SHA-256, byte-searches B for the nonce, scans both clones for the original absolute path, confirms both writes in A, and checks B's database integrity and original row count. The seeded fixtures contain no absolute paths; this tests their absence, not path relocation.

An additional plug-in control retains an idle SQLite connection with a committed WAL-only row and both WAL/SHM files present. No writes occur while its files are cloned. Its fresh clones must recover that row. A separate hardlink control deliberately shares the source files.

Measurement environment: arm64 Darwin, apfs, 14 CPU cores, Python 3.12.15, SQLite 3.53.1. The runner uses nice 19 and background task policy. Clone time covers tree creation, traversal and clonefile calls, excluding marker/load sampling. Percentiles use nearest rank: p95 is the sorted sample at rank ceil(0.95 × n). At n=40, p95 is rank 38. Throughput is each cell's completed probe count divided by its wall time, including guard subprocesses, mutation, verification and clone deletion; the initial baseline hash and fixture generation are excluded. There is one cell per fixture/worker pair, no warm-up or repeated throughput trial. This is guarded fixture throughput, not a projection for real probes.

Recovery: the 10 ordinary cells come from a runner invocation that crashed in diskutil after their timing completed; the WAL/hardlink controls and the environment block come from a separate recovery step run later, at a different machine load (see each row's load range).

The busy marker and `sysctl -n vm.loadavg` are sampled immediately before every clone. Table load ranges are the one-minute values across the 40 samples per cell (see each row); aggregate.csv also records five- and fifteen-minute ranges, marker states, and the minimum free space. Large fixtures run sequentially and are deleted after their cells; the runner keeps only the 2 fixtures of 10 MB or less (home-10, plugin-10). Peak extra disk was planned, not measured. The arithmetic bound is 420 MB maximum fixture payload + 20 MB earlier retained payload + 8 MB for clone writes (2 MB per clone, two clones per worker at 2 workers) + 16 MB metadata/test allowance = 464 MB, below 500 MB. This assumes APFS shared extents and the bounded fixture writes; it is not a measured allocation guarantee. Logical clone sizes are not summed as physical usage.

Reproduce on APFS with caller-supplied scratch, receipt and marker locations (the runner refuses an existing fixture destination). `--retained-payload-mb 20` is machine-specific: it declares payload an earlier run left in the measurement machine's scratch; set it to what your scratch holds (0 when empty).

```sh
nice -n 19 taskpolicy -b uv run --offline --python 3.12 --no-project python spikes/s3/clone_probe.py --scratch "$SCRATCH" --output "$RECEIPTS" --busy-command "$BICENTENNIAL_BUSY_CMD" --workers 1 2 --probes 20 --retained-payload-mb 20
nice -n 19 taskpolicy -b uv run --offline --python 3.12 --no-project python spikes/s3/summarize.py "$RECEIPTS/measurements.json" --destination spikes/s3 --validation "$VALIDATION_LINE"
```

## Results

Timing rows have n=40 clones and n=20 completed probes (individual counts are shown below); throughput has one wall-time observation per row.

| Store | Workers | Clone n | Probe n | Clone p50 / p95 (ms) | Probes/hour | Wall (s) | Load 1m range | Marker exit |
|---|---:|---:|---:|---:|---:|---:|---|---|
| home-10 | 1 | 40 | 20 | 9.644 / 147.683 | 2836.8 | 25.381 | 11.12–14.35 | 10 |
| home-10 | 2 | 40 | 20 | 31.603 / 199.788 | 2668.8 | 26.978 | 13.38–14.87 | 10 |
| plugin-10 | 1 | 40 | 20 | 14.761 / 106.087 | 1259.3 | 57.173 | 13.14–15.83 | 10 |
| plugin-10 | 2 | 40 | 20 | 16.851 / 129.563 | 5804.5 | 12.404 | 14.45–15.52 | 10 |
| home-100 | 1 | 40 | 20 | 7.480 / 24.764 | 3017.2 | 23.863 | 13.30–15.21 | 10 |
| home-100 | 2 | 40 | 20 | 7.480 / 21.466 | 7088.8 | 10.157 | 13.30–15.44 | 10 |
| plugin-100 | 1 | 40 | 20 | 9.746 / 14.019 | 3438.0 | 20.942 | 12.49–15.40 | 10 |
| plugin-100 | 2 | 40 | 20 | 17.399 / 36.115 | 3319.4 | 21.691 | 11.66–12.49 | 10 |
| home-400 | 1 | 40 | 20 | 10.206 / 24.751 | 1561.5 | 46.109 | 10.94–26.16 | 10 |
| home-400 | 2 | 40 | 20 | 9.910 / 13.963 | 2753.6 | 26.148 | 12.93–16.85 | 10 |
| uncheckpointed | 1 | 40 | 20 | 10.198 / 17.594 | 5457.2 | 13.194 | 5.44–6.16 | 10 |

Across 440 clone-admission samples: marker exits 10; states row; glm=true in 0 samples.

Isolation by probe, in zero-based index order within each cell. Each `P` means all 5 checks passed for that probe; no probe is omitted.

| Store | Workers | Probe results |
|---|---:|---|
| home-10 | 1 | `PPPPPPPPPPPPPPPPPPPP` |
| home-10 | 2 | `PPPPPPPPPPPPPPPPPPPP` |
| plugin-10 | 1 | `PPPPPPPPPPPPPPPPPPPP` |
| plugin-10 | 2 | `PPPPPPPPPPPPPPPPPPPP` |
| home-100 | 1 | `PPPPPPPPPPPPPPPPPPPP` |
| home-100 | 2 | `PPPPPPPPPPPPPPPPPPPP` |
| plugin-100 | 1 | `PPPPPPPPPPPPPPPPPPPP` |
| plugin-100 | 2 | `PPPPPPPPPPPPPPPPPPPP` |
| home-400 | 1 | `PPPPPPPPPPPPPPPPPPPP` |
| home-400 | 2 | `PPPPPPPPPPPPPPPPPPPP` |
| uncheckpointed | 1 | `PPPPPPPPPPPPPPPPPPPP` |

The uncheckpointed control had both sidecars present (n=1 fixture) and passed all checks in 20/20 probes, including the WAL-only row. This receipt's control predates the runner's check that the WAL is non-empty and the main file alone lacks the WAL-only row, so it does not exclude a stray checkpoint. Exactly one hardlink negative-control probe is run, and it was caught: the nonce leaked into the original and into fresh B, changing the original tree hash. These are expected failures of isolation.

Focused validation: `22 passed in 0.85s` (caller-supplied test receipt).

## What is deferred

The 4- and 8-worker counts are deferred: the busy marker exited 10 throughout and never 0 (idle), so, as the spec requires, they were left as a script and not run. No throughput is inferred for them; the committed runner can measure them when the marker exits 0.

Reflinks on other platforms, the SQLite backup API, active-writer snapshots, path-bearing stores, and repeated/cold-cache trials remain deferred.

## Does not prove

No live daemon held a measured ordinary store open. The idle-WAL control does not establish an atomic snapshot under concurrent writes. Real services need their own quiesce/resume protocol. No result establishes any real memory-system layout, relocation behaviour, real probe/model throughput, benchmark score, or the full board's runtime. No memory system was run or tuned.
