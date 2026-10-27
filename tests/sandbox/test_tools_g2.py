"""G2 tools: golden traces, replay compatibility and 200 keyed sequence cases."""

import ast
import copy
import io
import json
import os
import select
import subprocess
import sys
from pathlib import Path

import pytest

from bicentennial.canon import canon, sha256_canon
from bicentennial.genres.g2_assistant import envseed as envmod
from bicentennial.genres.g2_assistant.envseed import (
    env_key,
    env_state_hashes,
    envseed,
    probe_envseed,
)
from bicentennial.genres.g2_assistant.world import build_base
from bicentennial.keyed import choice, uniform_int
from bicentennial.runtime.clock import SimClock
from bicentennial.sandbox.envserver import tools_g2
from bicentennial.sandbox.envserver.ask import ASK_REPLY
from bicentennial.sandbox.envserver.server import _tools, serve
from bicentennial.sandbox.envserver.state import State, trace
from bicentennial.sandbox.envserver.tools_g2 import (
    ACTION_TOOLS,
    COLLECTIONS,
    G2_ENV_ID,
    SEARCH_TOOLS,
    SEED_TOOLS,
    VALUE_SCHEMAS,
    G2State,
)
from bicentennial.sandbox.envserver.tools_g2.state import check_value, search
from bicentennial.world.processes import mint
from bicentennial.world.scale import named

ROOT = Path(__file__).resolve().parents[2]
NAMES = [
    "get_mail", "get_note", "get_calendar_entry", "get_booking", "get_option", "book",
    "cancel_booking", "add_note", "send_mail", "add_calendar_entry", "search_mail",
    "search_notes", "search_calendar", "search_bookings", "search_options", "ask_user",
]
STRING_MAP = {
    "type": "object", "minProperties": 1,
    "propertyNames": {"type": "string", "minLength": 1,
                      "not": {"enum": ["items", "t_sim", "from"]}},
    "additionalProperties": {"type": "string", "minLength": 1},
}


@pytest.fixture(scope="module")
def life(tmp_path_factory):
    result = build_base(tmp_path_factory.mktemp("g2-tools") / "t1.db",
                        seed="r11b-t1", life="life-a", scale=named("t1"))
    yield result
    result.db.close()


@pytest.fixture(scope="module")
def probe(life):
    s = len(life.schedule.sessions)
    return probe_envseed(life.db, s + 1, s)


def request(mid, method, **params):
    return {"jsonrpc": "2.0", "id": mid, "method": method, "params": params}


def tool_requests(calls):
    return [request(i, "tools/call", name=name, arguments=args)
            for i, (name, args) in enumerate(calls, 1)]


def load_log(path):
    raw = (path / "env_actions.jsonl").read_bytes()
    rows = [json.loads(line) for line in raw.splitlines()]
    assert b"".join(canon(row) + b"\n" for row in rows) == raw
    return rows, raw


def run(seed, path, calls, *, tick_before=None):
    path.mkdir()
    clock = SimClock(path / "clock.json", 100, 17)

    def source():
        for i, msg in enumerate(tool_requests(calls)):
            if i == tick_before:
                clock.tick()
            yield canon(msg) + b"\n"

    sink = io.BytesIO()
    state = serve(seed, path, clock.path, source(), sink)
    replies = [json.loads(line)["result"] for line in sink.getvalue().splitlines()]
    rows, raw = load_log(path)
    return state, replies, rows, raw


def assert_replay(seed, state, rows):
    replay = State(seed)
    assert rows[0]["kind"] == "session_start"
    assert rows[-1]["kind"] == "session_end"
    assert [row["kind"] for row in rows if row["type"] == "boundary"] == ["session_start", "session_end"]
    assert rows[0]["state_hash"] == sha256_canon(seed["state"])
    for seq, (previous, row) in enumerate(zip(rows, rows[1:-1], strict=False), 1):
        assert row["type"] == "action" and row["seq"] == seq
        if row["ok"] and row["state_changed"]:
            assert row["tool"] in ACTION_TOOLS
            replay.call(row["tool"], row["args"])
        else:
            assert row["state_changed"] is False
            assert row["state_hash"] == previous["state_hash"]
        assert row["state_hash"] == sha256_canon(replay.state)
    assert replay.state == state
    assert rows[-1]["state_hash"] == sha256_canon(state)


