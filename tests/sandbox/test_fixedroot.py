"""Fixed root trust, cleanup and open-file-description lock lifetime."""

import errno
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
    # A link outside into the base, then the base's link back out: the sweep would unlink the second.
    (outside / "into").symlink_to(parent / "bicentennial-2" / "alias", target_is_directory=True)
    assert fixedroot.overlaps(outside / "into" / "results")


def test_overlaps_other_spelling_of_a_base(tmp_path, monkeypatch):
    parent = Path(os.path.realpath(tmp_path)) / "parent"
    (parent / "bicentennial-4").mkdir(parents=True)
    other = parent / "BICENTENNIAL-4"
    if not other.exists():
        pytest.skip("case-sensitive volume: no other spelling names the base")
    monkeypatch.setattr(fixedroot, "PARENT", str(parent))
    assert fixedroot.overlaps(other) and fixedroot.overlaps(other / "packs")
    assert not fixedroot.overlaps(parent / "BICENTENNIAL-40")



def test_overlaps_dotdot_after_a_link(tmp_path, monkeypatch):
    root = Path(os.path.realpath(tmp_path))
    parent, outside = root / "parent", root / "outside"
    (parent / "bicentennial-5" / "deep").mkdir(parents=True)
    (outside / "a" / "b").mkdir(parents=True)
    (root / "far" / "deep").mkdir(parents=True)
    monkeypatch.setattr(fixedroot, "PARENT", str(parent))
    # `..` applies to where the link before it leads, as the system resolves the path.
    (outside / "jump").symlink_to(parent / "bicentennial-5" / "deep", target_is_directory=True)
    assert fixedroot.overlaps(f"{outside}/jump/../packs")
    (parent / "bicentennial-5" / "escape").symlink_to(outside / "a" / "b", target_is_directory=True)
    assert fixedroot.overlaps(f"{parent}/bicentennial-5/escape/../../result")
    (parent / "jump").symlink_to(root / "far" / "deep", target_is_directory=True)
    assert not fixedroot.overlaps(f"{parent}/jump/../bicentennial-5/out")


def test_overlaps_other_case_of_a_missing_base(tmp_path, monkeypatch):
    parent = Path(os.path.realpath(tmp_path)) / "parent"
    parent.mkdir()
    monkeypatch.setattr(fixedroot, "PARENT", str(parent))
    # No base exists yet, so no identity can match: the name in any case under the parent's identity does.
    assert fixedroot.overlaps(parent / "BICENTENNIAL-0" / "results")
    assert fixedroot.overlaps(f"{parent}/x/../Bicentennial-7")
    assert not fixedroot.overlaps(parent / "BICENTENNIAL-40" / "results")
    assert not fixedroot.overlaps(Path(os.path.realpath(tmp_path)) / "BICENTENNIAL-0")
    assert sorted(p.name for p in parent.iterdir()) == []

def test_overlaps_ignores_a_linked_base(tmp_path, monkeypatch):
    root = Path(os.path.realpath(tmp_path))
    parent, data = root / "parent", root / "data"
    (parent / "bicentennial-0").mkdir(parents=True)
    data.mkdir()
    monkeypatch.setattr(fixedroot, "PARENT", str(parent))
    # A linked base is never leased, so its target is no base: one malformed slot must not refuse every path.
    (parent / "bicentennial-9").symlink_to("/", target_is_directory=True)
    (parent / "bicentennial-8").symlink_to(data, target_is_directory=True)
    assert not fixedroot.overlaps(root / "out") and not fixedroot.overlaps(data / "packs")
    assert fixedroot.overlaps(parent / "bicentennial-0" / "out")


