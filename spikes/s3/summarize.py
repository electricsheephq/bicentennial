"""Reduce private measurement receipts to public-safe S3 tables."""

import argparse
import csv
import json
import math
from pathlib import Path

from clone_probe import CHECKS, percentile, validate_cell


def validate(data):
    cells = data["cells"]
    if not cells:
        raise ValueError("empty measurement receipt")
    for cell in cells:
        validate_cell(cell)
        if cell["source_bytes"] <= 0:
            raise ValueError("missing measured source size")
    wal = [c for c in cells if c["store"] == "uncheckpointed"]
    if len(wal) != 1:
        raise ValueError("receipt requires exactly one WAL control")
    negative = data["negative_control"]
    if (not negative["caught"] or negative["checks"]["original_unchanged"]
            or negative["checks"]["fresh_nonce_absent"]):
        raise ValueError("negative control not caught")
    return wal[0]


def summarize(receipt, destination, validation=None):
    data = json.loads(receipt.read_text())
    wal = validate(data)
    cells = data["cells"]
    records = []
    for cell in cells:
        samples = [sample for row in cell["rows"] for sample in row["clones"]]
        times = [sample["seconds"] * 1000 for sample in samples]
        record = {
            "store": cell["store"], "workers": cell["workers"],
            "source_bytes": cell["source_bytes"],
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
    probe_counts = sorted({r["probe_n"] for r in records})
    clone_counts = sorted({r["clone_n"] for r in records})
    probe_n = ", ".join(map(str, probe_counts))
    clone_n = ", ".join(map(str, clone_counts))
    samples = [s for c in cells for row in c["rows"] for s in row["clones"]]
    env = data["environment"]
    plan = data["planned_disk_mb"]
    ordinary = [c for c in cells if c["store"] != "uncheckpointed"]
    fixture_labels = sorted({c["store"] for c in ordinary})
    # The runner deletes fixtures above 10 MB after their cells and keeps the rest.
    kept = sorted({c["store"] for c in ordinary if c.get("size_mb", math.inf) <= 10})
    kept_text = (f"the runner keeps only the {len(kept)} fixtures of 10 MB or less ("
                 + ", ".join(kept) + ")" if kept else "the runner keeps no fixture")
    exits = sorted({s["marker"]["exit"] for s in samples}, key=str)
    recovery = ([f"Recovery: the {len(ordinary)} ordinary cells come from a runner "
                 "invocation that crashed in diskutil after their timing completed; "
                 "the WAL/hardlink controls and the environment block come from a "
                 "separate recovery step run later, at a different machine load "
                 "(see each row's load range).", ""] if data.get("recovery") else [])
    lines = [
        "# S3: copy-on-write store clones", "", "## Claim", "",
        "**advisory** — APFS fixture-store clones isolated every measured probe; "
        "this is a mechanics spike with no memory-system score.", "", "## Method", "",
        "Synthetic shapes: a native-home shape (markdown memory, SQLite state "
        "in WAL mode, and opaque session files) and a plug-in shape (SQLite plus "
        "blobs). Measured fixture labels: " + ", ".join(fixture_labels) +
        ". Sizes in labels are decimal MB. SQLite is checkpointed with TRUNCATE and "
        "closed before the ordinary snapshots. Payloads contain only synthetic bytes.", "",
        f"Cells run {probe_n} probes (see each row), distributed across separate "
        "worker roots. Workers are threads in one process, using ThreadPoolExecutor, "
        "with one sandbox root per worker. Each "
        "probe clones A with the native clonefile call, commits a fresh nonce to "
        "SQLite and appends it to a file, then clones B from the original. It checks "
        "the original whole-tree SHA-256, byte-searches B for the nonce, scans both "
        "clones for the original absolute path, confirms both writes in A, and "
        "checks B's database integrity and original row count. The seeded fixtures "
        "contain no absolute paths; this tests their absence, not path relocation.", "",
        "An additional plug-in control retains an idle SQLite connection "
        "with a committed WAL-only row and both WAL/SHM files present. No writes "
        "occur while its files are cloned. Its fresh clones must recover that row. "
        "A separate hardlink control deliberately shares the source files.", "",
        f"Measurement environment: {env['architecture']} {env['system']}, "
        f"{env['filesystem']}, {env['cpu_cores']} CPU cores, Python {env['python']}, "
        f"SQLite {env['sqlite']}. The runner uses nice 19 and background task policy. Clone "
        "time covers tree creation, traversal and clonefile calls, excluding "
        "marker/load sampling. Percentiles use nearest rank: p95 is the sorted "
        "sample at rank ceil(0.95 × n). " + "; ".join(
            f"At n={n}, p95 is rank {math.ceil(.95 * n)}"
            for n in clone_counts) + ". Throughput is "
        "each cell's completed probe count divided by its wall time, including guard "
        "subprocesses, mutation, verification and clone deletion; the initial "
        "baseline hash and fixture generation are excluded. There is one cell "
        "per fixture/worker pair, no warm-up or repeated throughput trial. This "
        "is guarded fixture throughput, not a projection for real probes.", "",
        *recovery,
        "The busy marker and `sysctl -n vm.loadavg` are sampled immediately "
        "before every clone. Table load ranges are the one-minute values across "
        f"the {clone_n} samples per cell (see each row); aggregate.csv also records five- and "
        "fifteen-minute ranges, marker states, and the minimum free space. "
        f"Large fixtures run sequentially and are deleted after their cells; {kept_text}. "
        f"Peak extra disk was planned, not measured. The arithmetic bound is "
        f"{plan['fixture_payload_mb']} MB maximum fixture payload + "
        f"{plan['retained_payload_mb']} MB earlier retained payload + "
        f"{plan['clone_write_allowance_mb']} MB for clone writes (2 MB per clone, "
        f"two clones per worker at {max(data['requested_workers'])} workers) + "
        f"{plan['metadata_test_allowance_mb']} MB metadata/test allowance = "
        f"{sum(plan.values())} MB, below 500 MB. This assumes APFS shared extents "
        "and the bounded fixture writes; it is not a measured allocation guarantee. "
        "Logical clone sizes are not summed as physical usage.", "",
        "Reproduce on APFS with caller-supplied scratch, receipt and marker "
        "locations (the runner refuses an existing fixture destination). "
        f"`--retained-payload-mb {plan['retained_payload_mb']}` is machine-specific: it "
        "declares payload an earlier run left in the measurement machine's scratch; "
        "set it to what your scratch holds (0 when empty).", "",
        "```sh",
        'nice -n 19 taskpolicy -b uv run --offline --python 3.12 --no-project python spikes/s3/clone_probe.py --scratch "$SCRATCH" --output "$RECEIPTS" --busy-command "$BICENTENNIAL_BUSY_CMD" --workers '
        + " ".join(map(str, data["requested_workers"])) + f" --probes {cells[0]['probes']}"
        + f" --retained-payload-mb {plan['retained_payload_mb']}",
        'nice -n 19 taskpolicy -b uv run --offline --python 3.12 --no-project python spikes/s3/summarize.py "$RECEIPTS/measurements.json" --destination spikes/s3 --validation "$VALIDATION_LINE"',
        "```", "", "## Results", "",
        f"Timing rows have n={clone_n} clones and n={probe_n} completed probes "
        "(individual counts are shown below); "
        "throughput has one wall-time observation per row.", "",
        "| Store | Workers | Clone n | Probe n | Clone p50 / p95 (ms) | Probes/hour | Wall (s) | Load 1m range | Marker exit |",
        "|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for r in records:
        lines.append(f"| {r['store']} | {r['workers']} | {r['clone_n']} | {r['probe_n']} | {r['p50_ms']:.3f} / {r['p95_ms']:.3f} "
                     f"| {r['probes_per_hour']:.1f} | {r['elapsed_s']:.3f} "
                     f"| {r['load1_min']:.2f}–{r['load1_max']:.2f} | {r['marker_exits']} |")
    lines += ["", f"Across {len(samples)} clone-admission samples: marker exits "
              + ", ".join(map(str, sorted({s['marker']['exit'] for s in samples})))
              + "; states " + ", ".join(sorted({s['marker']['state'] for s in samples}))
              + f"; glm=true in {sum(bool(s['marker']['glm']) for s in samples)} samples."]
    lines += ["", "Isolation by probe, in zero-based index order within each cell. Each `P` "
              f"means all {len(CHECKS)} checks passed for that probe; no probe is omitted.", "",
              "| Store | Workers | Probe results |", "|---|---:|---|"]
    for cell in cells:
        flags = "".join("P" if all(row["checks"][key] for key in CHECKS) else "F"
                        for row in cell["rows"])
        lines.append(f"| {cell['store']} | {cell['workers']} | `{flags}` |")
    wal_n = len(wal["rows"])
    lines += ["", f"The uncheckpointed control had both sidecars present (n={sum(c['store'] == 'uncheckpointed' for c in cells)} fixture) "
              f"and passed all checks in {wal_n}/{wal['probes']} probes, including the WAL-only row. "
              + ("" if wal.get("wal_pending_checked") else
                 "This receipt's control predates the runner's check that the WAL is "
                 "non-empty and the main file alone lacks the WAL-only row, so it does "
                 "not exclude a stray checkpoint. ") +
              "Exactly one hardlink negative-control probe is run, and it was caught: the nonce "
              "leaked into the original and into fresh B, changing the original "
              "tree hash. These are expected failures of isolation.", "",
              "Focused validation: " + (f"`{validation}` (caller-supplied test receipt)."
                                        if validation else "not supplied; see PR evidence."), "",
              "## What is deferred", ""]
    deferred_workers = sorted({1, 2, 4, 8} - {r["workers"] for r in records})
    if deferred_workers:
        reason = ("the busy marker exited " + ", ".join(map(str, exits)) +
                  " throughout and never 0 (idle), so, as the spec requires, they "
                  "were left as a script and not run" if 0 not in exits else
                  "they were not requested, or the immediately preceding marker "
                  "was not idle")
        lines.append("The " + "- and ".join(map(str, deferred_workers)) +
                     "-worker counts are deferred: " + reason + ". No throughput "
                     "is inferred for them; the committed runner can measure them "
                     "when the marker exits 0.")
    else:
        lines.append("No worker count was deferred.")
    lines += ["", "Reflinks on other platforms, the SQLite backup API, active-writer "
              "snapshots, path-bearing stores, and repeated/cold-cache trials remain deferred.",
              "", "## Does not prove", "",
              "No live daemon held a measured ordinary store open. The idle-WAL "
              "control does not establish an atomic snapshot under concurrent "
              "writes. Real services need their own quiesce/resume protocol. "
              "No result establishes any real memory-system layout, relocation "
              "behaviour, real probe/model throughput, benchmark score, or the "
              "full board's runtime. No memory system was run or tuned.", ""]
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / "aggregate.csv").open("w") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    (destination / "REPORT.md").write_text("\n".join(lines))
    print(f"Summary: {len(cells)} cells; "
          f"{sum(c['probes'] for c in cells)} probes; negative control detected")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--validation", help="verbatim result line from focused tests")
    args = parser.parse_args()
    summarize(args.receipt, args.destination, args.validation)
