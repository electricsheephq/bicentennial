"""Synthetic, schema-validated Hermes ledgers; no harness or model execution."""

import ast
import copy
import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.keyed import choice, uniform_int
from bicentennial.ledger import BlobStore, Guard, Ledger
from bicentennial.render.session_cut import Cut
from bicentennial.render.stream import seal, write_branch
from bicentennial.score import exposure as module
from bicentennial.score.exposure import (
    Span,
    context_text,
    exposure,
    load_spans,
    locked_tokens,
    present,
    report_bytes,
    spans,
)
from bicentennial.world.db import (
    create_world,
    insert_entity,
    insert_fact,
    insert_locked_token,
)

ROOT = Path(__file__).resolve().parents[2]
E = "bcw-80b2baf589c6a41d"
E2 = "bcw-other-event"
F = "bcw-fact"
TOKEN = "TOK-4410"
SID = "bcw-session"
LOCK = "c" * 64


def fixture(name):
    return json.loads((ROOT / f"schemas/fixtures/gen/{name}.json").read_bytes())


def row(eid=E, session=SID, turn=2, text=None, facts=None, payload=None):
    value = fixture("stream")
    value.update(event_id=eid, session_id=session, turn_key=f"{session}/t{turn}",
                 fact_ids=[F] if facts is None else facts, text=text or f"Evidence {TOKEN}.")
    if payload is not None:
        value.pop("text")
        value.update(payload=payload, channel="tool_result", kind="tool",
                     tool={"name": "exec", "args": {}}, call_id="call-1",
                     expected_result_sha256=sha256(canon(payload)).hexdigest())
    return seal(value)


def item(gold=None, point=2, iid=None):
    value = fixture("item")
    value.update(gold_spans=[E] if gold is None else gold, probe_point=point)
    if iid is not None:
        value["item_id"] = iid
    if gold == []:
        value["options"] = [value["options"][-1]]
        value["gold"] = {"never_observed": True, "option_id": value["options"][0]["option_id"]}
    validate("item", value)
    return value


def body(text="absent"):
    return {"model": "fixture-model", "messages": [{"role": "tool", "content": text}], "tools": []}


def record(text="absent", *, cursor=(1, 2), role="replay_main", subrole="cursor",
           status=200, upstream=None, request=None, **changes):
    return dict(text=text, cursor=cursor, role=role, subrole=subrole, status=status,
                upstream=upstream, request=request, changes=changes)


def append(writer, spec):
    rec = json.loads((ROOT / "tests/fixtures/run/contracts.json").read_bytes())["contracts"]["ledger-record"]
    for key in ("seq", "prev_hash", "hash", "lock_hash", "attempt_id"):
        del rec[key]
    request = body(spec["text"]) if spec["request"] is None else spec["request"]
    req = writer.blob(request)
    upstream = [] if spec["upstream"] is None else [
        {"role": "write_turn", "req": writer.blob(body(spec["upstream"]))}]
    cursor = spec["cursor"]
    rec.update(life="life", branch="B0", system="hermes", role=spec["role"],
               subrole=spec["subrole"], status=spec["status"], req=req,
               resp=writer.blob({"choices": []}), upstream=upstream,
               cursor=None if cursor is None else dict(zip(("session", "turn"), cursor, strict=True)))
    rec.update(spec["changes"])
    result = writer.append(rec)
    validate("ledger-record", result)
    return result


def ledger(root, records, lock=LOCK, attempt_id="att-1"):
    writer = Ledger(root, Guard([]), lock_hash=lock, attempt_id=attempt_id)
    try:
        for spec in records:
            append(writer, spec)
    finally:
        writer.close()
    return root


def score(roots, indexed=None, items=None, probes=None, recall=True, **kwargs):
    indexed = {E: Span(E, 1, 2, (TOKEN,))} if indexed is None else indexed
    items = [item()] if items is None else items
    probes = {i["item_id"]: (2, 1) for i in items} if probes is None else probes
    return exposure(roots, life="life", branch="B0", system="hermes",
                    spans=indexed, items=items, probes=probes, recall=recall, **kwargs)


def verdict(report):
    return report["items"][item()["item_id"]]