def booking_keys(life):
    return tuple(env_key(life.schedule.seed, "booking", life.bookings[k])
                 for k in ("saturday", "dinner"))


def golden_cases(life, probe):
    st0 = probe.seed["state"]
    sat, din = booking_keys(life)
    cases = []
    for name, collection in (("get_mail", "mail"), ("get_calendar_entry", "calendar"),
                             ("get_booking", "bookings"), ("get_option", "inventory")):
        key = min(st0[collection])
        cases.append((name, [(name, {"id": key})], st0[collection][key], copy.deepcopy(st0)))
    for tool in SEARCH_TOOLS:
        cases.append((tool["name"], [(tool["name"], {"query": ""})],
                      st0[tool["collection"]], copy.deepcopy(st0)))
    seats = {k: v for k, v in st0["inventory"].items() if v["domain"] == "seat"}
    cases.append(("seat_search", [("search_options", {"query": "seat"})], seats, copy.deepcopy(st0)))
    seat = next(v["value"] for k, v in seats.items()
                if v["scope"] == ["context", "long_haul"] and probe.labels[k])
    booking = {"slot": st0["bookings"][sat]["slot"], "seat": seat}
    for case, calls, collection, key, value in (
        ("note", [("add_note", {"id": "n1", "note": {"text": "x"}}),
                  ("get_note", {"id": "n1"})], "notes", "n1", {"text": "x"}),
        ("book", [("book", {"id": sat, "booking": booking})], "bookings", sat, booking),
        ("cancel", [("cancel_booking", {"id": din})], "bookings", din, None),
        ("mail", [("send_mail", {"id": "m1", "message": {"to": "Principal", "text": "x"}})],
         "mail", "m1", {"to": "Principal", "text": "x"}),
        ("calendar", [("add_calendar_entry", {"id": "c1", "entry": {"when": "Friday", "text": "x"}})],
         "calendar", "c1", {"when": "Friday", "text": "x"}),
    ):
        expected = copy.deepcopy(st0)
        if value is None:
            result = expected[collection].pop(key)
        else:
            expected[collection][key] = value
            result = value
        cases.append((case, calls, result, expected))
    return cases


def test_catalog_and_all_generated_seeds(life, probe):
    assert G2_ENV_ID == envmod.ENV_ID
    assert COLLECTIONS == envmod.COLLECTIONS
    assert [dict(t) for t in SEED_TOOLS] == [dict(t) for t in envmod.TOOLS]
    assert ACTION_TOOLS == ("book", "cancel_booking", "add_note", "send_mail", "add_calendar_entry")
    assert set(VALUE_SCHEMAS) == {"book", "send_mail", "add_note", "add_calendar_entry"}
    assert all(schema == STRING_MAP for schema in VALUE_SCHEMAS.values())
    for p in [envseed(life.db, k) for k in range(1, len(life.schedule.sessions) + 1)] + [probe]:
        before = canon(p.seed)
        state = G2State(p.seed)
        assert sha256_canon(state.state) == p.env_state_hash
        assert [*state.tools, "ask_user"] == NAMES
        assert canon(p.seed) == before
        assert len(p.seed["tools"]) == 10


def test_per_tool_golden_traces(life, probe, tmp_path):
    for case, calls, result, expected in golden_cases(life, probe):
        state, replies, rows, _ = run(probe.seed, tmp_path / case, calls)
        assert all(not reply["isError"] for reply in replies)
        assert replies[-1] == {"content": [{"type": "text", "text": canon(result).decode("utf-8")}],
                               "isError": False}
        assert state == expected
        assert rows[-2]["state_hash"] == rows[-1]["state_hash"] == sha256_canon(expected)
        assert_replay(probe.seed, state, rows)
    assert probe.seed["state"]["notes"] == {}
    assert len(search(probe.seed["state"]["inventory"], "seat")) == 6


def test_read_only_every_session(life, tmp_path):
    calls = [(t["name"], {"query": ""}) for t in SEARCH_TOOLS]
    calls.append(("ask_user", {"question": "以前の発言は？"}))
    for k, expected in env_state_hashes(life.db).items():
        seed = envseed(life.db, k).seed
        state, replies, rows, _ = run(seed, tmp_path / str(k), calls)
        assert all(not reply["isError"] for reply in replies)
        assert rows[-1]["state_hash"] == expected
        assert trace(rows, ACTION_TOOLS) == (True, False, None)
        assert_replay(seed, state, rows)


