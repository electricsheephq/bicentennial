"""Real SQLite stores for E32's compression, naming and disclosure rules."""

import bz2
import gzip
import lzma
import sqlite3
import zlib
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.score import invariants as inv
from bicentennial.score import sqlite_scan
from tests.score.test_sqlite_scan import (
    NEEDLES,
    TOKEN,
    assert_status,
    checkpoint,
    database,
    scan,
)

CODECS = [zlib, gzip, bz2, lzma]
ENCODINGS = ["utf-8", "utf-16-le", "utf-16-be"]


def blob_store(root, value):
    _, db = database(root)
    db.execute("INSERT INTO memory(value) VALUES (?)", (value,))
    db.commit()
    db.close()


def assert_no_encoded_token(root):
    encoded = [TOKEN.encode(e) for e in ENCODINGS]
    assert all(not any(n in p.read_bytes() for n in encoded) for p in root.rglob("*") if p.is_file())


@pytest.mark.parametrize("codec", CODECS, ids=["zlib", "gzip", "bz2", "xz"])
@pytest.mark.parametrize("encoding", ENCODINGS)
def test_compressed_blob_token_is_store_hit(tmp_path, codec, encoding):
    blob_store(tmp_path, codec.compress(("x" * 1024 + TOKEN + "y" * 1024).encode(encoding)))
    assert_no_encoded_token(tmp_path)
    assert_status(tmp_path, "FAIL", "store_hit")
    result, report = scan(tmp_path)
    assert result.hit_paths == ("store.db#memory.value",)
    assert report["counts"]["sqlite"]["found"] == 1


@pytest.mark.parametrize("magic", [bytes.fromhex("28b52ffd"), bytes.fromhex("04224d18")], ids=["zstd", "lz4"])
def test_unsupported_compression_is_opaque(tmp_path, magic):
    blob_store(tmp_path, magic + b"\xff\0unreadable")
    assert_no_encoded_token(tmp_path)
    assert_status(tmp_path, "INCONCLUSIVE", "opaque_store")
    result, report = scan(tmp_path)
    assert (result.verdict, result.reason) == ("inconclusive", "opaque_store")
    assert report["counts"]["sqlite"]["inconclusive"] == 1


@pytest.mark.parametrize("codec", CODECS, ids=["zlib", "gzip", "bz2", "xz"])
@pytest.mark.parametrize("extra", [0, 1], ids=["at-cap", "past-cap"])
def test_decompression_cap_is_opaque(tmp_path, monkeypatch, codec, extra):
    # A small injected cap checks the exact boundary for each decoder without large fixtures.
    monkeypatch.setattr(sqlite_scan, "DECOMPRESS_CAP", 1024, raising=False)
    blob_store(tmp_path, codec.compress(b"x" * (1024 + extra)))
    assert_status(tmp_path, "INCONCLUSIVE", "opaque_store")


def test_production_decompression_cap_is_opaque(tmp_path):
    # Exercise the actual production limit too, without assuming that the constant already exists.
    cap = getattr(sqlite_scan, "DECOMPRESS_CAP", 64 * 1024 * 1024)
    blob_store(tmp_path, zlib.compress(b"x" * cap))
    assert_status(tmp_path, "INCONCLUSIVE", "opaque_store")


@pytest.mark.parametrize("header", [b"\x78\x9c", b"\x1f\x8b", b"BZh9", b"\xfd7zXZ\0"],
                         ids=["zlib", "gzip", "bz2", "xz"])
def test_invalid_compression_header_keeps_absent(tmp_path, header):
    blob_store(tmp_path, header + bytes.fromhex("e731a952f008c619"))
    assert_status(tmp_path, "PASS", "")
    assert scan(tmp_path)[0].verdict == "absent"


@pytest.mark.parametrize("codec", CODECS, ids=["zlib", "gzip", "bz2", "xz"])
def test_compressed_blob_without_token_keeps_absent(tmp_path, codec):
    blob_store(tmp_path, codec.compress(b"unrelated memory"))
    assert_status(tmp_path, "PASS", "")
    assert scan(tmp_path)[0].verdict == "absent"


