import json
import subprocess
import sys
from fractions import Fraction
from time import monotonic

import pytest

from bicentennial.api import Adapter
from bicentennial.api.adapters.bm25 import BM25, log_fixed
from bicentennial.api.adapters.mutants import (
    forget_cached_output,
    forget_ignored,
    orphan_tool_result,
    stale_wins,
    truncate_after_compaction,
    wipe_on_restart,
)
from bicentennial.api.adapters.nomemory import NoMemory
from bicentennial.api.adapters.oracle_evidence import OracleEvidence
from bicentennial.api.adapters.reference_store import ReferenceStore
from bicentennial.api.conformance import CHECKS, EXEMPTIONS, run

ADAPTERS = (ReferenceStore, BM25, NoMemory, OracleEvidence, wipe_on_restart,
            truncate_after_compaction, orphan_tool_result, forget_ignored, stale_wins,
            forget_cached_output)
FAILURES = {wipe_on_restart: "checkpoint_restore",
            truncate_after_compaction: "maintain_lossless",
            orphan_tool_result: "tool_grouping", forget_ignored: "forget_removes",
            stale_wins: "supersession_current", forget_cached_output: "forget_removes"}


def event(i, text, t_sim=None, kind="message", **extra):
    return dict(event_id=i, t_sim=1 if t_sim is None else t_sim,
                kind=kind, actor="tester", text=text, **extra)


def task(prompt, **extra):
    return dict(task_id="test", prompt=prompt, **extra)


def scalar_walk(value):
    assert not isinstance(value, float)
    if isinstance(value, dict):
        for key, child in value.items():
            assert type(key) is str
            scalar_walk(child)
    elif isinstance(value, list):
        for child in value:
            scalar_walk(child)
    else:
        assert type(value) in (str, int)


def test_conformance_matrix(capsys):
    start = monotonic()
    matrix = {factory.__name__: run(factory) for factory in ADAPTERS}
    elapsed = monotonic() - start
    with capsys.disabled():
        print("\nadapter | " + " | ".join(CHECKS))
        for factory in ADAPTERS:
            row = matrix[factory.__name__]
            print(factory.__name__ + " | " + " | ".join(
                "EXEMPT" if check in EXEMPTIONS.get(factory, ()) else
                "PASS" if row[check] else "FAIL" for check in CHECKS))
    for factory in ADAPTERS:
        row = matrix[factory.__name__]
        assert tuple(row) == CHECKS
        assert all(type(result) is bool for result in row.values())
        assert {check for check, passed in row.items() if not passed} == (
            {FAILURES[factory]} if factory in FAILURES else set())
    assert elapsed < 20, "conformance matrix exceeded its 20-second acceptance budget"


@pytest.mark.parametrize("factory", ADAPTERS)
def test_return_shapes_have_no_floats(factory):
    a = factory()
    assert isinstance(a, Adapter)
    assert a.reset() is None
    assert a.ingest(event("one", "quartz")) is None
    assert a.settle(5) is True
    result = a.query(task("quartz", oracle_evidence=["one"]), 1)
    assert set(result) == {"output", "citations", "confidence_milli"}
    scalar_walk(result)
    assert type(result["output"]) is str
    assert type(result["citations"]) is list
    assert all(type(i) is str for i in result["citations"])
    assert type(result["confidence_milli"]) is int
    assert 0 <= result["confidence_milli"] <= 1000
    stats = a.stats()
    assert set(stats) == {"tokens", "latency_ms"}
    assert all(type(v) is int and v >= 0 for v in stats.values())
    scalar_walk(stats)
    data = a.checkpoint()
    assert type(data) is bytes
    scalar_walk(json.loads(data))
    assert a.maintain() is None
    assert a.restore(data) is None
    assert a.forget(dict(event_ids=["one"])) is None


