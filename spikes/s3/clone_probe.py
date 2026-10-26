"""Synthetic store cloning only; no memory-system or model calls.

Run with Python 3.12 on APFS. Roots and the busy command are supplied by
the caller; outputs contain labels and aggregate metadata, never root paths.
"""

import argparse
import concurrent.futures
from contextlib import closing
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import plistlib
import shlex
import shutil
import sqlite3
import subprocess
import tempfile
import time
import uuid


MB = 1_000_000
LIBC = ctypes.CDLL(None, use_errno=True)
CHECKS = ("original_unchanged", "fresh_nonce_absent", "paths_absent",
          "write_verified", "fresh_database_valid")


def files(root):
    return sorted(p for p in root.rglob("*") if p.is_file())


def tree_hash(root):
    digest = hashlib.sha256()
    for path in files(root):
        digest.update(str(path.relative_to(root)).encode() + b"\0")
        digest.update(path.stat().st_size.to_bytes(8, "big"))
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(MB), b""):
                digest.update(chunk)
    return digest.hexdigest()


def contains(root, needles):
    """Streaming byte search, including matches across chunk boundaries."""
    found = set()
    overlap = max(map(len, needles)) - 1
    for path in files(root):
        tail = b""
        with path.open("rb") as stream:
            while chunk := stream.read(MB):
                data = tail + chunk
                found.update(n for n in needles if n in data)
                tail = data[-overlap:] if overlap else b""
    return found


def layout(root):
    shape = json.loads((root / "fixture.json").read_text())["shape"]
    if shape == "home":
        return root / "state.sqlite", root / "memory" / "note-00.md"
    return root / "store.sqlite", root / "blobs" / "blob-00.txt"


def generate(root, shape, size_mb, wal=False):
    """Return an idle connection only for the explicitly uncheckpointed case."""
    root.mkdir(parents=True, exist_ok=False)
    (root / "fixture.json").write_text(json.dumps({"shape": shape}) + "\n")
    db = root / ("state.sqlite" if shape == "home" else "store.sqlite")
    connection = sqlite3.connect(db)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE entries (id INTEGER PRIMARY KEY, value TEXT)")
    connection.executemany("INSERT INTO entries(value) VALUES (?)",
                           [("synthetic-record-" + str(i) + "-" + "x" * 256,)
                            for i in range(256)])
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    if wal:
        connection.execute("INSERT INTO entries(value) VALUES ('wal-only-record')")
        connection.commit()
    else:
        connection.close()
    names = ([f"memory/note-{i:02}.md" for i in range(4)] +
             [f"sessions/session-{i:02}.jsonl" for i in range(8)]
             if shape == "home" else [f"blobs/blob-{i:02}.txt" for i in range(12)])
    remaining = size_mb * MB - sum(p.stat().st_size for p in files(root))
    block = (b"synthetic fixture content; no external records\n" * 23000)[:MB]
    for index, name in enumerate(names):
        path = root / name
        path.parent.mkdir(exist_ok=True)
        count = remaining // (len(names) - index)
        with path.open("wb") as stream:
            left = count
            while left:
                chunk = block[:min(left, len(block))]
                stream.write(chunk)
                left -= len(chunk)
        remaining -= count
    return connection if wal else None


def clone(source, target, hardlink=False):
    target.mkdir(parents=True, exist_ok=False)
    for path in files(source):
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if hardlink:
            os.link(path, destination)
        elif LIBC.clonefile(os.fsencode(path), os.fsencode(destination), 0):
            raise OSError(ctypes.get_errno(), "clonefile failed")


def mutate(root, nonce):
    db, text = layout(root)
    with closing(sqlite3.connect(db)) as connection:
        with connection:
            connection.execute("INSERT INTO entries(value) VALUES (?)", (nonce,))
    with text.open("a") as stream:
        stream.write("\n" + nonce + "\n")
    with closing(sqlite3.connect(db)) as connection:
        row = connection.execute("SELECT count(*) FROM entries WHERE value=?",
                                 (nonce,)).fetchone()[0]
    return row == 1 and nonce.encode() in text.read_bytes()


def verify(source, first, fresh, baseline, nonce, written, expected_rows=256):
    token, root_path = nonce.encode(), os.fsencode(source.resolve())
    original_unchanged = tree_hash(source) == baseline
    fresh_found = contains(fresh, [token, root_path])
    first_found = contains(first, [root_path])
    # Scan before opening SQLite: recovery can alter sidecar bytes.
    db, _ = layout(fresh)
    with closing(sqlite3.connect(db)) as connection:
        valid = (connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                 and connection.execute("SELECT count(*) FROM entries").fetchone()[0]
                 == expected_rows)
    return dict(zip(CHECKS, [original_unchanged, token not in fresh_found,
                            root_path not in fresh_found | first_found,
                            written, valid]))


