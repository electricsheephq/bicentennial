"""Offline route and swap acceptance using K13-valid timeline fixtures."""

import json
from copy import deepcopy
from hashlib import sha256

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.director import routes
from bicentennial.director.routes import (
    RouteTable,
    UnknownRoute,
    route_table_hash,
    segment_of,
)
from bicentennial.runtime.faultlite import FaultLite


def script():
    sessions = []
    for index in range(1, 21):
        sessions.append({"index": index, "kind": "replay", "turns": [
            {"n": n, "kind": "replay", "user": "Remember this.",
             "assistant": "Recorded.", "tool_calls": []} for n in (1, 2)]})
        if index in (10, 20):
            sessions.append({"index": 21 if index == 10 else 22, "kind": "probe", "turns": [
                {"n": 1, "kind": "probe", "user": "Recall?", "assistant": None,
                 "tool_calls": []}]})
    obj = {"canary": "c168e5f8-3948-4553-8554-7aa162054723", "life_id": "route-life",
           "genre": "G1", "harness": "hermes", "sessions": sessions}
    validate("script", obj)
    return obj


def row(segment=0, system="hermes"):
    return {"system": system, "segment": f"seg{segment}", "probe_model": f"probe-{segment}",
            "summariser": f"summary-{segment}", "vision": None, "served_by": "scripted",
            "alias": "bicentennial-main" if segment == 0 else "bicentennial-swap"}


def faults(swap=15):
    return [{"kind": "swap", "session": swap, "turn": None},
            {"kind": "compaction", "session": 8, "turn": 2},
            {"kind": "kill", "session": 11, "turn": 1},
            {"kind": "restart", "session": 11, "turn": 1},
            {"kind": "compaction", "session": 13, "turn": 2}]


def test_ring0_routes_and_checkpoint_probe():
    schedule = FaultLite.load(faults(), script())
    table = RouteTable.load({"routes": [row(1), row()]})
    for session, segment, alias in [(14, 0, "bicentennial-main"),
                                    (15, 1, "bicentennial-swap"),
                                    (16, 1, "bicentennial-swap"),
                                    (21, 0, "bicentennial-main"),
                                    (22, 1, "bicentennial-swap")]:
        assert segment_of(session, schedule) == f"seg{segment}"
        route = table.resolve("hermes", session, schedule)
        assert route == row(segment)
        assert route["alias"] == alias
        assert route["probe_model"] == f"probe-{segment}"
        assert route["summariser"] == f"summary-{segment}"
    assert schedule.at(11, 1) == [
        {"kind": "kill", "session": 11, "turn": 1},
        {"kind": "restart", "session": 11, "turn": 1}]
    assert schedule.at(8, 2)[0]["kind"] == "compaction"
    assert schedule.at(13, 2)[0]["kind"] == "compaction"


def test_swap_at_ten_and_multiple_swaps():
    schedule = FaultLite.load(faults(10), script())
    table = RouteTable.load({"routes": [row(), row(1)]})
    assert table.resolve("hermes", 9, schedule) == row()
    assert table.resolve("hermes", 10, schedule) == row(1)
    assert table.resolve("hermes", 11, schedule) == row(1)
    assert table.resolve("hermes", 21, schedule) == row(1)
    schedule = FaultLite.load(faults(10) + [{"kind": "swap", "session": 15, "turn": None}], script())
    table = RouteTable.load({"routes": [row(2), row(), row(1)]})
    assert table.resolve("hermes", 14, schedule) == row(1)
    assert table.resolve("hermes", 15, schedule) == row(2)


def test_segments_follow_timeline_even_for_nonmonotonic_replay_indices():
    obj = script()
    obj["sessions"] = [obj["sessions"][14], obj["sessions"][0], obj["sessions"][10]]
    assert [s["index"] for s in obj["sessions"]] == [14, 1, 21]
    schedule = FaultLite.load([{"kind": "swap", "session": 14, "turn": None}], obj)
    assert segment_of(1, schedule) == segment_of(21, schedule) == "seg1"


@pytest.mark.parametrize("system,session", [("missing", 14), ("hermes", 15)])
def test_unknown_route(system, session):
    table = RouteTable.load({"routes": [row()]})
    with pytest.raises(UnknownRoute):
        table.resolve(system, session, FaultLite.load(faults(), script()))


