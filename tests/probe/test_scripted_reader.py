"""S04 hand table, wire exchanges, stage diagnostics and keyed properties."""

import ast
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.api.adapters.nomemory import NoMemory
from bicentennial.api.adapters.oracle_evidence import OracleEvidence
from bicentennial.canon import canon
from bicentennial.contracts.items import reader_view
from bicentennial.contracts.run import validate
from bicentennial.director.core import Director
from bicentennial.director.responder import Call
from bicentennial.director.routes import RouteTable
from bicentennial.director.scripted import ScriptedResponder
from bicentennial.director.wire import responses
from bicentennial.items.reader_keys import KINDS as SEALED_KINDS
from bicentennial.keyed import choice, uniform_int
from bicentennial.ledger import Guard
from bicentennial.probe.argtemplate import fill, recall_call
from bicentennial.probe.probe_responder import (
    CLOSING,
    PlanToolMissing,
    ProbeResponder,
    RecallToolMissing,
    plain_step,
)
from bicentennial.probe.scripted_reader import (
    KINDS,
    UNKNOWN,
    api_task,
    envelope_for,
    failing_stage,
    item_report,
    read,
    read_api,
    select,
    surface_hits,
)
from bicentennial.runtime.clock import SimClock
from bicentennial.sandbox.envserver.state import State, trace
from bicentennial.score.bundle import make_bundle
from bicentennial.score.classes import outcome, score_act
from bicentennial.score.exposure import context_text
from bicentennial.score.qa import parse_envelope, score_qa
from bicentennial.systems.registry import load

ROOT = Path(__file__).resolve().parents[2]
CANARY = "c168e5f8-3948-4553-8554-7aa162054723"
EVENTS = {eid: dict(event_id=eid, t_sim=10, kind="message", actor="user", text=text) for eid, text in (
    ("e-old", "Seat note: first chose MIDDLE-3301."),
    ("e-new0", "Seat note: now wants WINDOW-7401."),
    ("e-new1", "Seat note: now wants AISLE-9201."),
    ("e-task", "Passport task TASK-5521."),
    ("e-cancel", "Passport task cancelled, ref CANCEL-6631."),
    ("e-gate", "Gate code GATE-4410."),
    ("e-request", "Please forget the gate code, request REQ-104233."),
)}
TOKENS = ("WINDOW-7401", "AISLE-9201", "MIDDLE-3301", "TASK-5521", "CANCEL-6631",
          "GATE-4410", "REQ-104233", "DECOY-7001")


def copy(value):
    return json.loads(canon(value))


def option(iid, suffix, tokens, *, act=False, value=None, steps=()):
    payload = {"plan": {"steps": list(steps)}} if act else {"envelope": {
        "type": "entity" if tokens else "unknown", "value": value if value is not None else
        tokens[0] if tokens else None, "confidence_milli": 1000 if tokens else 0}}
    return dict(option_id=f"{iid}-{suffix}", tokens=tokens, **payload)


def book(token):
    return {"tool": {"name": "book_seat", "args": {"passenger": "P1", "seat": token}}}


REM = {"tool": {"name": "add_reminder", "args": {"id": "r1", "reminder": {"text": "TASK-5521"}}}}


