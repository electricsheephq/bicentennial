"""S05 acceptance fixtures; script mode emits canonical, token-free verdicts."""

import ast
import json
import runpy
import sqlite3
import sys
from compression import zstd
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from bicentennial.api.adapters import mutants
from bicentennial.api.adapters.bm25 import BM25
from bicentennial.api.adapters.nomemory import NoMemory
from bicentennial.api.adapters.oracle_evidence import OracleEvidence
from bicentennial.api.adapters.reference_store import ReferenceStore
from bicentennial.canon import canon
from bicentennial.contracts.items import reader_view
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.items.levers import STRESS_TAGS
from bicentennial.items.protocol import DIRECTIONS
from bicentennial.keyed import choice, uniform_int
from bicentennial.probe.scripted_reader import read
from bicentennial.score import invariants as inv

ROOT = SCHEMAS.parent
FAILURES = runpy.run_path(str(ROOT / "tests" / "api" / "test_conformance.py"))["FAILURES"]
TOKEN = "GATE-4410"
TOKENS = ("LOCK-4417", "SLOT-2202", "SLOT-1101", "ZONE-4404", "ZONE-3303", TOKEN)
ADAPTERS = (ReferenceStore, BM25, mutants.truncate_after_compaction, mutants.stale_wins,
            mutants.orphan_tool_result, mutants.forget_ignored, mutants.forget_cached_output,
            mutants.reset_cached_output, mutants.wipe_on_restart, NoMemory, OracleEvidence)
EXPECTED = ("PPPP", "PPPP", "FPPP", "PFPP", "PPFP", "PPPF", "PPPF", "PPPP", "FFFP", "IFFP", "IFFP")


def load(path):
    return json.loads(path.read_bytes())


def option(i, token, *, act=False):
    result = dict(option_id=i, tokens=[token] if token else [])
    if act:
        result["plan"] = {"steps": [{"tool": {"name": "choose_region", "args": {"region": token}}}]
                          if token else []}
    else:
        result["envelope"] = dict(type="entity" if token else "unknown", value=token,
                                  confidence_milli=1000 if token else 0)
    return result


def evidence(i, cell, token, context, *, old=None, act=False, direction="recency",
             crossed=("crash",), restart=True, forbidden=(), baseline=None, roots=None):
    item = load(SCHEMAS / "fixtures" / "gen" / ("act-item.json" if act else "item.json"))
    item.update(item_id=i, cell_id=cell, prompt="Choose the current value.",
                options=[option(i + "-new", token, act=act)]
                + ([option(i + "-old", old, act=act)] if old else [])
                + ([option(i + "-unknown", None, act=act)] if token else []),
                gold=dict(option_id=i + "-new", never_observed=False))
    record = load(ROOT / "tests" / "fixtures" / "items" / "contracts.json")["contracts"]["item_record"]
    record.update(item_id=i, direction=direction, crossed=list(crossed))
    keys = dict(item_id=i, life="s05-run", branch="B0", canary=item["canary"],
                required=[token] if token else [], forbidden=list(forbidden),
                competing=[dict(kind="stale", token=old)] if old else [],
                oracle_spans=item["gold_spans"], recall_query=item["prompt"])
    for name, value in (("item", item), ("item_record", record), ("reader_keys", keys)):
        validate(name, value)
    result = read(reader_view(item), keys, context, mode="hermes")
    return inv.ItemEvidence(item, record, keys, result, None, restart, baseline, roots)


def run_rows(context):
    return [evidence("t-verb", "RECALL-VERB", "LOCK-4417", context, direction=inv.VERBATIM),
            evidence("t-new", "FAULT-NEWEST", "SLOT-2202", context, old="SLOT-1101"),
            evidence("t-drift", "DRIFT-CUR", "ZONE-4404", context, old="ZONE-3303", act=True),
            evidence("t-extract", "RECALL-VERB", "HOST-8823", context,
                     direction="extraction and consolidation", crossed=("compaction",)),
            evidence("t-nocross", "DRIFT-CUR", "ZONE-4404", context, act=True, restart=False)]


def compressed():
    blob = zstd.compress(b"".join(f"GATE-{i:04d}\n".encode() for i in range(4000, 4500)))
    assert blob[:4] == bytes.fromhex("28b52ffd")
    assert TOKEN.encode() not in blob
    return blob


def chat(calls=(), outputs=()):
    return {"messages": [dict(role="assistant", tool_calls=[
        {"id": i, "function": {"name": "fetch_status", "arguments": "{}"}} for i in calls])]
        + [dict(role="tool", tool_call_id=i, content="ok") for i in outputs]}


