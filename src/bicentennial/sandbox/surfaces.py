"""Clone quiescent trees, journal serial swaps, and verify fresh surfaces."""

import ctypes
import errno
import fcntl
import json
import os
import re
import shutil
import stat
import sys
import uuid
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.contracts.surfaces import tree_hash, tree_listing

_LISTINGS = {}
PORT_FILES = ("config.yaml", "mem0.json")


class SwapBusy(RuntimeError):
    """The canonical path has an active swap or an unrecovered journal."""


class NotEmpty(ValueError):
    """A hash mismatch; paths are exact when the baseline listing is cached."""

    def __init__(self, paths, paths_known):
        self.paths, self.paths_known = tuple(paths), paths_known
        super().__init__("surface hash mismatch" + (": " + ", ".join(paths) if paths else ""))


def _directory(path):
    path = Path(path)
    if not stat.S_ISDIR(path.lstat().st_mode):
        raise ValueError("expected a real directory")
    return path


def _walk(root):
    def fail(error):
        raise error
    return os.walk(root, followlinks=False, onerror=fail)


def _separate(first, second):
    if first == second or first in second.parents or second in first.parents:
        raise ValueError("trees must be disjoint")


def clone_tree(source, target) -> str:
    """Clone regular files on macOS; preserve symlinks without following them."""
    source, target = _directory(source), Path(target)
    _separate(source.resolve(), target.parent.resolve() / target.name)
    method = "clonefile" if sys.platform == "darwin" else "copy"
    native = getattr(ctypes.CDLL(None, use_errno=True), "clonefile", None)
    if native is not None:
        native.argtypes, native.restype = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int], ctypes.c_int

    def copy(src, dst):
        nonlocal method
        if method == "clonefile" and native is not None:
            if native(os.fsencode(src), os.fsencode(dst), 0) == 0:
                # clonefile clears setuid and setgid; K13 hashes the full mode.
                os.chmod(dst, stat.S_IMODE(os.lstat(src).st_mode))
                return dst
            code = ctypes.get_errno()
            if code not in (errno.ENOTSUP, errno.EXDEV, errno.ENOSYS):
                raise OSError(code, "clonefile failed")
        method = "copy"
        return shutil.copy2(src, dst)

    shutil.copytree(source, target, symlinks=True, copy_function=copy)
    return method


def _paths(canonical):
    canonical = Path(canonical)
    canonical = canonical.parent.resolve() / canonical.name
    return canonical, canonical.with_name(f".{canonical.name}.swap.json")


@contextmanager
def _lock(journal):
    # A persistent lock inode avoids unlink/recreate races across processes.
    with journal.with_suffix(".lock").open("a+b") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SwapBusy("canonical path is busy") from None
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _restore(canonical, journal):
    data = json.loads(journal.read_bytes())
    parking, clone = Path(data["parking"]), Path(data["clone"])
    if (data["version"] != 1 or parking.parent != canonical.parent
            or not parking.name.startswith(f".{canonical.name}.original-")):
        raise ValueError("invalid swap journal")
    _separate(canonical, clone)
    _separate(parking, clone)
    original = parking if parking.exists() else canonical
    info = _directory(original).stat()
    if [info.st_dev, info.st_ino] != data["original"]:
        raise ValueError("original identity differs from journal")
    if parking.exists():
        if os.path.lexists(canonical):
            _directory(canonical)
            if os.path.lexists(clone):
                raise FileExistsError("clone return path is occupied")
            canonical.rename(clone)
        parking.rename(canonical)
    journal.unlink()