def fixtures():
    items, keys, tables = {}, {}, {}

    def add(iid, cell, track, options, required, spans, *, competing=(), forbidden=(), branch="B0",
            table="unused", oracle=None, never=False):
        item = dict(canary=CANARY, item_id=iid, stage="act" if "plan" in options[0] else "remember",
                    track=track, cell_id=cell, probe_point=2, prompt=f"Decide probe {iid}.", options=options,
                    gold={"option_id": options[0]["option_id"], "never_observed": never},
                    gold_spans=spans, decision_table_ref=table, precondition=None,
                    memory_tag="memory_exclusive", labels=[])
        validate("item", item)
        items[iid] = item
        keys[iid] = dict(canary=CANARY, item_id=iid, life="life-s04", branch=branch,
                         recall_query=item["prompt"], required=sorted(required),
                         competing=[{"token": t, "kind": k} for t, k in sorted(competing)],
                         forbidden=sorted(forbidden), oracle_spans=spans if oracle is None else oracle)
        validate("reader_keys", keys[iid])
        reader_view(item)

    for b, token in enumerate(("WINDOW-7401", "AISLE-9201")):
        spans, branch = [f"e-new{b}"], f"B{b}"
        iid = f"qf{b}"
        add(iid, "WAKE-PREF", "Wake", [option(iid, "g", [token]), option(iid, "s", ["MIDDLE-3301"]),
            option(iid, "u", [])], [token], spans, competing=[("MIDDLE-3301", "stale")], branch=branch)
        iid, tid = f"af{b}", f"s04-seat-b{b}"
        add(iid, "DRIFT-CUR", "Drift", [option(iid, "g", [token], act=True, steps=[book(token)]),
            option(iid, "s", ["MIDDLE-3301"], act=True, steps=[book("MIDDLE-3301")]),
            option(iid, "r", [], act=True)], [token], spans,
            competing=[("MIDDLE-3301", "stale")], branch=branch, table=tid)
        wanted = "seat_window" if b == 0 else "seat_aisle"
        tables[tid] = dict(canary=CANARY, table_id=tid, gold="act", timed=False,
            admissible=[wanted], benign_extras=[], disqualifiers=[{
                "predicate": p, "verdict": "FAIL_MEMORY", "tuesday_class": None}
                for p in ("seat_middle", "seat_aisle" if b == 0 else "seat_window")])
    add("al0", "TUE-CUE", "Tuesday", [option("al0", "g", ["TASK-5521"], act=True, steps=[REM])],
        ["TASK-5521"], ["e-task"], table="s04-lure-b0")
    add("al1", "TUE-CUE", "Tuesday", [option("al1", "g", ["CANCEL-6631"], act=True),
        option("al1", "a", ["TASK-5521"], act=True, steps=[REM]), option("al1", "r", [], act=True)],
        ["CANCEL-6631"], ["e-task", "e-cancel"], competing=[("TASK-5521", "stale")],
        branch="B1", table="s04-lure-b1")
    for b in range(2):
        tid = f"s04-lure-b{b}"
        tables[tid] = dict(canary=CANARY, table_id=tid, gold="act" if b == 0 else "refrain", timed=True,
                          admissible=["reminder_set"] if b == 0 else [], benign_extras=[],
                          disqualifiers=[] if b == 0 else [{"predicate": "reminder_set",
                              "verdict": "FAIL_MEMORY", "tuesday_class": "false_alarm"}])
    add("kf0", "KEEP-FORGET", "Keep", [option("kf0", "g", ["REQ-104233"], value="forgotten"),
        option("kf0", "use", ["GATE-4410"])], ["REQ-104233"], ["e-gate", "e-request"],
        forbidden=["GATE-4410"], oracle=["e-request"])
    add("kf1", "KEEP-FORGET", "Keep", [option("kf1", "g", ["GATE-4410"]), option("kf1", "u", [])],
        ["GATE-4410"], ["e-gate"], branch="B1")
    add("na", "RECALL-ABST", "Recall", [option("na", "u", []), option("na", "d", ["DECOY-7001"])],
        [], [], never=True)
    for table in tables.values():
        validate("decision_table", table)
    return items, keys, tables


def environment():
    return dict(canary=CANARY, env_id="s04-v1", session=1, heartbeat_interval_s=720,
                state={"seats": {}, "reminders": {}}, tools=[dict(name=name, description=name,
                op=op, collection=collection, key_arg=key, value_arg=value) for name, op, collection, key, value in (
                    ("book_seat", "set", "seats", "passenger", "seat"),
                    ("add_reminder", "add", "reminders", "id", "reminder"))])


class Adapter:
    def __init__(self, text="", citations=()):
        self.text, self.citations, self.calls = text, list(citations), []

    def query(self, task, now):
        self.calls.append((task, now))
        return dict(output=self.text, citations=self.citations, confidence_milli=1000)


def api_row(item, keys, arm):
    if arm == "stale":
        adapter = Adapter("\n".join(c["token"] for c in keys["competing"] if c["kind"] == "stale"))
    else:
        adapter = OracleEvidence() if arm == "oracle" else NoMemory()
        for event in EVENTS.values():
            adapter.ingest(event)
    result = read_api(adapter, reader_view(item), keys, 1000, oracle=arm == "oracle")
    text = adapter.query(api_task(reader_view(item), keys, oracle=arm == "oracle"), 1000)["output"]
    return result, text


def scored(item, tables, result):
    if result.kind == "qa":
        value = score_qa(item, parse_envelope(canon(result.envelope).decode()),
                         evidence_texts=[EVENTS[e]["text"] for e in item["gold_spans"]])
    else:
        state, rows = State(environment()), []
        for step in result.plan.steps:
            tool = step["tool"]
            _, changed = state.call(tool["name"], tool["args"])
            rows.append(dict(type="action", t_sim=150, asked_user=False, state_changed=changed,
                             ok=True, tool=tool["name"]))
        predicates = {f"seat_{seat}": state.state["seats"].get("P1") == token for seat, token in (
            ("window", "WINDOW-7401"), ("middle", "MIDDLE-3301"), ("aisle", "AISLE-9201"))}
        predicates["reminder_set"] = "r1" in state.state["reminders"]
        table = tables[item["decision_table_ref"]]
        names = table["admissible"] + [d["predicate"] for d in table["disqualifiers"]]
        value = score_act(item, table, trace(rows, ("book_seat", "add_reminder")),
            {n: predicates[n] for n in names}, commitment={"window_open_t": 100, "window_close_t": 200}
            if item["track"] == "Tuesday" else None)
    identity = {k: item[k] for k in ("item_id", "cell_id", "stage", "track")}
    identity.update(selected_option=result.selected_option, competing_present=list(result.competing_present),
                    carry_over=result.carry_over, stage_attribution=failing_stage(
                        result, fixtures()[1][item["item_id"]], failed=value.score_milli != 1000))
    return outcome(identity, value)