@pytest.fixture
def tokens(tmp_path):
    db = create_world(tmp_path / "world.db", dict(generator_version="v1", genre="fixture", seed="s", scale=1))
    try:
        insert_entity(db, id="entity", kind="person", canonical_name="Fixture", aliases_json=[],
                      created_t=0, retired_t=None)
        insert_fact(db, id=F, subject_id="entity", predicate="code", object=TOKEN,
                    polarity="affirm", modality="stated", strength=1000, speech_act="assert")
        insert_locked_token(db, token_id="token-1", fact_id=F, kind="code", value=TOKEN)
        db.commit()
        before = db.total_changes
        result = locked_tokens(db)
        assert db.total_changes == before
        yield result
    finally:
        db.close()


@pytest.mark.parametrize(("cut", "offset", "exposed"), [(4000, 5000, False), (6000, 5000, True),
                                                           (4000, 100, True)])
def test_truncation(tmp_path, tokens, cut, offset, exposed):
    stdout = "x" * offset + " " + TOKEN
    rows = [row(payload={"stdout": stdout})]
    indexed = spans(rows, [SID], tokens, [E])
    text = stdout[:cut] + "\n[truncated]"
    cursors = [(1, t) for t in range(2, 6)] + [(2, t) for t in range(1, 6)]
    root = ledger(tmp_path / "ledger", [record(text, cursor=c, subrole="tool_results") for c in cursors])
    report = score([root], indexed)
    assert report["spans"][E]["present"] == ([list(c) for c in cursors] if exposed else [])
    assert report["spans"][E]["first"] == ([1, 2] if exposed else None)
    assert verdict(report)["cause"] == (None if exposed else "N/A_EXPOSURE")
    assert verdict(report)["unexposed"] == ([] if exposed else [E])


def test_suffix_excluded_but_top_level_write_turn_counts(tmp_path):
    token = "TOK-5510"
    indexed = spans([row(E2, turn=1, text=token)], [SID], {F: (token,)}, [E2])
    first = ledger(tmp_path / "suffix", [record(cursor=(1, 1), upstream=token)])
    report = score([first], indexed, [item([E2])])
    assert report["spans"][E2]["present"] == []
    assert verdict(report)["cause"] == "N/A_EXPOSURE"
    second = ledger(tmp_path / "control", [record(token, cursor=(1, 1), role="write_turn")])
    assert score([second], indexed, [item([E2])])["spans"][E2]["first"] == [1, 1]


@pytest.mark.parametrize("spec", [record(TOKEN, role="probe_main"),
                                  record(TOKEN, role="summariser", cursor=None),
                                  record(TOKEN, role="memory_write", cursor=None),
                                  record(TOKEN, status=503),
                                  record(request=body() | {TOKEN: "absent"}),
                                  record(TOKEN, role="aux"), record(TOKEN, role="embeddings"),
                                  record(TOKEN, role="unknown"), record(TOKEN, cursor=None)])
def test_excluded_records(tmp_path, spec):
    report = score([ledger(tmp_path, [spec])])
    assert report["spans"][E]["present"] == []
    assert verdict(report)["cause"] == "N/A_EXPOSURE"


def test_delivery_and_probe_bounds(tmp_path):
    root = ledger(tmp_path, [record(TOKEN, cursor=(1, 1)), record(TOKEN, cursor=(3, 1))])
    report = score([root])
    assert report["spans"][E] == dict(delivered=[1, 2], present=[[1, 1], [3, 1]], first=[3, 1])
    assert verdict(report)["cause"] == "N/A_EXPOSURE"
    assert verdict(score([root], items=[item(point=3)]))["cause"] is None
    with pytest.raises(ValueError, match="future"):
        score([root], {E: Span(E, 3, 1, (TOKEN,))})
    before = ledger(tmp_path / "before", [record(TOKEN, cursor=(1, 1))])
    assert score([before])["spans"][E]["first"] is None


def test_and_rules(tmp_path):
    indexed = spans([row(facts=[F, "other"]), row(E2, turn=1)], [SID],
                    {F: (TOKEN,), "other": ("TOK-OTHER",)}, [E, E2])
    report = score([ledger(tmp_path, [record(TOKEN)])], indexed, [item([E, E2])])
    assert report["spans"][E]["first"] is None
    assert report["spans"][E2]["first"] == [1, 2]
    assert verdict(report)["unexposed"] == [E]
    assert verdict(report)["cause"] == "N/A_EXPOSURE"


