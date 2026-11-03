"""Real SQLite residue at local and overflow junctions, before copy recovery."""

import sqlite3
from contextlib import contextmanager

import pytest

from bicentennial.score import sqlite_pages as pages
from bicentennial.score import sqlite_scan

from .test_sqlite_scan import NEEDLES, TOKEN, assert_status, scan


def varint(data, offset):
    value = 0
    for count in range(9):
        byte = data[offset + count]
        value = (value << (8 if count == 8 else 7)) | (byte if count == 8 else byte & 127)
        if byte < 128 or count == 8:
            return value, offset + count + 1
    raise AssertionError("invalid test record")


def split_record(path, db, encoding, junction, short, token):
    """Choose lengths using the real cell's payload size and record header."""
    unit = 1 if encoding == "utf-8" else 2
    prefix = 20
    for _ in range(10):
        value = ("x" * prefix, token, "y" * (4000 - prefix - len(token))) if short else (
            "", "x" * prefix + token + "y" * (4000 - prefix - len(token)), "")
        db.execute("DELETE FROM memory")
        db.execute("INSERT INTO memory VALUES (?, ?, ?)", value)
        db.commit()
        data = path.read_bytes()[1024:2048]
        cell = int.from_bytes(data[8:10], "big")
        payload, offset = varint(data, cell)
        _, offset = varint(data, offset)  # rowid
        header, _ = varint(data, offset)
        minimum = (1024 - 12) * 32 // 255 - 23
        local = minimum + (payload - minimum) % 1020
        if local > 989:
            local = minimum
        boundary = local + (1020 if junction == "overflow" else 0)
        chosen = (boundary - header - 4 * unit) // unit
        if prefix == chosen:
            left = boundary - header - prefix * unit
            encoded = token.encode(encoding)
            assert 0 < left < len(encoded)
            return value, encoded[:left], encoded[left:]
        prefix = chosen
    raise AssertionError("record geometry did not converge")


@contextmanager
def residue(root, kind, *, encoding="utf-8", junction="local", short=False, token=TOKEN):
    path = root / "store.db"
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA page_size=1024")
        db.execute(f"PRAGMA encoding='{encoding.replace("16-", "16")}'")
        db.execute("PRAGMA secure_delete=ON")
        db.execute("CREATE TABLE memory(lead, value, tail)")
        value, left, right = split_record(path, db, encoding, junction, short, token)
        if kind in ("journal", "journal-segments"):
            assert db.execute("PRAGMA journal_mode=PERSIST").fetchone() == ("persist",)
            if kind == "journal-segments":
                db.executemany("INSERT INTO memory VALUES ('', ?, '')", [("z" * 4000,)] * 40)
                db.commit()
                db.execute("PRAGMA cache_size=2")
        else:
            db.execute("DELETE FROM memory")
            db.commit()
            db.execute("VACUUM")
            assert db.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
            db.execute("PRAGMA wal_autocheckpoint=0")
            db.execute("INSERT INTO memory VALUES (?, ?, ?)", value)
            db.commit()
            if kind == "main":
                assert db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] == 0
        db.execute("DELETE FROM memory")
        db.commit()
        if kind == "stale":
            assert db.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()[0] == 0
            db.execute("INSERT INTO memory VALUES ('keep', 'other', '')")
            db.commit()  # Restarts WAL without truncating the preceding generation's tail.
        assert not any(token in str(row) for row in db.execute("SELECT * FROM memory"))
        assert_split_files(root, token, encoding, left, right)
        yield path, left, right
    finally:
        db.close()


def assert_split_files(root, token, encoding, left, right):
    files = [p.read_bytes() for p in root.iterdir() if p.is_file()]
    # All encodings are absent, including the one this database actually uses.
    assert all(token.encode(e) not in data for e in ("utf-8", "utf-16-le", "utf-16-be") for data in files)
    assert any(left in data for data in files)
    assert all(any(right[o:o + 1020] in data for data in files) for o in range(0, len(right), 1020))
    assert left + right == token.encode(encoding)


def base_scan(root, monkeypatch, needles=NEEDLES):
    # Exercise #276's actual raw/SQL/freelist path, without reading git history.
    with monkeypatch.context() as patch:
        patch.setattr(sqlite_scan, "linked_hits", lambda *args: ())
        return scan(root, needles)[0]