def test_two_processes_are_identical():
    script = """
from bicentennial.api.adapters.reference_store import ReferenceStore
from bicentennial.api.adapters.bm25 import BM25
from bicentennial.api.adapters.nomemory import NoMemory
from bicentennial.api.adapters.oracle_evidence import OracleEvidence
from bicentennial.api.adapters.mutants import (
    wipe_on_restart, truncate_after_compaction, orphan_tool_result, forget_ignored, stale_wins,
    forget_cached_output)
from bicentennial.api.conformance import run
from bicentennial.canon import canon
rows = {}
for factory in (ReferenceStore, BM25, NoMemory, OracleEvidence, wipe_on_restart,
                truncate_after_compaction, orphan_tool_result, forget_ignored, stale_wins,
                forget_cached_output):
    a = factory()
    for i, text in enumerate(('quartz old', 'quartz new', 'topaz')):
        a.ingest(dict(event_id=str(i), t_sim=i, kind='message', actor='fixture', text=text))
    assert a.settle(5)
    rows[factory.__name__] = dict(
        checks=run(factory), checkpoint=a.checkpoint().decode(), stats=a.stats(),
        query=a.query(dict(task_id='q', prompt='quartz', oracle_evidence=['1']), 3))
print(canon(rows).decode())
"""
    outputs = [subprocess.run([sys.executable, "-c", script], capture_output=True,
                              check=True, timeout=10).stdout for _ in range(2)]
    assert outputs[0] == outputs[1]
    assert set(json.loads(outputs[0])) == {factory.__name__ for factory in ADAPTERS}


def test_optimized_python_keeps_every_check():
    script = """
from bicentennial.api.adapters import mutants
from bicentennial.api.adapters.reference_store import ReferenceStore
from bicentennial.api.conformance import run
assert False, "python -O must strip this line"
"""
    probe = """
import json
from bicentennial.api.adapters import mutants
from bicentennial.api.adapters.reference_store import ReferenceStore
from bicentennial.api.conformance import run
names = ("ReferenceStore", "wipe_on_restart", "truncate_after_compaction",
         "orphan_tool_result", "forget_ignored", "stale_wins", "forget_cached_output")
factories = [ReferenceStore] + [getattr(mutants, name) for name in names[1:]]
print(json.dumps({f.__name__: sorted(c for c, ok in run(f).items() if not ok) for f in factories}))
"""
    subprocess.run([sys.executable, "-O", "-c", script], check=True, timeout=10)  # -O is active
    rows = json.loads(subprocess.run([sys.executable, "-O", "-c", probe], capture_output=True,
                                     check=True, timeout=20).stdout)
    assert rows == {factory.__name__: sorted({FAILURES[factory]} if factory in FAILURES else ())
                    for factory in (ReferenceStore, *FAILURES)}


@pytest.mark.parametrize("factory", (ReferenceStore, BM25))
def test_supported_store_path(factory):
    a = factory()
    call = event("zcall", "dispatch", t_sim=2, kind="tool_call")
    result = event("aresult", "delivered", t_sim=2, kind="tool_result", call_id="zcall")
    for e in (call, result, result):
        a.ingest(e)
    data = a.checkpoint()
    a.reset()
    a.restore(data)
    assert a.checkpoint() == data
    assert a.query(task("delivered"), 2)["citations"] == ["aresult"]
    assert a.query(task("dispatch"), 2)["citations"] == ["zcall"]
    a.forget(dict(event_ids=["zcall"]))
    assert a.checkpoint() == b"[]"  # Erasing a call erases dependent results too.


def test_reference_ranking_and_temporal_boundary():
    a = ReferenceStore()
    for e in (event("b", "CAFÉ Azure", 3), event("a", "café azure", 3),
              event("later", "azure", 8), event("repeated", "azure azure azure", 1)):
        a.ingest(e)
    assert a.query(task("café azure"), 10)["citations"] == ["b"]
    assert a.query(task("azure"), 10)["citations"] == ["later"]
    assert a.query(task("azure"), 2)["citations"] == ["repeated"]
    assert a.query(task("absent"), 10) == dict(
        output="UNKNOWN", citations=[], confidence_milli=0)


