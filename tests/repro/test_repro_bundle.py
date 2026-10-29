"""Replay bundle examples with hand-computed frequencies and constraint failures."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.keyed import mint_id
from bicentennial.repro.bundle import build_bundle, rerun
from bicentennial.repro.ddmin import Constraints, ddmin

EVENTS = tuple(mint_id("repro-235", n) for n in range(1, 41))
PAIR = {EVENTS[6], EVENTS[18]}


def flaky(kept, attempt):
    return "A" if PAIR <= set(kept) and attempt % 3 != 2 else None


@pytest.fixture
def life():
    # Copy the 13 life fields of tests/corpus/test_corpus.py::obj; no regeneration.
    return {
        "catalogue_row": "g2-wake-pref-mft-1", "generator_version": "v0.1",
        "genre": "G2", "seed": 1, "recipe": "catalogue-v0:wake-pref-v1",
        "template": "wake-pref-v1", "c7_entry_sha256": "a" * 64,
        "levers": {"genre": "G2", "seed": 1, "sessions": 3, "distance": 1,
                   "wake": "kill", "recipe": "catalogue-v0:wake-pref-v1",
                   "template": "wake-pref-v1"},
        "fault_points": [{"kind": "kill", "session": 3, "turn": 1}],
        "world_hash_b0": "b" * 64, "world_hash_b1": "c" * 64,
        "history_set_hash": "d" * 64, "items": ["bcw-0000000000000001"],
    }


def make_bundle(life, *, max_tests=None):
    constraints = Constraints()
    shrink = ddmin(EVENTS, flaky, target="A", constraints=constraints, max_tests=max_tests)
    return build_bundle(system="system-v1", life=life, events=EVENTS,
                        constraints=constraints, shrink=shrink, oracle="pair-v1",
                        target="A", threshold=1)


@pytest.fixture
def bundle(life):
    return make_bundle(life)


def test_bundle_validates(bundle):
    validate("repro_bundle", bundle)
    assert json.loads(canon(bundle)) == bundle
    assert canon(json.loads(canon(bundle))) == canon(bundle)
    assert bundle["repro_class"] == "replay-from-schedule"
    assert bundle["schedule"]["kept"] == [EVENTS[6], EVENTS[18]]
    assert bundle["frequency"] == {"failures": 2, "runs": 3}
    assert bundle["minimality"]["claim"] == "1-minimal-under-tested"
    assert len(bundle["life"]) == 13
    assert not {"case_id", "source", "expected"} & bundle["life"].keys()


def test_budget_bundle_claim(life):
    bundle = make_bundle(life, max_tests=3)
    assert bundle["minimality"] == {"claim": "budget-exhausted", "tests": 3}
    assert bundle["schedule"]["kept"] == list(EVENTS[:20])
    assert bundle["frequency"] == {"failures": 2, "runs": 3}
    validate("repro_bundle", bundle)


def test_bundle_rerun(bundle):
    calls = []

    def oracle(kept, attempt):
        calls.append((kept, attempt))
        return flaky(kept, attempt)

    assert rerun(bundle, oracle) == 2
    assert calls == [((EVENTS[6], EVENTS[18]), attempt) for attempt in (0, 1, 2)]


@pytest.mark.parametrize("mutation", [
    "kept-order", "kept-empty", "failures-high", "failures-low", "float-frequency",
    "unknown-class", "extra-top", "life-case-id", "life-source", "split-group",
    "orphan-derivative", "group-order", "nonhex-event", "duplicate-event",
    "duplicate-kept", "unknown-kept", "overlap-groups", "empty-group", "unknown-group",
    "group-member-order", "empty-sources", "self-source", "unknown-derivative",
    "unknown-source", "requires-order", "source-order", "requirement-shape",
    "threshold-high", "tests-zero", "bool-runs",
])
def test_bundle_rejects(bundle, mutation):
    b = deepcopy(bundle)
    schedule = b["schedule"]
    if mutation == "kept-order":
        schedule["kept"].reverse()
    elif mutation == "kept-empty":
        schedule["kept"] = []
    elif mutation == "failures-high":
        b["frequency"]["failures"] = 4
    elif mutation == "failures-low":
        b["frequency"]["failures"] = 1
        b["failure"]["threshold"] = 2
    elif mutation == "float-frequency":
        b["frequency"]["failures"] = 2.0
    elif mutation == "unknown-class":
        b["repro_class"] = "snapshot-probe"
    elif mutation == "extra-top":
        b["extra"] = 1
    elif mutation in ("life-case-id", "life-source"):
        b["life"]["case_id" if mutation == "life-case-id" else "source"] = "forbidden"
    elif mutation == "split-group":
        schedule["groups"] = [[EVENTS[6], EVENTS[7]]]
    elif mutation == "orphan-derivative":
        schedule["requires"] = [[EVENTS[18], [EVENTS[2]]]]
    elif mutation == "group-order":
        schedule["groups"] = [[EVENTS[18]], [EVENTS[6]]]
    elif mutation == "nonhex-event":
        schedule["events"][0] = "bcw-gggggggggggggggg"
    elif mutation == "duplicate-event":
        schedule["events"].append(EVENTS[0])
    elif mutation == "duplicate-kept":
        schedule["kept"].append(EVENTS[18])
    elif mutation == "unknown-kept":
        schedule["kept"] = [mint_id("other-schedule", 1)]
    elif mutation == "overlap-groups":
        schedule["groups"] = [[EVENTS[6]], [EVENTS[6], EVENTS[18]]]
    elif mutation == "empty-group":
        schedule["groups"] = [[]]
    elif mutation == "unknown-group":
        schedule["groups"] = [[mint_id("other-schedule", 1)]]
    elif mutation == "group-member-order":
        schedule["groups"] = [[EVENTS[18], EVENTS[6]]]
    elif mutation == "empty-sources":
        schedule["requires"] = [[EVENTS[18], []]]
    elif mutation == "self-source":
        schedule["requires"] = [[EVENTS[18], [EVENTS[18]]]]
    elif mutation == "unknown-derivative":
        schedule["requires"] = [[mint_id("other-schedule", 1), [EVENTS[6]]]]
    elif mutation == "unknown-source":
        schedule["requires"] = [[EVENTS[18], [mint_id("other-schedule", 1)]]]
    elif mutation == "requires-order":
        schedule["requires"] = [[EVENTS[18], [EVENTS[6]]], [EVENTS[6], [EVENTS[18]]]]
    elif mutation == "source-order":
        schedule["requires"] = [[EVENTS[18], [EVENTS[6], EVENTS[2]]]]
    elif mutation == "requirement-shape":
        schedule["requires"] = [[EVENTS[18]]]
    elif mutation == "threshold-high":
        b["failure"]["threshold"] = 4
    elif mutation == "tests-zero":
        b["minimality"]["tests"] = 0
    elif mutation == "bool-runs":
        b["frequency"]["runs"] = True
    else:
        raise AssertionError(mutation)
    with pytest.raises(ValueError):
        validate("repro_bundle", b)


@pytest.mark.parametrize("mutation", [
    "genre", "seed-bool", "template", "catalogue", "recipe", "hash", "items-empty",
    "items-order", "sessions", "distance", "lever-mismatch", "fault-session",
    "fault-turn", "extra-lever", "nested-float",
])
def test_life_rejects(bundle, mutation):
    life = bundle["life"]
    if mutation == "genre":
        life["genre"] = "G3"
    elif mutation == "seed-bool":
        life["seed"] = True
    elif mutation == "template":
        life["template"] = "wake-pref-v0"
    elif mutation == "catalogue":
        life["catalogue_row"] = "g1-wake-pref-mft-1"
    elif mutation == "recipe":
        life["recipe"] = "catalogue-v0:other-v1"
    elif mutation == "hash":
        life["world_hash_b0"] = "A" * 64
    elif mutation == "items-empty":
        life["items"] = []
    elif mutation == "items-order":
        life["items"] = ["bcw-0000000000000002", "bcw-0000000000000001"]
    elif mutation == "sessions":
        life["levers"]["sessions"] = 4
    elif mutation == "distance":
        life["levers"]["distance"] = 3
    elif mutation == "lever-mismatch":
        life["levers"]["seed"] = 2
    elif mutation == "fault-session":
        life["fault_points"][0]["session"] = 4
    elif mutation == "fault-turn":
        life["fault_points"][0]["turn"] = None
    elif mutation == "extra-lever":
        life["levers"]["extra"] = 1
    elif mutation == "nested-float":
        life["fault_points"][0]["turn"] = 1.0
    else:
        raise AssertionError(mutation)
    with pytest.raises(ValueError):
        validate("repro_bundle", bundle)


def test_optional_schedule_seed(bundle):
    bundle["life"]["levers"]["schedule_seed"] = 0
    validate("repro_bundle", bundle)


def test_builder_canonical_constraint_order(life):
    # Schedule order deliberately differs from lexical id order.
    a, b, c, d, e = (f"bcw-{n:016x}" for n in (48, 16, 32, 64, 80))
    events = (a, b, c, d, e)
    constraints = Constraints(groups=(frozenset((e, d)), frozenset((b, a))), requires=(
        (e, frozenset((c, a))), (e, frozenset((c, b))), (d, frozenset((a,))),
    ))
    shrink = ddmin(events, lambda kept, attempt: "A" if set(kept) == set(events) else None,
                   target="A", constraints=constraints)
    bundle = build_bundle(system="system-v1", life=life, events=events,
                          constraints=constraints, shrink=shrink, oracle="all-v1",
                          target="A", threshold=1)
    assert bundle["schedule"]["kept"] == list(events)
    assert bundle["schedule"]["groups"] == [[a, b], [d, e]]
    # Same derivative: compare canonical S arrays lexically, after d's position.
    assert bundle["schedule"]["requires"] == [[d, [a]], [e, [b, c]], [e, [a, c]]]
    assert bundle["frequency"] == {"failures": 3, "runs": 3}
    validate("repro_bundle", bundle)


def test_builder_detaches_life(life):
    bundle = make_bundle(life)
    life["levers"]["distance"] = 0
    life["fault_points"].clear()
    assert bundle["life"]["levers"]["distance"] == 1
    assert bundle["life"]["fault_points"] == [{"kind": "kill", "session": 3, "turn": 1}]


def test_registry_and_schema_bytes(life):
    path = Path(__file__).resolve().parents[1] / "fixtures/repro/contracts.json"
    registry = json.loads(path.read_bytes())
    assert list(registry["contracts"]) == ["repro_bundle"]
    bundle = registry["contracts"]["repro_bundle"]
    assert registry["canary"] == bundle["canary"] == "c168e5f8-3948-4553-8554-7aa162054723"
    assert bundle["life"] == life
    assert bundle["frequency"] == {"failures": 2, "runs": 3}
    assert bundle["minimality"]["tests"] == 3
    assert bundle["schedule"]["kept"] == ["bcw-0000000000000007", "bcw-0000000000000013"]
    validate("repro_bundle", bundle)
    raw = (SCHEMAS / "repro_bundle.schema.json").read_bytes()
    assert canon(json.loads(raw)) == raw