@pytest.mark.parametrize("kind", ["main", "wal", "journal"])
@pytest.mark.parametrize("junction", ["local", "overflow"])
def test_superseded_main_old_wal_and_persisted_journal(tmp_path, monkeypatch, kind, junction):
    with residue(tmp_path, kind, junction=junction):
        before = {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
        assert base_scan(tmp_path, monkeypatch).verdict == "absent"
        result, _ = scan(tmp_path)
        assert result.verdict == "found"
        expected = "store.db" + {"main": "", "wal": "-wal", "journal": "-journal"}[kind]
        assert expected in result.hit_paths
        assert "store.db#memory.value" not in result.hit_paths
        assert_status(tmp_path, "FAIL", "store_hit")
        assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}


def test_stale_wal_generation_retains_split_overflow_token(tmp_path, monkeypatch):
    with residue(tmp_path, "stale", junction="overflow") as (path, left, right):
        wal = path.with_name(path.name + "-wal").read_bytes()
        stale = [wal[o + 24:o + 1048] for o in range(32, len(wal) - 1047, 1048)
                 if wal[o + 8:o + 16] != wal[16:24]]
        assert any(p.endswith(left) for p in stale)
        assert any(p[4:].startswith(right) for p in stale)
        assert base_scan(tmp_path, monkeypatch).verdict == "absent"
        assert scan(tmp_path)[0].hit_paths == ("store.db-wal",)
        assert_status(tmp_path, "FAIL", "store_hit")


def test_persisted_journal_with_multiple_segments(tmp_path, monkeypatch):
    with residue(tmp_path, "journal-segments", junction="overflow") as (path, left, right):
        journal = path.with_name(path.name + "-journal").read_bytes()
        assert journal[:28] == bytes(28)
        assert pages.JOURNAL_MAGIC in journal[28:]
        versions = pages.page_versions(path)
        collected = [p for images in versions.values() for name, p in images if name.endswith("-journal")]
        assert any(p.endswith(left) for p in collected)
        assert any(p[4:].startswith(right) for p in collected)
        assert base_scan(tmp_path, monkeypatch).verdict == "absent"
        assert scan(tmp_path)[0].hit_paths == ("store.db-journal",)
        assert_status(tmp_path, "FAIL", "store_hit")


def test_short_column_split_by_earlier_columns(tmp_path, monkeypatch):
    with residue(tmp_path, "main", short=True):
        assert base_scan(tmp_path, monkeypatch).verdict == "absent"
        assert scan(tmp_path)[0].hit_paths == ("store.db",)
        assert_status(tmp_path, "FAIL", "store_hit")


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_utf16_split_tokens_in_old_wal(tmp_path, monkeypatch, encoding):
    with residue(tmp_path, "wal", encoding=encoding):
        assert base_scan(tmp_path, monkeypatch).verdict == "absent"
        assert scan(tmp_path)[0].hit_paths == ("store.db-wal",)
        assert_status(tmp_path, "FAIL", "store_hit")


