"""Parent-held source observations; failed reads never establish system provenance."""

import sqlite3
import stat


def _file_rule(path):
    with path.open("rb") as stream:
        if stream.read(16) != b"SQLite format 3\x00":
            return "file"
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        return "sqlite_valid" if db.execute("PRAGMA quick_check").fetchall() == [("ok",)] else "sqlite_malformed"
    except sqlite3.DatabaseError as error:
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