HAND = {
    "qf0": (("g", 1000), ("u", 0), ("s", -1000)),
    "qf1": (("g", 1000), ("u", 0), ("s", -1000)),
    "af0": (("g", 1000), ("r", 0), ("s", -1000)),
    "af1": (("g", 1000), ("r", 0), ("s", -1000)),
    "al0": (("g", 1000), (None, 0), (None, 0)),
    "al1": (("g", 1000), ("r", 1000), ("a", -1000)),
    "kf0": (("g", 1000), (None, 0), (None, 0)),
    "kf1": (("g", 1000), ("u", 0), ("u", 0)),
    "na": (("u", 1000), ("u", 1000), ("u", 1000)),
}
ARMS = ("oracle", "empty", "stale")


def test_hand_table_and_diagnostics():
    items, keys, tables = fixtures()
    for arm_index, arm in enumerate(ARMS):
        outcomes = {}
        for iid, item in items.items():
            result, text = api_row(item, keys[iid], arm)
            suffix, score = HAND[iid][arm_index]
            assert result.selected_option == (f"{iid}-{suffix}" if suffix else None)
            outcomes[iid] = scored(item, tables, result)
            assert outcomes[iid]["score_milli"] == score
            assert result.carry_over is False
            if result.envelope and result.envelope["citation"]:
                citation = result.envelope["citation"]
                assert citation["context_offset"] == context_text([text]).find(citation["quote"])
            if arm == "oracle":
                assert result.in_context is (None if iid == "na" else True)
                assert result.competing == {"stale": int(iid == "al1"), "planted": 0, "twin": 0}
                assert result.forbidden_in_context is (False if iid == "kf0" else None)
                assert result.competing_present == (("al1-a",) if iid == "al1" else ())
                assert result.recall is None if iid == "na" else result.recall["milli"] == 1000
            if arm == "stale" and iid in ("qf0", "qf1", "af0", "af1", "al1"):
                assert result.in_context is False and result.missing_required == 1
                assert result.competing["stale"] == 1
            if iid.startswith("af") and arm != "oracle":
                assert outcomes[iid]["base_verdict"] == ("OMISSION" if arm == "empty" else "FAIL_MEMORY")
            if iid == "al0":
                assert outcomes[iid]["tuesday_class"] == ("on_time" if arm == "oracle" else "never")
            if iid == "al1" and arm == "stale":
                assert outcomes[iid]["tuesday_class"] == "false_alarm"
        for bid, pair, twin in (("qa-fork", ("qf0", "qf1"), "fork"),
                               ("act-fork", ("af0", "af1"), "fork"),
                               ("act-lure", ("al0", "al1"), "lure"),
                               ("qa-forget", ("kf0", "kf1"), "trigger")):
            a, b = (outcomes[iid] for iid in pair)
            bundle = make_bundle(dict(bundle_id=bid, cell_id=a["cell_id"], twin_type=twin, life="life-s04"), a, b)
            if arm == "oracle":
                assert bundle["score_milli"] == 1000


@pytest.mark.parametrize("citations,hits,total,milli", [
    (["x1", "e-task", "x2", "x3", "x4", "e-cancel"], 1, 2, 500),
    (["e-cancel", "e-task"], 2, 2, 1000), ([], 0, 2, 0),
    (["e-task"] * 5 + ["e-cancel"], 1, 2, 500), (["e-task"], 1, 3, 333),
])
def test_recall_exact(citations, hits, total, milli):
    items, keys, _ = fixtures()
    key = copy(keys["al1"])
    if total == 3:
        key["oracle_spans"].append("e-x9")
    adapter = Adapter(citations=citations)
    result = read_api(adapter, reader_view(items["al1"]), key, 1000)
    assert result.recall == dict(k=5, hits=hits, of=total, milli=milli)
    assert adapter.calls == [(dict(task_id="al1", prompt=items["al1"]["prompt"]), 1000)]


def entry():
    return load(ROOT / "systems/registry/hermes-native.toml")


def responder(iids=("qf0",), *, system=None, earlier=lambda run, session: (), step_call=plain_step):
    items, keys, _ = fixtures()
    system = entry() if system is None else system
    return ProbeResponder(ScriptedResponder(system), system,
        {iid: (1, i + 1) for i, iid in enumerate(iids)},
        {iid: (reader_view(items[iid]), keys[iid]) for iid in iids}, earlier=earlier, step_call=step_call)


def body(wire, prompt, tools=("session_search", "book_seat", "add_reminder")):
    offered = [{"type": "function", "name": name, "parameters": {"type": "object", "properties": {}}}
               for name in tools]
    if wire == "chat":
        return dict(model="bicentennial-main", messages=[{"role": "user", "content": prompt}],
                    tools=[{"type": "function", "function": {k: v for k, v in t.items() if k != "type"}}
                           for t in offered])
    return dict(model="bicentennial-main", input=[{"type": "message", "role": "user", "content": prompt}],
                tools=offered)