def test_within(tmp_path):
    root = Path(os.path.realpath(tmp_path))
    scratch, outside = root / "scratch", root / "outside"
    (scratch / "check-B0-0").mkdir(parents=True)
    outside.mkdir()
    assert fixedroot.within(scratch, scratch) and fixedroot.within(scratch / "check-B0-0" / "new", scratch)
    assert not fixedroot.within(outside, scratch) and not fixedroot.within(root, scratch)
    (outside / "jump").symlink_to(scratch / "check-B0-0", target_is_directory=True)
    assert fixedroot.within(outside / "jump" / "life", scratch)
    assert fixedroot.within(f"{outside}/../scratch/x", scratch)
    # A link spelled inside scratch is unlinked by a reset, so it is inside although its target is not.
    (scratch / "check-B0-0" / "alias").symlink_to(outside, target_is_directory=True)
    assert fixedroot.within(scratch / "check-B0-0" / "alias", scratch)
    # An outside link into a job root, then an input link there: the walk visits the job root.
    (outside / "safe-pin.json").write_text("{}")
    (scratch / "check-B0-0" / "pin.json").symlink_to(outside / "safe-pin.json")
    (outside / "jump2").symlink_to(scratch / "check-B0-0", target_is_directory=True)
    assert fixedroot.within(outside / "jump2" / "pin.json", scratch)
    # A link read on the way, even when the path ends outside.
    (scratch / "check-B0-0" / "hop").symlink_to(outside, target_is_directory=True)
    (outside / "jump3").symlink_to(scratch / "check-B0-0" / "hop", target_is_directory=True)
    assert fixedroot.within(outside / "jump3" / "safe-pin.json", scratch)
    # A resolution the walk cannot finish is refused: a loop, and a chain longer than the bound into a job root.
    loop = root / "loop"
    loop.symlink_to(loop)
    assert fixedroot.within(loop / "x", scratch)
    chain = scratch / "check-B0-0"
    for i in range(41):
        (outside / f"c{i}").symlink_to(chain, target_is_directory=True)
        chain = outside / f"c{i}"
    assert fixedroot.within(chain / "pin.json", scratch)
    assert fixedroot.within(outside / "c40", scratch) and not fixedroot.within(outside / "safe-pin.json", scratch)
    other = root / "SCRATCH"
    if other.exists():
        assert fixedroot.within(other / "check-B0-0", scratch)
    assert not fixedroot.within(outside, root / "missing")



def test_within_propagates_unexpected_errors(tmp_path, monkeypatch):
    # Only a missing entry ends a branch; any other error propagates, so the caller refuses instead of guessing.
    root = Path(os.path.realpath(tmp_path))
    scratch, outside = root / "scratch", root / "outside"
    (scratch / "check-B0-0").mkdir(parents=True)
    outside.mkdir()

    def failing(real, target):
        def call(path, *args, **kwargs):
            if Path(path) == target:
                raise OSError(errno.EIO, "injected")
            return real(path, *args, **kwargs)
        return call

    with monkeypatch.context() as patch:
        patch.setattr(os, "stat", failing(os.stat, scratch))
        with pytest.raises(OSError):
            fixedroot.within(scratch / "check-B0-0", scratch)
    with monkeypatch.context() as patch:
        patch.setattr(os, "lstat", failing(os.lstat, outside))
        with pytest.raises(OSError):
            fixedroot.within(outside / "pin.json", scratch)
    assert not fixedroot.within(root / "missing" / "pin.json", scratch)
    assert not fixedroot.within(outside / "pin.json", root / "no-scratch")

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


@pytest.mark.parametrize("kind", ["symlink", "mode", "owner", "parent", "file", "lock", "hardlink"])
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
        elif kind == "hardlink":
            # The lease truncates its lock, which would empty the file a hard link shares.
            precious = parent / "precious"
            precious.write_text("keep")
            os.link(precious, base / ".lock")
        else:
            (base / ".lock").symlink_to(tmp_path / "target")
    with pytest.raises(T1Refused, match="sandbox_root_untrusted"):
        with fixedroot.lease(0, T1Refused):
            pytest.fail("untrusted root acquired")
    if kind == "parent":
        assert not base.exists()
    if kind == "hardlink":
        assert (parent / "precious").read_text() == "keep"


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