def context(workers, busy_command, require_marker=True, scratch=None):
    if busy_command:
        result = subprocess.run(shlex.split(busy_command), capture_output=True,
                                text=True, check=False)
        marker = json.loads(result.stdout)
        code = result.returncode
        # Full marker rows are private operational metadata; retain counts only.
        state = {"exit": code, "state": marker.get("state"),
                 "glm": marker.get("glm"), "rows": len(marker.get("rows", [])),
                 "measurement_locks": len(marker.get("measurement_locks", []))}
        if code not in (0, 10) or (workers > 2 and code != 0):
            raise RuntimeError("marker does not permit this worker count")
    elif require_marker:
        raise RuntimeError("a busy command is required for measurements")
    else:
        state = {"exit": None, "state": "test"}
    free = shutil.disk_usage(scratch if scratch is not None else Path.cwd()).free
    if require_marker and free < 150 * 1024**3:
        raise RuntimeError("free disk below required floor")
    load = subprocess.check_output(["sysctl", "-n", "vm.loadavg"], text=True)
    return {"marker": state, "loadavg": [float(x) for x in load.strip("{} \n").split()],
            "free_gb": round(free / 1024**3, 2)}


def probe(source, sandbox, baseline, index, busy_command, workers,
          expected_rows=256, hardlink=False, require_marker=True):
    sandbox.mkdir(parents=True, exist_ok=False)
    first, fresh = sandbox / "a", sandbox / "b"
    nonce = "probe-nonce-" + uuid.uuid4().hex
    try:
        before = context(workers, busy_command, require_marker, sandbox)
        start = time.perf_counter()
        clone(source, first, hardlink)
        first_seconds = time.perf_counter() - start
        written = mutate(first, nonce)
        second_context = context(workers, busy_command, require_marker, sandbox)
        start = time.perf_counter()
        clone(source, fresh, hardlink)
        fresh_seconds = time.perf_counter() - start
        checks = verify(source, first, fresh, baseline, nonce, written, expected_rows)
        # Each clone timing has its own immediately preceding load/marker sample.
        return {"probe": index, "checks": checks,
                "clones": [{"seconds": first_seconds, **before},
                           {"seconds": fresh_seconds, **second_context}]}
    finally:
        shutil.rmtree(sandbox)


def measure(source, roots, workers, probes, busy_command, expected_rows=256):
    start_context = context(workers, busy_command, scratch=source)
    baseline = tree_hash(source)
    start = time.perf_counter()

    def worker(worker_id):
        root = roots / f"worker-{worker_id}"
        root.mkdir(parents=True, exist_ok=False)
        try:
            return [probe(source, root / f"probe-{i}", baseline, i,
                          busy_command, workers, expected_rows)
                    for i in range(worker_id, probes, workers)]
        finally:
            root.rmdir()

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        rows = [row for group in pool.map(worker, range(workers)) for row in group]
    elapsed = time.perf_counter() - start
    return {"workers": workers, "seconds": elapsed, "probes": probes,
            "probes_per_hour": probes * 3600 / elapsed, "context": start_context,
            "rows": sorted(rows, key=lambda row: row["probe"])}


def percentile(values, quantile):
    ordered = sorted(values)
    # Nearest rank; sample count accompanies both percentiles.
    return ordered[max(0, math.ceil(len(ordered) * quantile) - 1)]


def validate_cell(cell):
    if cell["probes"] <= 0 or len(cell["rows"]) != cell["probes"]:
        raise ValueError("row count differs from positive probe count")
    if any(len(row["clones"]) != 2 for row in cell["rows"]):
        raise ValueError("each probe requires two clone samples")
    if not all(row["checks"][key] for row in cell["rows"] for key in CHECKS):
        raise ValueError("isolation failed")
    if cell["store"] == "uncheckpointed" and not cell["sidecars_present"]:
        raise ValueError("WAL control invalid: sidecars absent")


def wal_pending(db):
    """Sidecars exist, the WAL is non-empty, and the main file alone lacks the WAL row."""
    if not all(Path(str(db) + suffix).exists() for suffix in ("-wal", "-shm")):
        return False
    if Path(str(db) + "-wal").stat().st_size == 0:
        return False
    with tempfile.TemporaryDirectory() as scratch:
        main = Path(scratch) / db.name
        shutil.copyfile(db, main)  # No sidecars: SQLite sees only the main file.
        with closing(sqlite3.connect(main)) as connection:
            return connection.execute("SELECT count(*) FROM entries").fetchone()[0] == 256


