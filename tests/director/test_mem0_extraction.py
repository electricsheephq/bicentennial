"""Items 2–3: mem0ai 2.2.1's additive request and unchanged scripted replies."""

import ast
import inspect
import json
import textwrap
from dataclasses import asdict
from importlib.metadata import version

import pytest

from bicentennial.canon import canon
from bicentennial.director import scripted
from bicentennial.director.responder import Call
from bicentennial.systems.registry import REGISTRY, load

EXTRACTION = ("Automatic extraction exercised with the scripted extractive reply (RING0 E28): one memory per "
              "new user message, cut to 240 characters and the reply budget; extraction quality is not measured.")
EXISTING = [{"id": "0", "text": "existing-only alpha"}, {"id": "1", "text": "existing-only beta"}]
NEW = ["new first", "new second é\ncontinued\n\n## A message heading\nmore", "new third 猫  "]


def additive_messages(texts=NEW):
    # Quoted-source fixture: mem0/memory/utils.py:61-76; mem0/configs/prompts.py:1033-1062.
    # The system text is a sentinel: recognition depends on roles and user sections.
    parsed_messages = "".join(f"user: {text}\n" for text in texts)
    sections = [
        "## Summary\n",
        "## Last k Messages\nuser: history-only sentinel\n",
        "## Recently Extracted Memories\n[]",
        f"## Existing Memories\n{json.dumps(EXISTING, ensure_ascii=False)}",
        f"## New Messages\n{parsed_messages}",
        "## Observation Date\n2026-11-03",
        "## Current Date\n2026-11-03",
        "## Custom Instructions\ncustom-only sentinel",
        "# Output:",
    ]
    return [{"role": "system", "content": "system-only sentinel\n## New Messages\nuser: system-only"},
            {"role": "user", "content": "\n\n".join(sections)}]


def request(messages, wire="chat", limit=None, role="aux", subrole="extraction", tools=()):
    body = {"messages" if wire == "chat" else "input": messages, "tools": list(tools)}
    if limit is not None:
        body["max_tokens" if wire == "chat" else "max_output_tokens"] = limit
    if wire == "chat":
        body["response_format"] = {"type": "json_object"}
    return Call(role, subrole, wire, body, "extraction-model", None, "attempt")


def respond(call, entry=None):
    return scripted.ScriptedResponder(entry or load(REGISTRY / "mem0-oss.toml")).respond(call)


def parsed_reply(reply):
    # mem0ai 2.2.1 mem0/memory/main.py:980, the successful JSON path.
    assert reply.status == 200
    return json.loads(reply.text, strict=False).get("memory", [])


@pytest.mark.parametrize("wire", ["chat", "responses", "responses_compact"])
def test_item2_pinned_additive_request_extracts_only_new_user_texts(wire):
    reply = respond(request(additive_messages(), wire))
    assert parsed_reply(reply) == [{"text": text} for text in NEW]
    for sentinel in ("existing-only", "history-only", "system-only", "custom-only"):
        assert sentinel not in reply.text
    # A section-like Markdown heading in history is not the builder's New Messages section.
    messages = additive_messages()
    messages[1]["content"] = messages[1]["content"].replace(
        "user: history-only sentinel\n", "user: history-only\n\n## New Messages\nuser: history-only decoy\n")
    assert parsed_reply(respond(request(messages, wire))) == [{"text": text} for text in NEW]


def test_item2_new_section_excludes_other_roles_and_preserves_empty_messages():
    messages = additive_messages(["first\n", "", "last"])
    messages[1]["content"] = messages[1]["content"].replace(
        "user: first\n", "system: inner-system\nassistant: inner-assistant\nuser: first\n", 1)
    assert parsed_reply(respond(request(messages))) == [{"text": t} for t in ("first\n", "", "last")]
    assert parsed_reply(respond(request(additive_messages([])))) == []


@pytest.mark.parametrize("wire", ["chat", "responses", "responses_compact"])
def test_item2_cut_and_reply_budget_drop_trailing_entries_or_refuse(wire):
    texts = ["é猫" * 180, "second" * 60, "third"]
    messages = additive_messages(texts)
    expected = [{"text": text[:240]} for text in texts]
    assert parsed_reply(respond(request(messages, wire))) == expected
    # The independent byte estimator checks the largest prefix that fits each budget.
    for limit in (0, 2, 3, 4, 8, 24, 180, 220, 300, 400):
        reply = respond(request(messages, wire, limit))
        fits = [expected[:n] for n in range(4) if len(canon({"memory": expected[:n]})) <= 4 * limit]
        if fits:
            assert parsed_reply(reply) == fits[-1]
            assert len(reply.text.encode()) <= 4 * limit
        else:
            assert (reply.status, reply.served, reply.text) == (400, "reply_over_budget", "")
    call = request(messages, wire, 400)
    if wire == "chat":
        call.body["max_completion_tokens"] = 4
        assert parsed_reply(respond(call)) == []


def base_mem0(call, messages):
    """Copy of the base _mem0; the compatibility oracle needs no git objects."""
    users = [scripted._text(m.get("content")) for m in messages if m.get("role") == "user"]
    update = len(users) == 1 and not any(m.get("role") in ("system", "developer") for m in messages)
    facts = [f[:240] for f in scripted._last_facts(users[0])] if update else [t[:240] for t in users if t]
    while True:
        obj = {"memory": [{"event": "ADD", "id": str(i), "text": f} for i, f in enumerate(facts)]} if update else {
            "facts": facts}
        text = canon(obj).decode()
        if scripted._cut(text, call) == text:
            return text
        if not facts:
            raise scripted._Refusal("reply_over_budget")
        facts.pop()


def reply_bytes(call, entry):
    return canon(asdict(respond(call, entry)))