def test_duplicate_system_segment_refused_but_systems_are_independent():
    with pytest.raises(ValueError, match="duplicate"):
        RouteTable.load({"routes": [row(), row()]})
    table = RouteTable.load({"routes": [row(), row(system="other")]})
    assert table.resolve("other", 1, FaultLite.load([], script()))["system"] == "other"


@pytest.mark.parametrize("visions", [["vision-a"], ["vision-a", "vision-a", "vision-a"]])
def test_non_null_vision_loads(visions):
    rows = [row(n) | {"vision": vision} for n, vision in enumerate(visions)]
    assert RouteTable.load({"routes": rows}).to_obj() == {"routes": rows}


@pytest.mark.parametrize("visions", [[None, "vision-b"], ["vision-a", "vision-b"], ["vision-a", None]])
def test_moved_vision_refused(visions):
    rows = [row(n) | {"vision": vision} for n, vision in enumerate(visions)]
    with pytest.raises(ValueError, match="must not move vision"):
        RouteTable.load({"routes": rows})


def test_vision_invariant_survives_future_schema_admission(monkeypatch):
    # Isolate the swap guard from schema validation.
    monkeypatch.setattr(routes, "validate", lambda name, obj: None)
    with pytest.raises(ValueError, match="must not move vision"):
        RouteTable.load({"routes": [row(10) | {"vision": "b"},
                                    row(2) | {"vision": "a"}]})


@pytest.mark.parametrize("segment", ["pre-swap", "seg01", "seg-1", "seg"])
def test_noncanonical_segment_refused(segment):
    with pytest.raises(ValueError):
        RouteTable.load({"routes": [row() | {"segment": segment}]})


@pytest.mark.parametrize("obj", [{}, {"routes": [row() | {"extra": 1}]},
                                 {"routes": [row() | {"alias": ""}]},
                                 {"routes": [row() | {"vision": ""}]},
                                 {"routes": [row() | {"vision": 1}]},
                                 {"routes": [row() | {"served_by": "unknown"}]}])
def test_route_schema_enforced(obj):
    with pytest.raises(ValueError):
        RouteTable.load(obj)


@pytest.mark.parametrize("session", [99, True, "15"])
def test_unknown_or_invalid_session_refused(session):
    with pytest.raises(ValueError):
        segment_of(session, FaultLite.load([], script()))


def test_probe_without_preceding_replay_uses_base_segment():
    obj = script()
    obj["sessions"] = [obj["sessions"][10]]
    schedule = FaultLite.load([], obj)
    assert schedule.replay_prefix(21) == ()
    assert segment_of(21, schedule) == "seg0"
    with pytest.raises(ValueError, match="not in the script"):
        segment_of(1, schedule)


def test_table_roundtrip_and_snapshot_isolation():
    obj = {"routes": [row(), row(1)]}
    table = RouteTable.load(obj)
    encoded = canon(table.to_obj())
    assert encoded == canon(obj)
    assert canon(RouteTable.load(json.loads(encoded)).to_obj()) == encoded
    assert route_table_hash(table) == sha256(encoded).hexdigest()
    obj["routes"][0]["alias"] = "changed"
    snapshot = table.to_obj()
    snapshot["routes"][0]["alias"] = "changed"
    table.resolve("hermes", 1, FaultLite.load([], script()))["alias"] = "changed"
    assert canon(table.to_obj()) == encoded


@pytest.mark.parametrize("field,value", [("system", "other"), ("segment", "seg2"),
                                         ("probe_model", "other"), ("summariser", "other"),
                                         ("alias", "other"), ("served_by", "live")])
def test_each_changeable_route_value_changes_hash(field, value):
    obj = {"routes": [row()]}
    changed = deepcopy(obj)
    changed["routes"][0][field] = value
    assert route_table_hash(RouteTable.load(obj)) != route_table_hash(RouteTable.load(changed))


def test_table_hash_includes_route_order_and_all_rows():
    obj = {"routes": [row(), row(1)]}
    digest = route_table_hash(RouteTable.load(obj))
    assert digest != route_table_hash(RouteTable.load({"routes": obj["routes"][::-1]}))
    assert digest != route_table_hash(RouteTable.load({"routes": [row()]}))
    assert RouteTable.load({"routes": []}).to_obj() == {"routes": []}