def test_admissible_options(life, probe, tmp_path):
    st0 = probe.seed["state"]
    sat, _ = booking_keys(life)
    for scope, pref, j in (("long_haul", "seat-long", 1), ("short_haul", "seat-short", 0)):
        options = {k: v for k, v in st0["inventory"].items()
                   if v["domain"] == "seat" and v["scope"] == ["context", scope]}
        true_key = env_key(life.schedule.seed, "option",
                           mint(life.schedule, "corrections", f"pref-{pref}", "fact", "value", j))
        truths = []
        for key, option in options.items():
            value = {"slot": st0["bookings"][sat]["slot"], "seat": option["value"]}
            state, replies, rows, _ = run(probe.seed, tmp_path / key,
                                          [("book", {"id": sat, "booking": value})])
            assert not replies[0]["isError"]
            assert state["bookings"][sat]["seat"] == option["value"]
            matching = [k for k, o in options.items() if o["value"] == state["bookings"][sat]["seat"]]
            assert matching == [key]
            assert probe.labels[key] is (key == true_key)
            truths.append(probe.labels[key])
            assert state["inventory"] == st0["inventory"]
            expected = copy.deepcopy(st0)
            expected["bookings"][sat] = value
            assert rows[-1]["state_hash"] == sha256_canon(expected)
            assert_replay(probe.seed, state, rows)
        assert sum(truths) == 1


@pytest.mark.parametrize("name,value_arg,value", [
    ("book", "booking", {"seat": "12A"}),
    ("book", "booking", {"trip": "TRIP-104233", "delivery": "PARCEL-552190"}),
    ("send_mail", "message", {"place": "Rosa Lind", "gate_code": "GATE-4410"}),
    ("add_note", "note", {"person": "Rosa Lind", "stop": "STOP-2219"}),
    ("add_calendar_entry", "entry", {"person": "Rosa Lind", "birthday": "DATE-0611"}),
])
def test_g15_plan_maps(probe, tmp_path, name, value_arg, value):
    args = {"id": "plan", value_arg: value}
    st = G2State(probe.seed)
    assert st.call(name, args) == (canon(value).decode("utf-8"), True)
    assert canon(st.state[st.tools[name]["collection"]]["plan"]) == canon(value)
    state, replies, rows, _ = run(probe.seed, tmp_path / "plan", [(name, args)])
    assert replies[0]["isError"] is False
    assert state == st.state
    assert_replay(probe.seed, state, rows)


def test_nested_search(probe):
    mail = probe.seed["state"]["mail"]
    key, message = next(iter(mail.items()))
    # A seeded predicate is inside items, never in the message's other fields.
    query = message["items"][0][1]
    expected = {k: v for k, v in mail.items() if any(query in str(item[1]) for item in v["items"])}
    assert query not in message["from"]
    assert key in expected
    assert json.loads(G2State(probe.seed).call("search_mail", {"query": query})[0]) == expected
    assert search({"row": {"needle": [123456, {"child": ["CaseSensitive"]}]}}, "needle") == {}
    assert search({"row": {"needle": [123456, {"child": ["CaseSensitive"]}]}}, "123456") == {}
    assert search({"row": {"needle": [123456, {"child": ["CaseSensitive"]}]}}, "casesensitive") == {}
    assert search({"row": {"a": [0, {"b": ["CaseSensitive"]}]}}, "Sensitive") == {
        "row": {"a": [0, {"b": ["CaseSensitive"]}]}}
    st = G2State(probe.seed)
    for query in ("items", str(message["t_sim"]), message["from"].swapcase()):
        assert st.call("search_mail", {"query": query}) == ("{}", False)


