import importlib.util
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location("clone_probe", Path(__file__).with_name("clone_probe.py"))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


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


def test_hardlinks_fail_isolation(tmp_path):
    source = tmp_path / "source"
    probe.generate(source, "plugin", 1)
    result = probe.probe(source, tmp_path / "sandbox", probe.tree_hash(source),
                         0, None, 1, hardlink=True, require_marker=False)
    assert not result["checks"]["original_unchanged"]
    assert not result["checks"]["fresh_nonce_absent"]


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