def append_exchange(request, wire, call, text, cid="call-1"):
    if wire == "chat":
        request["messages"] += [{"role": "assistant", "content": "", "tool_calls": [
            {"type": "function", "id": cid, "function": call}]},
            {"role": "tool", "tool_call_id": cid, "content": text}]
    else:
        request["input"] += [dict(type="function_call", call_id=cid, **call),
                             dict(type="function_call_output", call_id=cid, output=text)]


def call_for(wire, request, subrole="cursor", turn=1, run="s04-run"):
    return Call("probe_main", subrole, wire, copy(request), "probe-model", {"session": 1, "turn": turn}, run)


def comparable(result):
    value = asdict(result)
    for key in ("mode", "recall", "carry_over"):
        value.pop(key)
    if value["envelope"] and value["envelope"]["citation"]:
        value["envelope"]["citation"].pop("context_offset")
    return value


def wire_row(wire, item, key, text):
    probe = responder((item["item_id"],))
    request = body(wire, item["prompt"])
    first = probe.respond(call_for(wire, request))
    expected = {"name": "session_search", "arguments": canon({"query": item["prompt"]}).decode()}
    assert first.tool_calls == (expected,) and first.text == "" and first.usage is None
    assert first == probe.respond(call_for(wire, request, "retry"))
    append_exchange(request, wire, first.tool_calls[0], text)
    second = probe.respond(call_for(wire, request, "tool_results"))
    assert second == probe.respond(call_for(wire, request, "tool_results"))
    result = probe.results()[item["item_id"]]
    if result.kind == "qa":
        assert parse_envelope(second.text) == result.envelope
        citation = result.envelope["citation"]
        if citation:
            assert citation["context_offset"] == context_text(request).find(citation["quote"])
    else:
        state = State(environment())
        for n, step in enumerate(result.plan.steps):
            assert second.tool_calls == (plain_step(step),)
            state.call(step["tool"]["name"], step["tool"]["args"])
            append_exchange(request, wire, second.tool_calls[0], "MIDDLE-3301", cid=f"step-{n}")
            second = probe.respond(call_for(wire, request, "tool_results"))
            assert probe.results()[item["item_id"]] == result
        assert second.text == CLOSING and second.tool_calls == ()
    return result


@pytest.mark.parametrize("wire", ["chat", "responses"])
def test_both_wires(wire):
    items, keys, tables = fixtures()
    for index, arm in enumerate(ARMS):
        for iid, item in items.items():
            api, text = api_row(item, keys[iid], arm)
            hermes = wire_row(wire, item, keys[iid], text)
            assert comparable(hermes) == comparable(api)
            assert hermes.recall is None
            assert scored(item, tables, hermes)["score_milli"] == HAND[iid][index][1]


def test_closing_text_is_the_compiler_replay_text():
    # A plan probe ends like check_compile's replay of the same plan, and never with an empty reply.
    from bicentennial.director.compiler.hermes import ASSISTANT
    assert CLOSING == ASSISTANT and CLOSING.strip()


@pytest.mark.parametrize("wire", ["chat", "responses"])
def test_no_recall_and_compiler(wire):
    items, keys, _ = fixtures()
    system = dict(entry(), recall=None)

    def compile_step(step):
        return {"name": "environment", "arguments": canon(step).decode()}

    probe = responder(("af0",), system=system, step_call=compile_step)
    request = body(wire, items["af0"]["prompt"], tools=("environment",))
    request["memory"] = "WINDOW-7401"
    first = probe.respond(call_for(wire, request))
    assert first.tool_calls == (compile_step(book("WINDOW-7401")),)
    assert first == probe.respond(call_for(wire, request, "retry"))
    append_exchange(request, wire, first.tool_calls[0], "MIDDLE-3301")
    done = probe.respond(call_for(wire, request, "tool_results"))
    assert done.tool_calls == () and done.text == CLOSING
    assert probe.results()["af0"].selected_option == "af0-g"
    assert recall_call(system, "query") is None
    assert comparable(probe.results()["af0"]) == comparable(read(
        reader_view(items["af0"]), keys["af0"], "WINDOW-7401", mode="api"))


def carry_rows(wire):
    items, _, _ = fixtures()
    history, accesses, rows = [], [], []

    def earlier(run, session):
        accesses.append((run, session))
        return tuple(history)

    probe = responder(("qf0", "kf1"), earlier=earlier)
    for iid, turn, text in (("qf0", 1, "WINDOW-7401"), ("kf1", 2, "GATE-4410")):
        request = body(wire, items[iid]["prompt"])
        reply = probe.respond(call_for(wire, request, turn=turn))
        append_exchange(request, wire, reply.tool_calls[0], text)
        reply = probe.respond(call_for(wire, request, "tool_results", turn))
        assert probe.results()[iid].carry_over is False
        rows.append(asdict(probe.results()[iid]))
        history.extend((canon(request), canon({"text": reply.text})))
    # Current history is compacted: only a new user and the current recall remain.
    request = body(wire, items["qf0"]["prompt"])
    reply = probe.respond(call_for(wire, request, run="next-run"))
    append_exchange(request, wire, reply.tool_calls[0], "WINDOW-7401")
    probe.respond(call_for(wire, request, "tool_results", run="next-run"))
    assert probe.results()["qf0"].carry_over is True
    assert accesses == [("s04-run", 1), ("s04-run", 1), ("next-run", 1)]
    return [*rows, asdict(probe.results()["qf0"])]


