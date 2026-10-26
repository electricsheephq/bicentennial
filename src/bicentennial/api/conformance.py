"""Isolated adapter checks; run returns a bool for every named check.

Only exact NoMemory/OracleEvidence classes are exempt from maintain_lossless,
tool_grouping and supersession_current: these require ordinary store retrieval.
Exempt checks return True (not a claim of retrieval); EXEMPTIONS exposes them.
All other checks apply. Each check uses a fresh adapter and settles before
every probe/checkpoint; exceptions fail that check and do not abort the suite.
"""

from .adapters.nomemory import NoMemory
from .adapters.oracle_evidence import OracleEvidence
from .contract import shape

CHECKS = ("reset_empty", "duplicate_id_idempotent", "citations_are_event_ids",
          "checkpoint_restore", "maintain_lossless", "tool_grouping", "forget_removes",
          "supersession_current", "settle_returns")
EXEMPTIONS = dict.fromkeys((NoMemory, OracleEvidence), frozenset(
    ("maintain_lossless", "tool_grouping", "supersession_current")))


def _event(i, text, kind="message", **extra):
    return dict(event_id=f"e{i}", t_sim=i, kind=kind, actor="fixture", text=text, **extra)


def _query(adapter, text, ids=()):
    assert adapter.settle(5) is True
    result = adapter.query(dict(task_id="probe", prompt=text, oracle_evidence=list(ids)), 100)
    # Every probe also checks the answer's shape: a float or extra field fails the check it is in.
    shape(result, dict(output=str, citations=list, confidence_milli=int))
    assert all(type(c) is str for c in result["citations"]) and 0 <= result["confidence_milli"] <= 1000
    return result


def _checkpoint(adapter):
    assert adapter.settle(5) is True
    return adapter.checkpoint()


def _check(name, a, factory):
    a.reset()
    a.ingest(_event(1, "quartz"))
    if name == "reset_empty":
        _query(a, "quartz")  # A query cache that survives reset must not answer the next one.
        a.reset()
        assert _query(a, "quartz")["citations"] == []
    elif name == "duplicate_id_idempotent":
        a.ingest(_event(2, "quartz"))  # A competing match: a re-ranked duplicate shows up here.
        before = _checkpoint(a), _query(a, "quartz", ["e1"])
        a.ingest(_event(1, "quartz"))
        assert before == (_checkpoint(a), _query(a, "quartz", ["e1"]))
    elif name == "citations_are_event_ids":
        a.ingest(_event(2, "topaz"))
        for text in ("quartz", "topaz", "absent", ""):
            assert set(_query(a, text, ["e1", "e2"])["citations"]) <= {"e1", "e2"}
    elif name == "checkpoint_restore":
        a.ingest(_event(2, "topaz"))
        a.ingest(_event(3, "garnet"))
        probes = (("quartz", "e1"), ("topaz", "e2"), ("garnet", "e3"))
        before, data = [_query(a, t, [i]) for t, i in probes], _checkpoint(a)
        a.reset()
        a.restore(data)
        fresh = factory()  # A restore that ignores its bytes, or keeps only part, fails here.
        fresh.restore(data)
        for restored in (a, fresh):
            assert [_query(restored, t, [i]) for t, i in probes] == before
    elif name == "maintain_lossless":
        texts = ["quartz"] + [f"gem{i:02d}" for i in range(2, 51)]  # More than any small cap.
        for i, text in enumerate(texts[1:], 2):
            a.ingest(_event(i, text))
        a.maintain()
        for i, text in enumerate(texts, 1):
            result = _query(a, text)
            assert result["output"] == text and result["citations"] == [f"e{i}"]
    elif name == "tool_grouping":
        a.ingest(_event(2, "dispatch", "tool_call"))
        a.ingest(_event(3, "delivered", "tool_result", call_id="e2"))
        a.maintain()  # Compaction must not orphan a tool result.
        for text, event_id in (("delivered", "e3"), ("dispatch", "e2")):
            result = _query(a, text)
            assert result["output"] == text and result["citations"] == [event_id]
    elif name == "forget_removes":
        a.ingest(_event(2, "ERASE_SECRET_SENTINEL"))
        a.forget(dict(event_ids=["e2"]))
        data = _checkpoint(a)  # Casefolded copies, as an index vocabulary keeps them, count too.
        assert b"ERASE_SECRET_SENTINEL" not in data and b"erase_secret_sentinel" not in data
        for text in ("ERASE_SECRET_SENTINEL", "e2", "quartz", ""):
            assert "e2" not in _query(a, text)["citations"]
    elif name == "supersession_current":
        # The later t_sim wins against both id order and arrival order, in either direction.
        for word, newer, older in (("azure", ("e7", 3), ("e8", 2)), ("amber", ("e6", 5), ("e5", 4))):
            first, last = (newer, older) if word == "azure" else (older, newer)
            for event_id, t_sim in (first, last):
                a.ingest(dict(event_id=event_id, t_sim=t_sim, kind="message", actor="fixture",
                              text=f"{'current' if (event_id, t_sim) == newer else 'former'} {word}"))
            assert _query(a, word)["citations"] == [newer[0]]
    elif name == "settle_returns":
        assert a.settle(5) is True
        shape(a.stats(), dict(tokens=int, latency_ms=int))  # Bytes are measured externally only.


def run(adapter_factory) -> dict[str, bool]:
    results = {}
    for name in CHECKS:
        try:
            adapter = adapter_factory()
            if name not in EXEMPTIONS.get(type(adapter), ()):
                _check(name, adapter, adapter_factory)
            results[name] = True
        except Exception:
            results[name] = False
    return results
