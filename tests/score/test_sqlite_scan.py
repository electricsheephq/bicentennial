"""Synthetic store evidence for content-aware forgetting checks."""

import json
import sqlite3

import pytest

from bicentennial.api.adapters.reference_store import ReferenceStore
from bicentennial.canon import canon
from bicentennial.harness.hermes import plugin_host
from bicentennial.sandbox.spansearch import span_search
from bicentennial.score import invariants as inv
from bicentennial.score import sqlite_scan

TOKEN = "GATE-4410"
NEEDLES = inv.needles_for([TOKEN])


def database(root, *, encoding="UTF-8", wal=False):
    path = root / "store.db"
    db = sqlite3.connect(path)
    db.execute("PRAGMA page_size=1024")
    db.execute(f"PRAGMA encoding='{encoding}'")
    if wal:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        db.execute("PRAGMA wal_autocheckpoint=0")
    db.execute("CREATE TABLE memory(value, deleted INTEGER DEFAULT 0)")
    db.commit()
    return path, db


def scan(root, needles=NEEDLES):
    collector = inv.ForgetScan()
    result = inv.search_store(root, needles, collector)
    return result, collector.to_obj()


def adapter(root, *, data=b"[]"):
    class Store(ReferenceStore):
        def checkpoint(self):
            return data

    return inv.adapter_invariant(Store, "INV-FORGET", bound_s=5, snapshot=lambda a: (root,))


def assert_status(root, status, reason):
    verdict = adapter(root)
    assert (verdict.status, verdict.reasons) == (status, (reason,) if reason else ())


def test_m1_flagged_row_is_store_hit_with_column(tmp_path):
    _, db = database(tmp_path)
    db.execute("INSERT INTO memory VALUES (?, 1)", (TOKEN,))
    db.commit()
    db.close()
    assert_status(tmp_path, "FAIL", "store_hit")
    result, report = scan(tmp_path)
    assert "store.db#memory.value" in result.hit_paths
    assert report["counts"]["sqlite"]["found"] == 1


def test_m2_fts_shadow_values_are_read_even_without_raw_hit(tmp_path):
    path, db = database(tmp_path, encoding="UTF-16le")
    db.execute("PRAGMA secure_delete=ON")
    # Missing FTS5 is a failed test, rather than a skipped proof obligation.
    db.execute("CREATE VIRTUAL TABLE fts USING fts5(value)")
    db.execute("INSERT INTO memory(value) VALUES (?)", (TOKEN,))
    db.execute("INSERT INTO fts(value) VALUES (?)", (TOKEN,))
    db.execute("DELETE FROM memory")
    db.commit()
    db.execute("VACUUM")
    db.close()
    assert TOKEN.encode() not in path.read_bytes()
    result, _ = scan(tmp_path)
    assert result.verdict == "found"
    assert "store.db#fts_content.c0" in result.hit_paths
    assert_status(tmp_path, "FAIL", "store_hit")


def test_m3_deleted_bytes_remain_raw_store_hit(tmp_path):
    path, db = database(tmp_path)
    db.execute("PRAGMA secure_delete=OFF")
    db.execute("INSERT INTO memory(value) VALUES (?)", (TOKEN * 600,))
    db.commit()
    db.execute("DELETE FROM memory")
    db.commit()
    db.close()
    assert TOKEN.encode() in path.read_bytes()
    assert "store.db" in scan(tmp_path)[0].hit_paths
    assert_status(tmp_path, "FAIL", "store_hit")


def free_store(root, secure):
    path, db = database(root)
    db.execute(f"PRAGMA secure_delete={'ON' if secure else 'OFF'}")
    db.executemany("INSERT INTO memory(value) VALUES (?)", [("x" * 1800,)] * 12)
    db.commit()
    db.execute("DELETE FROM memory")
    db.commit()
    assert db.execute("PRAGMA freelist_count").fetchone()[0] > 0
    db.close()
    return path


def test_m3_nonzero_free_pages_without_whole_token_are_inconclusive(tmp_path):
    free_store(tmp_path, False)
    assert not any(span_search(tmp_path, list(NEEDLES)).values())
    result, counts = scan(tmp_path)
    assert (result.verdict, result.reason) == ("inconclusive", "sqlite_freelist")
    assert counts["counts"]["sqlite"]["inconclusive"] == 1
    assert_status(tmp_path, "INCONCLUSIVE", "sqlite_freelist")


def test_secure_delete_zero_free_leaves_and_trunk_tails_certify_absence(tmp_path):
    free_store(tmp_path, True)
    assert scan(tmp_path)[0].verdict == "absent"
    assert_status(tmp_path, "PASS", "")


