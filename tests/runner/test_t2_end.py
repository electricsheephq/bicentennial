"""One run end after the full credential scan, with every published file scanned."""

import re
import time
from pathlib import Path

import pytest
from test_t2 import live_settings, read, scenario, t2_scenario  # noqa: F401

from bicentennial.runner import t2, units


def test_one_run_end_after_full_scan(t2_scenario, monkeypatch):  # noqa: F811
    clock, returned_ms = [int(time.time())], []
    scan = t2._scan

    def now():
        clock[0] += 1
        return clock[0]

    def scanned(out, needles):
        scan(out, needles)
        # Model a slow scan without sleeping; later receipt clock reads also differ.
        clock[0] += 60
        returned_ms.append(int(time.time() * 1000))

    monkeypatch.setattr(time, "time", now)
    monkeypatch.setattr(t2, "_scan", scanned)
    assert t2_scenario.invoke() == 0
    timing = read(t2_scenario.out, "units.json")
    assert len(returned_ms) == 1
    assert timing["end_ms"] >= returned_ms[0]
    for name in ("receipt.json", "receipts/system.json", "receipts/no_memory.json"):
        assert read(t2_scenario.out, name)["wall_end_ms"] == timing["end_ms"]
    rows = [{k: v for k, v in row.items() if k != "slots"} for row in timing["units"]]
    assert timing["arm_time"] == t2.calculate_arm_times(
        timing["slots"], rows, timing["start_ms"], timing["end_ms"])


def test_every_published_file_is_scanned(t2_scenario, monkeypatch, tmp_path):  # noqa: F811
    s = t2_scenario
    scan, scan_end, read_bytes = t2._scan, t2._scan_end_files, Path.read_bytes
    full, tail, phase = set(), set(), []

    def scanned(out, needles):
        full.update(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
        return scan(out, needles)

    def end_scanned(out, needles):
        phase.append(out)
        try:
            return scan_end(out, needles)
        finally:
            phase.pop()

    def observed_read(path):
        if phase:
            tail.add(path.relative_to(phase[-1]).as_posix())
        return read_bytes(path)

    monkeypatch.setattr(t2, "_scan", scanned)
    monkeypatch.setattr(t2, "_scan_end_files", end_scanned)
    monkeypatch.setattr(Path, "read_bytes", observed_read)
    assert s.invoke(cache=tmp_path / "cache") == 0
    assert tail == {"units.json", "receipts/system.json", "receipts/no_memory.json", ".receipt.json"}
    assert not full & tail
    assert ".card.json" in full
    assert any(name.startswith("kept/") and name != "kept/index.json" for name in full)
    final_names = {".receipt.json": "receipt.json", ".card.json": "card.json"}
    scanned_names = {final_names.get(name, name) for name in full | tail}
    assert {p.relative_to(s.out).as_posix() for p in s.out.rglob("*") if p.is_file()} == scanned_names


@pytest.mark.parametrize("target", ["units.json", "receipts/system.json", "receipts/no_memory.json", ".receipt.json"])
def test_credential_only_in_end_file_is_refused(t2_scenario, monkeypatch, tmp_path, target):  # noqa: F811
    s, write = t2_scenario, t2._write
    cache = tmp_path / "cache"
    planted = []

    def write_row(out, name, obj):
        if out / name == s.out / target:
            # Receipt rows have no free-text field; inject at the final serialization boundary only.
            obj = dict(obj, units=[dict(row, failure_message="synthetic-access-token") for row in obj["units"]])
            planted.append(target)
        return write(out, name, obj)

    monkeypatch.setattr(t2, "_write", write_row)
    assert s.invoke(cache=cache) == 3
    assert planted == [target]
    assert read(s.out, "refusal.json") == {"code": "credential_scan"}
    assert {p.name for p in s.out.iterdir()} == {"refusal.json"}
    assert not list(cache.glob("*"))


def test_replay_order_erratum_matches_session_constants():
    text = (Path(__file__).resolve().parents[2] / "specs/ring0/RING0.md").read_text()
    erratum = text.split("**Erratum, 2026-11-04 (#391): the replay order.**", 1)[1].split("\n\n", 1)[0]
    match = re.search(r"(\d+) s per replay session and (\d+) s per probe session", erratum)
    assert match is not None
    assert tuple(map(int, match.groups())) == (units.REPLAY_SESSION_SECONDS, units.PROBE_SESSION_SECONDS)
