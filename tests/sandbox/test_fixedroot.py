"""Fixed root trust, cleanup and open-file-description lock lifetime."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from bicentennial.runner.t1 import T1Refused
from bicentennial.sandbox import fixedroot


def test_default_parent():
    assert fixedroot.default_parent("darwin") == "/private/tmp"
    assert fixedroot.default_parent("linux") == "/tmp"
    parent = fixedroot.default_parent()
    assert isinstance(parent, str) and os.path.realpath(parent) == parent


def test_overlaps(tmp_path):
    parent = Path(fixedroot.PARENT)
    for slot in (0, 9):
        base = parent / f"bicentennial-{slot}"
        assert fixedroot.overlaps(base) and fixedroot.overlaps(base / "results" / "deep")
    link = tmp_path / "link"
    link.symlink_to(parent, target_is_directory=True)
    assert fixedroot.overlaps(link / "bicentennial-3" / "out")
    for other in (parent, parent / "bicentennial-10", parent / "bicentennial-0x", tmp_path / "bicentennial-0"):
        assert not fixedroot.overlaps(other)


def test_overlaps_through_a_link_inside_a_base(tmp_path, monkeypatch):
    root = Path(os.path.realpath(tmp_path))
    parent, outside = root / "parent", root / "outside"
    (parent / "bicentennial-2").mkdir(parents=True)
    outside.mkdir()
    (parent / "bicentennial-2" / "alias").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(fixedroot, "PARENT", str(parent))
    # The sweep unlinks the link, so a path spelled through it is refused although it resolves outside.
    assert fixedroot.overlaps(parent / "bicentennial-2" / "alias" / "new-output")
    assert not fixedroot.overlaps(outside / "new-output")


def test_overlaps_other_spelling_of_a_base(tmp_path, monkeypatch):
    parent = Path(os.path.realpath(tmp_path)) / "parent"
    (parent / "bicentennial-4").mkdir(parents=True)
    other = parent / "BICENTENNIAL-4"
    if not other.exists():
        pytest.skip("case-sensitive volume: no other spelling names the base")
    monkeypatch.setattr(fixedroot, "PARENT", str(parent))
    assert fixedroot.overlaps(other) and fixedroot.overlaps(other / "packs")
    assert not fixedroot.overlaps(parent / "BICENTENNIAL-40")


@pytest.mark.parametrize("slot", [-1, 10, "0", None, 0.0, True])
def test_invalid_slot(slot):
    with pytest.raises(T1Refused, match="sandbox_slot"):
        with fixedroot.lease(slot, T1Refused):
            pytest.fail("invalid slot acquired")


def test_busy_and_distinct_slots():
    assert fixedroot.held() == ()
    with fixedroot.lease(0, T1Refused) as base:
        assert base == Path(fixedroot.PARENT) / "bicentennial-0"
        (base / "holder").write_text("untouched")
        with pytest.raises(T1Refused, match="sandbox_busy") as caught:
            with fixedroot.lease(0, T1Refused):
                pytest.fail("busy slot acquired")
        assert caught.value.detail == (f"holder_pid={os.getpid()}",)
        assert (base / "holder").read_text() == "untouched"
        with fixedroot.lease(1, T1Refused) as other:
            assert other != base and len(fixedroot.held()) == 2
    assert fixedroot.held() == ()


@pytest.mark.parametrize("kind", ["symlink", "mode", "owner", "parent", "file", "lock"])
def test_untrusted(tmp_path, monkeypatch, kind):
    parent = Path(fixedroot.PARENT)
    base = parent / "bicentennial-0"
    if kind == "parent":
        link = tmp_path / "parent-link"
        link.symlink_to(parent, target_is_directory=True)
        monkeypatch.setattr(fixedroot, "PARENT", str(link))
    elif kind == "symlink":
        base.symlink_to(tmp_path, target_is_directory=True)
    elif kind == "file":
        base.write_text("not a directory")
    else:
        base.mkdir(mode=0o700)
        if kind == "mode":
            base.chmod(0o755)
        elif kind == "owner":
            monkeypatch.setattr(os, "geteuid", lambda: base.stat().st_uid + 1)
        else:
            (base / ".lock").symlink_to(tmp_path / "target")
    with pytest.raises(T1Refused, match="sandbox_root_untrusted"):
        with fixedroot.lease(0, T1Refused):
            pytest.fail("untrusted root acquired")
    if kind == "parent":
        assert not base.exists()


@pytest.mark.parametrize("error", [False, True])
def test_sweeps(tmp_path, error):
    base = Path(fixedroot.PARENT) / "bicentennial-0"
    base.mkdir(mode=0o700)
    stale = base / "stale" / "nested"
    stale.mkdir(parents=True)
    (stale / "data").write_text("stale")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_text("keep")
    (base / "link").symlink_to(outside, target_is_directory=True)
    try:
        with fixedroot.lease(0, T1Refused):
            assert sorted(p.name for p in base.iterdir()) == [".lock"]
            (base / "own").mkdir()
            (base / "own" / "data").write_text("own")
            if error:
                raise RuntimeError("injected")
    except RuntimeError as caught:
        assert error and str(caught) == "injected"
    assert sorted(p.name for p in base.iterdir()) == [".lock"]
    assert (outside / "keep").read_text() == "keep"


def test_sweep_read_only():
    base = Path(fixedroot.PARENT) / "bicentennial-0"
    with fixedroot.lease(0, T1Refused):
        inner = base / "locked" / "inner"
        inner.mkdir(parents=True)
        (inner / "data").write_text("data")
        inner.chmod(0o555)
        hidden = base / "hidden"
        hidden.mkdir()
        (hidden / "data").write_text("data")
        hidden.chmod(0o000)
    assert sorted(p.name for p in base.iterdir()) == [".lock"]
    with fixedroot.lease(0, T1Refused):
        assert sorted(p.name for p in base.iterdir()) == [".lock"]


@pytest.mark.parametrize("error", [False, True])
def test_failed_exit_sweep(monkeypatch, error):
    # A failed exit sweep never replaces the body's result or refusal; the next lease sweeps again.
    base, real = Path(fixedroot.PARENT) / "bicentennial-0", fixedroot.remove_tree

    def fail(path):
        raise OSError("injected")

    try:
        with fixedroot.lease(0, T1Refused):
            (base / "left").mkdir()
            monkeypatch.setattr(fixedroot, "remove_tree", fail)
            if error:
                raise T1Refused("check_compile")
    except T1Refused as caught:
        assert error and caught.code == "check_compile"
    else:
        assert not error
    monkeypatch.setattr(fixedroot, "remove_tree", real)
    assert (base / "left").is_dir() and fixedroot.held() == ()
    with fixedroot.lease(0, T1Refused):
        assert sorted(p.name for p in base.iterdir()) == [".lock"]


def test_sigkilled_holder():
    code = """
import sys
from bicentennial.sandbox import fixedroot
from bicentennial.runner.t1 import T1Refused
fixedroot.PARENT = sys.argv[1]
with fixedroot.lease(0, T1Refused):
    print('ready', flush=True)
    sys.stdin.read()
"""
    proc = subprocess.Popen([sys.executable, "-c", code, fixedroot.PARENT],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "ready"
        proc.kill()
        proc.wait(timeout=10)
        with fixedroot.lease(0, T1Refused):
            pass
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)


def test_inherited_fd_keeps_busy():
    proc = None
    try:
        with fixedroot.lease(0, T1Refused):
            proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.stdin.read()"],
                                    stdin=subprocess.PIPE, pass_fds=fixedroot.held())
        assert fixedroot.held() == ()
        with pytest.raises(T1Refused, match="sandbox_busy"):
            with fixedroot.lease(0, T1Refused):
                pytest.fail("orphan lost the lease")
        proc.communicate(timeout=10)
        with fixedroot.lease(0, T1Refused):
            pass
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=10)