def test_m4_overflow_value_is_reassembled_when_raw_search_misses(tmp_path):
    path, db = database(tmp_path)
    db.execute("PRAGMA secure_delete=ON")
    for prefix in range(1024):
        db.execute("DELETE FROM memory")
        db.execute("INSERT INTO memory(value) VALUES (?)", ("x" * prefix + TOKEN + "y" * 3000,))
        db.commit()
        db.execute("VACUUM")
        if TOKEN.encode() not in path.read_bytes():
            break
    else:
        pytest.fail("could not split the synthetic token across overflow pages")
    db.close()
    assert not any(span_search(tmp_path, list(NEEDLES)).values())
    assert "store.db#memory.value" in scan(tmp_path)[0].hit_paths
    assert_status(tmp_path, "FAIL", "store_hit")


@pytest.mark.parametrize("encoding", ["UTF-16le", "UTF-16be"])
def test_m4_database_text_encoding_is_used(tmp_path, encoding):
    path, db = database(tmp_path, encoding=encoding)
    db.execute("INSERT INTO memory(value) VALUES (?)", (TOKEN,))
    db.commit()
    db.close()
    assert TOKEN.encode() not in path.read_bytes()
    assert "store.db#memory.value" in scan(tmp_path)[0].hit_paths
    assert_status(tmp_path, "FAIL", "store_hit")


def test_m5_other_binary_stays_opaque(tmp_path):
    (tmp_path / "binary").write_bytes(b"\0\xffunrelated")
    result, report = scan(tmp_path)
    assert (result.verdict, result.reason) == ("inconclusive", "opaque_store")
    assert report["counts"]["opaque"]["inconclusive"] == 1
    assert_status(tmp_path, "INCONCLUSIVE", "opaque_store")


def test_deleted_vacuumed_store_passes_by_sqlite(tmp_path):
    _, db = database(tmp_path)
    db.execute("PRAGMA secure_delete=ON")
    db.execute("INSERT INTO memory(value) VALUES (?)", (TOKEN,))
    db.commit()
    db.execute("DELETE FROM memory")
    db.commit()
    db.execute("VACUUM")
    db.close()
    assert scan(tmp_path)[1]["counts"]["sqlite"]["absent"] == 1
    assert_status(tmp_path, "PASS", "")


def test_old_wal_frame_is_raw_store_hit_before_recovery(tmp_path):
    _, db = database(tmp_path, wal=True)
    try:
        db.execute("PRAGMA secure_delete=ON")
        db.execute("INSERT INTO memory(value) VALUES (?)", (TOKEN,))
        db.commit()
        db.execute("DELETE FROM memory")
        db.commit()
        assert db.execute("SELECT * FROM memory").fetchall() == []
        assert TOKEN.encode() in (tmp_path / "store.db-wal").read_bytes()
        result, _ = scan(tmp_path)
        assert result.verdict == "found"
        assert "store.db-wal" in result.hit_paths
        assert "store.db#memory.value" not in result.hit_paths
        assert_status(tmp_path, "FAIL", "store_hit")
    finally:
        db.close()


@pytest.mark.parametrize("value,token", [(441012345, "441012345"), (4410.25, "4410.25")])
def test_d4_numeric_values_use_sqlite_text_form(tmp_path, value, token):
    path, db = database(tmp_path)
    db.execute("INSERT INTO memory(value) VALUES (?)", (value,))
    db.commit()
    db.close()
    assert token.encode() not in path.read_bytes()
    result, _ = scan(tmp_path, inv.needles_for([token]))
    assert result.verdict == "found"
    assert "store.db#memory.value" in result.hit_paths


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16-le", "utf-16-be"])
def test_d4_blob_matches_all_required_encodings(tmp_path, encoding):
    _, db = database(tmp_path)
    db.execute("INSERT INTO memory(value) VALUES (?)", (TOKEN.encode(encoding),))
    db.commit()
    db.close()
    assert "store.db#memory.value" in scan(tmp_path)[0].hit_paths
    assert_status(tmp_path, "FAIL", "store_hit")


def test_d2_corruption_is_unreadable_never_absent(tmp_path):
    path, db = database(tmp_path)
    db.execute("INSERT INTO memory(value) VALUES ('unrelated')")
    db.commit()
    db.close()
    with path.open("r+b") as stream:
        stream.seek(1024)
        stream.write(b"\xff" * 32)
    result, _ = scan(tmp_path)
    assert (result.verdict, result.reason) == ("inconclusive", "sqlite_unreadable")
    assert_status(tmp_path, "INCONCLUSIVE", "sqlite_unreadable")


