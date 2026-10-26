"""Offline generator contracts: sealed boundaries and canonical wire identity."""

import copy
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.items import Bundle, Item, reader_view
from bicentennial.contracts.pack import Pack
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.contracts.stream import Session, StreamEvent
from bicentennial.contracts.world import World
from bicentennial.keyed import mint_id, shuffle

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "schemas/fixtures/gen"
CLASSES = {"world": World, "stream": StreamEvent, "session": Session,
           "item": Item, "bundle": Bundle, "pack": Pack}
CANARY = "c168e5f8-3948-4553-8554-7aa162054723"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_bytes())


@pytest.mark.parametrize("name", CLASSES)
def test_golden_contracts_and_closed_canary_boundary(name):
    value = fixture(name)
    validate(name, value)
    assert value["canary"] == CANARY
    assert CLASSES[name].from_json(canon(value)).to_json() == canon(value)
    for edit in (lambda v: v.update(extra=True), lambda v: v.pop("canary"),
                 lambda v: v.update(canary="wrong-guid")):
        bad = copy.deepcopy(value)
        edit(bad)
        with pytest.raises(ValueError):
            validate(name, bad)
        with pytest.raises(ValueError):
            CLASSES[name].from_json(canon(bad))
    with pytest.raises(ValueError):
        replace(CLASSES[name].from_json(canon(value)), canary="wrong-guid").to_json()


@pytest.mark.parametrize("name,contract", [
    ("act-item", "item"), ("unknown-item", "item"), ("payload-stream", "stream"),
])
def test_alternative_golden_payloads(name, contract):
    value = fixture(name)
    validate(contract, value)
    assert CLASSES[contract].from_json(canon(value)).to_json() == canon(value)


def test_registry_and_all_fixture_bytes_are_canonical_float_free():
    registry = fixture("contracts")
    assert registry["canary"] == CANARY
    assert set(registry["contracts"]) == set(CLASSES)
    for name in CLASSES:
        assert registry["contracts"][name] == fixture(name)
        raw = (SCHEMAS / f"{name}.schema.json").read_bytes()
        assert canon(json.loads(raw)) == raw
    for path in FIXTURES.glob("*.json"):
        raw = path.read_bytes()
        value = json.loads(raw)
        assert value["canary"] == CANARY
        assert canon(value) == raw


@pytest.mark.parametrize("edit", [
    pytest.param(lambda v: v["options"][0].update(tokens=["abc"]), id="three-character-token"),
    pytest.param(lambda v: v.update(prompt="What about WINDOW-7401?"), id="token-in-prompt"),
    pytest.param(lambda v: v["options"][0].update(tokens=[]), id="two-empty-options"),
    pytest.param(lambda v: v["options"].reverse(), id="gold-present-but-not-first"),
    lambda v: v["options"][0].update(plan={"steps": []}),
    lambda v: v["options"][0]["envelope"].update(confidence_milli=1001),
    lambda v: v["options"][0]["envelope"].update(confidence_milli=500),
    lambda v: v["options"].clear(),
    lambda v: v["options"].append(copy.deepcopy(v["options"][0])),
    lambda v: v.update(stage="act"),
    lambda v: v["gold"].update(never_observed=True),
    lambda v: v["options"][0].update(extra="not allowed"),
    lambda v: v["options"][0]["envelope"].update(extra="not allowed"),
    lambda v: v.update(cell_id="RECALL-NOTREAL"),
    lambda v: v["gold"].update(extra=True),
])
def test_invalid_items(edit):
    value = fixture("item")
    edit(value)
    with pytest.raises(ValueError):
        validate("item", value)


def test_token_presence_normalizes_nfc_and_is_case_sensitive():
    value = fixture("item")
    value["options"][0]["tokens"] = ["Cafe\u0301-7401"]
    value["prompt"] = "Café-7401 is which preference?"
    with pytest.raises(ValueError, match="token present"):
        validate("item", value)
    value["prompt"] = "CAFÉ-7401 is which preference?"
    validate("item", value)


def test_empty_options_and_decimal_number_encoding():
    value = fixture("unknown-item")
    value["options"][0]["envelope"].update(type="entity")
    with pytest.raises(ValueError, match="UNKNOWN"):
        validate("item", value)
    value = fixture("act-item")
    value["options"][1]["plan"]["steps"] = copy.deepcopy(value["options"][0]["plan"]["steps"])
    with pytest.raises(ValueError, match="refrain"):
        validate("item", value)
    value = fixture("item")
    envelope = value["options"][0]["envelope"]
    envelope["type"] = "number"
    for number in (12, "-12.345", "0.000"):
        envelope["value"] = number
        validate("item", value)
    for number in (True, "1e3", "NaN", {"n": 1}):
        envelope["value"] = number
        with pytest.raises(ValueError):
            validate("item", value)


def test_reader_view_contains_only_reader_inputs_and_is_detached():
    value = fixture("item")
    for item in (value, Item.from_json(canon(value))):
        view = reader_view(item)
        assert set(view) == {"item_id", "prompt", "options"}
        assert view == {key: value[key] for key in view}
        view["options"][0]["tokens"].clear()
        assert value["options"][0]["tokens"] == ["WINDOW-7401"]


