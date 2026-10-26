# S3: copy-on-write store clones

## Claim

**advisory** — APFS fixture-store clones isolated every measured probe; this is a mechanics spike with no memory-system score.

## Method

Two synthetic shapes: a native-home shape (markdown memory, SQLite state in WAL mode, and opaque session files) and a plug-in shape (SQLite plus blobs). Each has decimal 10 MB and 100 MB fixtures; the home shape also has a decimal 400 MB fixture. SQLite is checkpointed with TRUNCATE and closed before the ordinary snapshots. Payloads contain only synthetic bytes.

Each cell runs 20 probes distributed across separate worker roots. Each probe clones A with the native clonefile call, commits a fresh nonce to SQLite and appends it to a file, then clones B from the original. It checks the original whole-tree SHA-256, byte-searches B for the nonce, scans both clones for the original absolute path, confirms both writes in A, and checks B's database integrity and original row count. The seeded fixtures contain no absolute paths; this tests their absence, not path relocation.

An additional 1 MB plug-in control retains an idle SQLite connection with a committed WAL-only row and both WAL/SHM files present. No writes occur while its files are cloned. Its fresh clones must recover that row. A separate hardlink control deliberately shares the source files.

Measurement environment: arm64 APFS, 14 CPU cores, Python 3.12.15, SQLite 3.53.1. Processes use nice 19 and background task policy. Clone time covers tree creation, traversal and clonefile calls, excluding marker/load sampling. Percentiles use nearest rank. Throughput is 20 completed probes divided by one cell's wall time, including guard subprocesses, mutation, verification and clone deletion; the initial baseline hash and fixture generation are excluded. There is one cell per fixture/worker pair, no warm-up or repeated throughput trial. This is guarded fixture throughput, not a projection for real probes.

The busy marker and `sysctl -n vm.loadavg` are sampled immediately before every clone. Table load ranges are the one-minute values across the 40 samples per cell; aggregate.csv also records five- and fifteen-minute ranges, marker states, and the minimum free space. Large fixtures run sequentially; only the two small fixtures remain. The planned physical disk envelope is below 0.49 GB: 420 MB maximum fixture payload, bounded small COW writes and test overhead; logical clone sizes are shared extents and are not summed as physical usage.

Reproduce on APFS with caller-supplied scratch, receipt and marker locations (the runner refuses an existing fixture destination):

```sh
nice -n 19 taskpolicy -b uv run --offline --python 3.12 --no-project python spikes/s3/clone_probe.py --scratch "$SCRATCH" --output "$RECEIPTS" --busy-command "$BICENTENNIAL_BUSY_CMD" --workers 1 2 4 8 --probes 20
nice -n 19 taskpolicy -b uv run --offline --python 3.12 --no-project python spikes/s3/summarize.py "$RECEIPTS/measurements.json" --destination spikes/s3
```

## Results

Every timing row has n=40 clones and n=20 completed probes; throughput has one wall-time observation per row.

| Store | Workers | Clone p50 / p95 (ms) | Probes/hour | Wall (s) | Load 1m range | Marker exit |
|---|---:|---:|---:|---:|---|---|
| home-10 | 1 | 8.826 / 47.950 | 3343.0 | 21.538 | 11.23–12.71 | 10 |
| home-10 | 2 | 20.366 / 267.529 | 4426.6 | 16.265 | 10.85–11.27 | 10 |
| plugin-10 | 1 | 10.734 / 146.507 | 3563.5 | 20.205 | 9.94–10.69 | 10 |
| plugin-10 | 2 | 24.504 / 153.528 | 3883.3 | 18.541 | 9.97–10.59 | 10 |
| home-100 | 1 | 13.131 / 107.071 | 2315.1 | 31.100 | 10.10–11.64 | 10 |
| home-100 | 2 | 14.194 / 32.283 | 3995.1 | 18.022 | 10.39–10.85 | 10 |
| plugin-100 | 1 | 7.884 / 17.133 | 3467.9 | 20.762 | 8.50–10.27 | 10 |
| plugin-100 | 2 | 8.505 / 28.249 | 6040.1 | 11.920 | 8.03–8.50 | 10 |
| home-400 | 1 | 6.646 / 15.258 | 1848.8 | 38.944 | 7.27–8.04 | 10 |
| home-400 | 2 | 10.172 / 25.426 | 2903.0 | 24.802 | 7.34–7.98 | 10 |
| uncheckpointed | 1 | 8.986 / 18.246 | 5286.5 | 13.620 | 7.16–7.46 | 10 |

All 440 clone-admission samples reported marker exit 10, state `row`, and `glm=false`; the run stayed within the light-work limit.

Isolation by probe, in zero-based index order 0–19. Each `P` means all five checks passed for that probe; no probe is omitted.

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

The uncheckpointed control had both sidecars present (n=1 fixture) and passed all checks in 20/20 probes, including the WAL-only row. The hardlink negative control was caught in 1/1 probe: the nonce leaked into the original and into fresh B, changing the original tree hash. These are expected failures of isolation.

Focused validation: `8 passed in 3.65s` (n=8 tests).

## What is deferred

Worker counts 4 and 8 were deferred where the immediately preceding marker was not idle; no throughput is inferred for those cells. The committed runner can measure them when the marker exits 0.

Reflinks on other platforms, the SQLite backup API, active-writer snapshots, path-bearing stores, and repeated/cold-cache trials remain deferred.

## Does not prove

No live daemon held a measured ordinary store open. The idle-WAL control does not establish an atomic snapshot under concurrent writes. Real services need their own quiesce/resume protocol. No result establishes any real memory-system layout, relocation behaviour, real probe/model throughput, benchmark score, or the full board's runtime. No memory system was run or tuned.