def wal_control(source, roots, probes, busy_command):
    keeper = generate(source, "plugin", 1, wal=True)
    try:
        db, _ = layout(source)
        sidecars = wal_pending(db)
        if not sidecars:
            raise ValueError("WAL control invalid: sidecars absent or checkpointed")
        control = measure(source, roots, 1, probes, busy_command, expected_rows=257)
        # A checkpoint during the run would let fresh clones pass from the main file.
        sidecars = wal_pending(db)
        control.update(store="uncheckpointed", sidecars_present=sidecars,
                       wal_pending_checked=True,
                       source_bytes=sum(p.stat().st_size for p in files(source)))
        validate_cell(control)
        return control
    finally:
        keeper.close()
        shutil.rmtree(source)


def environment(scratch):
    # diskutil accepts a device or mount point, not an arbitrary directory.
    mount = subprocess.check_output(["df", "-P", str(scratch)], text=True)
    mount = mount.splitlines()[-1].split(None, 5)[5]
    disk = plistlib.loads(subprocess.check_output(["diskutil", "info", "-plist", mount]))
    return {"architecture": platform.machine(), "system": platform.system(),
            "filesystem": disk["FilesystemType"], "cpu_cores": os.cpu_count(),
            "python": platform.python_version(), "sqlite": sqlite3.sqlite_version}


def run(args):
    disk_plan = {"fixture_payload_mb": 420,
                 "retained_payload_mb": args.retained_payload_mb,
                 "clone_write_allowance_mb": max(args.workers) * 2 * 2,
                 "metadata_test_allowance_mb": 16}
    if sum(disk_plan.values()) >= 500:
        raise ValueError("planned extra disk reaches the 0.5 GB limit")
    args.scratch.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    context(1, args.busy_command, scratch=args.scratch)
    runtime_environment = environment(args.scratch)
    cells = []
    deferred = []
    shapes = [("home", 10), ("plugin", 10), ("home", 100),
              ("plugin", 100), ("home", 400)]
    for shape, size in shapes:
        context(1, args.busy_command, scratch=args.scratch)
        source = args.scratch / f"{shape}-{size}"
        generate(source, shape, size)
        try:
            for workers in args.workers:
                try:
                    context(workers, args.busy_command, scratch=args.scratch)
                except RuntimeError:
                    if workers <= 2:
                        raise
                    deferred.append({"store": source.name, "workers": workers,
                                     "reason": "marker not idle"})
                    continue
                cell = measure(source, args.scratch / "roots", workers,
                               args.probes, args.busy_command)
                cell.update(store=source.name, shape=shape, size_mb=size,
                            source_bytes=sum(p.stat().st_size for p in files(source)))
                validate_cell(cell)
                cells.append(cell)
                (args.output / "measurements.json").write_text(json.dumps(cells, indent=2))
                print(f"{source.name} workers={workers}: {args.probes} probes PASS", flush=True)
        finally:
            if size > 10:
                shutil.rmtree(source)
    # Quiet, open connection keeps WAL/SHM present; this is a separate control,
    # not a claim about an actively writing process or a daemon.
    context(1, args.busy_command, scratch=args.scratch)
    cells.append(wal_control(args.scratch / "wal-control", args.scratch / "wal-roots",
                             args.probes, args.busy_command))
    context(1, args.busy_command, scratch=args.scratch)
    source = args.scratch / "negative-control"
    generate(source, "plugin", 1)
    try:
        negative = probe(source, args.scratch / "hardlink", tree_hash(source), 0,
                         args.busy_command, 1, hardlink=True)
        caught = (not negative["checks"]["original_unchanged"]
                  and not negative["checks"]["fresh_nonce_absent"])
        if not caught:
            raise RuntimeError("hardlink negative control was not caught")
    finally:
        shutil.rmtree(source)
    output = {"cells": cells, "deferred": deferred, "environment": runtime_environment,
              "requested_workers": args.workers, "planned_disk_mb": disk_plan,
              "negative_control": {"caught": caught, **negative}}
    (args.output / "measurements.json").write_text(json.dumps(output, indent=2) + "\n")
    print("WAL control: PASS; hardlink nonce leak: DETECTED", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, nargs="+", choices=[1, 2, 4, 8], default=[1, 2])
    parser.add_argument("--probes", type=int, default=20)
    parser.add_argument("--retained-payload-mb", type=int, default=0)
    parser.add_argument("--busy-command", default=os.environ.get("BICENTENNIAL_BUSY_CMD"))
    run(parser.parse_args())
