"""Regressions for the four PR 79 review findings, using offline worlds only."""

import unicodedata
from dataclasses import replace

import pytest

from bicentennial.canon import canon
from bicentennial.items import Option, compile_branch, compile_life
from bicentennial.score.answer_types import matches
from bicentennial.score.qa import score_qa
from tests.items.test_compile import (
    assertion,
    fact,
    make_cut,
    plan,
    qa_instance,
    table,
    template,
    world,
)


@pytest.mark.parametrize("wake,stress", [("kill", "crash"), ("compaction", "compaction"), ("swap", "swap")])
@pytest.mark.parametrize("fault_cell", [False, True])
def test_crossings_include_earlier_required_span(tmp_path, wake, stress, fault_cell):
    db, schedule = world(tmp_path / "world.db", wake=wake)
    assertion(db, schedule, "detail", "WINDOW-7401", (1, 2))
    assertion(db, schedule, "support", "SUPPORT-8811", (3, 2))
    c = make_cut(db, schedule)
    instance = qa_instance(spans=("event-support", "event-detail"))
    cell = {"kill": "FAULT-CRASH", "compaction": "FAULT-COMPACT", "swap": "FAULT-NEWEST"}[wake] if fault_cell else "RECALL-VERB"
    item, meta = compile_branch(db, schedule, c, [template([instance], cell_id=cell)]).entries[0]
    assert meta["crossed"] == [stress]
    assert item["stage"] == "survive" and item["labels"] == [f"survive:{stress}", "voice: template"]
    # Distances and proximity still use the last span, after the stress.
    assert meta["evidence_session"] == 3
    assert meta["levers"]["distance_sessions"] == 0
    assert meta["levers"]["distance_s"] == schedule.sessions[2].t_end - schedule.sessions[2].turn_t[1] - 60
    assert meta["levers"]["dispersion"] == 2
    assert meta["levers"]["wake_events"] == 1
    assert meta["levers"]["fault_proximity"] is None
    # The late span alone crosses none of these stresses, including wake-before compaction.
    late = replace(instance, gold_spans=("event-support",))
    late_item, late_meta = compile_branch(db, schedule, c, [template([late])]).entries[0]
    assert late_meta["crossed"] == [] and late_item["stage"] == "remember"
    db.close()


@pytest.mark.parametrize("foreign", [r"C:\secret\9911", 'QUOTED-"9911"', "C:\\secre\u0301t\\9911"])
@pytest.mark.parametrize("location", ["scalar", "nested-value", "nested-key", "tuple-value"])
@pytest.mark.parametrize("kind", ["qa", "act"])
def test_foreign_tokens_in_decoded_payload(tmp_path, foreign, location, kind):
    db, schedule = world(tmp_path / "world.db")
    assertion(db, schedule, "detail", "WINDOW-7401", (1, 2))
    fact(db, "foreign", foreign)
    decoded = unicodedata.normalize("NFC", foreign)
    value = decoded if location == "scalar" else {
        "outer": [{decoded: "safe"} if location == "nested-key" else {"value": decoded}]}
    if location == "tuple-value":
        value["outer"] = tuple(value["outer"])
    assert decoded not in unicodedata.normalize("NFC", canon(value).decode())
    if kind == "qa":
        option = Option(key="gold", token_fact_ids=("detail",),
                        envelope={"type": "entity" if location == "scalar" else "env_state", "value": value})
        t = template()
        instance = qa_instance(options=(option,))
    else:
        option = Option(key="gold", token_fact_ids=("detail",), plan=plan(value))
        t = template(cell_id="WAKE-PREF", kind="act", twin_type="fork", decision_tables=(table(),))
        instance = qa_instance(options=(option,), decision_table_ref=table()["table_id"])
    c = make_cut(db, schedule)
    with pytest.raises(ValueError, match="foreign token in option: gold") as error:
        compile_branch(db, schedule, c, [replace(t, rows=(instance,))])
    assert foreign not in str(error.value) and decoded not in str(error.value)
    # Escaping and NFC do not forbid the option's declared tokens.
    own = replace(instance, options=(replace(option, token_fact_ids=("detail", "foreign")),))
    item, _ = compile_branch(db, schedule, c, [replace(t, rows=(own,))]).entries[0]
    assert item["options"][0]["tokens"] == ["WINDOW-7401", foreign]
    db.close()


@pytest.mark.parametrize("kind,left,right", [
    ("set", ["a", "b"], ["b", "a"]),
    ("number", 7, "7.00"),
    ("span", "CAFÉ  Ledger", " cafe\u0301\tLEDGER "),
    ("citation", "CAFÉ  Ledger", " cafe\u0301\tLEDGER "),
    ("premise_correction", "CAFÉ  Ledger", " cafe\u0301\tLEDGER "),
    # Set matching is directional when one gold contains duplicate elements.
    ("set", ["a", "a", "b"], ["b", "a"]),
    ("set", ["b", "a"], ["a", "a", "b"]),
])
def test_qa_twins_refuse_scorer_equivalent_golds(tmp_path, kind, left, right):
    db, schedule = world(tmp_path / "world.db")
    assertion(db, schedule, "detail", "WINDOW-7401", (1, 2))
    branches, envelopes = [], []
    for branch, value in (("B0", left), ("B1", right)):
        envelope = {"type": kind, "value": value}
        envelopes.append(envelope)
        option = Option(key="gold", token_fact_ids=("detail",), envelope=envelope)
        t = template([qa_instance(options=(option,))], twin_type="fork")
        branches.append(compile_branch(db, schedule, make_cut(db, schedule, branch), [t]))
    assert canon(envelopes[0]) != canon(envelopes[1])
    assert matches(*envelopes) or matches(*reversed(envelopes))
    # Each direction that matches also earns full credit under the QA scorer.
    for index in (0, 1):
        if matches(envelopes[index], envelopes[1 - index]):
            answer = envelopes[1 - index] | {"confidence_milli": 1000, "citation": None}
            assert score_qa(branches[index].entries[0][0], answer, evidence_texts=()).score_milli == 1000
    with pytest.raises(ValueError, match="different gold"):
        compile_life(*branches)
    db.close()
