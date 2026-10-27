"""Local fixtures only: ledger integrity, credential refusal and deterministic identity."""

import copy
import json
from compression import zstd
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import pytest

from bicentennial.canon import canon
from bicentennial.ledger import (
    BlobCorrupt,
    BlobStore,
    ChainBroken,
    CredentialLeak,
    Guard,
    Ledger,
    LedgerBusy,
    TornTail,
    apply_masks,
    stable_digest,
    verify,
)

LOCK = "a" * 64
RUN_VALUES = {"sandbox_root": "/sandbox/run-a", "director_port": "48123"}
ROOT = Path(__file__).resolve().parents[1]


def request(**changes):
    rec = json.loads((ROOT / "fixtures/run/contracts.json").read_bytes())["contracts"]["ledger-record"]
    for key in ("seq", "prev_hash", "hash", "lock_hash", "attempt_id"):
        del rec[key]
    return rec | changes


def ledger(root, guard=None):
    return Ledger(root, guard or Guard([]), lock_hash=LOCK, attempt_id="attempt-a")


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None
            for p in root.rglob("*")}


def test_canonical_durable_append_resume_and_blob(tmp_path):
    obj = {"body": "fixture", "nested": [1, True, None, "é"]}
    first = ledger(tmp_path)
    try:
        ref = first.blob(obj)
        assert ref == sha256(canon(obj)).hexdigest()
        assert BlobStore(tmp_path / "blobs", Guard([])).get(ref) == canon(obj)
        with patch("bicentennial.ledger.ledger.os.fsync") as sync:
            r1 = first.append(request(req=ref, resp=ref))
            sync.assert_called_once()
            assert (tmp_path / "ledger.jsonl").read_bytes() == canon(r1) + b"\n"
        assert r1["seq"] == 1 and r1["prev_hash"] == "0" * 64
    finally:
        first.close()
    second = ledger(tmp_path)
    try:
        r2 = second.append({"type": "lifecycle", "details": [1, None]})
        assert r2["seq"] == 2 and r2["prev_hash"] == r1["hash"]
        for line in (tmp_path / "ledger.jsonl").read_bytes().splitlines():
            rec = json.loads(line)
            assert canon(rec) == line
            h = rec.pop("hash")
            assert h == sha256(rec["prev_hash"].encode() + canon(rec)).hexdigest()
        assert verify(tmp_path) == dict(records=2, chain_breaks=0, truncated_tail=0,
                                        bad_blobs=0, missing_lock_fields=0)
    finally:
        second.close()


def test_one_byte_record_and_blob_tamper(tmp_path, capsys):
    writer = ledger(tmp_path)
    ref = writer.blob({"text": "AAAA"})
    writer.append(request(req=ref, resp=writer.blob({"text": "BBBB"})))
    writer.append({"type": "lifecycle"})
    writer.close()
    path = tmp_path / "ledger.jsonl"
    raw = path.read_bytes()
    changed = raw.replace(b'"status":200', b'"status":201', 1)
    assert sum(a != b for a, b in zip(raw, changed, strict=True)) == 1
    path.write_bytes(changed)
    blob = tmp_path / "blobs" / ref[:2] / f"{ref}.json.zst"
    raw = blob.read_bytes()
    blob.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    result = verify(tmp_path)
    assert result["chain_breaks"] == result["bad_blobs"] == 1
    with pytest.raises(ChainBroken):
        ledger(tmp_path)
    assert path.read_bytes() == changed
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("tail", [b'{"seq":', b'{"type":"lifecycle"}'])
def test_torn_tail_refuses_without_changes(tmp_path, tail):
    writer = ledger(tmp_path)
    writer.append({"type": "lifecycle"})
    writer.close()
    path = tmp_path / "ledger.jsonl"
    path.write_bytes(path.read_bytes() + tail)
    before = snapshot(tmp_path)
    with pytest.raises(TornTail):
        ledger(tmp_path)
    assert snapshot(tmp_path) == before
    assert verify(tmp_path)["truncated_tail"] == 1


