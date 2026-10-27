import ctypes
import errno
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.surfaces import tree_hash, tree_listing
from bicentennial.sandbox import surfaces
from bicentennial.sandbox.bytes import allocated_bytes, apply_budget, store_bytes
from bicentennial.sandbox.spansearch import CHUNK_SIZE, span_search
from bicentennial.sandbox.surfaces import (
    NotEmpty,
    SwapBusy,
    clone_tree,
    recover,
    surface_hash,
    swap_in,
    verify_empty,
    wipe_to_fresh,
)


def home(path, text="fresh"):
    path.mkdir()
    (path / ".bicentennial-sandbox").touch()
    (path / "config").write_text(text)
    return path


def test_nonce_sqlite_wal_isolation(tmp_path):
    original = home(tmp_path / "original")
    with closing(sqlite3.connect(original / "state.sqlite")) as keeper:
        keeper.execute("PRAGMA journal_mode=WAL")
        keeper.execute("PRAGMA wal_autocheckpoint=0")
        keeper.execute("CREATE TABLE entries(value TEXT)")
        keeper.execute("INSERT INTO entries VALUES ('checkpointed')")
        keeper.commit()
        keeper.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        keeper.execute("INSERT INTO entries VALUES ('wal-only')")
        keeper.commit()
        assert (original / "state.sqlite-wal").stat().st_size > 0
        shutil.copy2(original / "state.sqlite", tmp_path / "main-only.sqlite")
        with closing(sqlite3.connect(tmp_path / "main-only.sqlite")) as main:
            assert main.execute("SELECT count(*) FROM entries").fetchone() == (1,)
        baseline = surface_hash(original, [])
        first, second = tmp_path / "a", tmp_path / "b"
        assert clone_tree(original, first) in {"clonefile", "copy"}
        assert clone_tree(original, second) in {"clonefile", "copy"}
        nonce = b"r06-synthetic-nonce-6e3e35"
        with closing(sqlite3.connect(first / "state.sqlite")) as writer:
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("INSERT INTO entries VALUES (?)", (nonce.decode(),))
            writer.commit()
            with (first / "config").open("ab") as stream:
                stream.write(nonce)
            assert surface_hash(original, []) == baseline
            assert span_search(first, [nonce])[nonce] == ["config", "state.sqlite-wal"]
            assert span_search(second, [nonce])[nonce] == []
            with closing(sqlite3.connect(second / "state.sqlite")) as reader:
                assert reader.execute("PRAGMA integrity_check").fetchone() == ("ok",)
                assert reader.execute("SELECT count(*) FROM entries").fetchone() == (2,)


def test_clone_preserves_links_modes_and_refuses_existing_target(tmp_path):
    source = home(tmp_path / "source")
    (source / "config").chmod(0o640)
    (source / "empty").mkdir(mode=0o750)
    (source / "dangling").symlink_to("absent")
    (source / "outside").symlink_to(tmp_path, target_is_directory=True)
    target = tmp_path / "copy"
    clone_tree(source, target)
    assert surface_hash(source, []) == surface_hash(target, [])
    assert (source / "config").stat().st_ino != (target / "config").stat().st_ino
    baseline = surface_hash(target, [])
    with pytest.raises(FileExistsError):
        clone_tree(source, target)
    assert surface_hash(target, []) == baseline
    with pytest.raises(ValueError, match="disjoint"):
        clone_tree(source, source / "nested")


def test_plain_copy_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(surfaces.sys, "platform", "linux")
    source = home(tmp_path / "source")
    assert clone_tree(source, tmp_path / "target") == "copy"
    assert surface_hash(source, []) == surface_hash(tmp_path / "target", [])


@pytest.mark.parametrize("code", [errno.ENOTSUP, errno.EXDEV, errno.ENOSYS, errno.EACCES])
def test_clone_native_fallback_is_limited(tmp_path, monkeypatch, code):
    def native(*args):
        ctypes.set_errno(code)
        return -1

    monkeypatch.setattr(surfaces.sys, "platform", "darwin")
    monkeypatch.setattr(surfaces.ctypes, "CDLL", lambda *a, **k: SimpleNamespace(clonefile=native))
    source = home(tmp_path / "source")
    if code == errno.EACCES:
        with pytest.raises(shutil.Error):
            clone_tree(source, tmp_path / "target")
    else:
        assert clone_tree(source, tmp_path / "target") == "copy"
        assert surface_hash(source, []) == surface_hash(tmp_path / "target", [])


