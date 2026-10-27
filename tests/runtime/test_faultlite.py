"""Offline boundary validation and canonical fault schedule acceptance."""

import json
from copy import deepcopy
from hashlib import sha256

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.runtime.faultlite import FaultLite, fault_lite_hash


def script():
    obj = {"canary": "c168e5f8-3948-4553-8554-7aa162054723", "life_id": "fault-life",
           "genre": "G1", "harness": "hermes", "sessions": [
               {"index": index, "kind": kind, "turns": [
                   {"n": n, "kind": kind, "user": "A turn.", "assistant": None,
                    "tool_calls": []} for n in turns]}
               for index, kind, turns in [(1, "replay", (1, 3)), (21, "probe", (1,)),
                                          (2, "replay", (2,)), (3, "replay", ())]]}
    validate("script", obj)
    return obj


def fault(kind="kill", session=1, turn=None):
    return {"kind": kind, "session": session, "turn": turn}


@pytest.mark.parametrize("kind", ["kill", "restart", "compaction"])
@pytest.mark.parametrize("turn", [None, 1, 3])
def test_process_and_compaction_faults_at_each_existing_boundary(kind, turn):
    obj = [fault(kind, turn=turn)]
    schedule = FaultLite.load(obj, script())
    assert schedule.at(1, turn) == obj
    assert schedule.at(99, turn) == []
    assert schedule.at(2, turn) == []


@pytest.mark.parametrize("obj,message", [
    ([fault(turn=2)], "turn is not in"),
    ([fault(session=2, turn=1)], "turn is not in"),
    ([fault(session=99)], "session is not in"),
    ([fault(session=21)], "replay sessions"),
    ([fault("swap", turn=1)], "session start"),
    ([fault(), fault()], "duplicate"),
    ([fault(turn=3), fault(turn=3)], "duplicate"),
])
def test_semantic_refusals(obj, message):
    with pytest.raises(ValueError, match=message):
        FaultLite.load(obj, script())


@pytest.mark.parametrize("obj", [None, {}, [fault("delivery")], [fault(turn=0)],
                                 [fault(turn=True)], [fault(session=True)],
                                 [fault() | {"extra": 1}], [fault() | {"turn": 1.0}]])
def test_schema_refusals_are_value_errors(obj):
    with pytest.raises(ValueError):
        FaultLite.load(obj, script())


def test_script_is_validated_before_binding():
    obj = script()
    obj["sessions"].append(deepcopy(obj["sessions"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        FaultLite.load([], obj)


def test_start_is_distinct_from_after_first_turn_and_empty_session_has_start():
    schedule = FaultLite.load([fault(), fault(turn=1), fault("swap", session=3)], script())
    assert schedule.at(1, None) == [fault()]
    assert schedule.at(1, 1) == [fault(turn=1)]
    assert schedule.at(1, 3) == []
    assert schedule.at(3, None) == [fault("swap", session=3)]


def test_sort_roundtrip_and_snapshot_isolation():
    expected = [fault("compaction"), fault(), fault("restart"), fault("swap"),
                fault("kill", turn=1), fault("restart", turn=1), fault("compaction", turn=3),
                fault("restart", session=2, turn=2)]
    obj = deepcopy(expected[::-1])
    life = script()
    schedule = FaultLite.load(obj, life)
    assert schedule.to_obj() == expected
    encoded = canon(schedule.to_obj())
    assert canon(FaultLite.load(json.loads(encoded), life).to_obj()) == encoded
    assert fault_lite_hash(schedule) == sha256(encoded).hexdigest()
    assert fault_lite_hash(FaultLite.load(expected, life)) == fault_lite_hash(schedule)
    obj[0]["kind"] = "kill"
    life["sessions"].clear()
    snapshot = schedule.to_obj()
    snapshot[0]["kind"] = "kill"
    schedule.at(1, None)[0]["kind"] = "kill"
    assert canon(schedule.to_obj()) == encoded
    assert schedule.replay_prefix(21) == (1,)


@pytest.mark.parametrize("field,value", [("kind", "restart"), ("session", 2), ("turn", 3)])
def test_each_fault_value_changes_hash(field, value):
    obj = [fault()]
    changed = [fault() | {field: value}]
    assert fault_lite_hash(FaultLite.load(obj, script())) != fault_lite_hash(FaultLite.load(changed, script()))


def test_empty_schedule_roundtrips():
    schedule = FaultLite.load([], script())
    assert schedule.to_obj() == []
    assert schedule.at(1, None) == []
    assert fault_lite_hash(schedule) == sha256(b"[]").hexdigest()
