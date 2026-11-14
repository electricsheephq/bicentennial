"""Attribute live action input faults against the untouched probe clone."""

import errno
import os
import stat


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
        if not changed:
            raise
        repairs.update(changed)
        return None, "permission"
    except OSError as error:
        if error.errno == errno.ELOOP and any(
                stat.S_ISLNK(mode) and baseline.get(entry.relative_to(workspace).as_posix(), {}).get("kind")
                in (None, "file", "dir") for entry, mode in _parts(workspace, path)):
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
        os.chmod(entry, stat.S_IMODE(mode) | (0o700 if stat.S_ISDIR(mode) else 0o400), follow_symlinks=False)
