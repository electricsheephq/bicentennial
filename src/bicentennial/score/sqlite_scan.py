"""Private-copy SQLite evidence for forgetting checks."""

import shutil
import sqlite3
import stat
from pathlib import Path
from tempfile import TemporaryDirectory

from bicentennial.sandbox.spansearch import span_search

SQLITE_HEADER = b"SQLite format 3\0"
SIDECARS = ("-wal", "-shm", "-journal")


def _quoted(name):
    return '"' + name.replace('"', '""') + '"'


def _free_pages(path, connection):
    """Check free leaves and trunk tails after checkpointing the private copy."""
    checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    if checkpoint[0] != 0:
        raise sqlite3.DatabaseError("checkpoint incomplete")
    count = connection.execute("PRAGMA freelist_count").fetchone()[0]
    if count == 0:
        return True
    data = path.read_bytes()
    page_size = int.from_bytes(data[16:18], "big")
    page_size = 65536 if page_size == 1 else page_size
    if page_size < 512 or page_size & (page_size - 1) or len(data) % page_size:
        raise sqlite3.DatabaseError("invalid page size")
    number = int.from_bytes(data[32:36], "big")
    if int.from_bytes(data[36:40], "big") != count:
        raise sqlite3.DatabaseError("inconsistent free list")
    seen = set()

    def page(number):
        if number <= 1 or number > len(data) // page_size or number in seen:
            raise sqlite3.DatabaseError("invalid free page")
        seen.add(number)
        return data[(number - 1) * page_size:number * page_size]

    clean = True
    while number:
        trunk = page(number)
        leaves = int.from_bytes(trunk[4:8], "big")
        end = 8 + 4 * leaves
        if end > page_size:
            raise sqlite3.DatabaseError("invalid free trunk")
        clean &= not any(trunk[end:])
        for offset in range(8, end, 4):
            clean &= not any(page(int.from_bytes(trunk[offset:offset + 4], "big")))
        number = int.from_bytes(trunk[:4], "big")
    if len(seen) != count:
        raise sqlite3.DatabaseError("incomplete free list")
    return clean


def scan_sqlite(source, relative, needles):
    """Return hit locations and a doubt reason; never open a source with SQLite."""
    hits, reason = set(), ""
    texts = tuple(n.decode("utf-8") for n in needles)
    blobs = tuple({t.encode(encoding) for t in texts
                   for encoding in ("utf-8", "utf-16-le", "utf-16-be")})
    try:
        with TemporaryDirectory(prefix="forget-sqlite-") as temporary:
            root = Path(temporary)
            copy = root / source.name
            for suffix in ("", *SIDECARS):
                try:
                    path = source.with_name(source.name + suffix)
                    if suffix and not path.exists() and not path.is_symlink():
                        continue
                    if not stat.S_ISREG(path.lstat().st_mode):
                        raise OSError("nonregular SQLite file")
                    shutil.copyfile(path, root / path.name)
                except OSError:
                    reason = "sqlite_unreadable"
            # Recovery can discard frames or journal bytes, so search before opening.
            raw = span_search(root, list(needles))
            hits.update(relative + p[len(source.name):] for group in raw.values() for p in group)
            if reason:
                return tuple(sorted(hits)), reason
            connection = sqlite3.connect(copy)
            try:
                tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
                tables.add("sqlite_schema")
                for table in sorted(tables):
                    try:
                        columns = [r[1] for r in connection.execute(f"PRAGMA table_xinfo({_quoted(table)})")]
                        if not columns:
                            raise sqlite3.DatabaseError("unreadable table")
                        # SQLite supplies the numeric text form and decodes its own text encoding.
                        expressions = [f"CASE WHEN typeof({_quoted(c)}) IN ('integer','real') "
                                       f"THEN CAST({_quoted(c)} AS TEXT) ELSE {_quoted(c)} END" for c in columns]
                        for row in connection.execute(f"SELECT {','.join(expressions)} FROM {_quoted(table)}"):
                            for column, value in zip(columns, row, strict=True):
                                if (isinstance(value, str) and any(t in value for t in texts) or
                                        isinstance(value, bytes) and any(b in value for b in blobs)):
                                    hits.add(f"{relative}#{table}.{column}")
                    except sqlite3.Error:
                        reason = "sqlite_unreadable"
                if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    reason = "sqlite_unreadable"
                if not _free_pages(copy, connection) and not reason:
                    reason = "sqlite_freelist"
            finally:
                connection.close()
    except (OSError, sqlite3.Error, UnicodeError, ValueError):
        reason = "sqlite_unreadable"
    return tuple(sorted(hits)), reason
