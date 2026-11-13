"""Hand-computed selection, size boundaries, future isolation and quote recall."""

import pytest

from bicentennial.anchors import quote_recall
from bicentennial.anchors.bm25 import BM25
from bicentennial.anchors.grep import Grep
from bicentennial.anchors.window import RecentWindow
from bicentennial.api.contract import answer
from bicentennial.world.tokens import estimate_tokens


def event(eid, text, t=0):
    return dict(event_id=eid, text=text, t_sim=t, kind="message", actor="fixture")


def query(cls, events, prompt="common rare", *, window=16384, now=10):
    adapter = cls(window=window)
    for e in events:
        adapter.ingest(e)
    return adapter.query(dict(task_id="probe", prompt=prompt), now)


@pytest.mark.parametrize("cls", [BM25, Grep, RecentWindow])
def test_empty_unknown_and_future_isolation(cls):
    assert query(cls, []) == answer()
    future = event("future", "common rare", 11)
    assert query(cls, [future]) == answer()
    assert query(cls, [event("past", "common", 10), future])["citations"] == ["past"]


@pytest.mark.parametrize("cls", [BM25, Grep])
def test_unmatched_prompt_unknown(cls):
    assert query(cls, [event("past", "different words")]) == answer()


def test_bm25_positive_only_chunk_ties_and_top_five():
    events = [event(f"e{i}", "alpha") for i in reversed(range(7))]
    events.append(event("absent", "beta"))
    assert query(BM25, events, "alpha")["citations"] == [f"e{i}" for i in range(5)]
    long = "alpha " * 90
    result = query(BM25, [event("same", long)], "alpha")
    assert result["citations"] == ["same"] * 3
    assert result["output"].splitlines()[0] == ("alpha " * 40).strip()


def test_grep_rarest_first_then_newest_budget_and_time_output():
    events = [event("a", "rare", 1), event("b", "common", 2), event("c", "common", 3)]
    result = query(Grep, events, window=3)
    assert result == dict(output="rare\ncommon", citations=["a", "c"], confidence_milli=1000)
    assert query(RecentWindow, events, window=3)["citations"] == ["c"]


def test_grep_word_boundaries_alphabetical_term_ties_and_deduplication():
    events = [event("a", "zeta", 1), event("b", "alpha", 2), event("c", "alphabet", 3)]
    assert query(Grep, events, "zeta alpha", window=2)["citations"] == ["b"]
    assert query(Grep, [event("a", "alpha zeta")], "alpha zeta")["citations"] == ["a"]


@pytest.mark.parametrize("cls", [Grep, RecentWindow])
def test_utf8_newlines_exact_budget_and_stop_before_large_event(cls):
    events = [event(f"e{i}", "猫", i) for i in range(3)]
    result = query(cls, events, "猫", window=2)
    assert result["citations"] == ["e1", "e2"]
    assert estimate_tokens(result["output"]) == 2
    events.append(event("large", "猫 " * 10, 4))
    assert query(cls, events, "猫", window=2) == answer()


def test_quote_recall_requires_tokens_together_and_counts_id_fallback():
    key = dict(oracle_spans=["a", "b", "missing"], required=["alpha", "beta"])
    events = {"a": event("a", "alpha beta"), "b": event("b", "other")}
    recall, fallback = quote_recall(key, events, [("a", "alpha"), ("a", "beta"), ("b", "other")])
    assert recall == dict(k=3, hits=1, of=3, milli=333)
    assert fallback == dict(hits=1, of=1)
    recall, fallback = quote_recall(key, events, [("a", "alpha beta"), ("b", "other")])
    assert recall == dict(k=2, hits=2, of=3, milli=667)
    assert fallback == dict(hits=1, of=1)
