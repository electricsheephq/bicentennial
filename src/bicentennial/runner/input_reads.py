"""Attribute live action input faults against the untouched probe clone."""

import errno
import os
import stat
from pathlib import Path


def _parts(workspace, path):
    """Inspect lexical parts, stopping before traversal through any link."""
    current = workspace
    for part in ("", *path.split("/")):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except (FileNotFoundError, NotADirectoryError, PermissionError):
            break
        yield current, mode
        if stat.S_ISLNK(mode):
            break


def _new_link(workspace, path, baseline):
    """Whether a part of the path is a link where the probe listing had a file, a directory or nothing."""
    return any(stat.S_ISLNK(mode) and baseline.get(entry.relative_to(workspace).as_posix(), {}).get("kind")
               in (None, "file", "dir") for entry, mode in _parts(workspace, path))


def read_input(workspace, path, baseline, repairs):
    """Return raw bytes or an attributed reason; leave all other faults to the harness."""
    target = workspace / path
    try:
        mode = target.stat().st_mode
        if stat.S_ISDIR(mode):
            return None, "directory"
        if not stat.S_ISREG(mode):
            if baseline.get(path, {}).get("kind") in (None, "file"):
                return None, "not_regular"
            raise OSError(errno.EINVAL, "non-regular baseline input")
        return target.read_bytes(), None
    except FileNotFoundError:
        return None, "missing"
    except IsADirectoryError:
        return None, "directory"
    except NotADirectoryError:
        return None, "not_a_directory"
    except PermissionError:
        changed = []
        for entry, mode in _parts(workspace, path):
            old = baseline.get(entry.relative_to(workspace).as_posix(), {}) if entry != workspace else {
                "kind": "dir", "mode": 0o700}
            bits = 0o500 if stat.S_ISDIR(mode) else 0o400 if stat.S_ISREG(mode) else 0
            if bits & old.get("mode", 0) & ~mode:
                changed.append(entry)
        if changed:
            repairs.update(changed)
            return None, "permission"
        if _new_link(workspace, path, baseline):  # the reader linked the input to something it cannot read
            return None, "symlink_target"
        raise
    except OSError as error:
        if error.errno == errno.ELOOP and _new_link(workspace, path, baseline):
            return None, "symlink_loop"
        raise


def repair_permissions(workspace, repairs):
    """Unlock only attributed clone entries, after all failed reads have receipts."""
    for entry in sorted(repairs, key=lambda p: len(p.parts)):
        # Never traverse a link to repair its target, even for a reader-made link.
        parts = list(_parts(workspace, entry.relative_to(workspace).as_posix()))
        if not parts or parts[-1][0] != entry or stat.S_ISLNK(parts[-1][1]):
            continue
        mode = parts[-1][1]
        # lstat just showed a file or a directory, not a link; chmod's follow_symlinks=False is not portable.
        os.chmod(entry, stat.S_IMODE(mode) | (0o700 if stat.S_ISDIR(mode) else 0o400))


def unlock_tree(root):
    """Give the owner read, write and execute on every directory under root, never following a link.

    A live reader can lock any directory of its probe clone, not only one on an input's path; the attempt's cleanup
    calls this only after a removal fails for lack of permission, so a clean run's cleanup is unchanged.
    """
    pending = [Path(root)]
    while pending:
        directory = pending.pop()
        try:
            mode = directory.lstat().st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(mode):
            continue
        if stat.S_IMODE(mode) & 0o700 != 0o700:
            os.chmod(directory, stat.S_IMODE(mode) | 0o700)  # a directory, never a link: lstat said so
        with os.scandir(directory) as entries:
            pending.extend(Path(e.path) for e in entries if e.is_dir(follow_symlinks=False))