@pytest.mark.parametrize("wire", ["chat", "responses", "responses_compact"])
def test_item2_old_update_neither_shape_and_all_systems_keep_reply_bytes(monkeypatch, wire):
    old = [{"role": "user", "content": 'Old memories: [{"text":"excluded"}]\nNew facts: ["one", "é" , "three"]'}]
    neither = [
        [{"role": "system", "content": "system"}, {"role": "user", "content": "plain text"}],
        [{"role": "developer", "content": "context"}, *old],
        old * 2,
        [],
        # Headers alone without the pinned roles/section end retain the base reply.
        [{"role": "user", "content": additive_messages()[1]["content"]}],
        [{"role": "system", "content": "system"}, {"role": "user", "content": "## New Messages\nuser: incomplete"}],
    ]
    assert parsed_reply(respond(request(old, wire))) == [
        {"event": "ADD", "id": str(i), "text": t} for i, t in enumerate(("one", "é", "three"))]
    for path in sorted(REGISTRY.glob("*.toml")):
        entry = load(path)
        # Every declared format is visited; only Mem0 declares one at this kit.
        assert all((entry["name"], key) in scripted.FORMATS for key in entry.get("structured_formats", {}))
        for messages in (old, *neither):
            for limit in (None, 0, 4, 30):
                call = request(messages, wire, limit)
                actual = reply_bytes(call, entry)
                with monkeypatch.context() as patch:
                    patch.setattr(scripted, "_mem0", base_mem0)
                    patch.setitem(scripted.FORMATS, ("mem0-oss", "extraction"), base_mem0)
                    assert actual == reply_bytes(call, entry)
        # Explicit writes also retain every reply field and the mem0_add argument bytes.
        name = scripted.WRITE_ARGS.get(entry["name"], (None,))[0]
        if name:
            tool = {"type": "function", "name": name, "parameters": {"type": "object"}}
            if wire == "chat":
                tool = {"type": "function", "function": {k: v for k, v in tool.items() if k != "type"}}
            for role in ("write_turn", "memory_write"):
                call = request(additive_messages(), wire, role=role, subrole="", tools=[tool])
                actual = reply_bytes(call, entry)
                with monkeypatch.context() as patch:
                    patch.setitem(scripted.FORMATS, ("mem0-oss", "extraction"), base_mem0)
                    assert actual == reply_bytes(call, entry)
        # Other systems' declared extraction replies also keep their bytes on the new shape.
        if entry["name"] != "mem0-oss":
            call = request(additive_messages(), wire)
            actual = reply_bytes(call, entry)
            with monkeypatch.context() as patch:
                patch.setitem(scripted.FORMATS, ("mem0-oss", "extraction"), base_mem0)
                assert actual == reply_bytes(call, entry)


def test_item3_registry_schema_accepts_additive_and_legacy_replies():
    from bicentennial.contracts.run import _check

    schema = load(REGISTRY / "mem0-oss.toml")["structured_formats"]["extraction"]["schema"]
    for messages in (additive_messages(), [{"role": "user", "content": '["old"]'}], []):
        value = json.loads(respond(request(messages)).text)
        matches = 0
        for branch in schema["oneOf"]:
            try:
                _check(branch, value)
            except ValueError:
                continue
            matches += 1
        assert matches == 1


@pytest.mark.parametrize("tier", ["t0", "t1"])
def test_item3_extraction_disclosure_follows_declared_format(tier):
    for entry in (load(REGISTRY / "mem0-oss.toml"), {"name": "other", "structured_formats": {"extraction": {}}}):
        assert dict(scripted.stub_disclosures(entry, tier))[f"{tier}.extraction"] == EXTRACTION
    for entry in ({"name": "mem0-oss"}, load(REGISTRY / "hermes-native.toml")):
        assert f"{tier}.extraction" not in dict(scripted.stub_disclosures(entry, tier))


def test_item2_installed_mem0_221_request_and_own_parse_code():
    pytest.importorskip("mem0", reason="mem0ai is not importable; quoted-source test covers the parse rule")
    if version("mem0ai") != "2.2.1":
        pytest.skip("optional integration requires mem0ai 2.2.1")
    from mem0.configs.prompts import (
        ADDITIVE_EXTRACTION_PROMPT,
        generate_additive_extraction_prompt,
    )
    from mem0.memory import main
    from mem0.memory.utils import parse_messages

    messages = [{"role": "user", "content": text} for text in NEW]
    user = generate_additive_extraction_prompt(
        existing_memories=EXISTING, new_messages=parse_messages(messages),
        last_k_messages=[{"role": "user", "content": "history-only sentinel"}],
        current_date="2026-11-03", custom_instructions="custom-only sentinel")
    assert user == additive_messages()[1]["content"]
    reply = respond(request([{"role": "system", "content": ADDITIVE_EXTRACTION_PROMPT},
                             {"role": "user", "content": user}]))
    # Execute the release's complete parse try-block, including its fence/fallback handling.
    method = ast.parse(textwrap.dedent(inspect.getsource(main.Memory._add_to_vector_store)))
    block = next(node for node in ast.walk(method) if isinstance(node, ast.Try)
                 and isinstance(node.body[0], ast.Assign)
                 and isinstance(node.body[0].value, ast.Call)
                 and isinstance(node.body[0].value.func, ast.Name)
                 and node.body[0].value.func.id == "remove_code_blocks")
    for response in (reply.text, f"```json\n{reply.text}\n```", f"prefix {reply.text} suffix"):
        namespace = {**vars(main), "response": response}
        exec(compile(ast.Module(body=[block], type_ignores=[]), "<mem0-parse>", "exec"), namespace)
        assert namespace["extracted_memories"] == [{"text": text} for text in NEW]