@pytest.mark.parametrize("kind", ["main", "wal", "journal", "stale"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-16-le", "utf-16-be"])
def test_same_stores_without_token_keep_absence(tmp_path, monkeypatch, kind, encoding):
    with residue(tmp_path, kind, token="VOID-5521", encoding=encoding,
                 junction="overflow" if kind == "stale" else "local"):
        assert base_scan(tmp_path, monkeypatch).verdict == "absent"
        assert scan(tmp_path)[0].verdict == "absent"
        assert_status(tmp_path, "PASS", "")


def test_link_must_name_page_holding_remainder(tmp_path, monkeypatch):
    with residue(tmp_path, "main") as (path, left, right):
        # Snapshot real superseded images, then model reuse of the named page:
        # put its former content at a different number, leaving the link intact.
        # The private SQL view is still supplied by the untouched WAL frames.
        data = bytearray(path.read_bytes())
        first = data.find(left)
        number = int.from_bytes(data[first + len(left):first + len(left) + 4], "big")
        start = (number - 1) * 1024
        assert data[start + 4:start + 4 + len(right)] == right
        data.extend(data[start:start + 1024])
        data[start:start + 1024] = bytes(1024)
        path.write_bytes(data)
        assert_split_files(tmp_path, TOKEN, "utf-8", left, right)
        assert base_scan(tmp_path, monkeypatch).verdict == "absent"
        assert scan(tmp_path)[0].verdict == "absent"
        assert_status(tmp_path, "PASS", "")


def test_needle_across_three_or_more_pages(tmp_path, monkeypatch):
    token = "GATE-" + "abcdefghijklm" * 200
    needles = (token.encode(),)
    with residue(tmp_path, "wal", token=token):
        assert base_scan(tmp_path, monkeypatch, needles).verdict == "absent"
        result, _ = scan(tmp_path, needles)
        assert result.hit_paths == ("store.db-wal",)


def test_uncommitted_wal_frames_are_evidence(tmp_path, monkeypatch):
    path = tmp_path / "store.db"
    db = sqlite3.connect(path)
    try:
        db.execute("PRAGMA page_size=1024")
        db.execute("PRAGMA secure_delete=ON")
        db.execute("CREATE TABLE memory(lead, value, tail)")
        value, left, right = split_record(path, db, "utf-8", "overflow", False, TOKEN)
        db.execute("DELETE FROM memory")
        db.commit()
        db.execute("VACUUM")
        assert db.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("PRAGMA cache_size=2")
        db.execute("PRAGMA cache_spill=ON")
        db.execute("BEGIN")
        db.execute("INSERT INTO memory VALUES (?, ?, ?)", value)
        db.executemany("INSERT INTO memory VALUES ('', ?, '')", [("z" * 4000,)] * 40)
        # Cache spills write actual uncommitted frames; no header manipulation.
        wal = path.with_name(path.name + "-wal").read_bytes()
        assert len(wal) > 32
        assert all(wal[o + 4:o + 8] == bytes(4) for o in range(32, len(wal) - 1047, 1048))
        assert_split_files(tmp_path, TOKEN, "utf-8", left, right)
        assert base_scan(tmp_path, monkeypatch).verdict == "absent"
        assert scan(tmp_path)[0].hit_paths == ("store.db-wal",)
        assert_status(tmp_path, "FAIL", "store_hit")
    finally:
        db.rollback()
        db.close()


def test_uncollectable_page_images_never_certify_absence(tmp_path, monkeypatch):
    path = tmp_path / "store.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE memory(value)")
    path.write_bytes(path.read_bytes()[:100])
    assert base_scan(tmp_path, monkeypatch).reason == "sqlite_unreadable"
    assert scan(tmp_path)[0].reason == "sqlite_unreadable"


@pytest.mark.parametrize("size", [512, 65536])
def test_database_header_page_size_extremes(tmp_path, monkeypatch, size):
    path = tmp_path / "store.db"
    with sqlite3.connect(path) as db:
        db.execute(f"PRAGMA page_size={size}")
        db.execute("CREATE TABLE memory(value)")
    assert all(len(page) == size for versions in pages.page_versions(path).values() for _, page in versions)
    assert base_scan(tmp_path, monkeypatch).verdict == "absent"
    assert scan(tmp_path)[0].verdict == "absent"


def test_reserved_bytes_are_excluded_from_linked_junction(tmp_path):
    with residue(tmp_path, "main", junction="overflow") as (path, left, right):
        data = bytearray(path.read_bytes())
        data[20] = 16
        path.write_bytes(data)
        # The real overflow suffix now lies inside a reserved region and must
        # not be joined. Move it to the usable end to establish a valid junction.
        assert not pages.linked_hits(path, NEEDLES)
        offset = data.find(left)
        assert (offset + len(left)) % 1024 == 0
        data[offset - 16:offset - 16 + len(left)] = left
        data[offset:offset + len(left)] = bytes(len(left))
        path.write_bytes(data)
        assert pages.linked_hits(path, NEEDLES) == {"store.db"}


@pytest.mark.parametrize("suffix", ["-wal", "-journal"])
def test_unparseable_sidecar_contributes_no_page_versions(tmp_path, monkeypatch, suffix):
    path = tmp_path / "store.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE memory(value)")
    expected = dict(pages.page_versions(path))
    path.with_name(path.name + suffix).write_bytes(b"unrecognizable" * 500)
    assert dict(pages.page_versions(path)) == expected
    assert base_scan(tmp_path, monkeypatch).verdict == "absent"
    assert scan(tmp_path)[0].verdict == "absent"


def test_wal_frame_without_page_number_keeps_other_frames(tmp_path, monkeypatch):
    with residue(tmp_path, "wal", junction="overflow") as (path, left, right):
        wal = path.with_name(path.name + "-wal")
        data = wal.read_bytes()
        wal.write_bytes(data[:32] + bytes(24 + 1024) + data[32:])  # a zeroed frame before every real one
        assert base_scan(tmp_path, monkeypatch).verdict == "absent"
        assert scan(tmp_path)[0].hit_paths == ("store.db-wal",)
        assert_status(tmp_path, "FAIL", "store_hit")


def test_incomplete_last_main_page_keeps_complete_pages(tmp_path, monkeypatch):
    with residue(tmp_path, "main", junction="overflow") as (path, left, right):
        assert path.with_name(path.name + "-wal").stat().st_size > 32  # WAL frames alone would hide the main file
        with path.open("ab") as stream:
            stream.write(bytes(100))
        assert "store.db" in scan(tmp_path)[0].hit_paths
        assert_status(tmp_path, "FAIL", "store_hit")
