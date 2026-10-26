import importlib.util
import copy
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


spec = importlib.util.spec_from_file_location("clone_probe", Path(__file__).with_name("clone_probe.py"))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
sys.modules["clone_probe"] = probe
import summarize as summary


requires_macos = pytest.mark.skipif(sys.platform != "darwin",
                                    reason="clonefile and vm.loadavg require macOS/APFS")


@requires_macos
@pytest.mark.parametrize("shape", ["home", "plugin"])
def test_clean_clone_isolation(tmp_path, shape):
    source = tmp_path / "source"
    probe.generate(source, shape, 1)
    assert not list(source.glob("*-wal"))
    assert not list(source.glob("*-shm"))
    result = probe.probe(source, tmp_path / "sandbox", probe.tree_hash(source),
                         0, None, 1, require_marker=False)
    assert all(result["checks"].values())
    assert not (tmp_path / "sandbox").exists()


@requires_macos
def test_uncheckpointed_wal_is_preserved(tmp_path):
    source = tmp_path / "source"
    keeper = probe.generate(source, "plugin", 1, wal=True)
    try:
        assert list(source.glob("*-wal"))
        assert list(source.glob("*-shm"))
        result = probe.probe(source, tmp_path / "sandbox", probe.tree_hash(source),
                             0, None, 1, expected_rows=257, require_marker=False)
        assert all(result["checks"].values())
    finally:
        keeper.close()


@requires_macos
def test_hardlinks_fail_isolation(tmp_path):
    source = tmp_path / "source"
    probe.generate(source, "plugin", 1)
    result = probe.probe(source, tmp_path / "sandbox", probe.tree_hash(source),
                         0, None, 1, hardlink=True, require_marker=False)
    assert not result["checks"]["original_unchanged"]
    assert not result["checks"]["fresh_nonce_absent"]


@requires_macos
def test_embedded_original_path_is_detected(tmp_path):
    source = tmp_path / "source"
    probe.generate(source, "plugin", 1)
    _, text = probe.layout(source)
    with text.open("a") as stream:
        stream.write(str(source.resolve()))
    result = probe.probe(source, tmp_path / "sandbox", probe.tree_hash(source),
                         0, None, 1, require_marker=False)
    assert not result["checks"]["paths_absent"]
    assert result["checks"]["original_unchanged"]


def test_byte_search_chunk_boundary(tmp_path):
    token = b"boundary-needle"
    (tmp_path / "blob").write_bytes(b"x" * (probe.MB - 3) + token)
    assert token in probe.contains(tmp_path, [token])


@requires_macos
def test_parallel_roots_are_distinct(tmp_path, monkeypatch):
    source = tmp_path / "source"
    probe.generate(source, "home", 1)
    real_context = probe.context
    monkeypatch.setattr(probe, "context", lambda *a, **k: real_context(2, None, False))
    result = probe.measure(source, tmp_path / "roots", 2, 4, None)
    assert len(result["rows"]) == 4
    assert all(all(row["checks"].values()) for row in result["rows"])
    assert not list((tmp_path / "roots").iterdir())


def test_busy_marker_blocks_elevated_workers(monkeypatch):
    class Result:
        returncode = 10
        stdout = '{"state":"row","glm":false,"rows":[]}'
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **k: Result())
    with pytest.raises(RuntimeError, match="marker"):
        probe.context(4, "synthetic-marker")


def receipt_fixture():
    sample = {"seconds": .001, "marker": {"exit": 0, "state": "idle", "glm": False},
              "free_gb": 200, "loadavg": [1, 2, 3]}
    row = {"probe": 0, "checks": dict.fromkeys(probe.CHECKS, True),
           "clones": [copy.deepcopy(sample), copy.deepcopy(sample)]}
    cell = {"store": "uncheckpointed", "workers": 1, "probes": 1, "seconds": 1,
            "probes_per_hour": 3600, "source_bytes": 123456, "sidecars_present": True,
            "rows": [row]}
    negative = {"caught": True, "checks": {"original_unchanged": False,
                                          "fresh_nonce_absent": False}}
    return {"cells": [cell], "negative_control": negative, "deferred": [],
            "environment": {"architecture": "fixture", "system": "Darwin",
                            "filesystem": "apfs", "cpu_cores": 2,
                            "python": "fixture", "sqlite": "fixture"},
            "requested_workers": [1],
            "planned_disk_mb": {"fixture_payload_mb": 420, "retained_payload_mb": 0,
                                "clone_write_allowance_mb": 4,
                                "metadata_test_allowance_mb": 16}}