class Unsettled(ReferenceStore):
    def settle(self, bound_s):
        return False


class Malformed(ReferenceStore):
    def query(self, task, now):
        return dict(output="", citations=[], confidence_milli=1.5)


def scenarios(root):
    rows = {f"api-{cls.__name__}": inv.adapter_invariants(cls, bound_s=5) for cls in ADAPTERS}
    for cls in (Unsettled, Malformed):
        rows[f"api-{cls.__name__}"] = inv.adapter_invariants(cls, bound_s=5)

    def broken_snapshot(adapter):
        raise OSError("fixture snapshot error")

    def snapshot(adapter, *, opaque=False):
        directory = root / ("opaque-api" if opaque else "plain-api")
        directory.mkdir(exist_ok=True)
        data = adapter.checkpoint()
        (directory / "store").write_bytes(zstd.compress(data) if opaque else data)
        return (directory,)

    rows["snapshot-error"] = inv.adapter_invariants(ReferenceStore, bound_s=5, snapshot=broken_snapshot)
    rows["snapshot-plain"] = inv.adapter_invariants(ReferenceStore, bound_s=5, snapshot=snapshot)
    rows["snapshot-opaque"] = inv.adapter_invariants(
        ReferenceStore, bound_s=5, snapshot=lambda a: snapshot(a, opaque=True))
    rows["snapshot-hit"] = inv.adapter_invariants(mutants.forget_ignored, bound_s=5, snapshot=snapshot)
    for name, context in (("system", " ".join(TOKENS)), ("wiped", ""),
                          ("stale", "LOCK-4417 SLOT-1101 ZONE-3303")):
        items = run_rows(context)
        rows[name] = inv.run_invariants(items, tier="T1")
        blocked = [replace(e, failure_class="BLOCKED") if e.item["item_id"] == "t-new" else e for e in items]
        rows[name + "-blocked"] = inv.run_invariants(blocked, tier="T1")
    system = run_rows(" ".join(TOKENS))
    for failure in ("SYSTEM_FAILURE", "N/A_EXPOSURE", "N/A_CLOCK", "FAIL_TASK"):
        rows[failure] = inv.run_invariants([replace(system[0], failure_class=failure,
                                                   result=system[0].result if failure == "FAIL_TASK" else None)], tier="T1")
    for baseline in (True, False):
        for present in (True, False):
            e = run_rows("LOCK-4417" if present else "")[0]
            rows[f"twin-{baseline}-{present}"] = inv.run_invariants(
                [replace(e, baseline_in_context=baseline)], tier="T0")
    for name, data in (("empty", None), ("hit", TOKEN.encode()), ("opaque", compressed())):
        directory = root / name
        directory.mkdir()
        if data is not None:
            (directory / "store").write_bytes(data)
        e = evidence("t-forget", "KEEP-FORGET", None, "", forbidden=[TOKEN], roots=(directory,))
        rows["forget-" + name] = inv.run_invariants([e], tier="T0")
        rows["forget-t1-" + name] = inv.run_invariants([e], tier="T1")
    for name, context in (("no-snapshot", ""), ("surfaced", TOKEN)):
        e = evidence("t-forget", "KEEP-FORGET", None, context, forbidden=[TOKEN])
        rows["forget-" + name] = inv.run_invariants([e], tier="T0")
    requests = {
        "chat-pair": ([("chat", chat(["c1"], ["c1"]))], ()),
        "orphan-result": ([("chat", chat([], ["c2"]))], ()),
        "responses-pair": ([("responses", {"input": [dict(type="function_call", call_id="r1", name="get"),
                                                          dict(type="function_call_output", call_id="r1", output="ok")]})], ()),
        "empty-request": ([("chat", {"messages": []})], ()),
        "no-request": (None, ()),
        "orphan-call": ([("chat", chat(["c1"], []))], ()),
        "mixed": ([("chat", chat(["c1", "c2"], ["c1"]))], ()),
        "lost-original": ([("chat", chat(["new"], ["new"]))], ("original",)),
        "lost-all": ([("chat", chat())], ("original",)),
        "no-request-expected": (None, ("original",)),
        "expected-present": ([("chat", chat(["original"], ["original"]))], ("original",)),
        "expected-later": ([("chat", chat(["new"], ["new"])),
                            ("chat", chat(["original"], ["original"]))], ("original",)),
        "none-id": ([("chat", chat([None], [None]))], ()),
    }
    for name, (reqs, expected) in requests.items():
        rows[name] = inv.run_invariants([], tier="T1", requests=reqs, expected_call_ids=expected)
    return rows