def named_database(root, name, *, wal=False):
    path, db = database(root)
    db.close()
    path.rename(root / name)
    db = sqlite3.connect(root / name)
    if wal:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        db.execute("PRAGMA wal_autocheckpoint=0")
    return root / name, db


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_database_named_like_sidefile_has_own_sql_scan(tmp_path, suffix):
    path, db = named_database(tmp_path, "store" + suffix)
    db.execute("PRAGMA secure_delete=ON")
    for prefix in range(1024):
        db.execute("DELETE FROM memory")
        db.execute("INSERT INTO memory(value) VALUES (?)", ("x" * prefix + TOKEN + "y" * 3000,))
        db.commit()
        db.execute("VACUUM")
        if TOKEN.encode() not in path.read_bytes():
            break
    else:
        pytest.fail("could not split token across real SQLite overflow pages")
    db.close()
    # Build the other database separately so SQLite cannot interpret its database sibling as a WAL.
    staging = tmp_path / "staging"
    staging.mkdir()
    base, db = database(staging)
    db.close()
    base.rename(tmp_path / "store")
    staging.rmdir()
    assert_no_encoded_token(tmp_path)
    assert_status(tmp_path, "FAIL", "store_hit")
    result, report = scan(tmp_path)
    assert "store" + suffix + "#memory.value" in result.hit_paths
    assert report["counts"]["sqlite"] == dict(absent=1, found=1, inconclusive=0)


def test_database_named_like_sidefile_has_own_wal(tmp_path):
    _, db = named_database(tmp_path, "store-wal", wal=True)
    try:
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.execute("INSERT INTO memory(value) VALUES (?)", (TOKEN,))
        db.commit()
        assert TOKEN.encode() in (tmp_path / "store-wal-wal").read_bytes()
        assert TOKEN.encode() not in (tmp_path / "store-wal").read_bytes()
        staging = tmp_path / "staging"
        staging.mkdir()
        base, other = database(staging)
        other.close()
        base.rename(tmp_path / "store")
        staging.rmdir()
        assert_status(tmp_path, "FAIL", "store_hit")
        result, report = scan(tmp_path)
        assert "store-wal-wal" in result.hit_paths
        assert "store-wal#memory.value" in result.hit_paths
        assert report["counts"]["sqlite"] == dict(absent=1, found=1, inconclusive=0)
    finally:
        db.close()


@pytest.mark.parametrize("with_database", [False, True])
def test_scan_discloses_sqlite_version_even_without_database(tmp_path, with_database):
    if with_database:
        _, db = database(tmp_path)
        db.close()
    assert scan(tmp_path)[1]["sqlite_version"] == sqlite3.sqlite_version
    assert inv.ForgetScan().to_obj()["sqlite_version"] == sqlite3.sqlite_version


@pytest.mark.parametrize("kind", ["header", "boundary", "materialization-error", "legacy"])
def test_whole_checkpoint_hit_has_found_count(tmp_path, monkeypatch, kind):
    # Carried stores, where present, are real SQLite databases; these hits belong to framing or boundaries.
    path, db = database(tmp_path)
    db.close()
    if kind == "header":
        header = dict(format=inv.CHECKPOINT_FORMAT, files=[], metadata=TOKEN)
        data = canon(header) + b"\n"
    elif kind == "boundary":
        data = checkpoint([(0, "store", path.read_bytes()), (0, "a", b"GATE-"), (0, "b", b"4410")])
    elif kind == "materialization-error":
        data = checkpoint([(0, "store", path.read_bytes()), (0, "text", TOKEN.encode())])

        def broken(*args, **kwargs):
            raise OSError("synthetic materialization failure")

        monkeypatch.setattr(Path, "write_bytes", broken)
    else:
        data = TOKEN.encode()
    collector = inv.ForgetScan()
    result = inv.search_checkpoint(data, NEEDLES, collector)
    assert result.verdict == "found"
    assert result.hit_paths == ("<checkpoint>",)
    assert collector.to_obj()["hits"] == ["<checkpoint>"]
    assert collector.to_obj()["counts"]["raw"]["found"] == 1


