"""Parent-held source observations; failed reads never establish system provenance."""

import sqlite3
import stat
from pathlib import Path

HEADER = b"SQLite format 3\x00"


def _database(path):
    with path.open("rb") as stream:
        header = stream.read(16) == HEADER
    if not header:
        return False, False
    try:
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            valid = db.execute("PRAGMA quick_check").fetchall() == [("ok",)]
    except sqlite3.DatabaseError as error:
        if getattr(error, "sqlite_errorcode", None) not in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
            raise
        valid = False
    finally:
        if "db" in locals():
            db.close()
    return True, valid


def _scan(root):
    if not stat.S_ISDIR(root.lstat().st_mode):
        return {root: "not_a_directory"}
    rows = {root: "directory"}
    def visit(directory):
        for path in sorted(directory.iterdir()):
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode):
                rows[path] = "directory"
                visit(path)
            elif stat.S_ISREG(mode):
                header, valid = _database(path)
                rows[path] = ("sqlite_valid" if valid else "sqlite_malformed") if header else "file"
            else:
                rows[path] = "link" if stat.S_ISLNK(mode) else "unsupported_entry"
    visit(root)
    return rows


class SourceBaseline:
    def __init__(self, surfaces, excluded):
        self.excluded, self.roots = set(excluded), {}
        for _, root in surfaces:
            try:
                rows = _scan(root)
                if not set(rows.values()) & {"not_a_directory", "unsupported_entry"}:
                    self.roots[root] = rows
            except Exception:
                pass

    def receipt(self):
        try:
            for root, before in self.roots.items():
                for path, rule in _scan(root).items():
                    if path in self.excluded or path.name.startswith(".config.yaml."):
                        continue
                    if rule == "file" and before.get(path) == "sqlite_valid":
                        rule = "sqlite_malformed"
                    if rule not in ("not_a_directory", "unsupported_entry", "sqlite_malformed"):
                        continue
                    if rule == "sqlite_malformed" and before.get(path) not in (None, "sqlite_valid"):
                        continue
                    return dict(path=str(path), root=str(root), rule=rule,
                                label="invalid_store" if rule == "sqlite_malformed" else "invalid_surface")
        except Exception:
            pass
        return None