@pytest.fixture
def cases(tmp_path):
    return scenarios(tmp_path)


def test_api_matrix_and_correlation(cases, capsys):
    with capsys.disabled():
        print("\nadapter | " + " | ".join(inv.INVARIANTS))
        for cls, expected in zip(ADAPTERS, EXPECTED, strict=True):
            row = cases[f"api-{cls.__name__}"]
            print(cls.__name__ + " | " + " | ".join(v.status for v in row.values()))
            assert "".join(v.status[0] for v in row.values()) == expected
            assert tuple(row) == inv.INVARIANTS
            for name, verdict in row.items():
                if verdict.status == "FAIL" and cls in FAILURES and cls is not mutants.wipe_on_restart:
                    assert inv.CONFORMANCE_PEER[name] == FAILURES[cls]
    expected_ids = {
        "truncate_after_compaction": {"INV-VERB": ("verb-1", "verb-2", "verb-3")},
        "stale_wins": {"INV-NEW": ("new-a", "new-b")},
        "orphan_tool_result": {"INV-PAIR": ("pair-call", "pair-result")},
        "forget_ignored": {"INV-FORGET": ("forget-1", "forget-2", "forget-store")},
        "forget_cached_output": {"INV-FORGET": ("forget-2",)},
        "wipe_on_restart": {"INV-VERB": ("verb-1", "verb-2", "verb-3"),
                            "INV-NEW": ("new-a", "new-b"), "INV-PAIR": ("pair-call", "pair-result")}}
    for cls, checks in expected_ids.items():
        assert {k: v.failed for k, v in cases["api-" + cls].items() if v.failed} == checks
    assert cases["api-orphan_tool_result"]["INV-PAIR"].reasons == ("system_failure",)
    assert cases["api-forget_cached_output"]["INV-FORGET"].reasons == ("surfaced",)
    for cls in (NoMemory, OracleEvidence):
        v = cases["api-" + cls.__name__]["INV-VERB"]
        assert (v.members, v.uninformative) == (0, 3)


def test_api_failure_classes(cases):
    for cls in (Unsettled, Malformed):
        for v in cases["api-" + cls.__name__].values():
            assert v.status == "FAIL" and v.reasons == ("system_failure",)
    for name, status, reason in (("error", "INFRA_FAILURE", "infra"), ("plain", "PASS", None),
                                 ("opaque", "INCONCLUSIVE", "opaque_store"), ("hit", "FAIL", "store_hit")):
        v = cases["snapshot-" + name]["INV-FORGET"]
        assert v.status == status
        assert reason in v.reasons if reason else v.reasons == ()


def test_store_search(tmp_path):
    needle = inv.needles_for([TOKEN])
    assert needle == (b"GATE-4410", b"gate-4410")
    assert inv.needles_for(["CAFE\u0301", "CAFÉ"]) == ("CAFÉ".encode(), "café".encode())
    assert inv.search_store(tmp_path, needle) == inv.StoreSearch("absent", (), ())
    for name, content in (("memories/MEMORY.md", b"remember GATE-4410"),
                          ("sessions/s1.jsonl", canon({"token": TOKEN}) + b"\n")):
        root = tmp_path / name.split("/")[0]
        root.mkdir()
        path = tmp_path / name
        path.write_bytes(content)
        assert inv.search_store(root, needle).hit_paths == (path.name,)
    opaque = tmp_path / "opaque"
    opaque.mkdir()
    (opaque / "blob.zst").write_bytes(compressed())
    assert inv.search_store(opaque, needle) == inv.StoreSearch("inconclusive", (), ("blob.zst",))
    (opaque / "MEMORY.md").write_text(TOKEN)
    assert inv.search_store(opaque, needle) == inv.StoreSearch("found", ("MEMORY.md",), ("blob.zst",))
    binary = tmp_path / "binary"
    binary.mkdir()
    (binary / "data").write_bytes(b"\xff\xfe\x00")
    assert inv.search_store(binary, needle).verdict == "inconclusive"
    links = tmp_path / "links"
    links.mkdir()
    outside = tmp_path / "outside"
    outside.write_text(TOKEN)
    (links / "file").symlink_to(outside)
    (links / "directory").symlink_to(opaque, target_is_directory=True)
    assert inv.search_store(links, needle) == inv.StoreSearch("absent", (), ())
    assert inv.searchable(links / "file") is False


