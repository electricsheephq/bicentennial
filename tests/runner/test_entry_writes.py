"""Outside scripted writes and coverage before installation."""

import json
from copy import deepcopy

import pytest
import test_outside_entry as entries

from bicentennial import cli
from bicentennial.canon import canon
from bicentennial.director.responder import Call
from bicentennial.director.scripted import ScriptedResponder
from bicentennial.runner import t0, t1
from bicentennial.systems import mapping, pins, registry

outside = entries.outside
deterministic = entries.deterministic


def declare(entry):
    entry["write_tools"] = [dict(tool=name, actions=[]) for name in ("store", "remove")]
    return entry


def write_call(wire, role, tool, content_key="content", limit=None):
    properties = {content_key: dict(type="string")}
    if limit is not None:
        properties[content_key]["maxLength"] = limit
    function = dict(name=tool, parameters=dict(type="object", properties=properties))
    tools = [dict(type="function", function=function) if wire == "chat" else dict(type="function", **function)]
    messages = [dict(role="user", content="old"), dict(role="assistant", content="earlier"),
                dict(role="user", content="latest é\nverbatim")]
    subrole = "cursor"
    if role == "memory_write":
        messages.append(dict(role="user", content="Review the conversation above and consider saving to memory if appropriate."))
        subrole = "background_review"
    body = dict(model="input-model", tools=tools)
    body["messages" if wire == "chat" else "input"] = messages
    return Call(role, subrole, wire, body, "route-model", dict(session=1, turn=1), "attempt-one")


def build(entry):
    try:
        return ScriptedResponder(entry)
    except ValueError as error:
        pytest.fail(f"declared recipe could not construct a responder: {error}")


@pytest.mark.parametrize("wire", ["chat", "responses"])
@pytest.mark.parametrize("role", ["write_turn", "memory_write"])
@pytest.mark.parametrize("limit", [None, 0, 8])
def test_outside_native_write_bytes(outside, wire, role, limit):
    builtin = registry.load(registry.REGISTRY / "hermes-native.toml")
    outside["write_tools"] = deepcopy(builtin["write_tools"])
    outside["recipe"]["write"] = dict(tool="memory", fixed=dict(action="add", target="memory"), content_key="content")
    call = write_call(wire, role, "memory", limit=limit)
    actual = build(outside).respond(call)
    expected = ScriptedResponder(builtin).respond(call)
    assert actual.tool_calls == expected.tool_calls
    text = "latest é\nverbatim"
    assert actual.tool_calls == (dict(name="memory", arguments=canon(dict(action="add", target="memory",
        content=text if limit is None else text[:limit])).decode()),)


@pytest.mark.parametrize("wire", ["chat", "responses"])
@pytest.mark.parametrize("role", ["write_turn", "memory_write"])
def test_outside_own_write_arguments(outside, wire, role):
    declare(outside)
    outside["recipe"]["write"] = dict(tool="store", fixed={}, content_key="content")
    outside["recipe"]["forget"] = dict(search_tool="search", search_fixed=dict(whole=True), query_key="query",
        listing_key="results", text_key="content", id_key="id", delete_tool="remove", delete_fixed={}, delete_key="memory_id")
    assert mapping.check_mapping(outside, mapping.resolve_mapping(outside)) is None
    reply = build(outside).respond(write_call(wire, role, "store"))
    assert reply.tool_calls == (dict(name="store", arguments=canon(dict(content="latest é\nverbatim")).decode()),)


def test_direct_missing_write_keeps_value_error(outside):
    declare(outside)
    del outside["recipe"]["write"]
    with pytest.raises(ValueError, match="^scripted write arguments are not declared for this system$"):
        ScriptedResponder(outside)


def test_recipe_mutation_keeps_write_calls(outside):
    declare(outside)
    outside["recipe"]["write"]["fixed"]["nested"] = dict(items=["original"])
    responder = build(outside)
    call = write_call("chat", "write_turn", "store", "text")
    before = responder.respond(call).tool_calls
    assert json.loads(before[0]["arguments"]) == dict(action="add", nested=dict(items=["original"]), text="latest é\nverbatim")
    outside["recipe"]["write"]["fixed"]["nested"]["items"].append("changed")
    outside["recipe"]["write"].update(tool="other", content_key="other", fixed={})
    assert responder.respond(call).tool_calls == before


@pytest.mark.parametrize("fault,code", [
    ("first", "write_mapping_missing:other"),
    ("second", "write_mapping_missing:extra"),
    ("unknown", "write_mapping_unknown:remove"),
    ("search", "forget_search_undeclared:search"),
    ("action", "write_mapping_action:store"),
], ids=["first", "second", "unknown", "search", "action"])
@pytest.mark.parametrize("boundary", ["t0", "t1", "pins"])
def test_mapping_refused_before_work(outside, tmp_path, monkeypatch, capsys, fault, code, boundary):
    declare(outside)
    if fault == "first":
        outside["write_tools"][0]["tool"] = "other"
    elif fault == "second":
        outside["write_tools"].append(dict(tool="extra", actions=[]))
    elif fault == "unknown":
        outside["write_tools"].pop()
    elif fault == "search":
        outside["read_tools"] = []
    else:
        outside["write_tools"][0]["actions"] = ["replace"]
    monkeypatch.setattr(t0, "verify", lambda *a, **kw: pytest.fail("pack work started"))
    monkeypatch.setattr(t1, "verify", lambda *a, **kw: pytest.fail("pack work started"))
    monkeypatch.setattr(pins, "_measure", lambda *a, **kw: pytest.fail("installation started"))
    path = entries.write_entry(tmp_path / "entry.toml", outside)
    if boundary == "pins":
        assert cli.main(["pins", "--entry", str(path), "--hermes", str(tmp_path),
                         "--plugin-source", str(tmp_path)]) == 3
        assert capsys.readouterr().err.strip() == code
    else:
        # Exercise the same loaded declaration that the CLI passes to the runners.
        loaded = registry.load_entry(path)
        with pytest.raises((t0.T0Refused, t1.T1Refused)) as caught:
            if boundary == "t0":
                t0._preflight(system=loaded["name"], entry=loaded, packs=tmp_path, selected=["all"],
                    pack_hash="1" * 64, hermes=tmp_path, plugin_source=tmp_path)
            else:
                entries.prepare(loaded, tmp_path)
        assert caught.value.code == code
    assert not (tmp_path / "out").exists()


def test_builtin_pins_ignores_coverage(tmp_path, monkeypatch):
    builtin = registry.load(registry.REGISTRY / "hermes-native.toml")
    monkeypatch.setattr(pins, "check_mapping", lambda *a, **kw: pytest.fail("built-in coverage checked"))
    expected = {"fresh_install_hash": "1" * 64}
    monkeypatch.setattr(pins, "_measure", lambda *a, **kw: expected)
    assert pins.measure(builtin, hermes=tmp_path) == expected


def test_outside_structured_format_still_refused(outside):
    declare(outside)
    outside["structured_formats"] = dict(extraction=dict(kind="text", schema=None))
    assert registry.outside_reasons(outside) == ["entry_recipe_unsupported:structured_formats"]