@pytest.mark.parametrize("codec", CODECS, ids=["zlib", "gzip", "bz2", "xz"])
def test_concatenated_compressed_members_are_searched(tmp_path, codec):
    value = codec.compress(b"first member") + codec.compress(b"x" * 1024 + TOKEN.encode() + b"y" * 1024)
    blob_store(tmp_path, value)
    assert_no_encoded_token(tmp_path)
    assert_status(tmp_path, "FAIL", "store_hit")


@pytest.mark.parametrize("tail", [b"trailing junk", b"\0" * 8 + b"junk", gzip.compress(b"x" * 64)[:-8]],
                         ids=["junk", "padding-then-junk", "truncated-member"])
def test_gzip_member_before_invalid_bytes_is_searched(tmp_path, tail):
    blob_store(tmp_path, gzip.compress(b"x" * 1024 + TOKEN.encode() + b"y" * 1024) + tail)
    assert_no_encoded_token(tmp_path)
    assert_status(tmp_path, "FAIL", "store_hit")


def test_gzip_member_after_zero_padding_is_searched(tmp_path):
    second = gzip.compress(b"x" * 1024 + TOKEN.encode() + b"y" * 1024)
    blob_store(tmp_path, gzip.compress(b"first member") + b"\0" * 16 + second)
    assert_no_encoded_token(tmp_path)
    assert_status(tmp_path, "FAIL", "store_hit")


def test_gzip_bad_checksum_keeps_earlier_members(tmp_path):
    later = bytearray(gzip.compress(b"later member"))
    later[-8] ^= 0xFF
    blob_store(tmp_path, gzip.compress(b"x" * 1024 + TOKEN.encode() + b"y" * 1024) + bytes(later))
    assert_no_encoded_token(tmp_path)
    assert_status(tmp_path, "FAIL", "store_hit")


def gzip_with_flags(data, flags, extra=b""):
    member = bytearray(gzip.compress(data))
    member[3] |= flags
    return bytes(member[:10]) + extra + bytes(member[10:])


@pytest.mark.parametrize("flags, extra", [(0x02, b"\x34\x12"), (0x20, b"")], ids=["wrong-header-crc", "reserved-flag"])
def test_gzip_header_fields_python_accepts_are_read(tmp_path, flags, extra):
    blob_store(tmp_path, gzip_with_flags(b"x" * 1024 + TOKEN.encode() + b"y" * 1024, flags, extra))
    assert_no_encoded_token(tmp_path)
    assert_status(tmp_path, "FAIL", "store_hit")


@pytest.mark.parametrize("codec", [zlib, gzip, lzma], ids=["zlib", "gzip", "xz"])
def test_truncated_stream_prefix_is_searched(tmp_path, codec):
    blob_store(tmp_path, codec.compress(b"x" * 1024 + TOKEN.encode() + b"y" * 65536)[:-24])
    assert_no_encoded_token(tmp_path)
    assert_status(tmp_path, "FAIL", "store_hit")


@pytest.mark.parametrize("codec, checksum", [(zlib, slice(-4, None)), (gzip, slice(-8, -4))], ids=["zlib", "gzip"])
@pytest.mark.parametrize("data, expected", [(b"x" * 1024, ("INCONCLUSIVE", "opaque_store")),
                                            ((b"x" * 500 + TOKEN.encode()).ljust(1024, b"y"), ("FAIL", "store_hit"))],
                         ids=["token-free", "token"])
def test_bad_checksum_at_cap_keeps_capped_output(tmp_path, monkeypatch, codec, checksum, data, expected):
    monkeypatch.setattr(sqlite_scan, "DECOMPRESS_CAP", 1024, raising=False)
    value = bytearray(codec.compress(data))
    value[checksum] = bytes(b ^ 0xFF for b in value[checksum])
    blob_store(tmp_path, bytes(value))
    assert_no_encoded_token(tmp_path)
    assert_status(tmp_path, *expected)


