"""Private-copy SQLite evidence for forgetting checks."""

import bz2
import io
import lzma
import shutil
import sqlite3
import stat
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory

from bicentennial.sandbox.spansearch import span_search
from bicentennial.score.sqlite_pages import linked_hits

SQLITE_HEADER = b"SQLite format 3\0"
SQLITE_VERSION = sqlite3.sqlite_version
SIDECARS = ("-wal", "-shm", "-journal")
# Larger than a realistic memory record; bounded reads also contain expansion bombs.
DECOMPRESS_CAP = 64 * 1024 * 1024
GZIP_MAGIC = b"\x1f\x8b"
GZIP_WBITS = 16 + zlib.MAX_WBITS


def _zlib_header(value):
    return (len(value) >= 2 and value[0] & 15 == 8 and value[0] >> 4 <= 7
            and int.from_bytes(value[:2], "big") % 31 == 0)


def _streams(value, header, wbits):
    """Decode consecutive complete zlib streams or gzip members; bytes after the last complete one are ordinary."""
    output = b""
    while header(value):
        decoder = zlib.decompressobj(wbits)
        try:
            chunk = decoder.decompress(value, DECOMPRESS_CAP - len(output))
        except zlib.error:
            # As with zlib.decompress, a complete preceding stream survives trailing junk.
            return output, False
        if len(output) + len(chunk) >= DECOMPRESS_CAP:
            return output + chunk, True
        if not decoder.eof:
            return output, False
        output += chunk
        # gzip readers skip zero padding between members.
        value = decoder.unused_data.lstrip(b"\0") if wbits == GZIP_WBITS else decoder.unused_data
    return output, False


def _decompressed(value):
    """One level only. Return searchable output and whether any content is opaque.

    Invalid streams are ordinary bytes. Consecutive complete zlib streams and gzip members are searched up to the
    first bytes that do not continue them; bz2 and xz readers keep their standard-library handling of
    concatenated streams and padding.
    """
    if value.startswith((b"\x28\xb5\x2f\xfd", b"\x04\x22\x4d\x18")):
        return b"", True
    if _zlib_header(value):
        return _streams(value, _zlib_header, zlib.MAX_WBITS)
    if value.startswith(GZIP_MAGIC):
        return _streams(value, lambda rest: rest.startswith(GZIP_MAGIC), GZIP_WBITS)
    opener = next((opener for header, opener in ((b"BZh", bz2.BZ2File), (b"\xfd7zXZ\0", lzma.LZMAFile))
                   if value.startswith(header)), None)
    if opener is None:
        return b"", False
    try:
        with opener(io.BytesIO(value), mode="rb") as stream:
            output = stream.read(DECOMPRESS_CAP)
    except (OSError, EOFError, lzma.LZMAError):
        return b"", False
    return output, len(output) >= DECOMPRESS_CAP


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


def scan_sqlite(source, relative, needles, *, sidecars=SIDECARS):
    """Return hit locations and a doubt reason; never open a source with SQLite."""
    hits, reason = set(), ""
    opaque = False
    texts = tuple(n.decode("utf-8") for n in needles)
    blobs = tuple({t.encode(encoding) for t in texts
                   for encoding in ("utf-8", "utf-16-le", "utf-16-be")})
    try:
        with TemporaryDirectory(prefix="forget-sqlite-") as temporary:
            root = Path(temporary)
            copy = root / source.name
            for suffix in ("", *sidecars):
                try:
                    path = source.with_name(source.name + suffix)
                    if suffix and not path.exists() and not path.is_symlink():
                        continue
                    if not stat.S_ISREG(path.lstat().st_mode):
                        raise OSError("nonregular SQLite file")
                    shutil.copyfile(path, root / path.name)
                except OSError:
                    reason = "sqlite_unreadable"
            # Recovery can discard frames or journal bytes, so search before opening. Deleted text keeps the database's
            # encoding, so the raw search uses every encoding SQLite stores text in.
            raw = span_search(root, sorted(blobs))
            hits.update(relative + p[len(source.name):] for group in raw.values() for p in group)
            try:
                hits.update(relative + p[len(source.name):] for p in linked_hits(copy, blobs))
            except (OSError, ValueError):
                reason = "sqlite_unreadable"
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
                                decoded = b""
                                if isinstance(value, bytes):
                                    decoded, unreadable = _decompressed(value)
                                    opaque |= unreadable
                                if (isinstance(value, str) and any(t in value for t in texts) or
                                        isinstance(value, bytes) and any(b in value or b in decoded for b in blobs)):
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
    return tuple(sorted(hits)), "opaque_store" if opaque else reason
