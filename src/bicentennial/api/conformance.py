"""Isolated adapter checks; run returns a bool for every named check.

Only exact NoMemory/OracleEvidence classes are exempt from maintain_lossless,
tool_grouping and supersession_current: these require ordinary store retrieval.
Exempt checks return True (not a claim of retrieval); EXEMPTIONS exposes them.
All other checks apply. Each check uses a fresh adapter and settles before
every probe/checkpoint; exceptions fail that check and do not abort the suite.
"""

from .adapters.nomemory import NoMemory
from .adapters.oracle_evidence import OracleEvidence

CHECKS = ("reset_empty", "duplicate_id_idempotent", "citations_are_event_ids",
          "checkpoint_restore", "maintain_lossless", "tool_grouping", "forget_removes",
          "supersession_current", "settle_returns")
EXEMPTIONS = dict.fromkeys((NoMemory, OracleEvidence), frozenset(
    ("maintain_lossless", "tool_grouping", "supersession_current")))


def _event(i, text, kind="message", **extra):
    return dict(event_id=f"e{i}", t_sim=i, kind=kind, actor="fixture", text=text, **extra)


def _query(adapter, text, ids=()):
    assert adapter.settle(5) is True
    return adapter.query(dict(task_id="probe", prompt=text, oracle_evidence=list(ids)), 100)


def _checkpoint(adapter):
    assert adapter.settle(5) is True
    return adapter.checkpoint()


def _check(name, a):
    a.reset()
    a.ingest(_event(1, "quartz"))
    if name == "reset_empty":
        a.reset()
        assert _query(a, "quartz")["citations"] == []
    elif name == "duplicate_id_idempotent":
        before = _checkpoint(a), _query(a, "quartz", ["e1"])
        a.ingest(_event(1, "quartz"))
        assert before == (_checkpoint(a), _query(a, "quartz", ["e1"]))
    elif name == "citations_are_event_ids":
        a.ingest(_event(2, "topaz"))
        for text in ("quartz", "topaz", "absent", ""):
            assert set(_query(a, text, ["e1", "e2"])["citations"]) <= {"e1", "e2"}
    elif name == "checkpoint_restore":
        before, data = _query(a, "quartz", ["e1"]), _checkpoint(a)
        a.reset()
        a.restore(data)
        assert _query(a, "quartz", ["e1"]) == before
    elif name == "maintain_lossless":
        for i, text in enumerate(("topaz", "garnet", "zircon"), 2):
            a.ingest(_event(i, text))
        a.maintain()
        for i, text in enumerate(("quartz", "topaz", "garnet", "zircon"), 1):
            result = _query(a, text)
            assert result["output"] == text and result["citations"] == [f"e{i}"]
    elif name == "tool_grouping":
        a.ingest(_event(2, "dispatch", "tool_call"))
        a.ingest(_event(3, "delivered", "tool_result", call_id="e2"))
        for text, event_id in (("delivered", "e3"), ("dispatch", "e2")):
            result = _query(a, text)
            assert result["output"] == text and result["citations"] == [event_id]
    elif name == "forget_removes":
        a.ingest(_event(2, "ERASE_SECRET_SENTINEL"))
        a.forget(dict(event_ids=["e2"]))
        assert b"ERASE_SECRET_SENTINEL" not in _checkpoint(a)
        for text in ("ERASE_SECRET_SENTINEL", "e2", "quartz", ""):
            assert "e2" not in _query(a, text)["citations"]
    elif name == "supersession_current":
        a.ingest(_event(3, "current azure"))
        a.ingest(_event(2, "former azure"))  # Arrival order cannot stand in for t_sim.
        assert _query(a, "azure")["citations"] == ["e3"]
    elif name == "settle_returns":
        assert a.settle(5) is True


def run(adapter_factory) -> dict[str, bool]:
    results = {}
    for name in CHECKS:
        try:
            adapter = adapter_factory()
            if name not in EXEMPTIONS.get(type(adapter), ()):
                _check(name, adapter)
            results[name] = True
        except Exception:
            results[name] = False
    return results