def test_write_map_validation_and_argument_precedence(probe, tmp_path):
    bad_values = [{}, {"items": "x"}, {"t_sim": "x"}, {"from": "x"}, {"": "x"},
                  {"text": ""}, {"text": 1}, {"text": []}, [], "x", None]
    calls, errors = [], []
    for tool in SEED_TOOLS:
        arg = tool["value_arg"]
        if arg is None:
            continue
        for value in bad_values:
            calls.append((tool["name"], {"id": "new", arg: value}))
            errors.append(f"{arg} does not match its schema")
        for args, error in (({"id": "new"}, "arguments must contain exactly the declared keys"),
                            ({"id": "new", arg: {}, "extra": 1},
                             "arguments must contain exactly the declared keys"),
                            ({"id": 1, arg: {}}, "key must be a string")):
            calls.append((tool["name"], args))
            errors.append(error)
    for args, error in (({}, "arguments must contain exactly the declared keys"),
                        ({"query": "", "extra": 1}, "arguments must contain exactly the declared keys"),
                        ({"query": 1}, "query must be a string")):
        calls.append(("search_mail", args))
        errors.append(error)
    calls.extend([("cancel_booking", {"id": "absent"}), ("get_note", {"id": "absent"})])
    errors.extend(["unknown key", "unknown key"])
    state, replies, rows, _ = run(probe.seed, tmp_path / "refusals", calls)
    assert [r["content"][0]["text"] for r in replies] == errors
    assert all(r["isError"] for r in replies)
    assert state == probe.seed["state"]
    assert all(r["state_hash"] == probe.env_state_hash for r in rows)
    assert_replay(probe.seed, state, rows)
    state, replies, rows, _ = run(probe.seed, tmp_path / "duplicate", [
        ("add_note", {"id": "n1", "note": {"text": "x"}}),
        ("add_note", {"id": "n1", "note": {"text": "y"}}),
    ])
    assert replies[-1] == {"content": [{"type": "text", "text": "key already exists"}], "isError": True}
    assert_replay(probe.seed, state, rows)
    # A1 removes the old slot/meal/extra-field restrictions.
    for value in ({"seat": "x"}, {"meal": "x"}, {"when": "x", "extra": "y"}):
        assert check_value(value)
    assert not check_value({1: "x"})


def test_seed_refusals(probe):
    for edit, error in (
        (lambda s: s.update(env_id="other"), "not a G2 seed"),
        (lambda s: s["tools"].remove(next(t for t in s["tools"] if t["name"] == "book")),
         "G2 seed tools differ"),
        (lambda s: s["state"].update(sixth={}), "G2 seed collections differ"),
    ):
        seed = copy.deepcopy(probe.seed)
        edit(seed)
        with pytest.raises(ValueError, match=f"^{error}$"):
            G2State(seed)
    seed = copy.deepcopy(probe.seed)
    seed["state"]["sixth"] = {}
    seed["tools"].append(dict(SEED_TOOLS[0], name="get_sixth", collection="sixth"))
    with pytest.raises(ValueError, match="^G2 seed tools differ$"):
        G2State(seed)


def test_clock_and_read_only_trace(probe, tmp_path):
    calls = [("search_mail", {"query": ""}), ("ask_user", {"question": "?"}),
             ("get_booking", {"id": min(probe.seed["state"]["bookings"])}),
             ("add_note", {"id": "n", "note": {"text": "x"}})]
    for i, tick in enumerate((None, 3)):
        state, _, rows, _ = run(probe.seed, tmp_path / str(i), calls, tick_before=tick)
        assert trace(rows, ACTION_TOOLS) == (True, True, 100 if tick is None else 117)
        assert trace(rows[:-2], ACTION_TOOLS) == (True, False, None)
        assert_replay(probe.seed, state, rows)


def test_noop_booking_and_detached_values(life, probe, tmp_path):
    sat, _ = booking_keys(life)
    value = copy.deepcopy(probe.seed["state"]["bookings"][sat])
    before = canon(probe.seed)
    state, replies, rows, _ = run(probe.seed, tmp_path / "noop", [
        ("book", {"id": sat, "booking": value}),
    ])
    assert replies[0]["isError"] is False
    assert rows[1]["state_changed"] is False
    assert rows[-1]["state_hash"] == probe.env_state_hash
    assert_replay(probe.seed, state, rows)
    st = G2State(probe.seed)
    st.call("book", {"id": sat, "booking": value})
    value["seat"] = "changed after call"
    assert st.state["bookings"][sat] == probe.seed["state"]["bookings"][sat]
    assert canon(probe.seed) == before