def test_sqlite_hit_and_encoded_miss(tmp_path):
    for encoded in (False, True):
        directory = tmp_path / str(encoded)
        directory.mkdir()
        with sqlite3.connect(directory / "store.sqlite") as connection:
            assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
            connection.execute("CREATE TABLE memory (value)")
            connection.execute("INSERT INTO memory VALUES (?)", (TOKEN.encode().hex() if encoded else TOKEN,))
            connection.commit()
            result = inv.search_store(directory, inv.needles_for([TOKEN]))
            assert result.verdict == ("inconclusive" if encoded else "found")
            if not encoded:
                assert "store.sqlite-wal" in result.hit_paths
            assert "store.sqlite" in result.opaque_paths and "store.sqlite-wal" in result.opaque_paths
            assert not inv.searchable(directory / "store.sqlite")
            assert not inv.searchable_bytes((directory / "store.sqlite").read_bytes())
    for suffix in ("-wal", "-shm", "-journal"):
        (tmp_path / ("fake" + suffix)).write_bytes(b"\xff\xfe")
        assert not inv.searchable(tmp_path / ("fake" + suffix))


def test_incremental_utf8_and_errors(tmp_path, monkeypatch):
    path = tmp_path / "large"
    path.write_bytes(b"a" * (1024 * 1024 - 1) + "é".encode())
    assert inv.searchable(path)
    path.write_bytes(b"a" * (1024 * 1024 - 1) + b"\xc3")
    assert not inv.searchable(path)
    assert inv.searchable_bytes(b"") and not inv.searchable_bytes(b"\xff")
    with pytest.raises(OSError):
        inv.search_store(tmp_path / "missing", [b"needle"])
    original, count = inv.span_search, []

    def counted(root, needles):
        count.append(1)
        return original(root, needles)

    monkeypatch.setattr(inv, "span_search", counted)
    inv.search_store(tmp_path, [b"needle"])
    assert count == [1]


def test_run_evidence(cases):
    assert (cases["system"]["INV-VERB"].status, cases["system"]["INV-VERB"].members) == ("PASS", 1)
    assert (cases["system"]["INV-NEW"].status, cases["system"]["INV-NEW"].members) == ("PASS", 2)
    assert cases["system"]["INV-FORGET"].status == "NOT_EXERCISED"
    assert cases["wiped"]["INV-VERB"].failed == ("t-verb",)
    assert cases["wiped"]["INV-NEW"].failed == ("t-drift", "t-new")
    assert cases["stale"]["INV-VERB"].status == "PASS"
    assert cases["stale"]["INV-NEW"].status == "FAIL"
    assert cases["system-blocked"]["INV-NEW"].status == "INFRA_FAILURE"
    assert cases["system-blocked"]["INV-NEW"].reasons == ("blocked",)
    assert cases["wiped-blocked"]["INV-NEW"].status == "FAIL"
    assert cases["SYSTEM_FAILURE"]["INV-VERB"].reasons == ("system_failure",)
    assert cases["SYSTEM_FAILURE"]["INV-VERB"].status == "FAIL"
    for failure in ("N/A_EXPOSURE", "N/A_CLOCK"):
        assert cases[failure]["INV-VERB"].status == "NOT_EXERCISED"
    assert cases["FAIL_TASK"]["INV-VERB"].status == "PASS"
    for name, expected in (("True-True", "PASS"), ("True-False", "FAIL"),
                            ("False-True", "INCONCLUSIVE"), ("False-False", "INCONCLUSIVE")):
        assert cases["twin-" + name]["INV-VERB"].status == expected
    for name, status, reason in (("hit", "FAIL", "store_hit"), ("empty", "PASS", None),
                                 ("opaque", "INCONCLUSIVE", "opaque_store"),
                                 ("no-snapshot", "INCONCLUSIVE", "no_snapshot"), ("surfaced", "FAIL", "surfaced")):
        v = cases["forget-" + name]["INV-FORGET"]
        assert v.status == status
        assert v.reasons == ((reason,) if reason else ())
    for name in ("hit", "empty", "opaque"):
        assert cases["forget-t1-" + name]["INV-FORGET"].status == "NOT_EXERCISED"


def test_requests(cases):
    for name in ("chat-pair", "responses-pair", "expected-present", "expected-later"):
        assert cases[name]["INV-PAIR"].status == "PASS"
    for name in ("orphan-result", "orphan-call", "mixed", "none-id"):
        v = cases[name]["INV-PAIR"]
        assert v.status == "FAIL" and v.failed == ("req-1",) and v.reasons == ("orphan_result",)
    for name in ("empty-request", "no-request"):
        assert cases[name]["INV-PAIR"].status == "NOT_EXERCISED"
    for name in ("lost-original", "lost-all", "no-request-expected"):
        v = cases[name]["INV-PAIR"]
        assert v.status == "FAIL" and v.failed == ("expected-1",)
    # Whole groups must coexist within a request, not across two requests.
    v = inv.run_invariants([], tier="T1", requests=[("chat", chat(["c"], [])),
                           ("chat", chat([], ["c"]))], expected_call_ids=["c"])["INV-PAIR"]
    assert v.failed == ("expected-1", "req-1", "req-2")