def test_credential_refusals_are_atomic_and_silent(tmp_path, monkeypatch, capsys):
    # Generate the fake value at runtime: no complete needle in source or fixtures.
    needle = "".join(chr(n) for n in [82, 48, 50, 45, 102, 97, 107, 101, 45, 107, 101, 121])
    monkeypatch.setenv("R02_TEST_CREDENTIAL", needle)
    monkeypatch.setenv("R02_TEST_EMPTY", "")
    monkeypatch.delenv("R02_TEST_ABSENT", raising=False)
    guard = Guard(["R02_TEST_CREDENTIAL", "R02_TEST_EMPTY", "R02_TEST_ABSENT"])
    writer = ledger(tmp_path, guard)
    try:
        writer.blob({"text": "safe"})
        before = snapshot(tmp_path)
        for operation in (lambda: writer.append({"type": "lifecycle", "text": needle}),
                          lambda: writer.append(request(subrole=needle)),
                          lambda: writer.blob({"nested": [needle]})):
            with pytest.raises(CredentialLeak) as error:
                operation()
            assert str(error.value) == "credential reached a ledger write"
            assert needle not in str(error.value)
            assert snapshot(tmp_path) == before
        assert all(needle.encode() not in data for data in snapshot(tmp_path).values() if data)
        assert all(needle.encode() not in zstd.decompress(p.read_bytes())
                   for p in (tmp_path / "blobs").rglob("*.zst"))
        assert needle not in repr(vars(guard))
        assert writer.append({"type": "lifecycle"})["seq"] == 1
        assert guard.check(b"safe") == b"safe"
        assert capsys.readouterr() == ("", "")
    finally:
        writer.close()


def test_exclusive_writer_and_thread_serialization(tmp_path):
    writer = ledger(tmp_path)
    try:
        with pytest.raises(LedgerBusy):
            ledger(tmp_path)
        with ThreadPoolExecutor(max_workers=2) as pool:
            records = list(pool.map(lambda n: writer.append({"type": "aux", "n": n}), range(8)))
        assert sorted(r["seq"] for r in records) == list(range(1, 9))
        assert verify(tmp_path)["chain_breaks"] == 0
    finally:
        writer.close()
    writer.close()
    resumed = ledger(tmp_path)
    resumed.close()
    with pytest.raises(ValueError, match="closed"):
        writer.append({"type": "aux"})


@pytest.mark.parametrize("changes", [{"seq": 1}, {"prev_hash": LOCK}, {"lock_hash": LOCK},
                                     {"attempt_id": "a"}, {"hash": LOCK},
                                     {"type": 1}, {"float": [1.25]}])
def test_refused_append_keeps_bytes_and_sequence(tmp_path, changes):
    writer = ledger(tmp_path)
    try:
        before = snapshot(tmp_path)
        with pytest.raises((ValueError, TypeError)):
            writer.append({"type": "aux"} | changes)
        assert snapshot(tmp_path) == before
        with pytest.raises(ValueError):
            writer.append({"type": "request"})
        assert writer.append({"type": "aux"})["seq"] == 1
    finally:
        writer.close()


def test_store_reuse_digest_mismatch_missing_and_invalid_address(tmp_path):
    store = BlobStore(tmp_path / "blobs", Guard([]))
    obj = {"text": "A"}
    ref = store.put(obj)
    with patch("bicentennial.ledger.blobs.os.replace") as replace:
        assert store.put(obj) == ref
        replace.assert_not_called()
    path = store._path(ref)
    path.write_bytes(zstd.compress(canon({"text": "B"})))
    with pytest.raises(BlobCorrupt, match="digest mismatch"):
        store.get(ref)
    for bad in ("f" * 64, "../escape", "F" * 64, None, 42):
        with pytest.raises(BlobCorrupt):
            store.get(bad)
    with pytest.raises(TypeError):
        store.put({"nested": [0.5]})
    assert not list(tmp_path.rglob("tmp*"))


def test_verify_all_upstream_refs_and_missing_lock_fields(tmp_path):
    writer = ledger(tmp_path)
    good = writer.blob({"fixture": True})
    writer.append({"type": "aux", "req": good, "resp": good,
                   "upstream": [{"req": "f" * 64, "resp": "e" * 64},
                                {"req": good, "resp": good}]})
    writer.close()
    assert verify(tmp_path)["bad_blobs"] == 2
    path = tmp_path / "ledger.jsonl"
    rec = json.loads(path.read_bytes())
    del rec["lock_hash"]
    del rec["attempt_id"]
    del rec["hash"]
    rec["hash"] = sha256(rec["prev_hash"].encode() + canon(rec)).hexdigest()
    path.write_bytes(canon(rec) + b"\n")
    assert verify(tmp_path)["missing_lock_fields"] == 1
    assert verify(tmp_path)["chain_breaks"] == 0


@pytest.mark.parametrize("line", [b"null", b"[]", b"{broken", b'{"seq":1.0}'])
def test_malformed_complete_line_is_chain_break(tmp_path, line):
    (tmp_path / "ledger.jsonl").write_bytes(line + b"\n")
    assert verify(tmp_path)["chain_breaks"] == 1
    with pytest.raises(ChainBroken):
        ledger(tmp_path)


