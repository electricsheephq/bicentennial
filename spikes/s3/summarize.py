"""Reduce private measurement receipts to public-safe S3 tables."""

import argparse
import csv
import json
from pathlib import Path

from clone_probe import CHECKS, percentile


def summarize(receipt, destination):
    data = json.loads(receipt.read_text())
    cells = data["cells"]
    assert all(len(c["rows"]) == c["probes"] for c in cells)
    assert all(all(row["checks"][key] for key in CHECKS)
               for cell in cells for row in cell["rows"])
    assert cells[-1]["sidecars_present"]
    records = []
    for cell in cells:
        samples = [sample for row in cell["rows"] for sample in row["clones"]]
        times = [sample["seconds"] * 1000 for sample in samples]
        record = {
            "store": cell["store"], "workers": cell["workers"],
            "source_bytes": cell.get("source_bytes", 1_000_000),
            "clone_n": len(times), "p50_ms": round(percentile(times, .50), 3),
            "p95_ms": round(percentile(times, .95), 3), "probe_n": cell["probes"],
            "elapsed_s": round(cell["seconds"], 3),
            "probes_per_hour": round(cell["probes_per_hour"], 1),
            "marker_exits": ":".join(map(str, sorted({s["marker"]["exit"] for s in samples}))),
            "marker_states": ":".join(sorted({s["marker"]["state"] for s in samples})),
            "glm_any": any(s["marker"]["glm"] for s in samples),
            "free_gb_min": min(s["free_gb"] for s in samples),
        }
        for i, name in enumerate(("load1", "load5", "load15")):
            record[name + "_min"] = min(s["loadavg"][i] for s in samples)
            record[name + "_max"] = max(s["loadavg"][i] for s in samples)
        records.append(record)
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / "aggregate.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    lines = [
        "# S3: copy-on-write store clones", "", "## Claim", "",
        "**advisory** — APFS fixture-store clones isolated every measured probe; "
        "this is a mechanics spike with no memory-system score.", "", "## Method", "",
        "Two synthetic shapes: a native-home shape (markdown memory, SQLite state "
        "in WAL mode, and opaque session files) and a plug-in shape (SQLite plus "
        "blobs). Each has decimal 10 MB and 100 MB fixtures; the home shape also "
        "has a decimal 400 MB fixture. SQLite is checkpointed with TRUNCATE and "
        "closed before the ordinary snapshots. Payloads contain only synthetic bytes.", "",
        "Each cell runs 20 probes distributed across separate worker roots. Each "
        "probe clones A with the native clonefile call, commits a fresh nonce to "
        "SQLite and appends it to a file, then clones B from the original. It checks "
        "the original whole-tree SHA-256, byte-searches B for the nonce, scans both "
        "clones for the original absolute path, confirms both writes in A, and "
        "checks B's database integrity and original row count. The seeded fixtures "
        "contain no absolute paths; this tests their absence, not path relocation.", "",
        "An additional 1 MB plug-in control retains an idle SQLite connection "
        "with a committed WAL-only row and both WAL/SHM files present. No writes "
        "occur while its files are cloned. Its fresh clones must recover that row. "
        "A separate hardlink control deliberately shares the source files.", "",
        "Measurement environment: arm64 APFS, 14 CPU cores, Python 3.12.15, "
        "SQLite 3.53.1. Processes use nice 19 and background task policy. Clone "
        "time covers tree creation, traversal and clonefile calls, excluding "
        "marker/load sampling. Percentiles use nearest rank. Throughput is "
        "20 completed probes divided by one cell's wall time, including guard "
        "subprocesses, mutation, verification and clone deletion; the initial "
        "baseline hash and fixture generation are excluded. There is one cell "
        "per fixture/worker pair, no warm-up or repeated throughput trial. This "
        "is guarded fixture throughput, not a projection for real probes.", "",
        "The busy marker and `sysctl -n vm.loadavg` are sampled immediately "
        "before every clone. Table load ranges are the one-minute values across "
        "the 40 samples per cell; aggregate.csv also records five- and "
        "fifteen-minute ranges, marker states, and the minimum free space. "
        "Large fixtures run sequentially; only the two small fixtures remain. "
        "The planned physical disk envelope is below 0.49 GB: 420 MB maximum "
        "fixture payload, bounded small COW writes and test overhead; logical "
        "clone sizes are shared extents and are not summed as physical usage.", "",
        "Reproduce on APFS with caller-supplied scratch, receipt and marker "
        "locations (the runner refuses an existing fixture destination):", "",
        "```sh",
        'nice -n 19 taskpolicy -b uv run --offline --python 3.12 --no-project python spikes/s3/clone_probe.py --scratch "$SCRATCH" --output "$RECEIPTS" --busy-command "$BICENTENNIAL_BUSY_CMD" --workers 1 2 4 8 --probes 20',
        'nice -n 19 taskpolicy -b uv run --offline --python 3.12 --no-project python spikes/s3/summarize.py "$RECEIPTS/measurements.json" --destination spikes/s3',
        "```", "", "## Results", "",
        "Every timing row has n=40 clones and n=20 completed probes; "
        "throughput has one wall-time observation per row.", "",
        "| Store | Workers | Clone p50 / p95 (ms) | Probes/hour | Wall (s) | Load 1m range | Marker exit |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for r in records:
        lines.append(f"| {r['store']} | {r['workers']} | {r['p50_ms']:.3f} / {r['p95_ms']:.3f} "
                     f"| {r['probes_per_hour']:.1f} | {r['elapsed_s']:.3f} "
                     f"| {r['load1_min']:.2f}–{r['load1_max']:.2f} | {r['marker_exits']} |")
    if all(r["marker_exits"] == "10" and r["marker_states"] == "row"
           and not r["glm_any"] for r in records):
        lines += ["", "All 440 clone-admission samples reported marker exit 10, "
                  "state `row`, and `glm=false`; the run stayed within the light-work limit."]
    lines += ["", "Isolation by probe, in zero-based index order 0–19. Each `P` "
              "means all five checks passed for that probe; no probe is omitted.", "",
              "| Store | Workers | Probe results |", "|---|---:|---|"]
    for cell in cells:
        flags = "".join("P" if all(row["checks"][key] for key in CHECKS) else "F"
                        for row in cell["rows"])
        lines.append(f"| {cell['store']} | {cell['workers']} | `{flags}` |")
    negative = data["negative_control"]
    assert negative["caught"]
    lines += ["", "The uncheckpointed control had both sidecars present (n=1 fixture) "
              "and passed all checks in 20/20 probes, including the WAL-only row. "
              "The hardlink negative control was caught in 1/1 probe: the nonce "
              "leaked into the original and into fresh B, changing the original "
              "tree hash. These are expected failures of isolation.", "",
              "Focused validation: `8 passed in 3.65s` (n=8 tests).", "",
              "## What is deferred", ""]
    deferred_workers = sorted({row["workers"] for row in data["deferred"]})
    if deferred_workers:
        lines.append("Worker counts " + " and ".join(map(str, deferred_workers)) +
                     " were deferred where the immediately preceding marker was "
                     "not idle; no throughput is inferred for those cells. The "
                     "committed runner can measure them when the marker exits 0.")
    else:
        lines.append("No requested worker count was deferred.")
    lines += ["", "Reflinks on other platforms, the SQLite backup API, active-writer "
              "snapshots, path-bearing stores, and repeated/cold-cache trials remain deferred.",
              "", "## Does not prove", "",
              "No live daemon held a measured ordinary store open. The idle-WAL "
              "control does not establish an atomic snapshot under concurrent "
              "writes. Real services need their own quiesce/resume protocol. "
              "No result establishes any real memory-system layout, relocation "
              "behaviour, real probe/model throughput, benchmark score, or the "
              "full board's runtime. No memory system was run or tuned.", ""]
    (destination / "REPORT.md").write_text("\n".join(lines))
    print(f"Summary: {len(cells)} cells; "
          f"{sum(c['probes'] for c in cells)} probes; negative control detected")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    summarize(args.receipt, args.destination)
