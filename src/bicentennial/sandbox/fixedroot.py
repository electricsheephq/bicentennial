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


@contextmanager
def holding(fd):
    # Workers spawned meanwhile get held() as pass_fds, so a killed holder's live workers keep fd's lock.
    _held.append(fd)
    try:
        yield
    finally:
        _held.remove(fd)


def overlaps(path):
    # A lease sweeps its base, so an operator path at or below any slot's base would be deleted. Each prefix of the
    # path as spelled (`..` kept, since the system applies it after the link before it) is resolved on its own, so a
    # link inside a base cannot carry a path out of it. An existing prefix is also matched by file identity, which
    # other spellings of a base share on a case-insensitive volume, and a base that does not exist yet by its name in
    # any case under the parent's identity.
    parent = Path(os.path.realpath(PARENT))
    bases = [parent / f"bicentennial-{slot}" for slot in range(10)]
    names = {base.name for base in bases}
    try:
        info = os.stat(parent)
        parent_id = (info.st_dev, info.st_ino)
    except OSError:
        parent_id = None
    ids = set()
    for base in bases:
        # A base that is a link is never leased, so nothing at its target is swept: its target is no base.
        try:
            info = os.lstat(base)
        except OSError:
            continue
        if not stat.S_ISLNK(info.st_mode):
            ids.add((info.st_dev, info.st_ino))
            # A link the resolution reads inside the base, even on the way back out, is unlinked by the sweep.
            if within(path, base):
                return True
    full = Path(os.getcwd(), path)
    for prefix in (*reversed(full.parents), full):
        real = Path(os.path.realpath(prefix))
        if any(real == base or base in real.parents for base in bases):
            return True
        if parent_id is not None and real.name.casefold() in names:
            try:
                info = os.stat(real.parent)
            except OSError:
                pass
            else:
                if (info.st_dev, info.st_ino) == parent_id:
                    return True
        try:
            info = os.stat(prefix)
        except OSError:
            continue
        if (info.st_dev, info.st_ino) in ids:
            return True
    return False


def within(path, root):
    # Whether resolving path, as the system does, visits root or anything below it: a directory it passes through or a
    # link it reads. A reset below root would delete what the path depends on. The walk follows each link where the
    # system would, and every visited entry is matched by file identity, which other spellings of root share on a
    # case-insensitive volume. It answers False only for a resolution it finished. A missing entry ends a branch, as
    # it ends the system's resolution; any other error propagates, and past 40 links (a loop, or a chain a caller's
    # own resolution might still finish) it answers True.
    def look(entry, follow=False):
        try:
            return os.stat(entry) if follow else os.lstat(entry)
        except (FileNotFoundError, NotADirectoryError):
            return None

    info = look(root, follow=True)
    if info is None:
        return False
    root_id = (info.st_dev, info.st_ino)

    def below(entry):  # entry's parent is fully resolved
        for prefix in (entry, *entry.parents):
            info = look(prefix)
            if info is not None and (info.st_dev, info.st_ino) == root_id:
                return True
        return False

    todo, current, links = list(Path(os.getcwd(), path).parts[1:]), Path("/"), 0
    while todo:
        part = todo.pop(0)
        if part == "..":
            current = current.parent
            continue
        entry = current / part
        if below(entry):
            return True
        info = look(entry)
        if info is not None and stat.S_ISLNK(info.st_mode):
            links += 1
            if links > 40:
                return True
            target = Path(os.readlink(entry))
            if target.is_absolute():
                current = Path("/")
            todo[:0] = target.parts[1:] if target.is_absolute() else target.parts
            continue
        current = entry
    return below(current)


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
    # The lock is truncated below, so a hard link to another file must be refused before then.
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid():
        os.close(fd)
        raise refused("sandbox_root_untrusted")
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
        with holding(fd):
            _sweep(base)
            try:
                yield base
            finally:
                try:
                    _sweep(base)
                except OSError:
                    # The next lease sweeps again under the lock; a failed exit sweep keeps the run's outcome.
                    pass
    finally:
        # Close without unlocking: an orphan retains the shared open file description.
        os.close(fd)