@contextmanager
def swap_in(clone, canonical):
    """Park the original, install the clone, then restore without deleting trees."""
    canonical, journal = _paths(canonical)
    clone = Path(clone)
    clone = clone.parent.resolve() / clone.name
    _separate(canonical, clone)
    with _lock(journal):
        if os.path.lexists(journal):
            raise SwapBusy("recover the existing swap journal first")
        info = _directory(canonical).stat()
        _directory(clone)
        parking = canonical.with_name(f".{canonical.name}.original-{uuid.uuid4().hex}")
        if os.path.lexists(parking):
            raise FileExistsError("original parking path is occupied")
        data = {"version": 1, "parking": str(parking), "clone": str(clone),
                "original": [info.st_dev, info.st_ino]}
        pending = journal.with_suffix(f".{uuid.uuid4().hex}.pending")
        with pending.open("xb") as stream:
            stream.write(canon(data))
            stream.flush()
            os.fsync(stream.fileno())
        pending.rename(journal)
        try:
            canonical.rename(parking)
            clone.rename(canonical)
            yield
        finally:
            _restore(canonical, journal)


def recover(canonical):
    """Restore a journaled original; refuse busy swaps and occupied destinations."""
    canonical, journal = _paths(canonical)
    with _lock(journal):
        if os.path.lexists(journal):
            _restore(canonical, journal)


def surface_hash(root, volatile_paths) -> str:
    """Use K13 exclusively; retain up to 128 listings for path-only diagnostics."""
    listing = tree_listing(root, volatile_paths)
    digest = tree_hash(listing)
    _LISTINGS[digest] = {row["path"]: row for row in listing}
    if len(_LISTINGS) > 128:
        del _LISTINGS[next(iter(_LISTINGS))]
    return digest


def install_hash(root, volatile_paths, port) -> str:
    """Hash a fresh tree with only benchmark-written director ports masked."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("port must be an int in 1..65535")
    listing = tree_listing(root, volatile_paths)
    pattern = rb"127\.0\.0\.1:" + str(port).encode() + rb"(?!\d)"
    for row in listing:
        if row["kind"] == "file" and row["path"] in PORT_FILES:
            masked = re.sub(pattern, b"127.0.0.1:{DIRECTOR_PORT}", (Path(root) / row["path"]).read_bytes())
            row.update(size=len(masked), sha256=sha256(masked).hexdigest())
    return tree_hash(listing)


def verify_empty(root, volatile_paths, fresh_install_hash) -> None:
    """Reject a mismatch even when a serialized baseline has no cached listing."""
    baseline = _LISTINGS.get(fresh_install_hash)
    actual = surface_hash(root, volatile_paths)
    if actual != fresh_install_hash:
        current = _LISTINGS[actual]
        paths = ([] if baseline is None else sorted(
            p for p in baseline.keys() | current.keys() if baseline.get(p) != current.get(p)))
        raise NotEmpty(paths, baseline is not None)


def _marked(root):
    root = _directory(root)
    marker = root / ".bicentennial-sandbox"
    if not marker.exists() or not stat.S_ISREG(marker.lstat().st_mode):
        raise ValueError("sandbox marker must be a regular file")
    return root


def _writable_dirs(root):
    # rmtree cannot unlink inside a read-only directory; links are never followed.
    for path, dirs, _ in _walk(root):
        for name in [".", *dirs]:
            info = os.lstat(os.path.join(path, name))
            if stat.S_ISDIR(info.st_mode):
                os.chmod(os.path.join(path, name), stat.S_IMODE(info.st_mode) | stat.S_IRWXU)


def wipe_to_fresh(root, fresh_snapshot):
    """Replace only a marked sandbox with a separately marked fresh snapshot."""
    # Resolve after the link check so the stage and backup sit beside the real root.
    root, fresh = _marked(root).resolve(), _marked(fresh_snapshot)
    _separate(root.resolve(), fresh.resolve())
    stage = root.with_name(f".{root.name}.fresh-{uuid.uuid4().hex}")
    backup = root.with_name(f".{root.name}.wiped-{uuid.uuid4().hex}")
    if os.path.lexists(backup):
        raise FileExistsError("wipe backup path is occupied")
    clone_tree(fresh, stage)
    root.rename(backup)
    try:
        stage.rename(root)
    except BaseException:
        backup.rename(root)
        raise
    _writable_dirs(_marked(backup))
    shutil.rmtree(backup)