def test_jsonpath_masks_and_literal_replacement():
    body = {"id": "response-root", "session_id": "session-a", "t": 1,
            "response": {"id": "response-nested"}, "timestamp": 2, "created": 3,
            "created_at": 4, "updated_at": 5,
            "nested": [{"session_id": "session-b", "call_id": "harness-call",
                        "tool_call_id": "harness-result", "response_id": "response-b",
                        "previous_response_id": "response-a",
                        "tool_calls": [{"id": "harness-tool"}, {"id": "bcw-stable"}]}],
            "text": "/sandbox/run-a/a 48123 and /sandbox/run-a/b 48123"}
    before = copy.deepcopy(body)
    masked = apply_masks(body, RUN_VALUES)
    assert body == before
    assert masked["id"] == masked["response"]["id"] == "{HARNESS_RESPONSE_ID}"
    assert masked["session_id"] == "{HERMES_SESSION_ID}"
    row = masked["nested"][0]
    assert row["session_id"] == "{HERMES_SESSION_ID}"
    assert all(row[k] == "{HARNESS_TOOL_CALL_ID}" for k in ("call_id", "tool_call_id"))
    assert all(row[k] == "{HARNESS_RESPONSE_ID}" for k in ("response_id", "previous_response_id"))
    assert row["tool_calls"] == [{"id": "{HARNESS_TOOL_CALL_ID}"}, {"id": "bcw-stable"}]
    assert all(masked[k] == "{WALL_CLOCK}" for k in ("t", "timestamp", "created", "created_at", "updated_at"))
    assert masked["text"] == "{SANDBOX_ROOT}/a {DIRECTOR_PORT} and {SANDBOX_ROOT}/b {DIRECTOR_PORT}"
    assert apply_masks({"id": "bcw-root", "session_id": "bcw-session"}, RUN_VALUES) == {
        "id": "bcw-root", "session_id": "bcw-session"}
    # Match concrete root/child selectors only; arbitrary ids and timestamp substrings survive.
    assert apply_masks({"nested": {"id": "keep"}, "content": "timestamp:123"}, RUN_VALUES) == {
        "nested": {"id": "keep"}, "content": "timestamp:123"}


@pytest.mark.parametrize("values", [{}, {"sandbox_root": "", "director_port": "1"},
                                   {"sandbox_root": "/s", "director_port": 123}])
def test_mask_run_values_are_explicit_nonempty_strings(values):
    with pytest.raises(ValueError):
        apply_masks({}, values)


def fixture_records(root, session, run_values, reverse=False, content="A", director_id="bcw-a"):
    writer = ledger(root)
    records = []
    try:
        for text in (["second", "first"] if reverse else ["first", "second"]):
            req = {"session_id": session, "tool_calls": [{"id": f"call-{session}"}], "text": text}
            resp = {"id": f"resp-{session}", "created": 200 if reverse else 100,
                    "content": content, "tool_calls": [{"id": director_id}],
                    "path": run_values["sandbox_root"] + "/data", "port": run_values["director_port"]}
            records.append(writer.append(request(
                role="aux", cursor=None, req=writer.blob(req), resp=writer.blob(resp),
                req_masked_sha256=sha256(canon(apply_masks(req, run_values))).hexdigest(),
                resp_masked_sha256=sha256(canon(apply_masks(resp, run_values))).hexdigest(),
                t=200 if reverse else 100, t_ms=2 if reverse else 1,
                load=[2, 3, 4] if reverse else [1, 2, 3])))
    finally:
        writer.close()
    return records


def test_stable_digest_real_fixture_ledgers(tmp_path):
    other_values = {"sandbox_root": "/sandbox/run-b", "director_port": "49123"}
    a = fixture_records(tmp_path / "a", "hermes-a", RUN_VALUES)
    b = fixture_records(tmp_path / "b", "hermes-b", other_values, reverse=True)
    assert a[0]["req"] != b[1]["req"]
    assert a[0]["seq"] != b[1]["seq"]
    original = copy.deepcopy(a)
    digest = stable_digest(a, RUN_VALUES)
    assert digest == stable_digest(b, other_values)
    assert a == original
    changed = fixture_records(tmp_path / "c", "hermes-a", RUN_VALUES, content="B")
    assert digest != stable_digest(changed, RUN_VALUES)
    changed_id = fixture_records(tmp_path / "d", "hermes-a", RUN_VALUES, director_id="bcw-b")
    assert digest != stable_digest(changed_id, RUN_VALUES)
    assert digest == stable_digest(a + [{"type": "lifecycle", "t": 999}], RUN_VALUES)


