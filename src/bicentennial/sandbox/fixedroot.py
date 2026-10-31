"""Fixed, exclusively leased Hermes sandbox roots."""

import fcntl
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path


def default_parent(platform=sys.platform):
    return "/private/tmp" if platform == "darwin" else "/tmp"


PARENT = default_parent()
_held = []


def validate_slot(slot, refused):
    if type(slot) is not int or not 0 <= slot <= 9:
        raise refused("sandbox_slot")


def held():
    return tuple(_held)


def remove_tree(path):
    # A unit can leave a read-only directory; unlinking inside it needs the owner's bits. Links are never followed.
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(info.st_mode):
        path.unlink(missing_ok=True)
        return
    os.chmod(path, stat.S_IMODE(info.st_mode) | stat.S_IRWXU)
    for child in sorted(path.iterdir()):
        remove_tree(child)
    path.rmdir()


def _sweep(base):
    for child in sorted(base.iterdir()):
        if child.name != ".lock":
            remove_tree(child)


@contextmanager
def lease(slot, refused):
    validate_slot(slot, refused)
    if os.path.realpath(PARENT) != PARENT:
        raise refused("sandbox_root_untrusted")
    base = Path(PARENT) / f"bicentennial-{slot}"
    try:
        os.mkdir(base, 0o700)
    except FileExistsError:
        info = base.lstat()
        if (not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700
                or os.path.realpath(str(base)) != str(base)):
            raise refused("sandbox_root_untrusted") from None
    try:
        fd = os.open(base / ".lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError:
        raise refused("sandbox_root_untrusted") from None
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            try:
                pid = os.pread(fd, 64, 0).decode().strip() or "unknown"
            except (OSError, UnicodeError):
                pid = "unknown"
            raise refused("sandbox_busy", detail=(f"holder_pid={pid}",)) from None
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        _held.append(fd)
        try:
            _sweep(base)
            try:
                yield base
            finally:
                _sweep(base)
        finally:
            _held.remove(fd)
    finally:
        # Close without unlocking: an orphan retains the shared open file description.
        os.close(fd)
