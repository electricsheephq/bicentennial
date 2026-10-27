"""Offline lock admission, ledger integration and process-stable attempt IDs."""

import json
import subprocess
import sys
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import validate
from bicentennial.director.routes import RouteTable, route_table_hash
from bicentennial.keyed import mint_id
from bicentennial.ledger import Guard, Ledger, verify
from bicentennial.runner.lock import (
    LockMismatch,
    SessionGate,
    attempt_id,
    build_lock,
    lock_hash,
    verify_lock,
)
from bicentennial.runtime.faultlite import FaultLite, fault_lite_hash

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/run/contracts.json"
UNIT = ("arm-a", "life-a", "B0", 1, 0)


def fixture(name):
    return json.loads(FIXTURE.read_bytes())["contracts"][name]


def make_lock():
    return build_lock(**fixture("lock"))


def test_build_validated_detached_canonical_lock():
    pins = fixture("lock")
    lock = build_lock(**pins)
    validate("lock", lock)
    assert lock == pins
    assert lock_hash(lock) == sha256(canon(pins)).hexdigest()
    assert lock_hash(dict(reversed(list(lock.items())))) == lock_hash(lock)
    pins["system_artifacts"][0]["version"] = "changed"
    pins["seeds"].append(9)
    pins["account_pool"].append("account-02")
    assert lock == fixture("lock")
    assert verify_lock(lock, deepcopy(lock)) is None


@pytest.mark.parametrize("field", sorted(fixture("lock")))
def test_every_pin_is_required(field):
    pins = fixture("lock")
    del pins[field]
    with pytest.raises(ValueError):
        build_lock(**pins)


@pytest.mark.parametrize("field,value", [
    ("unexpected", "extra"), ("benchmark_commit", "a" * 39),
    ("route_table_hash", "A" * 64), ("fault_lite_schedule_hash", "c" * 63),
    ("pack_hash", "d" * 65), ("seeds", [True]), ("seeds", [1.5]),
    ("tool_lists_hash", "a" * 64 + "\n"),
    ("system_artifacts", [{"name": "system", "version": "1"}]),
])
def test_schema_refusals(field, value):
    with pytest.raises(ValueError):
        build_lock(**(fixture("lock") | {field: value}))


@pytest.mark.parametrize("pool", [
    ["x" * 65], ["YQ.Yg"], ["YQ==.Yg=="], ["-_.__"],
    ["prefix YQ.Yg.Yw suffix"], [123], [{"id": "account-01"}],
    [""], "account-01", None,
])
def test_account_pool_refusals_do_not_echo_values(pool, capsys):
    with pytest.raises(ValueError) as error:
        build_lock(**(fixture("lock") | {"account_pool": pool}))
    assert str(error.value) == "account_pool: expected IDs only"
    assert capsys.readouterr() == ("", "")


def test_account_ids_at_length_boundary():
    lock = build_lock(**(fixture("lock") | {"account_pool": ["x" * 64]}))
    assert lock["account_pool"] == ["x" * 64]


@pytest.mark.parametrize("field", ["route_table_hash", "tool_lists_hash", "system_artifacts"])
def test_changed_pin_refuses_second_session(field, capsys):
    expected = make_lock()
    gate = SessionGate(expected)
    assert gate.start_session(expected, *UNIT) == (lock_hash(expected),
                                                  attempt_id(lock_hash(expected), *UNIT))
    changed = deepcopy(expected)
    if field == "system_artifacts":
        changed[field][0]["sha256"] = "e" * 64
    else:
        changed[field] = "e" * 64
    with pytest.raises(LockMismatch) as error:
        gate.start_session(changed, "arm-a", "life-a", "B0", 2, 0)
    assert error.value.code == "lock_mismatch"
    assert error.value.fields == (field,)
    assert str(error.value) == f"lock_mismatch: {field}"
    assert capsys.readouterr() == ("", "")
    assert gate.start_session(expected, *UNIT)[0] == lock_hash(expected)


@pytest.mark.parametrize("field", sorted(fixture("lock")))
def test_removed_pin_is_named_as_mismatch(field):
    expected = make_lock()
    changed = deepcopy(expected)
    del changed[field]
    with pytest.raises(LockMismatch) as error:
        verify_lock(expected, changed)
    assert str(error.value) == f"lock_mismatch: {field}"