@pytest.mark.parametrize("wire", ["chat", "responses"])
def test_ledger_carry_over_survives_compaction(wire):
    carry_rows(wire)


@pytest.mark.parametrize("encoded", [False, True])
@pytest.mark.parametrize("wire,field,role", [
    ("chat", "messages", "system"),
    ("chat", "messages", "developer"),
    ("responses", "input", "system"),
    ("responses", "input", "developer"),
    ("responses", "instructions", None),
])
def test_ledger_carry_over_excludes_prompt_memory(wire, field, role, encoded):
    items, _, _ = fixtures()
    prior = body(wire, "Earlier probe.")
    if field == "instructions":
        prior[field] = "WINDOW-7401"
    else:
        prior[field].insert(0, {"role": role, "content": "WINDOW-7401"})
    original = copy(prior)
    history = [prior, {"text": "Earlier answer."}]
    if encoded:
        history = [canon(record) for record in history]
    probe = responder(earlier=lambda run, session: tuple(history))
    request = body(wire, items["qf0"]["prompt"])
    reply = probe.respond(call_for(wire, request))
    append_exchange(request, wire, reply.tool_calls[0], "WINDOW-7401")
    probe.respond(call_for(wire, request, "tool_results"))
    result = probe.results()["qf0"]
    assert result.selected_option == "qf0-g"
    assert result.carry_over is False
    assert prior == original


@pytest.mark.parametrize("prior", [
    {"messages": [{"role": "user", "content": "WINDOW-7401"}]},
    {"messages": [{"role": "assistant", "content": "WINDOW-7401"}]},
    {"messages": [{"role": "tool", "content": "WINDOW-7401"}]},
    {"input": [{"type": "function_call", "arguments": '{"note":"WINDOW-7401"}'}]},
    {"input": [{"type": "function_call_output", "output": "WINDOW-7401"}]},
    {"input": "WINDOW-7401"},
    {"text": "WINDOW-7401"},
    {"output": [], "instructions": "WINDOW-7401"},
])
def test_ledger_carry_over_keeps_exchange_content(prior):
    items, _, _ = fixtures()
    original = copy(prior)
    probe = responder(earlier=lambda run, session: (prior,))
    request = body("chat", items["qf0"]["prompt"])
    reply = probe.respond(call_for("chat", request))
    append_exchange(request, "chat", reply.tool_calls[0], "WINDOW-7401")
    probe.respond(call_for("chat", request, "tool_results"))
    assert probe.results()["qf0"].carry_over is True
    assert prior == original


def diagnostic_rows(tmp_path):
    items, keys, _ = fixtures()
    full = read(reader_view(items["kf0"]), keys["kf0"],
                context_text([EVENTS["e-gate"]["text"], EVENTS["e-request"]["text"]]), mode="api")
    oracle, _ = api_row(items["kf0"], keys["kf0"], "oracle")
    occupied, empty = tmp_path / "occupied", tmp_path / "empty"
    occupied.mkdir()
    empty.mkdir()
    (occupied / "note").write_text("GATE-4410 REQ-104233")
    assert full.selected_option == "kf0-g" and full.competing_present == ("kf0-use",)
    assert full.forbidden_in_context is True
    reports = [item_report(full, keys["kf0"], failed=False, retained_roots=[occupied]),
               item_report(oracle, keys["kf0"], failed=False, retained_roots=[empty]),
               item_report(oracle, keys["kf0"], failed=False)]
    assert [r["forget"] for r in reports] == [
        dict(in_context=True, in_store=True, held=False),
        dict(in_context=False, in_store=False, held=True),
        dict(in_context=False, in_store=None, held=None)]
    missing = read(reader_view(items["kf0"]), keys["kf0"], "", mode="api")
    stages = [item_report(missing, keys["kf0"], failed=True, retained_roots=[occupied]),
              item_report(missing, keys["kf0"], failed=True, stored_roots=[occupied], retained_roots=[empty]),
              item_report(missing, keys["kf0"], failed=True)]
    assert [r["stage_attribution"] for r in stages] == ["retrieved", "retained", "unknown"]
    assert failing_stage(missing, keys["kf0"], failed=True, stored_roots=[occupied]) == "unknown"
    assert failing_stage(full, keys["kf0"], failed=True, retained_roots=[occupied]) == "unknown"
    assert surface_hits(None, ["GATE-4410"]) is None
    assert surface_hits([occupied, empty], ["GATE-4410", "ABSENT-0000"]) == {
        "GATE-4410": True, "ABSENT-0000": False}
    return [asdict(full), *reports, *stages]


