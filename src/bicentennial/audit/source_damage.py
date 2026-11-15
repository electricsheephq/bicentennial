"""Parent-held source observations; failed reads never establish system provenance."""

import os
import sqlite3
import stat

SIDECARS = ("-journal", "-wal", "-shm")
SQLITE = ("sqlite_valid", "sqlite_malformed", "sqlite_unchecked")


class RestoreWatch:
    """Record a swap's exit failure before the session handles it or continues."""

    def __init__(self, context, failures):
        self.context, self.failures = context, failures

    def __enter__(self):
        return self.context.__enter__()

    def __exit__(self, *exc):
        try:
            return self.context.__exit__(*exc)
        except Exception as error:
            self.failures.append(type(error).__name__)
            raise


def _sidecars_regular(path):
    # SQLite opens these beside the database, and opening a FIFO there would block the parent.
    for suffix in SIDECARS:
        try:
            mode = path.with_name(path.name + suffix).lstat().st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(mode):
            return False
    return True


def keep_sidecars(path, kept):
    """Move a database's regular -journal, -wal and -shm files beside its kept copy, yielding each suffix moved."""
    for suffix in SIDECARS:
        sidecar = path.with_name(path.name + suffix)
        try:
            if not stat.S_ISREG(sidecar.lstat().st_mode):
                continue
        except FileNotFoundError:
            continue
        sidecar.rename(kept.with_name(kept.name + suffix))
        yield suffix


def _file_rule(path):
    with path.open("rb") as stream:
        if stream.read(16) != b"SQLite format 3\x00":
            return "file"
    if not _sidecars_regular(path):
        return "sqlite_unchecked"  # not opened; the entry beside it is judged as itself
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        return "sqlite_valid" if db.execute("PRAGMA quick_check").fetchall() == [("ok",)] else "sqlite_malformed"
    except sqlite3.DatabaseError as error:
        if str(error).startswith("malformed database schema"):
            raise
        if getattr(error, "sqlite_errorcode", None) not in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
            raise
        return "sqlite_malformed"
    finally:
        db.close()


def _scan(root, nested=False):
    try:
        mode = root.lstat().st_mode
    except FileNotFoundError:
        return {} if nested else {root: "absent"}
    except OSError:
        return {root: "unobserved"}
    if not stat.S_ISDIR(mode):
        if not nested:
            return {root: "not_a_directory"}
        try:
            rule = (_file_rule(root) if stat.S_ISREG(mode) else
                    "link" if stat.S_ISLNK(mode) else "unsupported_entry")
        except (OSError, sqlite3.Error):
            rule = "unreadable"
        return {root: rule}
    rows = {root: "directory"}
    try:
        entries = sorted(root.iterdir())
    except OSError:
        return {root: "unreadable_directory"}
    for path in entries:
        rows.update(_scan(path, nested=True))
    return rows


def _text(field, name):
    # Receipts are written as UTF-8 JSON: other bytes are escaped, and kept exactly in hex.
    raw = os.fsencode(name)
    try:
        return {field: raw.decode("utf-8")}
    except UnicodeDecodeError:
        return {field: raw.decode("utf-8", "backslashreplace"), f"{field}_hex": raw.hex()}


class SourceBaseline:
    def __init__(self, surfaces, excluded):
        self.excluded, self.roots = set(excluded), {}
        for surface, root in surfaces:
            try:
                rows = _scan(root)
                if (rows.get(root) in ("directory", "unreadable_directory")
                        and "unsupported_entry" not in rows.values()):
                    self.roots[root] = (surface, rows)
            except Exception:
                pass

    def receipt(self, after_kill=False, restore_failures=()):
        """First proven damage; unreadable entries and possible harness residue charge nothing."""
        for root, (surface, before) in self.roots.items():
            rows = _scan(root)
            # A database the checker cannot read or list now was still proved one by its baseline read.
            sidecars = {p.with_name(p.name + suffix) for p, rule in rows.items()
                        if rule == "sqlite_unchecked" or (rule in ("unreadable", "unobserved") and before.get(p) in SQLITE)
                        for suffix in SIDECARS}
            for path, rule in rows.items():
                try:
                    if path in self.excluded:
                        continue
                    if before.get(path) == "unobserved" or any(
                            before.get(parent) in ("unobserved", "unreadable_directory") for parent in path.parents):
                        continue  # an unobserved baseline entry or subtree was never proved absent
                    if rule == "absent" and before.get(root) in ("directory", "unreadable_directory"):
                        if after_kill or restore_failures:
                            continue  # only a harness kill or a recorded restore failure can explain a missing root
                        return dict(_path=root, surface=f"{surface['root']}/{surface['relative']}",
                                    path=".", rule="missing_root", kind="absent", label="invalid_surface")
                    if (path in sidecars and rule in ("link", "directory", "unreadable_directory", "unsupported_entry")
                            and before.get(path) in (None, "file", "unreadable", "sqlite_valid",
                                                     "sqlite_malformed", "sqlite_unchecked")):
                        rule = "sqlite_sidecar"
                    if rule not in ("not_a_directory", "unsupported_entry", "sqlite_malformed", "sqlite_sidecar"):
                        continue
                    if rule == "sqlite_malformed" and before.get(path) not in (None, "sqlite_valid"):
                        continue
                    mode = path.lstat().st_mode
                    kind = next((name for check, name in ((stat.S_ISREG, "file"), (stat.S_ISLNK, "symlink"),
                        (stat.S_ISFIFO, "fifo"), (stat.S_ISSOCK, "socket"),
                        (stat.S_ISDIR, "directory")) if check(mode)), "other")
                    if after_kill and kind in ("fifo", "socket"):
                        continue  # judged again at the first check after the next clean end
                    return dict(_path=path, surface=f"{surface['root']}/{surface['relative']}",
                        **_text("path", path.relative_to(root).as_posix()), rule=rule, kind=kind,
                        **(_text("link", os.readlink(path)) if kind == "symlink" else {}),
                        label="invalid_store" if rule in ("sqlite_malformed", "sqlite_sidecar") else "invalid_surface")
                except (OSError, sqlite3.Error):
                    continue
        return None