def test_empty_gold_is_unknown_even_with_probe(tmp_path):
    root = ledger(tmp_path, [record(TOKEN, role="probe_main", cursor=(2, 1), subrole="tool_results")])
    result = verdict(score([root], items=[item([])]))
    assert result == dict(probe=[2, 1], cause=None, unexposed=[], in_context=None, missing=[])


@pytest.mark.parametrize(("recall", "specs", "expected"), [
    (True, [("cursor", "absent", 200), ("tool_results", TOKEN, 200)], True),
    (True, [("tool_results", "absent", 200), ("tool_results", TOKEN, 200)], False),
    (False, [("cursor", TOKEN, 200), ("tool_results", "absent", 200)], True),
    (False, [("cursor", "absent", 200), ("cursor", TOKEN, 200)], False),
    (False, [("cursor", "absent", 500), ("retry", TOKEN, 200)], True),
    (False, [("cursor", "absent", 200), ("retry", TOKEN, 200)], False),
    (False, [("retry", "absent", 200), ("cursor", TOKEN, 200)], False),
    (True, [("cursor", TOKEN, 200)], None),
    (True, [("tool_results", TOKEN, 503)], None),
    (True, [("tool_results", "absent", 503), ("tool_results", TOKEN, 200)], True),
    (False, [("tool_results", TOKEN, 200)], None),
])
def test_probe_first_matching_request(tmp_path, recall, specs, expected):
    root = ledger(tmp_path, [record(text, role="probe_main", cursor=(2, 1), subrole=sub, status=status)
                             for sub, text, status in specs])
    result = verdict(score([root], recall=recall))
    assert result["in_context"] is expected
    assert result["missing"] == ([E] if expected is False else [])
    assert result["cause"] == "N/A_EXPOSURE"


def test_probe_order_shared_cursor_and_cross_root(tmp_path):
    roots = [ledger(tmp_path / "a", [record(role="probe_main", cursor=(2, 1), subrole="tool_results")]),
             ledger(tmp_path / "b", [record(TOKEN, role="probe_main", cursor=(2, 1), subrole="tool_results")])]
    report = score(roots, items=[item(), item([], iid="other")])
    assert verdict(report)["in_context"] is False
    assert report["items"]["other"]["in_context"] is None
    assert verdict(score(list(reversed(roots))))["in_context"] is True


def test_presence_nfc_exact_escape_and_boundaries():
    token = "Zoë-4410"
    assert present((token,), context_text(body("Zoe\u0308-4410")))
    assert present((token,), context_text(body(token)))
    assert not present((token,), context_text(body("zoë-4410")))
    assert not present((token,), context_text(body(r"Zo\u00eb-4410")))
    assert not present(("ABCD",), context_text(["AB", "CD"]))
    assert present(("ABCD", "EFGH"), context_text(["ABCD", {"k": "EFGH"}]))
    assert context_text({"z": ["Z", None, 3, True], "a": {"not-a-value": "A"}}) == "A\x00Z"
    assert context_text({token: 1}) == ""


@pytest.mark.parametrize("needles", [(), ("",), ("a\x00b",), (TOKEN, "")])
def test_invalid_presence_needles(needles):
    with pytest.raises(ValueError):
        present(needles, TOKEN)


@pytest.mark.parametrize("needles", [(), ("",), ("a\x00b",), (TOKEN, "")])
def test_invalid_span_needles_before_ledger_read(tmp_path, monkeypatch, needles):
    root = ledger(tmp_path, [record(role="summariser", cursor=None)])
    indexed = {E: Span(E, 1, 2, (TOKEN,)), E2: Span(E2, 1, 1, needles)}

    def unexpected_read(root):
        pytest.fail("ledger read before span validation")

    monkeypatch.setattr(module, "verify", unexpected_read)
    with pytest.raises(ValueError, match="invalid presence needle"):
        score([root], indexed)


def test_span_normalisation_fallback_and_frozen():
    source = row(text="Zoe\u0308-4410", facts=[])
    value = spans([source], [SID], {}, [E])[E]
    assert value.needles == ("Zoë-4410",)
    with pytest.raises(FrozenInstanceError):
        value.turn = 3
    with pytest.raises(ValueError, match="payload"):
        spans([row(facts=[], payload={"stdout": "text"})], [SID], {}, [E])
    indexed = spans([row(facts=[F, "other"])], [SID],
                    {F: ("Zoe\u0308-4410", "ABCD"), "other": ("Zoë-4410",)}, [E])
    assert indexed[E].needles == ("ABCD", "Zoë-4410")