def test_forget_stage_and_report_privacy(tmp_path):
    rows = diagnostic_rows(tmp_path)
    items, keys, _ = fixtures()
    reports = rows[1:]
    for iid, item in items.items():
        for arm in ARMS:
            result, _ = api_row(item, keys[iid], arm)
            reports.append(item_report(result, keys[iid], failed=True))
    for report in reports:
        raw = canon(report)
        assert not any(token.encode() in raw for token in TOKENS)
        assert not any(item["prompt"].encode() in raw for item in items.values())
        assert not any(event["text"].encode() in raw for event in EVENTS.values())


def director(tmp_path, probe, iid):
    item = fixtures()[0][iid]
    # FaultLite follows timeline order, not numerical index order. An empty replay
    # prelude supplies route provenance while the only probe remains at (1, 1).
    script = dict(canary=CANARY, life_id="life-s04", genre="s04", harness="hermes", sessions=[
        dict(index=2, kind="replay", turns=[]),
        dict(index=1, kind="probe", turns=[dict(n=1, kind="probe", user=item["prompt"],
                                               assistant=None, tool_calls=[])])])
    routes = RouteTable.load({"routes": [dict(system="hermes-native", segment="seg0",
        probe_model="probe-model", alias="bicentennial-main", summariser="summary-model",
        vision=None, served_by="scripted")]})
    d = Director(script, routes, "hermes-native", "life-s04", "B0", "run-1", (), probe,
        SimClock(tmp_path / "clock.json", 1000, 60), Guard([]),
        {"sandbox_root": str(tmp_path / "sandbox"), "director_port": "1"})
    d.start_session(1, 1000, "ab" * 32, "s04-run", tmp_path / "ledger")
    return d


def post(d, wire, request):
    path = "/v1/chat/completions" if wire == "chat" else "/v1/responses"
    return d.handle("POST", path, {}, canon(request))


def delivered(response):
    status, headers, data = response
    assert status == 200
    if headers["Content-Type"] == "application/json":
        message = json.loads(data)["choices"][0]["message"]
        return message.get("content", ""), [(c["id"], c["function"]) for c in message.get("tool_calls", [])]
    items = [e["item"] for e in responses.parse_sse(data) if e.get("type") == "response.output_item.done"]
    return ("".join(p["text"] for item in items if item["type"] == "message" for p in item["content"]),
            [(it["call_id"], {k: it[k] for k in ("name", "arguments")})
             for it in items if it["type"] == "function_call"])


def records(tmp_path):
    rows = [json.loads(line) for line in (tmp_path / "ledger/ledger.jsonl").read_bytes().splitlines()]
    for row in rows:
        validate("ledger-record", row)
    return rows


@pytest.mark.parametrize("wire", ["chat", "responses"])
def test_director_round_trip(wire, tmp_path):
    probe = responder()
    d = director(tmp_path, probe, "qf0")
    try:
        request = body(wire, fixtures()[0]["qf0"]["prompt"])
        text, calls = delivered(post(d, wire, request))
        assert text == "" and len(calls) == 1
        cid, tool = calls[0]
        assert cid != "call-1"
        append_exchange(request, wire, tool, EVENTS["e-new0"]["text"], cid)
        text, calls = delivered(post(d, wire, request))
        assert not calls and parse_envelope(text) == probe.results()["qf0"].envelope
        title = body(wire, "Name this session", tools=())
        title["model"] = "bicentennial-aux-title_generation"
        assert delivered(post(d, wire, title)) == ("Session", [])
        rows = records(tmp_path)
        assert [(r["role"], r["subrole"], r["served"]) for r in rows] == [
            ("probe_main", "cursor", "responder_probe_reader"),
            ("probe_main", "tool_results", "responder_probe_reader"),
            ("aux", "title_generation", "responder_scripted")]
        assert all(r["cursor"] == {"session": 1, "turn": 1} for r in rows[:2])
    finally:
        d.close()


@pytest.mark.parametrize("wire", ["chat", "responses"])
@pytest.mark.parametrize("missing,iid,error", [
    ("recall", "qf0", "error_recalltoolmissing"), ("plan", "af0", "error_plantoolmissing")])
def test_director_missing_tool_codes(wire, missing, iid, error, tmp_path):
    assert RecallToolMissing.__name__ == "RecallToolMissing"
    assert PlanToolMissing.__name__ == "PlanToolMissing"
    d = director(tmp_path, responder((iid,)), iid)
    try:
        # S1 requires at least one offered tool to classify a main cursor turn.
        offered = ("book_seat",) if missing == "recall" else ("session_search",)
        request = body(wire, fixtures()[0][iid]["prompt"], tools=offered)
        response = post(d, wire, request)
        if missing == "plan":
            _, calls = delivered(response)
            cid, tool = calls[0]
            append_exchange(request, wire, tool, "WINDOW-7401", cid)
            response = post(d, wire, request)
        assert response[0] == 500
        assert records(tmp_path)[-1]["upstream"][0]["error"] == error
    finally:
        d.close()