def test_verify_empty_path_only_and_volatile_exclusions(tmp_path):
    root = home(tmp_path / "home")
    (root / "logs").mkdir()
    baseline = surface_hash(root, ["logs"])
    assert type(baseline) is str
    assert baseline == tree_hash(tree_listing(root, ["logs"]))
    verify_empty(root, ["logs"], baseline)
    (root / "logs" / "ignored").write_text("volatile")
    verify_empty(root, ["logs"], baseline)
    (root / "memory.txt").write_text("private-memory-entry")
    with pytest.raises(NotEmpty) as caught:
        verify_empty(root, ["logs"], baseline)
    assert caught.value.paths == ("memory.txt",)
    assert caught.value.paths_known
    assert str(caught.value) == "surface hash mismatch: memory.txt"
    assert "private-memory-entry" not in str(caught.value)
    assert str(root) not in str(caught.value)


def test_verify_empty_reports_modified_deleted_and_symlink_paths(tmp_path):
    root = home(tmp_path / "home")
    (root / "gone").touch()
    (root / "link").symlink_to("config")
    baseline = surface_hash(root, [])
    (root / "config").chmod(0o600)
    (root / "gone").unlink()
    (root / "link").unlink()
    (root / "link").symlink_to("missing")
    with pytest.raises(NotEmpty) as caught:
        verify_empty(root, [], baseline)
    assert caught.value.paths == ("config", "gone", "link")


def test_uncached_digest_still_rejects_without_guessing_paths(tmp_path):
    root = home(tmp_path / "home")
    baseline = tree_hash(tree_listing(root, []))
    monkeypatch_listing = surfaces._LISTINGS.copy()
    try:
        surfaces._LISTINGS.clear()
        verify_empty(root, [], baseline)
        surfaces._LISTINGS.clear()
        (root / "config").write_text("changed")
        with pytest.raises(NotEmpty) as caught:
            verify_empty(root, [], baseline)
        assert caught.value.paths == ()
        assert not caught.value.paths_known
    finally:
        surfaces._LISTINGS.clear()
        surfaces._LISTINGS.update(monkeypatch_listing)


def test_wipe_matches_marked_fresh_snapshot(tmp_path):
    fresh, root = home(tmp_path / "fresh"), home(tmp_path / "root", "dirty")
    (root / "memory").mkdir()
    (root / "memory" / "entry").write_text("remembered")
    outside = home(tmp_path / "outside", "untouched")
    (root / "outside").symlink_to(outside, target_is_directory=True)
    baseline = surface_hash(fresh, [])
    wipe_to_fresh(root, fresh)
    assert surface_hash(root, []) == baseline
    verify_empty(root, [], baseline)
    assert (outside / "config").read_text() == "untouched"
    assert not list(tmp_path.glob(".root.*"))


def test_clone_keeps_setuid_and_setgid_bits(tmp_path):
    source = home(tmp_path / "source")
    (source / "tool").write_text("run")
    (source / "tool").chmod(0o4755)
    (source / "group").write_text("run")
    (source / "group").chmod(0o2755)
    clone_tree(source, tmp_path / "copy")
    assert stat.S_IMODE((tmp_path / "copy" / "tool").stat().st_mode) == 0o4755
    assert stat.S_IMODE((tmp_path / "copy" / "group").stat().st_mode) == 0o2755
    assert surface_hash(source, []) == surface_hash(tmp_path / "copy", [])