def test_stdio_and_hashseed_identity(life, probe, tmp_path):
    cases = golden_cases(life, probe)
    calls = [call for _, steps, _, _ in cases for call in steps]
    expected_texts = [canon(result).decode("utf-8") for _, steps, result, _ in cases for _ in steps]
    first_write = next(i for i, (name, _) in enumerate(calls) if name in ACTION_TOOLS)
    calls.extend([
        ("book", {"id": "bad", "booking": {}}),
        ("cancel_booking", {"id": 1}),
        ("add_note", {"id": "bad", "note": {"items": "x"}}),
        ("send_mail", {"id": "bad", "message": {"to": ""}}),
        ("add_calendar_entry", {"id": "bad", "entry": {"when": 1}}),
        ("ask_user", {"question": "以前の発言は？"}),
    ])
    expected = copy.deepcopy(probe.seed["state"])
    sat, din = booking_keys(life)
    expected["notes"]["n1"] = {"text": "x"}
    expected["bookings"][sat] = next(e["bookings"][sat] for n, _, _, e in golden_cases(life, probe)
                                      if n == "book")
    del expected["bookings"][din]
    expected["mail"]["m1"] = {"to": "Principal", "text": "x"}
    expected["calendar"]["c1"] = {"when": "Friday", "text": "x"}
    logs = []
    for hashseed in ("0", "random"):
        path = tmp_path / hashseed
        path.mkdir()
        seed_path = path / "seed.json"
        seed_path.write_bytes(canon(probe.seed))
        clock = SimClock(path / "clock.json", 100, 17)
        proc = subprocess.Popen(
            [sys.executable, "-m", "bicentennial.sandbox.envserver", "--seed", str(seed_path),
             "--log-dir", str(path), "--clock", str(clock.path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, "PYTHONHASHSEED": hashseed}, cwd=ROOT,
        )

        def exchange(msg, proc=proc):
            proc.stdin.write(canon(msg) + b"\n")
            proc.stdin.flush()
            assert select.select([proc.stdout], [], [], 10)[0], "stdio response timed out"
            raw = proc.stdout.readline()
            reply = json.loads(raw)
            assert canon(reply) + b"\n" == raw
            assert reply["id"] == msg["id"]
            return reply["result"]

        try:
            assert exchange(request("init", "initialize"))["capabilities"] == {"tools": {}}
            advertised = exchange(request("list", "tools/list"))["tools"]
            assert [t["name"] for t in advertised] == NAMES
            for tool, row in zip((*SEED_TOOLS, *SEARCH_TOOLS), advertised[:-1], strict=True):
                props = {tool["key_arg"]: {"type": "string"}}
                if tool["value_arg"] is not None:
                    props[tool["value_arg"]] = STRING_MAP
                assert row == {"name": tool["name"], "description": tool["description"],
                               "inputSchema": {"type": "object", "properties": props,
                                               "required": list(props), "additionalProperties": False}}
            replies = []
            for i, msg in enumerate(tool_requests(calls)):
                if i == first_write:
                    clock.tick()
                replies.append(exchange(msg))
            assert all(not r["isError"] for r in replies[:-6])
            assert [r["content"][0]["text"] for r in replies[:-6]] == expected_texts
            assert all(r["isError"] for r in replies[-6:-1])
            assert replies[-1] == {"content": [{"type": "text", "text": ASK_REPLY}], "isError": False}
            proc.stdin.close()
            assert proc.wait(timeout=10) == 0, proc.stderr.read().decode()
            assert proc.stdout.read() == proc.stderr.read() == b""
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                stream.close()
        rows, raw = load_log(path)
        assert len(rows) == len(calls) + 2
        assert rows[-1]["state_hash"] == sha256_canon(expected)
        assert [r["ok"] for r in rows[1:-1]] == [not r["isError"] for r in replies]
        assert trace(rows, ACTION_TOOLS) == (True, True, 117)
        assert rows[first_write + 1]["t_sim"] == 117
        assert_replay(probe.seed, expected, rows)
        logs.append(raw)
    assert logs[0] == logs[1]


def generated_calls(seed, case):
    unit = ("r11b", str(case))
    length = uniform_int("r11b", unit, 0, "length", 1, 8)
    catalog = {t["name"]: t for t in (*SEED_TOOLS, *SEARCH_TOOLS)}
    calls = []
    for i in range(length):
        name = choice("r11b", unit, 0, f"tool-{i}", NAMES)
        tool = catalog.get(name)
        key_arg = "question" if tool is None else tool["key_arg"]
        value_arg = None if tool is None else tool["value_arg"]
        collection = {} if tool is None else seed["state"][tool["collection"]]
        args = {key_arg: "?" if tool is None else "" if tool["op"] == "search"
                else min(collection) if collection and tool["op"] in ("get", "remove") else f"new-{i}"}
        variants = ["valid", "missing value", "extra arg", "bad value shape", "non-string key"]
        if tool and tool["op"] != "search":
            variants.append("absent key")
            if collection:
                variants.append("existing key")
        if value_arg:
            args[value_arg] = {"plan": f"value-{case}-{i}"}
        variant = choice("r11b", unit, 0, f"variant-{i}", variants)
        if variant == "missing value":
            args.pop(value_arg or key_arg)
        elif variant == "extra arg":
            args["extra"] = "x"
        elif variant == "bad value shape":
            if value_arg:
                args[value_arg] = choice("r11b", unit, 0, f"bad-{i}",
                                         [{}, [], {"items": "x"}, {"x": ""}, {"x": 1}])
            else:
                args[key_arg] = []
        elif variant == "non-string key":
            args[key_arg] = 123
        elif variant == "existing key":
            args[key_arg] = min(collection)
        elif variant == "absent key":
            args[key_arg] = f"absent-{i}"
        calls.append((name, args))
    return calls


def test_keyed_sequence_properties_200_cases(life, probe, tmp_path):
    seen = set()
    for seed_number, seed in enumerate((probe.seed, envseed(life.db, 1).seed)):
        for case in range(200):
            calls = generated_calls(seed, case)
            seen.update(name for name, _ in calls)
            runs = [run(seed, tmp_path / f"{seed_number}-{case}-{n}", calls) for n in range(2)]
            assert runs[0][3] == runs[1][3]
            for state, replies, rows, _ in runs:
                assert len(rows) == len(calls) + 2
                assert [r["ok"] for r in rows[1:-1]] == [not r["isError"] for r in replies]
                for previous, row in zip(rows, rows[1:-1], strict=False):
                    if not row["ok"] or row["tool"] not in ACTION_TOOLS:
                        assert row["state_changed"] is False
                        assert row["state_hash"] == previous["state_hash"]
                assert_replay(seed, state, rows)
    assert seen == set(NAMES)


def test_r11a_tool_schemas_unchanged():
    seed = json.loads((ROOT / "tests/fixtures/env_seed/contracts.json").read_bytes())["contracts"]["env_seed"]
    advertised = _tools(State(seed))
    assert [t["name"] for t in advertised] == ["book_seat", "get_seat", "ask_user"]
    for tool, properties in zip(advertised, (
        {"passenger": {"type": "string"}, "seat": {}},
        {"passenger": {"type": "string"}}, {"question": {"type": "string"}},
    ), strict=True):
        assert tool["inputSchema"] == {"type": "object", "properties": properties,
                                       "required": list(properties), "additionalProperties": False}


def test_import_and_content_boundaries():
    package = Path(tools_g2.__file__).parent
    forbidden = ("bicentennial.world", "bicentennial.genres", "sqlite3", "random", "time", "socket", "subprocess")
    paths = [*package.rglob("*.py"), package.parent / "server.py"]
    for path in paths:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names]
            assert not any(n == f or n.startswith(f + ".") for n in names for f in forbidden), path
            if package in path.parents:
                if isinstance(node, ast.Name):
                    assert "label" not in node.id.lower()
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    assert "label" not in node.name.lower()
                if isinstance(node, ast.arg):
                    assert "label" not in node.arg.lower()
                if isinstance(node, ast.alias):
                    assert "label" not in node.name.lower()
                    assert "label" not in (node.asname or "").lower()
                if isinstance(node, ast.Attribute):
                    assert "label" not in node.attr.lower()
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    assert "label" not in node.value.lower()
                if isinstance(node, ast.ImportFrom):
                    assert ((node.level == 1 and node.module in ("catalog", "state"))
                            or (node.level == 2 and node.module == "state")
                            or (node.level == 0 and node.module in ("types", "json", "bicentennial.canon")))