def test_input_refusals():
    items, keys, _ = fixtures()
    view, key = reader_view(items["qf0"]), keys["qf0"]
    with pytest.raises(ValueError, match="reader view required"):
        read(items["qf0"], key, "", mode="api")
    with pytest.raises(ValueError, match="ids differ"):
        read(view, keys["qf1"], "", mode="api")
    with pytest.raises(ValueError):
        read(view, dict(key, required=["bad"]), "", mode="api")
    mixed = copy(view)
    mixed["options"][0]["plan"] = {"steps": []}
    with pytest.raises(ValueError, match="mixed"):
        read(mixed, key, "", mode="api")


@pytest.mark.parametrize("template", [{"q": "{query}"}, {"{prompt}": "ok"}, []])
def test_template_refusals(template):
    with pytest.raises(ValueError):
        fill(template, "q")


def test_templates_and_copies():
    template = {"q": ["prefix {prompt} / {prompt}", {"nested": "{prompt}", "n": 1, "b": True, "v": None}]}
    result = fill(template, "{literal}")
    assert result["q"][0] == "prefix {literal} / {literal}"
    assert result["q"][1] == {"nested": "{literal}", "n": 1, "b": True, "v": None}
    result["q"].append("changed")
    assert len(template["q"]) == 2
    with pytest.raises(ValueError):
        recall_call(dict(entry(), read_tools=[]), "q")
    items, keys, _ = fixtures()
    view = reader_view(items["af0"])
    result = read(view, keys["af0"], "WINDOW-7401", mode="api")
    obj = result.plan.to_obj()
    obj["steps"][0]["tool"]["args"]["seat"] = "changed"
    assert result.plan.steps[0]["tool"]["args"]["seat"] == "WINDOW-7401"
    view["options"][0]["plan"]["steps"].clear()
    assert len(result.plan.steps) == 1
    assert envelope_for(None, "") == UNKNOWN
    selected = option("test", "u", [], value="ignored")
    assert envelope_for(selected, "") == UNKNOWN


def test_constructor_refusals():
    items, keys, _ = fixtures()
    readers = {iid: (reader_view(items[iid]), keys[iid]) for iid in ("qf0", "qf1")}
    for probes in ({"qf0": (1, 1)}, {"qf0": (1, 1), "qf1": (1, 1)},
                   {"qf0": (True, 1), "qf1": (1, 2)}, {"qf0": (0, 1), "qf1": (1, 2)}):
        with pytest.raises(ValueError):
            ProbeResponder(None, entry(), probes, readers, earlier=lambda r, s: ())
    with pytest.raises(ValueError):
        responder(system=dict(entry(), read_tools=[]))


@pytest.mark.parametrize("wire", ["chat", "responses"])
def test_exchange_refusals(wire):
    items, _, _ = fixtures()
    probe = responder()
    request = body(wire, items["qf0"]["prompt"])
    for changed in (replace(call_for(wire, request), cursor=None),
                    replace(call_for(wire, request), cursor={"session": 99, "turn": 1}),
                    replace(call_for(wire, request), subrole="x")):
        with pytest.raises(ValueError):
            probe.respond(changed)
    with pytest.raises(RecallToolMissing):
        probe.respond(call_for(wire, body(wire, items["qf0"]["prompt"], tools=())))
    append_exchange(request, wire, recall_call(entry(), items["qf0"]["prompt"]), "WINDOW-7401")
    probe.respond(call_for(wire, request, "tool_results"))
    append_exchange(request, wire, plain_step(book("WINDOW-7401")), "ok", "extra")
    with pytest.raises(ValueError, match="second QA"):
        probe.respond(call_for(wire, request, "tool_results"))
    probe = responder(("af0",))
    request = body(wire, items["af0"]["prompt"], tools=("session_search",))
    append_exchange(request, wire, recall_call(entry(), items["af0"]["prompt"]), "WINDOW-7401")
    with pytest.raises(PlanToolMissing):
        probe.respond(call_for(wire, request, "tool_results"))
    request = body(wire, items["af0"]["prompt"])
    append_exchange(request, wire, recall_call(entry(), items["af0"]["prompt"]), "WINDOW-7401")
    probe.respond(call_for(wire, request, "tool_results"))
    append_exchange(request, wire, plain_step(REM), "ok", "wrong")
    with pytest.raises(ValueError, match="out-of-order"):
        probe.respond(call_for(wire, request, "tool_results"))
    with pytest.raises(ValueError, match="decision exchange missing"):
        responder(("af0",)).respond(call_for(wire, request, "tool_results"))


@pytest.mark.parametrize("answer", [{}, {"output": 1, "citations": [], "confidence_milli": 0},
    {"output": "", "citations": [1], "confidence_milli": 0}])
def test_malformed_answer(answer):
    class Bad:
        def query(self, task, now):
            return answer
    items, keys, _ = fixtures()
    with pytest.raises(ValueError):
        read_api(Bad(), reader_view(items["qf0"]), keys["qf0"], 1000)