def test_wipe_removes_a_tree_with_read_only_directories(tmp_path):
    fresh = home(tmp_path / "fresh")
    (fresh / "pkg").mkdir()
    (fresh / "pkg" / "module").write_text("cached")
    (fresh / "pkg").chmod(0o555)
    clone_tree(fresh, tmp_path / "root")
    (tmp_path / "root" / "memory").write_text("remembered")
    baseline = surface_hash(fresh, [])
    wipe_to_fresh(tmp_path / "root", fresh)
    assert surface_hash(tmp_path / "root", []) == baseline
    assert not list(tmp_path.glob(".root.*"))


def test_wipe_resolves_a_root_path_that_ends_in_dotdot(tmp_path):
    fresh, root = home(tmp_path / "fresh"), home(tmp_path / "root", "dirty")
    (root / "sub").mkdir()
    baseline = surface_hash(fresh, [])
    wipe_to_fresh(root / "sub" / "..", fresh)
    assert surface_hash(root, []) == baseline
    assert sorted(p.name for p in tmp_path.iterdir()) == ["fresh", "root"]


@pytest.mark.parametrize("bad", ["root", "fresh", "marker-link", "root-link", "nested"])
def test_wipe_refuses_unmarked_or_overlapping_trees(tmp_path, bad):
    root, fresh = home(tmp_path / "root"), home(tmp_path / "fresh")
    if bad in {"root", "fresh"}:
        ((root if bad == "root" else fresh) / ".bicentennial-sandbox").unlink()
    elif bad == "marker-link":
        (root / ".bicentennial-sandbox").unlink()
        (root / ".bicentennial-sandbox").symlink_to(fresh / ".bicentennial-sandbox")
    elif bad == "root-link":
        (tmp_path / "alias").symlink_to(root, target_is_directory=True)
        root = tmp_path / "alias"
    else:
        fresh = home(root / "fresh")
    before = surface_hash(fresh, [])
    with pytest.raises(ValueError):
        wipe_to_fresh(root, fresh)
    assert surface_hash(fresh, []) == before


def test_wipe_restores_old_root_if_install_fails(tmp_path, monkeypatch):
    root, fresh = home(tmp_path / "root", "old"), home(tmp_path / "fresh")
    baseline, rename = surface_hash(root, []), Path.rename

    def fail_stage(path, target):
        if ".fresh-" in path.name:
            raise OSError("synthetic install failure")
        return rename(path, target)

    monkeypatch.setattr(Path, "rename", fail_stage)
    with pytest.raises(OSError, match="synthetic"):
        wipe_to_fresh(root, fresh)
    assert surface_hash(root, []) == baseline


def test_swap_restores_original_and_retains_used_clone(tmp_path):
    canonical, clone = home(tmp_path / "canonical", "original"), home(tmp_path / "clone", "clone")
    baseline = surface_hash(canonical, [])
    with pytest.raises(RuntimeError, match="body failed"), swap_in(clone, canonical):
        assert (canonical / "config").read_text() == "clone"
        assert not clone.exists()
        journal = canonical.with_name(".canonical.swap.json")
        data = json.loads(journal.read_bytes())
        assert journal.read_bytes() == canon(data)
        assert Path(data["parking"]).is_dir()
        assert data["clone"] == str(clone)
        (canonical / "config").write_text("used clone")
        raise RuntimeError("body failed")
    assert surface_hash(canonical, []) == baseline
    assert (clone / "config").read_text() == "used clone"
    assert not journal.exists()
    recover(canonical)
    assert surface_hash(canonical, []) == baseline


@pytest.mark.parametrize("phase", ["before-park", "parked", "installed", "returned", "restored"])
def test_process_crash_recovery(tmp_path, phase):
    canonical, clone = home(tmp_path / "canonical", "original"), home(tmp_path / "clone", "clone")
    baseline = surface_hash(canonical, [])
    code = '''
import os, sys
from pathlib import Path
from bicentennial.sandbox.surfaces import swap_in
canonical, clone, phase = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
rename = Path.rename
def crash(path, target):
    if phase == "before-park" and path == canonical:
        os._exit(23)
    result = rename(path, target)
    if (phase == "parked" and path == canonical
        or phase == "installed" and path == clone
        or phase == "returned" and path == canonical and target == clone
        or phase == "restored" and ".original-" in path.name):
        os._exit(23)
    return result
Path.rename = crash
with swap_in(clone, canonical):
    pass
'''
    result = subprocess.run([sys.executable, "-c", code, str(canonical), str(clone), phase],
                            capture_output=True, text=True)
    assert result.returncode == 23, result.stderr
    with pytest.raises(SwapBusy):
        with swap_in(clone, canonical):
            pytest.fail("unrecovered journal admitted")
    recover(canonical)
    recover(canonical)
    assert surface_hash(canonical, []) == baseline
    assert (clone / "config").read_text() == "clone"
    assert not (tmp_path / ".canonical.swap.json").exists()