def test_bm25_idf_frequency_length_and_query_deduplication():
    assert log_fixed(Fraction(2)) == 693147
    assert log_fixed(Fraction(16)) == 2772588
    a = BM25()
    documents = [event("short", "quartz"), event("long", "quartz " + "filler " * 12),
                 event("frequent", "quartz quartz quartz")]
    for e in documents:
        a.ingest(e)
    scores = a.scores("quartz", documents)
    assert scores[2] > scores[0] > scores[1] > 0
    assert a.scores("quartz quartz", documents) == scores
    assert a.query(task("quartz"), 1)["citations"] == ["frequent"]
    assert a.scores("quartz", [event("empty", "")]) == [0]


def test_oracle_uses_exact_evidence_and_nomemory_keeps_nothing():
    oracle, empty = OracleEvidence(), NoMemory()
    for e in (event("one", "first"), event("two", "second"), event("three", "decoy")):
        oracle.ingest(e)
        empty.ingest(e)
    assert oracle.query(task("decoy", oracle_evidence=["two", "one"]), 1) == dict(
        output="second\nfirst", citations=["two", "one"], confidence_milli=1000)
    assert oracle.query(task("first"), 1)["output"] == "UNKNOWN"
    with pytest.raises(ValueError):
        oracle.query(task("first", oracle_evidence=["missing"]), 1)
    assert empty.checkpoint() == b"[]"
    assert empty.stats() == dict(tokens=0, latency_ms=0)
    assert empty.query(task("first", oracle_evidence=["one"]), 1) == dict(
        output="UNKNOWN", citations=[], confidence_milli=0)


@pytest.mark.parametrize("factory", (ReferenceStore, BM25, NoMemory, OracleEvidence))
@pytest.mark.parametrize("change", [dict(t_sim=1.0), dict(t_sim=True), dict(t_sim=-1),
                                    dict(event_id=""), dict(text=0), dict(kind="other"),
                                    dict(extra="field"), dict(call_id="unexpected")])
def test_rejects_malformed_events(factory, change):
    e = event("one", "quartz") | change
    with pytest.raises((ValueError, TypeError)):
        factory().ingest(e)


@pytest.mark.parametrize("factory", (ReferenceStore, BM25, NoMemory, OracleEvidence))
def test_input_validation_and_ownership(factory):
    a = factory()
    original = event("one", "quartz")
    a.ingest(original)
    data = a.checkpoint()
    original["text"] = "mutated"
    assert a.checkpoint() == data
    for bad in (task("x", oracle_evidence=[1]), task("x", oracle_evidence=["a", "a"]),
                task("x", extra="field"), dict(task_id="q", prompt=1.0)):
        with pytest.raises((TypeError, ValueError)):
            a.query(bad, 1)
    for bad in (-1, True, 0.5):
        with pytest.raises((TypeError, ValueError)):
            a.settle(bad)
        with pytest.raises((TypeError, ValueError)):
            a.query(task("x"), bad)
    with pytest.raises((TypeError, ValueError)):
        a.forget(dict(event_ids=[False]))
    a.reset()
    assert a.settle(0) is True


def test_restore_is_atomic_and_tool_links_are_validated():
    a = ReferenceStore()
    a.ingest(event("one", "quartz"))
    before = a.checkpoint()
    for bad in (b"{}", b"[1]", b"[{\"event_id\":1.0}]", b"not json"):
        with pytest.raises((TypeError, ValueError)):
            a.restore(bad)
        assert a.checkpoint() == before
    with pytest.raises(TypeError):
        a.restore("[]")
    for bad in (event("one", "changed"), event("r", "result", kind="tool_result"),
                event("r", "result", kind="tool_result", call_id="one")):
        with pytest.raises(ValueError):
            a.ingest(bad)


def test_exemptions_cannot_be_inherited_by_store_adapters():
    class PretendNoMemory(NoMemory):
        pass

    row = run(PretendNoMemory)
    assert not row["maintain_lossless"]
    assert not row["tool_grouping"]
    assert not row["supersession_current"]