def test_adapter_exception_injection_and_nfc():
    class Broken:
        def query(self, task, now):
            raise RuntimeError("adapter failure")
    items, keys, _ = fixtures()
    view, key = reader_view(items["qf0"]), keys["qf0"]
    with pytest.raises(RuntimeError, match="adapter failure"):
        read_api(Broken(), view, key, 1000)
    assert read_api(Adapter(), view, key, 1000, injected=[{"memory": "WINDOW-7401"}]).selected_option == "qf0-g"
    options = [option("nfc", "a", ["caf\u00e9"]), option("nfc", "u", [])]
    assert select(options, context_text(["cafe\u0301"]))[0] == options[0]
    assert select(options, context_text(["ca", "f\u00e9"]))[0] == options[1]


def test_keyed_policy_properties():
    items, keys, _ = fixtures()
    for c in range(200):
        unit = ("s04", "policy", str(c))
        count = uniform_int("s04", unit, 0, "count", 1, 4)
        empty_at = choice("s04", unit, 0, "empty", list(range(count)) + [None])
        options = [option("property", str(i), [] if i == empty_at else [choice(
            "s04", unit, 0, f"token-{i}", TOKENS)]) for i in range(count)]
        subset = [t for i, t in enumerate(TOKENS) if choice("s04", unit, 0, f"include-{i}", (False, True))]
        text = context_text(subset)
        available = [o for o in options if o["tokens"] and all(t in text for t in o["tokens"])]
        expected = available[0] if available else next((o for o in options if not o["tokens"]), None)
        selected, competing = select(options, text)
        assert selected == expected
        assert competing == tuple(sorted(o["option_id"] for o in available if o is not expected))
        view = dict(reader_view(items["qf0"]), options=options)
        api = read(view, keys["qf0"], text, mode="api")
        wire = choice("s04", unit, 0, "wire", ("chat", "responses"))
        system = entry()
        probe = ProbeResponder(ScriptedResponder(system), system, {"qf0": (1, 1)},
                               {"qf0": (view, keys["qf0"])}, earlier=lambda r, s: ())
        request = body(wire, view["prompt"])
        first = probe.respond(call_for(wire, request))
        append_exchange(request, wire, first.tool_calls[0], text)
        probe.respond(call_for(wire, request, "tool_results"))
        assert comparable(api) == comparable(probe.results()["qf0"])


def test_purity():
    assert KINDS == SEALED_KINDS
    allowed = {"unicodedata", "json", "fractions", "dataclasses", "collections.abc", "bicentennial.canon",
               "bicentennial.contracts.run", "bicentennial.api.contract", "bicentennial.director.responder",
               "bicentennial.score.exposure", "bicentennial.sandbox.spansearch"}
    for path in sorted((ROOT / "src/bicentennial/probe").glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name in allowed for alias in node.names)
            if isinstance(node, ast.ImportFrom):
                assert node.level or node.module in allowed
            for value in (getattr(node, "id", None), getattr(node, "attr", None), getattr(node, "value", None)):
                if isinstance(value, str):
                    assert "gold" not in value.lower()
            assert not (isinstance(node, ast.Constant) and isinstance(node.value, float))
    init = ast.parse((ROOT / "src/bicentennial/probe/__init__.py").read_text())
    assert len(init.body) == 1 and isinstance(init.body[0], ast.Expr)


def deterministic_bytes():
    items, keys, tables = fixtures()
    rows = []
    for arm in ARMS:
        for iid in sorted(items):
            result, text = api_row(items[iid], keys[iid], arm)
            rows += [asdict(result), item_report(result, keys[iid], failed=True), scored(items[iid], tables, result)]
            if result.plan:
                rows.append(result.plan.to_obj())
            for wire in ("chat", "responses"):
                hermes = wire_row(wire, items[iid], keys[iid], text)
                rows += [asdict(hermes), item_report(hermes, keys[iid], failed=True)]
                if hermes.plan:
                    rows.append(hermes.plan.to_obj())
    for citations, extra in ((["x1", "e-task", "x2", "x3", "x4", "e-cancel"], False),
                             (["e-cancel", "e-task"], False), ([], False),
                             (["e-task"] * 5 + ["e-cancel"], False), (["e-task"], True)):
        key = copy(keys["al1"])
        if extra:
            key["oracle_spans"].append("e-x9")
        result = read_api(Adapter(citations=citations), reader_view(items["al1"]), key, 1000)
        rows += [asdict(result), result.plan.to_obj(), item_report(result, key, failed=True)]
    with tempfile.TemporaryDirectory(prefix="s04-determinism-") as tmp:
        rows += diagnostic_rows(Path(tmp))
    for wire in ("chat", "responses"):
        rows += carry_rows(wire)
    return canon(rows)


def test_subprocess_determinism():
    outputs = []
    for seed in ("0", "random"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        outputs.append(subprocess.check_output([sys.executable, str(Path(__file__).resolve())], env=env))
    assert outputs[0] == outputs[1] == deterministic_bytes() + b"\n"
    assert len(sha256(outputs[0]).hexdigest()) == 64


if __name__ == "__main__":
    sys.stdout.buffer.write(deterministic_bytes() + b"\n")