def test_second_concurrent_swap_and_recovery_are_busy(tmp_path):
    canonical = home(tmp_path / "canonical")
    first, second = home(tmp_path / "first"), home(tmp_path / "second")

    def attempt():
        with pytest.raises(SwapBusy), swap_in(second, canonical):
            pytest.fail("overlapping swap admitted")
        with pytest.raises(SwapBusy):
            recover(canonical)

    with swap_in(first, canonical), ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(attempt).result(timeout=5)


def test_swap_collision_preserves_original_and_journal(tmp_path):
    canonical, clone = home(tmp_path / "canonical", "original"), home(tmp_path / "clone", "clone")
    baseline = surface_hash(canonical, [])
    with pytest.raises(FileExistsError), swap_in(clone, canonical):
        home(clone, "collision")
    data = json.loads((tmp_path / ".canonical.swap.json").read_bytes())
    assert surface_hash(data["parking"], []) == baseline
    assert (clone / "config").read_text() == "collision"
    clone.rename(tmp_path / "preserved-collision")
    recover(canonical)
    assert surface_hash(canonical, []) == baseline


def test_streaming_boundaries_long_needles_links_and_path_order(tmp_path):
    root = home(tmp_path / "root")
    needle = b"boundary-needle"
    long = b"a" * (CHUNK_SIZE + 17) + b"end"
    (root / "z").write_bytes(b"x" * (CHUNK_SIZE - 3) + needle + needle)
    (root / "a").write_bytes(needle + long)
    outside = tmp_path / "outside"
    outside.write_bytes(needle)
    (root / "link").symlink_to(outside)
    (root / "dir-link").symlink_to(tmp_path, target_is_directory=True)
    (root / "dangling").symlink_to("absent")
    assert span_search(root, [needle, long, b"absent", needle]) == {
        needle: ["a", "z"], long: ["a"], b"absent": []}
    assert span_search(root, []) == {}
    with pytest.raises(ValueError, match="nonempty bytes"):
        span_search(root, [b""])


def test_allocated_bytes_independent_walk_hardlinks_and_baseline(tmp_path):
    root = home(tmp_path / "root")
    (root / "data").write_bytes(b"x" * 32768)
    os.link(root / "data", root / "hardlink")
    (root / "symlink").symlink_to("data")
    (root / "volatile").mkdir()
    (root / "volatile" / "log").write_bytes(b"x" * 65536)
    (root / "volatile-file").write_bytes(b"x" * 16384)
    volatile = ["volatile", "volatile-file"]
    total, seen = 0, set()
    for directory, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "volatile"]
        for name in files:
            if name == "volatile-file":
                continue
            info = (Path(directory) / name).lstat()
            key = info.st_dev, info.st_ino
            if stat.S_ISREG(info.st_mode) and key not in seen:
                total += info.st_blocks * 512
                seen.add(key)
    assert total > 0
    assert allocated_bytes(root, volatile) == total
    assert allocated_bytes(root, []) > total
    baseline = (root / "config").stat().st_blocks * 512
    assert store_bytes(root, baseline, volatile) == total - baseline
    assert store_bytes(root, total + 1, volatile) == 0
    with pytest.raises(ValueError):
        allocated_bytes(root, ["../outside"])


@pytest.mark.parametrize("operation", [lambda root: span_search(root, [b"needle"]),
                                       lambda root: allocated_bytes(root, [])])
