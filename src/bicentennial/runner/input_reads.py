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


def _behind_baseline_link(path, baseline):
    """Whether a parent of the path was a link in the probe listing, which then recorded nothing below it."""
    parts = path.split("/")
    return any(baseline.get("/".join(parts[:i]), {}).get("kind") == "symlink" for i in range(1, len(parts)))


def _read_regular(target):
    """Read target through one descriptor: its bytes and mode, or None and the mode if it is not a regular file.

    O_NONBLOCK lets the open of a FIFO return at once (it changes nothing for a regular file), and the opened
    descriptor's own mode decides, so an entry replaced after the first stat is never read.
    """
    fd = os.open(target, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    try:
        mode = os.fstat(fd).st_mode
        if not stat.S_ISREG(mode):
            return None, mode
        chunks = []
        while chunk := os.read(fd, 1 << 20):
            chunks.append(chunk)
        return b"".join(chunks), mode
    finally:
        os.close(fd)


def read_input(workspace, path, baseline, repairs):
    """Return raw bytes or an attributed reason; leave all other faults to the harness."""
    target = workspace / path
    try:
        mode = target.stat().st_mode
        if stat.S_ISREG(mode):
            data, mode = _read_regular(target)
            if data is not None:
                return data, None
        if stat.S_ISDIR(mode):
            return None, "directory"
        # A FIFO, device or socket where the input was a file or nothing is never read (and opened only without blocking).
        if baseline.get(path, {}).get("kind") in (None, "file") and not _behind_baseline_link(path, baseline):
            return None, "not_regular"
        raise OSError(errno.EINVAL, "non-regular input the probe listing did not show as new")
    except FileNotFoundError:
        return None, "missing"
    except IsADirectoryError:
        return None, "directory"
    except NotADirectoryError:
        return None, "not_a_directory"
    except PermissionError as error:
        if error.errno != errno.EACCES:  # EPERM and the rest: a sandbox or the system refused, not a mode
            raise
        changed = []
        for entry, mode in _parts(workspace, path):
            old = baseline.get(entry.relative_to(workspace).as_posix(), {}) if entry != workspace else {
                "kind": "dir", "mode": 0o700}
            # Opening a known path needs search (execute) on each directory and read on the file; a directory's read
            # bit only lets it be listed, so its loss alone cannot deny this open (#579's review).
            bits = 0o100 if stat.S_ISDIR(mode) else 0o400 if stat.S_ISREG(mode) else 0
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
        # lstat just showed a file or a directory, not a link; chmod's follow_symlinks=False is not portable. A link
        # swapped in after that lstat would need a process that outlived the worker's killed process group, and the
        # change only adds owner bits to an entry the harness's own user owns (#564's review: an accepted tradeoff).
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