def test_tokenless_text_exposure_and_redaction(tmp_path):
    text = "Distinct evidence: Zoe\u0308 selected the quiet room."
    indexed = spans([row(text=text, facts=[])], [SID], {}, [E])
    root = ledger(tmp_path, [record(text), record(text, role="probe_main", cursor=(2, 1),
                                                 subrole="tool_results")])
    report = score([root], indexed)
    assert report["spans"][E]["first"] == [1, 2]
    assert verdict(report)["in_context"] is True
    for forbidden in (text, *indexed[E].needles):
        assert forbidden.encode() not in report_bytes(report)


def test_locked_tokens_order_nfc_and_read_only(tmp_path):
    db = create_world(tmp_path / "ordered.db", dict(generator_version="v1", genre="f", seed="s", scale=1))
    try:
        insert_entity(db, id="entity", kind="person", canonical_name="Fixture", aliases_json=[],
                      created_t=0, retired_t=None)
        for fid in (F, "other"):
            insert_fact(db, id=fid, subject_id="entity", predicate="code", object="value",
                        polarity="affirm", modality="stated", strength=1, speech_act="assert")
        for tid, fid, text in [("z", F, "ZZZZ"), ("a", F, "Zoe\u0308"), ("b", "other", "BBBB")]:
            insert_locked_token(db, token_id=tid, fact_id=fid, kind="code", value=text)
        db.commit()
        db.execute("PRAGMA query_only=ON")
        assert locked_tokens(db) == {F: ("Zoë", "ZZZZ"), "other": ("BBBB",)}
    finally:
        db.close()


def test_multi_root_union_and_digests(tmp_path):
    roots = [ledger(tmp_path / "a", [record(TOKEN, cursor=(2, 1)), record(TOKEN, cursor=(1, 3))]),
             ledger(tmp_path / "b", [record(TOKEN), record(TOKEN)])]
    report = score(roots)
    assert report["spans"][E]["present"] == [[1, 2], [1, 3], [2, 1]]
    assert report["spans"][E]["first"] == [1, 2]
    assert report["ledgers"] == [sha256((r / "ledger.jsonl").read_bytes()).hexdigest() for r in roots]
    assert report["volatile"] == ["ledgers", "report_hash"]


def test_empty_roots():
    with pytest.raises(ValueError, match="empty"):
        score([])


@pytest.mark.parametrize("target", ["ledger", "blob", "tail"])
def test_integrity_tamper(tmp_path, target):
    root = ledger(tmp_path, [record(TOKEN, upstream="upstream")])
    if target == "blob":
        rec = json.loads((root / "ledger.jsonl").read_bytes())
        ref = rec["upstream"][0]["req"]
        path = root / "blobs" / ref[:2] / f"{ref}.json.zst"
        raw = path.read_bytes()
        path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    else:
        path = root / "ledger.jsonl"
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] if target == "tail" else raw.replace(b'"status":200', b'"status":201'))
    with pytest.raises(ValueError, match="integrity"):
        score([root])


def test_empty_ledger(tmp_path):
    with pytest.raises(ValueError, match="integrity"):
        score([ledger(tmp_path, [])])


@pytest.mark.parametrize("key", ["life", "branch", "system"])
def test_foreign_identity_even_in_excluded_request(tmp_path, key):
    root = ledger(tmp_path, [record(TOKEN, role="summariser", cursor=None, **{key: "foreign"})])
    with pytest.raises(ValueError, match="identity"):
        score([root])


def test_mixed_lock_hashes(tmp_path):
    roots = [ledger(tmp_path / "a", [record(TOKEN)]),
             ledger(tmp_path / "b", [record(TOKEN)], "d" * 64)]
    with pytest.raises(ValueError, match="lock"):
        score(roots)


@pytest.mark.parametrize("same_root", [True, False])
def test_mixed_attempts_refused(tmp_path, same_root):
    first = ledger(tmp_path / "a", [record(TOKEN, status=500)])
    second = ledger(first if same_root else tmp_path / "b", [record()], attempt_id="att-2")
    with pytest.raises(ValueError, match="^mixed attempts$"):
        score([first] if same_root else [first, second])