@pytest.mark.parametrize("value, expected", [(zlib.compress(b"x" * 1024 + TOKEN.encode() + b"y" * 1024),
                                              ("FAIL", "store_hit")),
                                             (b"unrelated memory", ("INCONCLUSIVE", "sqlite_unreadable"))],
                         ids=["value-hit", "no-hit"])
def test_sql_values_are_read_when_page_images_cannot_be_collected(tmp_path, monkeypatch, value, expected):
    blob_store(tmp_path, value)

    def uncollectable(*args):  # torn trailing bytes no longer make the images uncollectable (E32)
        raise ValueError("no SQLite page images")

    monkeypatch.setattr(sqlite_scan, "linked_hits", uncollectable)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["store.db"]
    assert_no_encoded_token(tmp_path)
    assert_status(tmp_path, *expected)


@pytest.mark.parametrize("codec", CODECS, ids=["zlib", "gzip", "bz2", "xz"])
def test_truncated_compression_keeps_ordinary_bytes(tmp_path, codec):
    blob_store(tmp_path, codec.compress(b"unrelated memory" * 128)[:-8])
    assert_status(tmp_path, "PASS", "")


def test_opaque_compressed_value_doubt_and_hit_precedence(tmp_path):
    blob_store(tmp_path, bytes.fromhex("28b52ffd") + b"unreadable")
    db = sqlite3.connect(tmp_path / "store.db")
    db.execute("PRAGMA writable_schema=ON")
    db.execute("INSERT INTO sqlite_schema VALUES ('table','unavailable','unavailable',0,"
               "'CREATE VIRTUAL TABLE unavailable USING absent_module(value)')")
    db.commit()
    db.close()
    assert_status(tmp_path, "INCONCLUSIVE", "opaque_store")
    (tmp_path / "text").write_text(TOKEN)
    assert_status(tmp_path, "FAIL", "store_hit")


def test_hit_in_capped_output_still_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(sqlite_scan, "DECOMPRESS_CAP", 4096, raising=False)
    blob_store(tmp_path, zlib.compress(b"x" * 1024 + TOKEN.encode() + b"y" * 8192))
    assert_no_encoded_token(tmp_path)
    assert_status(tmp_path, "FAIL", "store_hit")


def test_many_tiny_zlib_streams_feed_input_once(monkeypatch):
    # Each stream once received the whole rest of the value: many empty streams cost time in the square of its length.
    fed, real = [], zlib.decompressobj

    class Counting:
        def __init__(self, *args):
            self.decoder = real(*args)

        def decompress(self, data, max_length=0):
            fed.append(len(data))
            return self.decoder.decompress(data, max_length)

        def __getattr__(self, name):
            return getattr(self.decoder, name)

    monkeypatch.setattr(sqlite_scan.zlib, "decompressobj", Counting)
    value = zlib.compress(b"") * 20000
    assert sqlite_scan._zlib_streams(value) == (b"", False)
    assert len(fed) == 20000
    assert sum(fed) <= 16 * len(value)


def test_token_across_many_tiny_zlib_streams_is_store_hit(tmp_path):
    parts = [b"x"] * 3000 + [TOKEN[:4].encode(), TOKEN[4:].encode()] + [b"y"] * 3000
    blob_store(tmp_path, b"".join(zlib.compress(part) for part in parts))
    assert_no_encoded_token(tmp_path)
    assert_status(tmp_path, "FAIL", "store_hit")


def test_zlib_error_keeps_output_of_earlier_steps(tmp_path):
    encoder = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    text = (TOKEN + " " + " ".join(map(str, range(3000)))).encode()
    body = encoder.compress(text) + encoder.flush(zlib.Z_FULL_FLUSH)
    # A full flush ends on a block boundary; 0x07 then starts a final block of the reserved type, which raises.
    blob_store(tmp_path, b"\x78\x9c" + body + b"\x07" + b"\0" * 64)
    assert_no_encoded_token(tmp_path)
    assert_status(tmp_path, "FAIL", "store_hit")