@pytest.mark.parametrize("bad", ["tier", "item", "record", "keys", "record-id", "keys-id", "result-id",
                                     "duplicate", "class", "none", "fail-task-none", "baseline", "wire"])
def test_refusals(bad):
    e = run_rows("LOCK-4417")[0]
    items, kw = [e], dict(tier="T1")
    if bad in ("item", "record", "keys"):
        items = [replace(e, **{bad: {}})]
    elif bad in ("record-id", "keys-id"):
        field = bad.removesuffix("-id")
        items = [replace(e, **{field: getattr(e, field) | {"item_id": "other"}})]
    elif bad == "result-id":
        items = [replace(e, result=replace(e.result, item_id="other"))]
    elif bad == "duplicate":
        items *= 2
    elif bad in ("none", "fail-task-none"):
        items = [replace(e, result=None, failure_class="FAIL_TASK" if bad == "fail-task-none" else None)]
    elif bad == "class":
        items = [replace(e, failure_class="INFRA_FAILURE")]
    elif bad == "baseline":
        kw["tier"] = "T0"
    elif bad == "wire":
        kw["requests"] = [("bad", {})]
    else:
        kw["tier"] = "T2"
    with pytest.raises(ValueError):
        inv.run_invariants(items, **kw)


def test_keyed_properties():
    for c in range(200):
        unit = ("s05", "ctx", str(c))
        mask = uniform_int("s05", unit, 0, "subset", 0, (1 << len(TOKENS)) - 1)
        selected = [t for n, t in enumerate(TOKENS) if mask & (1 << n)]
        context = choice("s05", unit, 0, "separator", (" ", "\n", " | ")).join(selected)
        evidence_rows = run_rows(context)
        verdicts = inv.run_invariants(evidence_rows, tier="T1")
        assert (verdicts["INV-VERB"].status == "PASS") == ("LOCK-4417" in selected)
        assert verdicts["INV-NEW"].status == ("PASS" if all(t in selected for t in ("SLOT-2202", "ZONE-4404")) else "FAIL")
        reversed_rows = inv.run_invariants(reversed(evidence_rows), tier="T1")
        assert [v.to_obj() for v in verdicts.values()] == [v.to_obj() for v in reversed_rows.values()]


def test_hygiene(cases):
    assert inv.VERBATIM == DIRECTIONS[0]
    assert inv.STRESSES == tuple(sorted(STRESS_TAGS[k] for k in ("kill", "compaction")))
    assert inv.GATED_T1 == ("INV-VERB", "INV-NEW", "INV-PAIR")
    assert inv.INVARIANTS == ("INV-VERB", "INV-NEW", "INV-PAIR", "INV-FORGET")
    for row in cases.values():
        for verdict in row.values():
            blob = canon(verdict.to_obj())
            assert not any(t.encode() in blob for t in (*TOKENS, "HOST-8823", "OWNR-3391",
                                                        "Choose the current value.", "archive locker code"))
            for field in ("failed", "inconclusive", "infra", "reasons"):
                values = getattr(verdict, field)
                assert values == tuple(sorted(set(values)))
    tree = ast.parse(Path(inv.__file__).read_text())
    allowed = {"codecs", "json", "os", "stat", "unicodedata", "dataclasses", "pathlib", "collections.abc",
               "bicentennial.canon", "bicentennial.contracts.run", "bicentennial.api.contract",
               "bicentennial.probe.scripted_reader", "bicentennial.sandbox.spansearch", "bicentennial.audit.readback"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(a.name in allowed for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.module in allowed
        elif isinstance(node, ast.Constant):
            assert not isinstance(node.value, float)
    assert "lcm-x" not in Path(inv.__file__).read_text().casefold()
    v = inv.Verdict("INV-VERB", "FAIL", 1, 0, ("b", "a", "b"), (), (), ("not_newest", "not_newest"))
    assert v.failed == ("a", "b") and v.reasons == ("not_newest",)
    with pytest.raises(FrozenInstanceError):
        v.status = "PASS"


if __name__ == "__main__":
    with TemporaryDirectory() as directory:
        rows = scenarios(Path(directory))
        sys.stdout.buffer.write(canon({name: [v.to_obj() for v in row.values()]
                                       for name, row in sorted(rows.items())}) + b"\n")