@pytest.mark.parametrize("attempt_id", ["att-1", "att-2"])
def test_selected_attempt_isolates_history_and_probe(tmp_path, attempt_id):
    root = ledger(tmp_path, [record(TOKEN), record(role="probe_main", cursor=(2, 1),
                                                 subrole="tool_results")])
    ledger(root, [record(cursor=(1, 3)), record(TOKEN, role="probe_main", cursor=(2, 1),
                                              subrole="tool_results")], attempt_id="att-2")
    report = score([root], attempt_id=attempt_id)
    selected_first = attempt_id == "att-1"
    assert report["spans"][E]["present"] == ([[1, 2]] if selected_first else [])
    assert verdict(report)["cause"] == (None if selected_first else "N/A_EXPOSURE")
    assert verdict(report)["in_context"] is (not selected_first)
    assert verdict(report)["missing"] == ([E] if selected_first else [])


@pytest.mark.parametrize("case", ["unknown", "missing-probe", "extra-probe", "zero", "bool", "float",
                                  "short", "duplicate", "invalid-item"])
def test_item_and_probe_refusals(tmp_path, case):
    items = [item()]
    probes = {items[0]["item_id"]: (2, 1)}
    if case == "unknown":
        items[0]["gold_spans"] = ["unknown"]
    elif case == "missing-probe":
        probes = {}
    elif case == "extra-probe":
        probes["extra"] = (2, 1)
    elif case in ("zero", "bool", "float", "short"):
        probes[items[0]["item_id"]] = {"zero": (0, 1), "bool": (True, 1),
                                      "float": (1, 1.0), "short": (1,)}[case]
    elif case == "duplicate":
        items *= 2
    else:
        items[0]["probe_point"] = 0
    with pytest.raises(ValueError):
        score([ledger(tmp_path, [record()])], items=items, probes=probes)


@pytest.mark.parametrize("key", ["opaque", f"{SID}/t0", f"{SID}/t01", f"{SID}/t-1",
                                 f"{SID}/t1x", f"{SID}/t١", "other/t1", f"{SID}/t1\n"])
def test_malformed_turn_keys(key):
    source = row()
    source["turn_key"] = key
    with pytest.raises(ValueError, match="turn key"):
        spans([source], [SID], {F: (TOKEN,)}, [E])


@pytest.mark.parametrize("case", ["duplicate", "missing", "session", "nul", "empty", "duplicate-session"])
def test_span_refusals(case):
    rows, sessions, tokens, wanted = [row()], [SID], {F: (TOKEN,)}, [E]
    if case == "duplicate":
        rows *= 2
    elif case == "missing":
        wanted = [E2]
    elif case == "session":
        sessions = []
    elif case in ("nul", "empty"):
        tokens = {F: ("bad\x00token" if case == "nul" else "",)}
    else:
        sessions *= 2
    with pytest.raises(ValueError):
        spans(rows, sessions, tokens, wanted)


def test_load_spans_round_trip_and_tamper(tmp_path):
    rows = (row(), row(E2, session="second"))
    sessions = []
    for index in (1, 2):
        value = fixture("session")
        value["index"] = index
        sessions.append(value)
    cut = Cut("life", "B0", rows, tuple(sessions), LOCK, LOCK, "bank", LOCK, False,
              None, "principal", LOCK, LOCK)
    write_branch(tmp_path, cut)
    assert load_spans(tmp_path, "B0", {F: (TOKEN,)}, [E, E2]) == spans(
        rows, [SID, "second"], {F: (TOKEN,)}, [E, E2])
    path = tmp_path / "stream.B0.jsonl"
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b"TOK-4410", b"TOK-4411", 1))
    with pytest.raises(ValueError):
        load_spans(tmp_path, "B0", {F: (TOKEN,)}, [E])