def test_unreadable_subtree_is_an_error_not_an_empty_result(tmp_path, monkeypatch, operation):
    root = home(tmp_path / "root")
    blocked = root / "blocked"
    blocked.mkdir()
    scandir = os.scandir

    def denied(path):
        if Path(path) == blocked:
            raise PermissionError("synthetic unreadable subtree")
        return scandir(path)

    monkeypatch.setattr(os, "scandir", denied)
    with pytest.raises(PermissionError, match="synthetic"):
        operation(root)


@pytest.mark.parametrize("label", ["K30", "K10", "K3", "unknown"])
def test_budget_only_k100(label):
    assert not apply_budget(100, 100, "K100")
    assert apply_budget(101, 100, "K100")
    with pytest.raises(NotImplementedError, match="^v0.2$"):
        apply_budget(0, 100, label)


def test_install_hash_hermes_config_is_port_stable(tmp_path):
    from bicentennial.harness.hermes.config import hermes_config, write_config

    roots = [home(tmp_path / str(port)) for port in (40001, 40002)]
    for root, port in zip(roots, (40001, 40002), strict=True):
        write_config(root, hermes_config(port, "bicentennial-main"))
    first = surfaces.install_hash(roots[0], [], 40001)
    assert first == surfaces.install_hash(roots[1], [], 40002)
    assert surface_hash(roots[0], []) != surface_hash(roots[1], [])
    config = roots[0] / "config.yaml"
    original = config.read_bytes()
    changed = original.replace(b"bicentennial-main", b"bicentennial-Main")
    assert sum(a != b for a, b in zip(original, changed, strict=True)) == 1
    config.write_bytes(changed)
    assert surfaces.install_hash(roots[0], [], 40001) != first


@pytest.mark.parametrize("filename", ["config.yaml", "mem0.json"])
def test_install_hash_masks_all_exact_port_matches(tmp_path, filename):
    from hashlib import sha256

    assert surfaces.PORT_FILES == ("config.yaml", "mem0.json")
    raw = b"http://127.0.0.1:8080/a 127.0.0.1:8080 127.0.0.1:80801 127.0.0.1:8082"
    masked = (b"http://127.0.0.1:{DIRECTOR_PORT}/a 127.0.0.1:{DIRECTOR_PORT} "
              b"127.0.0.1:80801 127.0.0.1:8082")
    (tmp_path / filename).write_bytes(raw)
    listing = tree_listing(tmp_path, [])
    listing[0].update(size=len(masked), sha256=sha256(masked).hexdigest())
    cached = surfaces._LISTINGS.copy()
    assert surfaces.install_hash(tmp_path, [], 8080) == tree_hash(listing)
    assert surfaces._LISTINGS == cached
    assert (tmp_path / filename).read_bytes() == raw


@pytest.mark.parametrize("filename", [None, "config.yaml", "mem0.json", "sub/config.yaml", "other.json"])
def test_install_hash_preserves_unmasked_rows(tmp_path, monkeypatch, filename):
    if filename is not None:
        target = tmp_path / filename
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(b"127.0.0.1:80801" if filename in surfaces.PORT_FILES else b"127.0.0.1:8080")
    listing = tree_listing(tmp_path, [])
    expected = surface_hash(tmp_path, [])
    observed = []
    def capture(rows):
        observed.extend(rows)
        return tree_hash(rows)
    monkeypatch.setattr(surfaces, "tree_hash", capture)
    assert surfaces.install_hash(tmp_path, [], 8080) == expected
    assert observed == listing


def test_install_hash_respects_volatile_paths_and_symlinks(tmp_path):
    (tmp_path / "config.yaml").write_bytes(b"127.0.0.1:8080")
    (tmp_path / "mem0.json").symlink_to("config.yaml")
    assert surfaces.install_hash(tmp_path, ["config.yaml"], 8080) == surface_hash(tmp_path, ["config.yaml"])


@pytest.mark.parametrize("port", [0, 65536, "8080", True])
def test_install_hash_rejects_invalid_port(tmp_path, port):
    with pytest.raises(ValueError):
        surfaces.install_hash(tmp_path, [], port)