def test_disk_guard_uses_scratch_volume(tmp_path, monkeypatch):
    seen = []

    def usage(path):
        seen.append(path)
        return SimpleNamespace(free=149 * 1024**3)

    monkeypatch.setattr(probe.shutil, "disk_usage", usage)
    monkeypatch.setattr(probe.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=0, stdout='{"state":"idle","glm":false,"rows":[]}'))
    with pytest.raises(RuntimeError, match="free disk"):
        probe.context(1, "synthetic-marker", scratch=tmp_path)
    assert seen == [tmp_path]


def test_environment_queries_mount_point(tmp_path, monkeypatch):
    calls = []

    def output(args, **kwargs):
        calls.append(args)
        if args[0] == "df":
            return "Filesystem 512-blocks Used Available Capacity Mounted on\n" \
                   "fixture 100 10 90 10% /fixture volume\n"
        return probe.plistlib.dumps({"FilesystemType": "apfs"})

    monkeypatch.setattr(probe.subprocess, "check_output", output)
    assert probe.environment(tmp_path)["filesystem"] == "apfs"
    assert calls == [["df", "-P", str(tmp_path)],
                     ["diskutil", "info", "-plist", "/fixture volume"]]


@pytest.mark.parametrize("invalid", ["sidecars", "checks"])
def test_runner_rejects_invalid_wal_control(tmp_path, monkeypatch, invalid):
    control = receipt_fixture()["cells"][0]
    if invalid == "checks":
        control["rows"][0]["checks"]["fresh_database_valid"] = False
    else:
        real_exists = Path.exists
        monkeypatch.setattr(Path, "exists", lambda p: False if str(p).endswith("-shm")
                            else real_exists(p))
    monkeypatch.setattr(probe, "measure", lambda *a, **k: control)
    with pytest.raises(ValueError, match="sidecars|isolation"):
        probe.wal_control(tmp_path / "source", tmp_path / "roots", 1, None)


@pytest.mark.parametrize("invalid", ["rows", "checks", "sidecars", "negative", "wal"])
def test_invalid_receipt_writes_nothing_even_optimized(tmp_path, invalid):
    data = receipt_fixture()
    if invalid == "rows":
        data["cells"][0]["probes"] = 2
    elif invalid == "checks":
        data["cells"][0]["rows"][0]["checks"]["fresh_database_valid"] = False
    elif invalid == "sidecars":
        data["cells"][0]["sidecars_present"] = False
    elif invalid == "negative":
        data["negative_control"]["caught"] = False
    else:
        data["cells"][0]["store"] = "ordinary"
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(data))
    destination = tmp_path / "summary"
    destination.mkdir()
    for name in ("aggregate.csv", "REPORT.md"):
        (destination / name).write_text("prior output")
    result = subprocess.run([sys.executable, "-O", summary.__file__, str(receipt),
                             "--destination", str(destination)], capture_output=True)
    assert result.returncode != 0
    assert all(p.read_text() == "prior output" for p in destination.iterdir())


def test_summary_derives_counts_environment_and_wal_size(tmp_path):
    data = receipt_fixture()
    ordinary = copy.deepcopy(data["cells"][0])
    ordinary.update(store="plugin-1", workers=4, probes=2)
    ordinary["rows"].append(copy.deepcopy(ordinary["rows"][0]))
    ordinary["rows"][1]["probe"] = 1
    data["cells"].append(ordinary)  # WAL control need not be last.
    data["requested_workers"] = [1, 4]
    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps(data))
    summary.summarize(receipt, tmp_path / "summary", "fixture test receipt")
    report = (tmp_path / "summary" / "REPORT.md").read_text()
    assert "n=2, 4 clones and n=1, 2 completed probes" in report
    assert "Across 6 clone-admission samples" in report
    assert "1/1 probes" in report
    assert "fixture Darwin, apfs, 2 CPU cores" in report
    assert "fixture test receipt" in report
    assert "123456" in (tmp_path / "summary" / "aggregate.csv").read_text()
    assert "440 clone-admission" not in report and "20/20" not in report