def test_keyed_presence_properties_200_cases(tmp_path):
    roles = [("replay_main", "cursor"), ("replay_main", "tool_results"), ("write_turn", "cursor"),
             ("probe_main", "cursor"), ("summariser", "cursor"), ("memory_write", "cursor")]
    for case in range(200):
        unit = ("s03", "presence", str(case))

        def integer(name, lo, hi, unit=unit):
            return uniform_int("s03-seed", unit, 0, name, lo, hi)

        def pick(name, values, unit=unit):
            return choice("s03-seed", unit, 0, name, values)

        specs, expected = [], set()
        for session in range(1, integer("sessions", 1, 3) + 1):
            for turn in range(1, integer(f"turns-{session}", 1, 5) + 1):
                cursor = (session, turn)
                for n in range(integer(f"count-{cursor}", 0, 3)):
                    name = f"{cursor}-{n}"
                    role, subrole = pick(name + "role", roles)
                    status = pick(name + "status", (200, 503))
                    location = pick(name + "location", ("top", "upstream", "absent"))
                    pos = None if role in ("summariser", "memory_write") else cursor
                    specs.append(record(TOKEN if location == "top" else "absent", role=role,
                                        subrole=subrole, cursor=pos, status=status,
                                        upstream=TOKEN if location == "upstream" else None))
                    if role in ("replay_main", "write_turn") and status == 200 and location == "top":
                        expected.add(cursor)
        root = ledger(tmp_path / str(case), specs)
        # Empty generated ledgers still need a lifecycle record to pass integrity admission.
        if not specs:
            writer = Ledger(root, Guard([]), lock_hash=LOCK, attempt_id="att-1")
            writer.append({"type": "lifecycle"})
            writer.close()
        first = score([root])["spans"][E]
        assert first["present"] == [list(c) for c in sorted(expected)]
        eligible = sorted(c for c in expected if c >= (1, 2))
        assert first["first"] == (list(eligible[0]) if eligible else None)
        writer = Ledger(root, Guard([]), lock_hash=LOCK, attempt_id="att-1")
        try:
            append(writer, record("OTHER-SPAN-TOKEN"))
        finally:
            writer.close()
        assert score([root])["spans"][E] == first


def test_selected_blob_reads_and_no_mutation(tmp_path, monkeypatch):
    root = ledger(tmp_path, [record(upstream=TOKEN), record(TOKEN, role="summariser", cursor=None),
                             record(TOKEN, role="probe_main", cursor=(2, 1), subrole="tool_results"),
                             record(role="probe_main", cursor=(2, 1), subrole="tool_results")])
    records = [json.loads(line) for line in (root / "ledger.jsonl").read_bytes().splitlines()]
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    reads, original = [], BlobStore.get
    # The real verifier uses its own BlobStore; track only scoring reads here.
    class ScoringStore(BlobStore):
        def get(self, ref):
            reads.append(ref)
            return original(self, ref)

    monkeypatch.setattr(module, "BlobStore", ScoringStore)
    indexed, items = {E: Span(E, 1, 2, (TOKEN,))}, [item()]
    saved = copy.deepcopy((indexed, items))
    score([root], indexed, items)
    assert reads == [records[0]["req"], records[2]["req"]]
    assert (indexed, items) == saved
    assert before == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_report_hashseed_subprocesses_and_no_text(tmp_path):
    stdout = "x" * 5000 + " " + TOKEN
    indexed = spans([row(payload={"stdout": stdout})], [SID], {F: (TOKEN,)}, [E])
    text = stdout[:4000] + "\n[truncated]"
    cursors = [(1, t) for t in range(2, 6)] + [(2, t) for t in range(1, 6)]
    root = ledger(tmp_path / "ledger", [record(text, cursor=c, subrole="tool_results") for c in cursors])
    report = score([root], indexed)
    data = report_bytes(report)
    assert data == canon(report)
    for forbidden in (TOKEN, stdout, text):
        assert forbidden.encode() not in data
    code = ("import runpy,sys; n=runpy.run_path(sys.argv[1]); "
            "sys.stdout.buffer.write(n['report_bytes'](n['score']([n['Path'](sys.argv[2])])))")
    outputs = []
    for seed in ("0", "random"):
        env = os.environ.copy()
        env["PYTHONHASHSEED"] = seed
        outputs.append(subprocess.check_output([sys.executable, "-c", code, __file__, str(root)], env=env))
    assert outputs == [data, data]
    assert sha256(outputs[0]).digest() == sha256(outputs[1]).digest()
    print("truncation report sha256:", sha256(data).hexdigest())


def test_import_purity():
    tree = ast.parse(Path(module.__file__).read_text())
    forbidden = ("random", "time", "socket", "ssl", "http", "urllib", "subprocess",
                 "bicentennial.sandbox", "bicentennial.director", "bicentennial.audit", "spikes")
    for node in ast.walk(tree):
        names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                 else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
        assert not any(name == banned or name.startswith(banned + ".") for name in names for banned in forbidden)
        assert not (isinstance(node, ast.Constant) and isinstance(node.value, float))