def test_multiple_changes_are_sorted_and_canonical_types_are_distinct():
    expected = make_lock()
    expected["seeds"] = [1]
    changed = deepcopy(expected)
    changed["account_pool"] = ["account-02"]
    changed["seeds"] = [True]
    changed["extra_pin"] = None
    with pytest.raises(LockMismatch) as error:
        verify_lock(expected, changed)
    assert str(error.value) == "lock_mismatch: account_pool, extra_pin, seeds"


def test_gate_baseline_is_detached_from_caller():
    expected = make_lock()
    original = deepcopy(expected)
    gate = SessionGate(expected)
    expected["system_artifacts"][0]["version"] = "changed"
    with pytest.raises(LockMismatch, match="system_artifacts"):
        gate.start_session(expected, *UNIT)
    assert gate.start_session(original, *UNIT)[0] == lock_hash(original)


def test_r04_hashes_are_pinned_and_route_change_refuses_resume():
    row = fixture("route-table")["routes"][0] | {"segment": "seg0"}
    table = RouteTable.load({"routes": [row]})
    schedule = FaultLite.load([], fixture("script"))
    pins = fixture("lock") | {"route_table_hash": route_table_hash(table),
                              "fault_lite_schedule_hash": fault_lite_hash(schedule)}
    expected = build_lock(**pins)
    gate = SessionGate(expected)
    gate.start_session(expected, *UNIT)
    changed_table = RouteTable.load({"routes": [row | {"alias": "changed-route"}]})
    current = build_lock(**(pins | {"route_table_hash": route_table_hash(changed_table)}))
    with pytest.raises(LockMismatch, match="^lock_mismatch: route_table_hash$"):
        gate.start_session(current, "arm-a", "life-a", "B0", 2, 0)


def test_ledger_rows_carry_session_pair_and_verify(tmp_path):
    lock = make_lock()
    digest, identity = SessionGate(lock).start_session(lock, *UNIT)
    writer = Ledger(tmp_path, Guard([]), lock_hash=digest, attempt_id=identity)
    try:
        blob = writer.blob({"text": "fixture"})
        request = fixture("ledger-record")
        for field in ("seq", "prev_hash", "hash", "lock_hash", "attempt_id"):
            del request[field]
        for record in ({"type": "session_start"}, request | {"req": blob, "resp": blob},
                       {"type": "session_end"}):
            result = writer.append(record)
            assert (result["lock_hash"], result["attempt_id"]) == (digest, identity)
    finally:
        writer.close()
    rows = [json.loads(line) for line in (tmp_path / "ledger.jsonl").read_bytes().splitlines()]
    assert all((row["lock_hash"], row["attempt_id"]) == (digest, identity) for row in rows)
    assert verify(tmp_path) == dict(records=3, chain_breaks=0, truncated_tail=0,
                                    bad_blobs=0, missing_lock_fields=0)


def test_attempt_id_uses_k10_and_is_identical_in_two_processes():
    digest = lock_hash(make_lock())
    key = canon(["session-attempt", digest, list(UNIT[:-1])]).decode("utf-8")
    expected = mint_id(key, UNIT[-1])
    assert attempt_id(digest, *UNIT) == expected
    code = ("from bicentennial.runner.lock import attempt_id; "
            f"print(attempt_id({digest!r}, {', '.join(repr(v) for v in UNIT)}))")
    outputs = [subprocess.run([sys.executable, "-c", code], check=True, capture_output=True,
                              text=True, timeout=10).stdout for _ in range(2)]
    assert outputs == [expected + "\n"] * 2


@pytest.mark.parametrize("index,value", [(0, "e" * 64), (1, "arm-b"), (2, "life-b"),
                                        (3, "B1"), (4, 2), (5, 1)])
def test_each_argument_changes_attempt_id(index, value):
    args = [lock_hash(make_lock()), *UNIT]
    expected = attempt_id(*args)
    args[index] = value
    assert attempt_id(*args) != expected


def test_unit_boundaries_do_not_alias():
    digest = lock_hash(make_lock())
    assert attempt_id(digest, "a:b", "c", "B0", 1, 0) != attempt_id(
        digest, "a", "b:c", "B0", 1, 0)


@pytest.mark.parametrize("index,value", [(0, "bad"), (1, ""), (2, 1), (3, None),
                                        (4, True), (4, 0), (4, "1"), (5, True),
                                        (5, -1), (5, 1.0)])
def test_invalid_attempt_arguments_refused(index, value):
    args = [lock_hash(make_lock()), *UNIT]
    args[index] = value
    with pytest.raises(ValueError):
        attempt_id(*args)