def test_d2_copy_error_is_unreadable(tmp_path, monkeypatch):
    _, db = database(tmp_path)
    db.close()

    def broken(*args):
        raise OSError("synthetic copy failure")

    monkeypatch.setattr(sqlite_scan.shutil, "copyfile", broken)
    assert scan(tmp_path)[0].reason == "sqlite_unreadable"


def test_d2_missing_virtual_module_does_not_hide_shadow_hits(tmp_path):
    _, db = database(tmp_path, encoding="UTF-16le")
    db.execute("CREATE TABLE shadow(value)")
    db.execute("INSERT INTO shadow VALUES (?)", (TOKEN,))
    db.execute("PRAGMA writable_schema=ON")
    db.execute("INSERT INTO sqlite_schema VALUES ('table','unavailable','unavailable',0,"
               "'CREATE VIRTUAL TABLE unavailable USING absent_module(value)')")
    db.commit()
    db.close()
    result, _ = scan(tmp_path)
    assert result.verdict == "found"
    assert result.reason == "sqlite_unreadable"
    assert "store.db#shadow.value" in result.hit_paths


def test_d5_sibling_wal_is_included_not_opaque(tmp_path):
    _, db = database(tmp_path, wal=True)
    try:
        result, report = scan(tmp_path)
        assert result.verdict == "absent"
        assert not result.opaque_paths
        assert report["counts"]["opaque"]["inconclusive"] == 0
        assert report["counts"]["sqlite"]["absent"] == 1
        assert_status(tmp_path, "PASS", "")
    finally:
        db.close()


def test_d5_orphan_wal_keeps_opaque_rule(tmp_path):
    (tmp_path / "orphan-wal").write_bytes(b"\0\xff")
    assert scan(tmp_path)[0].reason == "opaque_store"


def checkpoint(files, *, format=inv.CHECKPOINT_FORMAT):
    header = dict(format=format, files=[dict(surface=s, path=p, mode=0o600, size=len(data))
                                       for s, p, data in files])
    return canon(header) + b"\n" + b"".join(data for _, _, data in files)


def test_d6_host_checkpoint_literal_matches_host():
    assert inv.CHECKPOINT_FORMAT == plugin_host.CHECKPOINT_FORMAT


def test_d6_host_checkpoint_clean_sqlite_is_not_opaque(tmp_path):
    path, db = database(tmp_path)
    db.close()
    data = checkpoint([(0, "memory/store.db", path.read_bytes())])
    collector = inv.ForgetScan()
    result = inv.search_checkpoint(data, NEEDLES, collector)
    assert result.verdict == "absent"
    assert collector.to_obj()["counts"]["sqlite"]["absent"] == 1
    assert adapter(tmp_path, data=data).status == "PASS"


def test_d6_checkpoint_sidecars_share_surface_and_carried_locations(tmp_path):
    path, db = database(tmp_path, wal=True)
    try:
        db.execute("INSERT INTO memory(value) VALUES (?)", (TOKEN,))
        db.commit()
        files = [(0, "nested/" + p.name, p.read_bytes()) for p in tmp_path.iterdir()]
        data = checkpoint(files)
        result = inv.search_checkpoint(data, NEEDLES)
        assert result.verdict == "found"
        assert "nested/store.db#memory.value" in result.hit_paths
        assert "nested/store.db-wal" in result.hit_paths
        assert not result.opaque_paths
        assert adapter(tmp_path, data=data).reasons == ("store_hit",)
    finally:
        db.close()


@pytest.mark.parametrize("format", [inv.CHECKPOINT_FORMAT, "another-format"])
def test_d6_binary_checkpoint_and_other_formats_keep_opaque_rule(tmp_path, format):
    data = checkpoint([(0, "binary", b"\0\xff")], format=format)
    assert adapter(tmp_path, data=data).reasons == ("opaque_store",)


def test_d6_checkpoint_header_raw_hit_is_still_failure(tmp_path):
    data = canon(dict(format=inv.CHECKPOINT_FORMAT, files=[], metadata=TOKEN)) + b"\n"
    assert adapter(tmp_path, data=data).reasons == ("store_hit",)


@pytest.mark.parametrize("path", ["../escape", "/absolute", "nested/../../escape"])
def test_d6_untrusted_checkpoint_paths_use_legacy_rule(path):
    data = checkpoint([(0, path, b"\0")])
    assert inv.search_checkpoint(data, NEEDLES).reason == "opaque_store"


