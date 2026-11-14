"""Parent-held source observations; failed reads never establish system provenance."""

import os
import sqlite3
import stat

SIDECARS = ("-journal", "-wal", "-shm")


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


def _scan(root):
    if not stat.S_ISDIR(root.lstat().st_mode):
        return {root: "not_a_directory"}
    rows = {root: "directory"}
    for path in sorted(root.iterdir()):
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            rows.update(_scan(path))
        else:
            rows[path] = (_file_rule(path) if stat.S_ISREG(mode) else
                          "link" if stat.S_ISLNK(mode) else "unsupported_entry")
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
                if not set(rows.values()) & {"not_a_directory", "unsupported_entry"}:
                    self.roots[root] = (surface, rows)
            except Exception:
                pass

    def receipt(self, after_kill=False):
        """The first proven damage, or None. After a harness kill, a FIFO or socket is a killed process's residue."""
        try:
            for root, (surface, before) in self.roots.items():
                for path, rule in _scan(root).items():
                    if path in self.excluded:
                        continue
                    if rule not in ("not_a_directory", "unsupported_entry", "sqlite_malformed"):
                        continue
                    if rule == "sqlite_malformed" and before.get(path) not in (None, "sqlite_valid"):
                        continue
                    mode = path.lstat().st_mode
                    kind = next((name for check, name in ((stat.S_ISREG, "file"), (stat.S_ISLNK, "symlink"),
                        (stat.S_ISFIFO, "fifo"), (stat.S_ISSOCK, "socket")) if check(mode)), "other")
                    if after_kill and rule == "unsupported_entry" and kind in ("fifo", "socket"):
                        continue  # judged again once the system's worker ends by itself
                    return dict(_path=path, surface=f"{surface['root']}/{surface['relative']}",
                        **_text("path", path.relative_to(root).as_posix()), rule=rule, kind=kind,
                        **(_text("link", os.readlink(path)) if kind == "symlink" else {}),
                        label="invalid_store" if rule == "sqlite_malformed" else "invalid_surface")
        except Exception:
            pass
        return None