def test_stable_projection_and_numeric_cursor_order(tmp_path):
    writer = ledger(tmp_path)
    try:
        records = [writer.append(request(cursor=cursor)) for cursor in
                   ({"session": 10, "turn": 1}, None, {"session": 2, "turn": 10},
                    {"session": 2, "turn": 2})]
    finally:
        writer.close()
    props = json.loads((ROOT.parent / "schemas/ledger-record.schema.json").read_bytes())["properties"]
    projected = [{k: v for k, v in r.items() if props[k]["x-stability"] == "stable"} for r in records]
    expected = [projected[i] for i in (1, 3, 2, 0)]
    assert stable_digest(records, RUN_VALUES) == sha256(canon(expected)).hexdigest()
    assert stable_digest([], RUN_VALUES) == sha256(canon([])).hexdigest()


def test_credential_in_a_field_name_never_reaches_the_schema_error(tmp_path, monkeypatch):
    needle = "".join(chr(n) for n in [75, 51, 89, 45, 102, 97, 107, 101, 45, 110, 97, 109, 101])
    monkeypatch.setenv("R02_TEST_KEY_NAME", needle)
    writer = ledger(tmp_path, Guard(["R02_TEST_KEY_NAME"]))
    try:
        for rec in (request(**{needle: 1}), request(cursor={"session": 1, "turn": 1, needle: 1})):
            with pytest.raises(CredentialLeak) as error:
                writer.append(rec)
            assert needle not in str(error.value)
        assert (tmp_path / "ledger.jsonl").read_bytes() == b""
    finally:
        writer.close()


def test_a_carriage_return_in_place_of_a_newline_is_a_chain_break(tmp_path):
    writer = ledger(tmp_path)
    try:
        for n in range(3):
            writer.append({"type": "lifecycle", "n": n})
    finally:
        writer.close()
    path = tmp_path / "ledger.jsonl"
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b"\n", b"\r", 1))
    assert verify(tmp_path)["chain_breaks"] >= 1
    with pytest.raises(ChainBroken):
        ledger(tmp_path)


def test_a_run_value_inside_a_hex_digest_is_not_masked(tmp_path):
    rec = {k: v for k, v in request().items()}
    digest = "0f48123" + "a" * 57  # the port of run A occurs inside the hash
    a = [dict(rec, seq=1, req_masked_sha256=digest, lock_hash=LOCK, attempt_id="x", type="request")]
    b = [dict(a[0])]
    assert stable_digest(a, RUN_VALUES) == stable_digest(
        b, {"sandbox_root": "/sandbox/run-b", "director_port": "49123"})


def test_an_escaped_credential_is_refused(tmp_path, monkeypatch):
    # Built at runtime with a quote and a backslash, which canon escapes.
    needle = "".join(chr(n) for n in [102, 97, 107, 101, 34, 107, 101, 121, 92, 118, 97, 108])
    monkeypatch.setenv("R02_TEST_CREDENTIAL", needle)
    writer = ledger(tmp_path, Guard(["R02_TEST_CREDENTIAL"]))
    try:
        for operation in (lambda: writer.append({"type": "lifecycle", "text": needle}),
                          lambda: writer.blob({"text": needle})):
            with pytest.raises(CredentialLeak):
                operation()
        assert writer.append({"type": "lifecycle"})["seq"] == 1
    finally:
        writer.close()


def test_a_failed_fsync_retires_the_writer(tmp_path):
    writer = ledger(tmp_path)
    with patch("bicentennial.ledger.ledger.os.fsync", side_effect=OSError("synthetic")):
        with pytest.raises(OSError, match="synthetic"):
            writer.append({"type": "lifecycle"})
    with pytest.raises(ValueError, match="closed"):
        writer.append({"type": "lifecycle"})
    reopened = ledger(tmp_path)
    try:
        assert reopened.append({"type": "lifecycle"})["seq"] == 2
    finally:
        reopened.close()
    assert verify(tmp_path)["chain_breaks"] == 0


def test_run_values_are_masked_in_object_keys():
    a = apply_masks({"files": {"/sandbox/run-a/data": "same"}}, RUN_VALUES)
    b = apply_masks({"files": {"/sandbox/run-b/data": "same"}},
                    dict(RUN_VALUES, sandbox_root="/sandbox/run-b"))
    assert a == b == {"files": {"{SANDBOX_ROOT}/data": "same"}}
    with pytest.raises(ValueError, match="merged"):
        apply_masks({"/sandbox/run-a/x": 1, "{SANDBOX_ROOT}/x": 2}, RUN_VALUES)