def test_read_only_scan_preserves_all_source_bytes_mtimes_and_entries(tmp_path):
    _, db = database(tmp_path, wal=True)
    try:
        db.execute("INSERT INTO memory(value) VALUES ('unrelated')")
        db.commit()

        def state():
            return {p.relative_to(tmp_path).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                    for p in tmp_path.rglob("*") if p.is_file()}

        before = state()
        assert scan(tmp_path)[0].verdict == "absent"
        assert state() == before
    finally:
        db.close()


def test_d7_reason_precedence_and_failure_precedence(tmp_path):
    free_store(tmp_path, False)
    assert scan(tmp_path)[0].reason == "sqlite_freelist"
    broken = tmp_path / "broken"
    broken.write_bytes(sqlite_scan.SQLITE_HEADER + b"\0" * 2048)
    assert_status(tmp_path, "INCONCLUSIVE", "sqlite_unreadable")
    (tmp_path / "binary").write_bytes(b"\0\xff")
    assert_status(tmp_path, "INCONCLUSIVE", "opaque_store")
    (tmp_path / "text").write_text(TOKEN)
    assert_status(tmp_path, "FAIL", "store_hit")


def test_schema_values_are_read_in_database_encoding(tmp_path):
    path, db = database(tmp_path, encoding="UTF-16le")
    db.execute(f'CREATE TABLE extra(value TEXT DEFAULT "{TOKEN}")')
    db.commit()
    db.close()
    assert TOKEN.encode() not in path.read_bytes()
    assert "store.db#sqlite_schema.sql" in scan(tmp_path)[0].hit_paths


def test_text_verdict_bytes_and_collector_zero_counts_are_unchanged(tmp_path):
    (tmp_path / "text").write_text("unrelated")
    verdict = adapter(tmp_path)
    expected = dict(invariant="INV-FORGET", status="PASS", members=3, uninformative=0,
                    failed=[], inconclusive=[], infra=[], reasons=[])
    assert canon(verdict.to_obj()) == canon(expected)
    result, report = scan(tmp_path)
    assert result == inv.StoreSearch("absent", (), ())
    assert report == dict(counts=dict(raw=dict(absent=1, found=0, inconclusive=0),
                                     sqlite=dict(absent=0, found=0, inconclusive=0),
                                     opaque=dict(absent=0, found=0, inconclusive=0)), hits=[])
    (tmp_path / "text").write_text(TOKEN)
    assert_status(tmp_path, "FAIL", "store_hit")
    assert TOKEN not in json.dumps(verdict.to_obj())



@pytest.mark.parametrize("suffix", ["-journal", "-shm"])
def test_sidecar_raw_hits_survive_recovery_or_sqlite_errors(tmp_path, suffix):
    _, db = database(tmp_path)
    db.close()
    (tmp_path / ("store.db" + suffix)).write_bytes(b"\0" * 64 + TOKEN.encode())
    result, _ = scan(tmp_path)
    assert result.verdict == "found"
    assert "store.db" + suffix in result.hit_paths
    assert_status(tmp_path, "FAIL", "store_hit")


def test_d2_unavailable_virtual_module_without_hit_is_unreadable(tmp_path):
    _, db = database(tmp_path)
    db.execute("PRAGMA writable_schema=ON")
    db.execute("INSERT INTO sqlite_schema VALUES ('table','unavailable','unavailable',0,"
               "'CREATE VIRTUAL TABLE unavailable USING absent_module(value)')")
    db.commit()
    db.close()
    assert_status(tmp_path, "INCONCLUSIVE", "sqlite_unreadable")


def test_d6_checkpoint_raw_hit_survives_materialization_error(tmp_path, monkeypatch):
    data = checkpoint([(0, "text", TOKEN.encode())])

    def broken(*args, **kwargs):
        raise OSError("synthetic temporary-directory failure")

    monkeypatch.setattr(inv, "TemporaryDirectory", broken)
    assert adapter(tmp_path, data=data).reasons == ("store_hit",)


def test_d6_same_carried_path_on_distinct_surfaces_is_scanned_separately(tmp_path):
    path, db = database(tmp_path)
    db.close()
    data = checkpoint([(0, "store", path.read_bytes()), (1, "store", b"\0\xff")])
    collector = inv.ForgetScan()
    result = inv.search_checkpoint(data, NEEDLES, collector)
    assert result.reason == "opaque_store"
    assert collector.to_obj()["counts"]["sqlite"]["absent"] == 1
    assert collector.to_obj()["counts"]["opaque"]["inconclusive"] == 1