def test_golden_priority_uses_keyed_competitor_order_and_minted_ids():
    value = fixture("item")
    assert value["item_id"] == mint_id("k12-golden-v1", 5)
    competitors = sorted(value["options"][1:], key=lambda o: not o["tokens"])
    assert value["options"][1:] == shuffle(
        "k12-golden-v1", (value["item_id"],), 0, "options", competitors)


@pytest.mark.parametrize("name,edit", [
    ("world", lambda v: v.update(exposure=[])),
    ("world", lambda v: v["fact"][0].update(event_id="not-a-column")),
    ("world", lambda v: v["fact"][0].update(strength=1001)),
    ("world", lambda v: v["fact"][0].update(speech_act="Assert")),
    ("world", lambda v: v["fact"][0].update(polarity="positive")),
    ("world", lambda v: v["event"][0].update(salience=1001)),
    ("world", lambda v: v["attr"][0].update(valid_to_t=0)),
    ("world", lambda v: v["link"][0].update(fact_id="missing")),
    ("world", lambda v: v["lineage"][0].update(source_fact_id="missing")),
    ("stream", lambda v: v.update(payload={})),
    ("stream", lambda v: v.pop("text")),
    ("stream", lambda v: v.update(t_sim=True)),
    ("stream", lambda v: v.update(tz="Imaginary/Zone")),
    ("stream", lambda v: v.update(sha256="bad")),
    ("stream", lambda v: v["render"].update(extra=True)),
    ("session", lambda v: v["wake_before"].append("not-a-wake")),
    ("session", lambda v: v["fault_points"].append({"kind": "kill", "session": 3, "turn": 1})),
    ("session", lambda v: v["expected_state"].update(env_state_hash="bad")),
    ("bundle", lambda v: v["items"].pop()),
    ("bundle", lambda v: v["items"].append("third")),
    ("bundle", lambda v: v["items"].__setitem__(1, v["items"][0])),
    ("pack", lambda v: v["qa_order"].clear()),
    ("pack", lambda v: v["qa_order"].append(v["qa_order"][0])),
    ("pack", lambda v: v["controls"].update(no_memory="unmeasured")),
    ("pack", lambda v: v["hashes"].update(world="bad")),
    ("pack", lambda v: v["bundles"][0]["items"].__setitem__(0, "missing")),
    ("pack", lambda v: v["items"][0]["options"][0].update(tokens=["abc"])),
])
def test_structural_and_registered_semantic_rejections(name, edit):
    value = fixture(name)
    edit(value)
    with pytest.raises(ValueError):
        validate(name, value)


def test_bitemporal_history_preserves_closed_revisions():
    value = fixture("world")
    old = value["attr"][0]
    new = copy.deepcopy(old)
    old["valid_to_t"] = 1700000010
    new.update(value="AISLE-9201", valid_from_t=1700000010, recorded_t=1700000020)
    value["attr"].append(new)
    validate("world", value)
    assert len(World.from_json(canon(value)).attr) == 2


@pytest.mark.parametrize("name,edit", [
    ("world", lambda v: v["attr"][0].update(value={"nested": [0.5]})),
    ("payload-stream", lambda v: v["tool"]["args"].update(value=[0.5])),
    ("item", lambda v: v["options"][0]["envelope"].update(value=[0.5])),
    ("act-item", lambda v: v["options"][0]["plan"]["steps"][0]["tool"]["args"].update(x=0.5)),
    ("pack", lambda v: v["controls"]["no_memory"].update(x=0.5)),
])
def test_open_json_payloads_still_reject_floats(name, edit):
    value = fixture(name)
    edit(value)
    contract = {"payload-stream": "stream", "act-item": "item"}.get(name, name)
    with pytest.raises(ValueError, match="float"):
        validate(contract, value)


def test_dataclasses_are_frozen_and_serialization_revalidates_mutable_rows():
    for name, cls in CLASSES.items():
        record = cls.from_json(canon(fixture(name)))
        with pytest.raises(FrozenInstanceError):
            record.canary = "changed"
    item = Item.from_json(canon(fixture("item")))
    item.options[0]["tokens"] = ["abc"]
    with pytest.raises(ValueError):
        item.to_json()


def test_canonical_round_trips_in_two_separate_processes():
    code = """
import json
import sys
from pathlib import Path
from bicentennial.canon import canon
from bicentennial.contracts.world import World
from bicentennial.contracts.stream import StreamEvent, Session
from bicentennial.contracts.items import Item, Bundle
from bicentennial.contracts.pack import Pack
root = Path('schemas/fixtures/gen')
classes = dict(world=World, stream=StreamEvent, session=Session, item=Item, bundle=Bundle, pack=Pack)
result = {}
for name, cls in classes.items():
    raw = (root / (name + '.json')).read_bytes()
    result[name] = json.loads(cls.from_json(raw).to_json())
for name, cls in [('act-item', Item), ('unknown-item', Item), ('payload-stream', StreamEvent)]:
    result[name] = json.loads(cls.from_json((root / (name + '.json')).read_bytes()).to_json())
sys.stdout.buffer.write(canon(result))
"""
    outputs = [subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                              check=True, capture_output=True).stdout for _ in range(2)]
    expected = {name: fixture(name) for name in (*CLASSES, "act-item", "unknown-item", "payload-stream")}
    assert outputs[0] == outputs[1] == canon(expected)
