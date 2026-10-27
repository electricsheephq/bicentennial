"""Compiler and build-time check acceptance; no model calls."""

import ast
import copy
import json
import os
import runpy
import shlex
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.audit import effects as ef
from bicentennial.audit import readback as rb
from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.run import scan_script, validate
from bicentennial.director.compiler import (
    ASSISTANT,
    compile_script,
    hermes_call,
    step_call,
    void_outcome,
    wire_call,
    write_script,
)
from bicentennial.director.compiler import hermes as compiler
from bicentennial.director.compiler.check import (
    Voids,
    expected_probe_env,
    precondition_holds,
)
from bicentennial.director.routes import segment_of
from bicentennial.director.serve import serve, shutdown
from bicentennial.genres.g1_software.diffs import (
    CALLS,
    EMPTY_TREE_HASH,
    PATHS,
    Read,
    read_state,
    render,
    repo_tree_hashes,
    write_reads,
)
from bicentennial.genres.g1_software.world import build_g1, world_meta
from bicentennial.genres.g2_assistant.envseed import (
    env_key,
    env_state_hashes,
    envseed,
    probe_envseed,
)
from bicentennial.genres.g2_assistant.world import build_base
from bicentennial.harness import normalize
from bicentennial.harness.hermes.adapter import HarnessFailed
from bicentennial.harness.hermes.config import layout, worker_env
from bicentennial.items.tags import check_precondition, precondition
from bicentennial.items.templates.g1.common import apply_steps, step
from bicentennial.keyed import uniform_int
from bicentennial.render.session_cut import cut
from bicentennial.render.stream import _canary, seal, stream_bytes, write_branch
from bicentennial.runtime.clock import SimClock
from bicentennial.runtime.faultlite import FaultLite
from bicentennial.score.classes import IDENTITY, RerunRequired, outcome
from bicentennial.world import create_world
from bicentennial.world.scale import TURN_S, named
from bicentennial.world.schedule import build_schedule

ROOT = Path(__file__).resolve().parents[2]
CORE = runpy.run_path(str(ROOT / "tests/director/test_core.py"))


def item(c, k, n, action=False):
    tool = ({"name": "book", "args": {"id": "saturday-booking", "booking": {"seat": "SEAT-4410"}}}
            if n == 1 else {"name": "send_mail", "args": {
                "id": "m1", "message": {"place": "Rosa Lind", "gate_code": "GATE-4410"}}})
    option = dict(option_id=f"option-{n}-gold", tokens=["SEAT-4410"])
    option.update(plan={"steps": [{"tool": tool}]} if action else {}, **({} if action else {
        "envelope": {"type": "entity", "value": "SEAT-4410", "confidence_milli": 1000}}))
    if not action:
        option.pop("plan")
    result = dict(canary=_canary(), item_id=f"item-{n}", stage="act" if action else "remember",
                  track="Wake" if action else "Recall", cell_id="WAKE-PREF" if action else "RECALL-VERB",
                  probe_point=k, prompt=f"Please answer question {n}.", options=[option],
                  gold={"option_id": option["option_id"], "never_observed": False}, gold_spans=[],
                  decision_table_ref="r14-table", precondition=precondition(c, k),
                  memory_tag="env_recoverable", labels=[])
    validate("item", result)
    return result


def fixture(root, genre):
    root.mkdir()
    if genre == "G1":
        schedule = build_schedule("r14-g1", "life-a", named("t1"))
        db = create_world(root / "world.db", world_meta("r14-g1", 20))
        principal = build_g1(db, schedule).principal
        t = db.execute("SELECT min(t_sim) FROM event WHERE kind='commit'").fetchone()[0]
        k = next(p.index for p in schedule.sessions if p.t_start <= t < p.t_end)
        write_reads(db, schedule, [Read(id=f"r14-{i}", session=k, turn=i % 5 + 1, name=n, args=a)
                                   for i, (n, a) in enumerate(CALLS)], principal=principal)
        state = {k: dict(repo_tree_hash=h, env_state_hash=sha256_canon({}))
                 for k, h in repo_tree_hashes(db, schedule).items()}
    else:
        life = build_base(root / "world.db", seed="r14-g2", life="life-a", scale=named("t1"))
        db, schedule, principal = life.db, life.schedule, life.people.principal
        state = {k: dict(repo_tree_hash=EMPTY_TREE_HASH, env_state_hash=h)
                 for k, h in env_state_hashes(db).items()}
    cuts = [cut(db, schedule, branch=b, principal_id=principal, expected_state=state) for b in ("B0", "B1")]
    for c in cuts:
        write_branch(root, c)
    items = [item(cuts[0], 10, 0), item(cuts[0], 20, 1, True), item(cuts[0], 20, 2, True)]
    if genre == "G2":
        items[1]["options"][0]["plan"]["steps"][0]["tool"]["args"]["id"] = env_key(
            schedule.seed, "booking", life.bookings["saturday"])
    db.commit()
    return root, db, schedule, cuts, items


@pytest.fixture(scope="module")
def worlds(tmp_path_factory):
    root = tmp_path_factory.mktemp("compiler-worlds")
    worlds = {g: fixture(root / g, g) for g in ("G1", "G2")}
    yield worlds
    for _, db, _, _, _ in worlds.values():
        db.close()


def compiled(world, **kwargs):
    root, db, schedule, _, items = world
    return compile_script(root, "B0", schedule, db, items=kwargs.pop("items", items), **(dict(step_s=60) | kwargs))


def rewrite(root, branch, rows=None, sessions=None):
    for name, value in (("stream", rows), ("sessions", sessions)):
        if value is not None:
            (root / f"{name}.{branch}.jsonl").write_bytes(stream_bytes(value))
    path = root / f"history.{branch}.json"
    manifest = json.loads(path.read_bytes())
    for name in ("stream", "sessions"):
        manifest[f"{name}_hash"] = sha256((root / f"{name}.{branch}.jsonl").read_bytes()).hexdigest()
    path.write_bytes(canon(manifest))


def test_fixture_compilation(worlds, tmp_path):
    for genre, world in worlds.items():
        result = compiled(world)
        validate("script", result.script)
        assert result.script["genre"] == genre
        assert scan_script(result.script, [r[0] for r in world[1].execute("SELECT id FROM event")], ()) == []
        assert len(result.calls) == (15 if genre == "G1" else 0)
        assert [(p.index, p.checkpoint) for p in result.probes] == [(21, 10), (22, 20), (23, 20)]
        for p in result.probes:
            assert p.sim_t_s == world[2].sessions[p.checkpoint - 1].t_end - len(p.item_ids) * 60
        for session in (s for s in result.script["sessions"] if s["kind"] == "replay"):
            for turn in session["turns"]:
                assert turn["assistant"] == ASSISTANT
                assert all(c["name"] == "terminal" and set(c["args"]) == {"command"} for c in turn["tool_calls"])
        for c in result.calls:
            assert hermes_call(c.call["name"], c.call["args"])["args"]["command"] == shlex.join(
                ["git", *c.call["args"]["argv"]] if c.call["name"] == "git" else ["cat", "--", c.call["args"]["path"]])
        write_script(tmp_path / f"{genre}.json", result)
        assert (tmp_path / f"{genre}.json").read_bytes() == canon(result.script)
        with pytest.raises(FileExistsError):
            write_script(tmp_path / f"{genre}.json", result)
        with pytest.raises(FrozenInstanceError):
            result.probes = ()
        statements = []
        world[1].set_trace_callback(statements.append)
        try:
            assert compiled(world) == result
        finally:
            world[1].set_trace_callback(None)
        assert all(s.startswith("SELECT") for s in statements)


def test_probe_checkpoint_order(worlds):
    result = compiled(worlds["G2"])
    assert [s["index"] for s in result.script["sessions"]] == [*range(1, 11), 21, *range(11, 21), 22, 23]


def test_probe_checkpoint_fault_prefix(worlds):
    result = compiled(worlds["G2"])
    faults = FaultLite.load([{"kind": "kill", "session": 11, "turn": 1},
                             {"kind": "swap", "session": 15, "turn": None}], result.script)
    assert faults.replay_prefix(21) == tuple(range(1, 11))


def test_probe_checkpoint_segments(worlds):
    result = compiled(worlds["G2"])
    faults = FaultLite.load([{"kind": "kill", "session": 11, "turn": 1},
                             {"kind": "swap", "session": 15, "turn": None}], result.script)
    assert segment_of(21, faults) == "seg0"
    assert segment_of(22, faults) == segment_of(23, faults) == "seg1"


def test_audit_turns_follow_checkpoint_order(worlds):
    turns = rb.turns_from_script(compiled(worlds["G2"]).script)
    assert [s for s, n, _ in turns if n == 1] == [*range(1, 11), 21, *range(11, 21), 22, 23]


def test_audit_probe_future_at_checkpoint_only(worlds):
    turns = rb.turns_from_script(compiled(worlds["G2"]).script)
    prompt = next(t["user"] for s, _, t in turns if s == 21)
    at_10 = next(i for i, (s, _, _) in enumerate(turns) if s == 10)
    at_11 = next(i for i, (s, _, _) in enumerate(turns) if s == 11)
    assert prompt in [t["user"] for _, _, t in turns[at_10 + 1:]]
    assert prompt not in [t["user"] for _, _, t in turns[at_11 + 1:]]


def test_hash_seed_determinism(worlds):
    for genre, (root, _, _, _, _) in worlds.items():
        code = '''
import sqlite3, sys
from pathlib import Path
from bicentennial.canon import canon
from bicentennial.director.compiler import compile_script
from bicentennial.world.scale import named
from bicentennial.world.schedule import build_schedule
root = Path(sys.argv[1])
db = sqlite3.connect(f"file:{root / 'world.db'}?mode=ro", uri=True)
schedule = build_schedule(sys.argv[2], "life-a", named("t1"))
sys.stdout.buffer.write(canon(compile_script(root, "B0", schedule, db, step_s=60).script))
'''
        outputs = [subprocess.run([sys.executable, "-c", code, str(root), f"r14-{genre.lower()}"],
                                  env=dict(os.environ, PYTHONHASHSEED=seed), check=True, capture_output=True,
                                  timeout=60).stdout for seed in ("0", "random")]
        assert outputs[0] == outputs[1]


@pytest.mark.parametrize("bad", ["empty", "duplicate", "audience", "turn_key", "payload", "sealed", "unknown", "git"])
def test_stream_refusals(worlds, tmp_path, bad):
    root, db, schedule, cuts, items = worlds["G1"]
    write_branch(tmp_path, cuts[0])
    rows = copy.deepcopy(list(cuts[0].rows))
    text = next(r for r in rows if "text" in r)
    if bad == "empty":
        for r in rows:
            if r["turn_key"] == text["turn_key"] and "text" in r:
                r["text"] = " "
    elif bad == "duplicate":
        other = next(r for r in rows if "text" in r and r["turn_key"] != text["turn_key"])
        # Collapse both groups to one identical text each.
        for r in rows:
            if "text" in r and r["turn_key"] in (text["turn_key"], other["turn_key"]):
                r["text"] = "same" if r is text or r is other else ""
    elif bad == "audience":
        text["audience"] = ["user"]
    elif bad == "turn_key":
        text["turn_key"] = f"{text['session_id']}/t6"
    elif bad == "sealed":
        text["text"] += " " + text["event_id"]
    else:
        tool = next(r for r in rows if r["kind"] == "tool")
        if bad == "payload":
            tool["expected_result_sha256"] = "a" * 64
        elif bad == "unknown":
            tool["tool"]["name"] = "unavailable"
        else:
            tool["tool"] = {"name": "git", "args": {"argv": ["status"]}}
    rewrite(tmp_path, "B0", [seal(r) for r in rows])
    with pytest.raises(ValueError) as error:
        compile_script(tmp_path, "B0", schedule, db, items=items, step_s=60)
    if bad == "sealed":
        assert '$["sessions"]' in str(error.value) and text["event_id"] not in str(error.value)


def test_schedule_and_probe_refusals(worlds):
    world = worlds["G2"]
    root, db, schedule, _, items = world
    bad_schedules = [replace(schedule, life="wrong"), replace(schedule, sessions=(
        replace(schedule.sessions[0], heartbeats=(1,)), *schedule.sessions[1:]))]
    for bad in bad_schedules:
        with pytest.raises(ValueError):
            compile_script(root, "B0", bad, db, step_s=60)
    for count, action in ((7, False), (3, True)):
        many = [item(world[3][0], 20, n + 10, action) for n in range(count)]
        with pytest.raises(ValueError, match="too many"):
            compiled(world, items=many)
    with pytest.raises(ValueError, match="before checkpoint"):
        compiled(world, step_s=4000)
    with pytest.raises(ValueError, match="checkpoint"):
        compiled(world, items=[dict(items[0], probe_point=9)])
    with pytest.raises(ValueError, match="duplicate user"):
        compiled(world, items=[items[0], dict(items[1], prompt=items[0]["prompt"])])
    bad = copy.deepcopy(compiled(world).script)
    bad["sessions"][0]["turns"][0]["tool_calls"] = [{"name": "book", "args": {"fact_id": "hidden"}}]
    with pytest.raises(ValueError, match="forbidden"):
        validate("script", bad)


def test_dialect_and_normalization_keyed_200():
    # Samples are the exact d923a5e terminal / MCP text-only success and error envelopes.
    for n in range(200):
        idx = uniform_int("r14-dialect", (str(n),), 0, "call", 0, len(CALLS) - 1)
        name, args = CALLS[idx]
        script, wire = hermes_call(name, args), wire_call(name, args)
        assert json.loads(wire["arguments"]) == script["args"] and wire["name"] == script["name"]
        text = f"value-{n} é\n\n"
        assert normalize.normalise({"name": name, "args": args}, json.dumps(
            {"output": text, "exit_code": 0, "error": None})) == {
                "stdout" if name == "git" else "content": text.rstrip("\n")}
        call = {"name": "get_mail", "args": {"id": str(n)}}
        assert normalize.normalise(call, json.dumps({"result": text})) == {"text": text, "isError": False}
        assert normalize.normalise(call, json.dumps({"error": text})) == {"text": text, "isError": True}
    for content in ('{"output":"x","exit_code":1}', '{"error":"failed"}', "bad json", "[]",
                    '{"content":"1|a\\n3|b","truncated":true}', '{"output":1,"exit_code":0}', "\ud800"):
        assert "unparsed_sha256" in normalize.normalise({"name": "read_file", "args": {}}, content)
    assert "unparsed_sha256" in normalize.normalise({"name": "unknown"}, '{"result":"text"}')
    for name, args in (("git", {"argv": ["status"]}), ("read_file", {"path": "../secret"}),
                       ("unknown", {}), ("book", []), ("git", {"argv": [1.2]})):
        with pytest.raises(ValueError, match=name):
            hermes_call(name, args)
    for name in compiler.ENV_TOOLS:
        got = step_call({"tool": {"name": name, "args": {"query": ""}}})
        assert got["name"] == "tool_call"
        assert json.loads(got["arguments"])["calls"][0]["name"] == f"mcp__envserver__{name}"
    text = "value'\n$(false)"
    step = {"tool": {"name": "write_file", "args": {"path": "config/settings.toml", "content": text}}}
    tokens = shlex.split(json.loads(step_call(step)["arguments"])["command"])
    assert tokens == ["printf", "%s", text, ">", "config/settings.toml"]
    with pytest.raises(ValueError):
        step_call({"tool": {"name": "write_file", "args": {"path": "README.md", "content": text}}})


@pytest.mark.parametrize("path", PATHS.values())
@pytest.mark.parametrize("entries,name", [
    ({"retry": "old value", "retry limit": "limit value"}, "retry limit"),
    ({"retry": "old value", "retry limit": "limit value"}, "alpha"),
    ({"alpha": "first value", "retry": "old value", "retry limit": "limit value"}, "middle"),
    ({"retry": "old value", "retry limit": "limit value"}, "zulu"),
    ({"retry": "old value"}, "retry limit"),
    ({"retry limit": "limit value"}, "retry"),
    ({}, "retry limit"),
    ({"retry": "old value", "retry limit": "limit value", "retry_limit": "underscore"}, "retry  limit"),
], ids=["replace", "before", "between", "after", "insert-longer-prefix", "insert-prefix", "empty", "spaces"])
@pytest.mark.parametrize("value", ["0042", "  Bob's $(false); [a-z] %s = : !  ",
                                   "".join(chr(c) for c in range(32, 127) if c not in (34, 92))])
def test_step_call_set_entry(tmp_path, path, entries, name, value):
    state = {p: {"other entry": "untouched ' % : value"} for p in PATHS.values()}
    state[path] = entries
    before = render(state)
    for p, data in before.items():
        target = tmp_path / p
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    plan_step = step(path, name, value)
    original = copy.deepcopy(plan_step)
    call = step_call(plan_step)
    assert call == step_call(plan_step)
    assert plan_step == original
    assert set(call) == {"name", "arguments"} and call["name"] == "terminal"
    args = json.loads(call["arguments"])
    assert set(args) == {"command"} and type(args["command"]) is str
    assert call["arguments"] == canon(args).decode()
    assert "\n" not in args["command"]
    subprocess.run(["sh", "-c", args["command"]], cwd=tmp_path, check=True)
    expected = apply_steps(state, [plan_step])
    assert {p: (tmp_path / p).read_bytes() for p in PATHS.values()} == render(expected)
    assert read_state(tmp_path) == expected
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()) == sorted(before)


@pytest.mark.parametrize("args", [
    {"path": "../outside.toml", "name": "retry", "value": "valid value"},
    {"path": "README.md", "name": "retry", "value": "valid value"},
    {"path": "config/flags.toml", "name": "retry", "value": "valid value", "extra": True},
    *({k: v for k, v in {"path": "config/flags.toml", "name": "retry", "value": "valid value"}.items()
       if k != missing} for missing in ("path", "name", "value")),
    *({"path": "config/flags.toml", "name": name, "value": "valid value"}
      for name in ("a", "Retry", "retry:", 'retry"', "retry\n", "retry1", "rétry", "retry_", None, 123)),
    *({"path": "config/flags.toml", "name": "retry", "value": value}
      for value in ("abc", 'bad"value', "bad\\value", "bad\nvalue", "café", None, 123)),
    None, [], "args", 123,
])
def test_step_call_set_entry_invalid(args):
    with pytest.raises(ValueError, match="^invalid plan step$"):
        step_call({"tool": {"name": "set_entry", "args": args}})


@pytest.mark.parametrize("retry", [False, True])
@pytest.mark.parametrize("n_calls", [0, 1])
def test_director_scripted_calls_and_audit(tmp_path, retry, n_calls):
    class Fake(CORE["Fake"]):
        def respond(self, call):
            reply = super().respond(call)
            if call.role == "write_turn":
                assert all(t["function"]["name"] != "terminal" for t in call.body["tools"])
                return replace(reply, tool_calls=(*reply.tool_calls, {
                    "name": "terminal", "arguments": '{"command":"unoffered attempt"}'}))
            return reply

    script = copy.deepcopy(CORE["SCRIPT"])
    script["sessions"] = script["sessions"][:1]
    script["sessions"][0]["turns"] = script["sessions"][0]["turns"][:1]
    turn = script["sessions"][0]["turns"][0]
    turn["tool_calls"] = [hermes_call(*CALLS[0]), hermes_call(*CALLS[-1])]
    fake = Fake()
    fake.n_calls = n_calls
    d = CORE["make"](tmp_path, fake, script=script)
    CORE["start"](d, tmp_path)
    server = serve(d)
    body = CORE["turn_body"](turn["user"], tools=("memory", "terminal"))
    path = "/main/v1/chat/completions"

    def request(body):
        status, _, raw = CORE["send"](server.port, "POST", path, body)
        assert status == 200
        return json.loads(raw)["choices"][0]["message"]

    def result(body, msg):
        return dict(body, messages=body["messages"] + [msg] + [
            {"role": "tool", "tool_call_id": c["id"], "content": (
                '{"success":false}' if c["function"]["name"] == "memory" else "{}")} for c in msg["tool_calls"]])

    try:
        calls = request(body)
        if n_calls:
            body = result(body, calls)
            calls = request(body)
        if retry:
            calls = request(CORE["turn_body"](turn["user"], tools=("memory", "terminal")))
        final = request(result(body, calls))
        assert final["content"] == turn["assistant"]
        assert request(CORE["turn_body"](turn["user"], tools=("memory", "terminal")))["content"] == final["content"]
    finally:
        shutdown(server)
        d.close()
    rows, blobs, _ = rb.load(tmp_path / "ledger", "kit")
    assert [r["served"] for r in rows] == [*(["write_tool_calls"] if n_calls else []), "script_tool_calls", *(
        ["script_tool_calls_retry"] if retry else []), "script", "script_retry"]
    assert not [r for r in rows if r["role"] == "unknown"]
    first_id = 2 + 2 * n_calls + 3 * retry
    assert [c["id"] for c in calls["tool_calls"]] == [CORE["mint_id"]("attempt-s1", i)
                                                      for i in (first_id, first_id + 1)]
    report = rb.audit(rows, blobs, rb.turns_from_script(script), "chat", fmt="kit",
                      model_for=lambda s: "probe-model", suffix=None, write_tools=("memory",), id_needles=[],
                      effects=lambda calls, requests, w: ef.effects(calls, requests, {"memory": "", "user": ""}, w))
    assert rb.failures(report) == [], report["A3"]["failures"]
    assert report["A3"]["non_write_attempts"] == report["A3"]["non_write_blocked"] == 1
    # An id that no reply issued still fails the same audit.
    blobs[rows[-2]["req"]]["messages"].append({"role": "tool", "tool_call_id": "unissued", "content": "{}"})
    report = rb.audit(rows, blobs, rb.turns_from_script(script), "chat", fmt="kit",
                      model_for=lambda s: "probe-model", suffix=None, write_tools=("memory",), id_needles=[],
                      effects=lambda calls, requests, w: ef.effects(calls, requests, {"memory": "", "user": ""}, w))
    assert any(f["kind"] == "unissued_execution" for f in report["A3"]["failures"])


def test_replay_instants(worlds, tmp_path):
    world = worlds["G2"]
    result = compiled(world, items=[])
    d = CORE["make"](tmp_path, CORE["Fake"](), script=result.script)
    d.clock = SimClock(tmp_path / "replay-clock.json", world[2].sessions[0].turn_t[0] - TURN_S, TURN_S)
    try:
        for plan, session in zip(world[2].sessions, result.script["sessions"], strict=True):
            d.start_session(plan.index, plan.turn_t[0] - TURN_S, CORE["LOCK"], f"replay-{plan.index}", tmp_path / "ledger")
            instants = []
            for turn in session["turns"]:
                status, _, _ = CORE["post"](d, "/main/v1/chat/completions", CORE["turn_body"](turn["user"], tools=("terminal",)))
                assert status == 200
                instants.append(d.clock.sim_t_s)
            assert tuple(instants) == plan.turn_t
    finally:
        d.close()


def test_absolute_worker_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = layout(Path("scratch/run"), Path("scratch"))
    env = worker_env(paths, 4321, Path("scratch/run/clock.json"), None)
    assert paths["root"] == (tmp_path / "scratch/run").resolve()
    for key in ("HOME", "HERMES_HOME", "TMPDIR", "BICENTENNIAL_CLOCK_FILE"):
        assert Path(env[key]).is_absolute() and Path(env[key]).is_relative_to(paths["root"])


def test_relative_scratch_adapter(tmp_path, monkeypatch):
    helper = runpy.run_path(str(ROOT / "tests/harness/test_hermes_adapter.py"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(helper["adapter"], "DRAIN_QUIET_S", 0.05)
    scratch = Path("relative-scratch")
    scratch.mkdir()
    checker = ("import os, runpy; from pathlib import Path; "
               "clock=Path(os.environ['BICENTENNIAL_CLOCK_FILE']); "
               "assert clock.is_absolute() and clock.is_file(); "
               "runpy.run_path(__import__('sys').argv[1], run_name='__main__')")
    a = helper["make"](scratch, "run", faults=[], worker_argv=[sys.executable, "-c", checker, str(helper["FAKE"])])
    try:
        try:
            result = helper["session"](a, 1)
        except HarnessFailed:
            log = (a.paths["logs"] / "worker-1.stderr").read_text()
            if "taskpolicy: setpriority(): Operation not permitted" in log:
                pytest.skip("sandbox denies taskpolicy setpriority before the stub worker starts")
            raise
        assert result.turns_ok == result.finals_matched == 5
    finally:
        a.close()


def test_import_boundaries():
    allowed = {"json", "re", "shlex", "dataclasses", "bicentennial.canon", "bicentennial.contracts.run",
               "bicentennial.render.stream", "bicentennial.genres.g1_software.diffs",
               "bicentennial.sandbox.envserver.tools_g2"}
    for module, imports in ((compiler, allowed), (normalize, {
            "json", "re", "hashlib", "bicentennial.genres.g1_software.diffs"})):
        for node in ast.walk(ast.parse(Path(module.__file__).read_bytes())):
            names = ([a.name for a in node.names] if isinstance(node, ast.Import) else
                     [node.module] if isinstance(node, ast.ImportFrom) else [])
            assert set(names) <= imports


def test_preconditions_and_voids(worlds):
    for genre, world in worlds.items():
        _, db, _, cuts, items = world
        v = Voids()
        assert v.summary() == {"checked": 0, "voided": 0, "void_milli": None}
        for arm in ("one", "two"):
            for i in items:
                repo = cuts[0].sessions[i["probe_point"] - 1]["expected_state"]["repo_tree_hash"]
                env = expected_probe_env(db, genre, 21, i["probe_point"])
                assert precondition_holds(i, repo_tree_hash=repo, env_state_hash=env, probe_env_state_hash=env)
                holds = precondition_holds(i, repo_tree_hash="0" * 64 if arm == "one" and i["probe_point"] == 20 else repo,
                                          env_state_hash=env, probe_env_state_hash=env)
                v.record(i["item_id"], arm, holds, call={"name": "precondition", "args": {"checkpoint": i["probe_point"]}},
                         expected_sha256=sha256_canon({"repo": repo, "env": env}),
                         got_sha256=sha256_canon({"repo": "0" * 64 if arm == "one" and i["probe_point"] == 20 else repo,
                                                 "env": env}))
        assert v.voided() == {i["item_id"] for i in items if i["probe_point"] == 20}
        assert v.summary() == {"checked": 3, "voided": 2, "void_milli": round(Fraction(2, 3) * 1000)}
        assert len(v.diagnostics) == 6 and all(r["call"] and r["expected_sha256"] and r["got_sha256"]
                                             for r in v.diagnostics)
        with pytest.raises(ValueError, match="duplicate"):
            v.record(items[0]["item_id"], "one", True)
        for text in (None, "{}", "not json", "[]", '{"after_session":1}'):
            with pytest.raises(ValueError):
                precondition_holds(dict(items[0], precondition=text), repo_tree_hash=repo,
                                   env_state_hash=env, probe_env_state_hash=env)
        with pytest.raises(ValueError, match="checkpoint"):
            precondition_holds(dict(items[0], probe_point=20), repo_tree_hash=repo,
                               env_state_hash=env, probe_env_state_hash=env)


def test_issue97_probe_state_not_session_start(tmp_path):
    for n in range(10):
        seed = f"r14-g2-{n}"
        life = build_base(tmp_path / f"{seed}.db", seed=seed, life="life-a", scale=named("t1"))
        try:
            for k in (10, 20):
                before, after = envseed(life.db, k), probe_envseed(life.db, 21, k)
                if before.env_state_hash == after.env_state_hash:
                    continue
                text = canon(dict(after_session=k, repo_tree_hash=EMPTY_TREE_HASH,
                                  env_state_hash=before.env_state_hash)).decode()
                i = {"probe_point": k, "precondition": text}
                assert not check_precondition(text, repo_tree_hash=EMPTY_TREE_HASH, env_state_hash=after.env_state_hash)
                assert precondition_holds(i, repo_tree_hash=EMPTY_TREE_HASH, env_state_hash=after.env_state_hash,
                                          probe_env_state_hash=expected_probe_env(life.db, "G2", 21, k))
                v = Voids()
                v.record("regression97", "planted-wrong-seed", precondition_holds(
                    i, repo_tree_hash=EMPTY_TREE_HASH, env_state_hash="0" * 64,
                    probe_env_state_hash=after.env_state_hash))
                assert v.voided() == {"regression97"}
                print(f"#97 regression: seed={seed}, checkpoint={k}")
                return
        finally:
            life.db.close()
    pytest.fail("no differing probe state found in the dispatched seed range")


def test_voids_preserve_assigned_coverage():
    from bicentennial.score.aggregate import compare

    fixture = json.loads((ROOT / "tests/fixtures/aggregate/two_lives.json").read_bytes())
    items, bundles = fixture["items"], fixture["bundles"]
    b = bundles[0]
    cause = void_outcome({"item_id": b["items"][0]})
    assert cause == {"item_id": b["items"][0], "cause": "INFRA_FAILURE"}
    for i in (i for i in items if i["item_id"] in b["items"]):
        identity = {k: i[k] for k in IDENTITY}
        for reruns in (0, 1):
            with pytest.raises(RerunRequired):
                outcome(identity, None, cause=cause["cause"], infra_reruns=reruns)
        i.update(outcome(identity, None, cause=cause["cause"], infra_reruns=2))
    b.update(score_milli=None, failure_class="BLOCKED")
    report = compare({"one": (items, bundles), "two": (items, bundles)})
    for arm in report.values():
        assert arm["coverage"]["assigned"] == len(bundles)
        assert arm["coverage"]["blocked"] == fixture["expected"]["coverage"]["blocked"] + 1


# R14b: fixture life directories and end-to-end worker checks.
def life_directory(world, target):
    import sqlite3

    root, db, schedule, _, items = world
    target.mkdir()
    (target / "life.json").write_bytes(canon(dict(canary=_canary(), life=schedule.life,
                                                 seed=schedule.seed, scale="t1")))
    for branch in ("B0", "B1"):
        with sqlite3.connect(target / f"world.{branch}.db") as out:
            db.backup(out)
        for stem, suffix in (("stream", "jsonl"), ("sessions", "jsonl"), ("history", "json")):
            (target / f"{stem}.{branch}.{suffix}").write_bytes((root / f"{stem}.{branch}.{suffix}").read_bytes())
        (target / f"items.{branch}.json").write_bytes(canon(items))
    return target


def check_life(life, scratch, **kwargs):
    helper = runpy.run_path(str(ROOT / "tests/harness/test_hermes_adapter.py"))
    from bicentennial.director.compiler.check import check_compile

    return check_compile(life, entry=helper["ENTRY"], route_table=helper["ROUTES"], harness_pin=None,
                         checkout=None, scratch=scratch,
                         worker_argv=[sys.executable, str(Path(__file__).with_name("fake_tool_worker.py"))], **kwargs)


@pytest.fixture
def fast_check(monkeypatch):
    from bicentennial.harness.hermes import adapter

    monkeypatch.setattr(adapter, "DRAIN_QUIET_S", 0.01)


def sandbox_check(life, scratch):
    try:
        report = check_life(life, scratch)
    except PermissionError as error:
        pytest.skip(f"sandbox denies process or loopback operation: {error}")
    startup = [m for b in report["branches"].values() for m in b["mismatches"]
               if m["kind"] == "harness_failed:worker_start"]
    if startup:
        logs = "\n".join(p.read_text() for p in scratch.glob("*/logs/*.stderr"))
        if "taskpolicy: setpriority(): Operation not permitted" in logs:
            pytest.skip("sandbox denies taskpolicy setpriority before the tool worker starts")
    return report


@pytest.mark.parametrize("genre", ["G1", "G2"])
def test_check_compile_fake(worlds, tmp_path, genre, fast_check):
    life = life_directory(worlds[genre], tmp_path / "life")
    report = sandbox_check(life, tmp_path / "runs")
    assert report["ok"], report
    for branch in report["branches"].values():
        assert branch == dict(sessions=1 if genre == "G1" else 2, calls=15 if genre == "G1" else 2, mismatches=[])
    if genre == "G2":
        rows = [json.loads(line) for p in (tmp_path / "runs").glob("*/env/*/life-*/env_actions.jsonl")
                for line in p.read_bytes().splitlines()]
        actions = [r for r in rows if r["type"] == "action"]
        assert len(actions) == 4 and all(r["ok"] and r["state_changed"] for r in actions)
        assert {r["t_sim"] for r in actions} == {worlds[genre][2].sessions[19].t_end}


def cli_args(life, scratch, tmp_path):
    from bicentennial.systems.registry import REGISTRY

    helper = runpy.run_path(str(ROOT / "tests/harness/test_hermes_adapter.py"))
    (tmp_path / "pin.json").write_bytes(canon(helper["ENTRY"]["artifact"]))
    (tmp_path / "routes.json").write_bytes(canon(helper["ROUTES"]))
    return ["check-compile", str(life), "--checkout", str(tmp_path / "absent-checkout"),
            "--harness-pin", str(tmp_path / "pin.json"), "--route-table", str(tmp_path / "routes.json"),
            "--entry", str(REGISTRY / "hermes-native.toml"), "--scratch", str(scratch)]


def test_planted_mismatch_cli(worlds, tmp_path, fast_check, monkeypatch, capfd):
    from bicentennial.director.compiler import __main__ as cli

    life = life_directory(worlds["G1"], tmp_path / "life")
    path = life / "stream.B0.jsonl"
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    row = next(r for r in rows if r["kind"] == "tool")
    row["payload"] = dict(content="planted") if row["tool"]["name"] == "read_file" else dict(stdout="planted")
    row["expected_result_sha256"] = sha256_canon(row["payload"])
    rewrite(life, "B0", [seal(r) for r in rows])
    report = sandbox_check(life, tmp_path / "runs")
    mismatches = report["branches"]["B0"]["mismatches"]
    assert not report["ok"] and len(mismatches) == 1
    mismatch = mismatches[0]
    assert mismatch["kind"] == "result" and mismatch["call"] == row["tool"]
    assert mismatch["expected_sha256"] == row["expected_result_sha256"]
    assert mismatch["got_sha256"] != mismatch["expected_sha256"]
    monkeypatch.setattr(cli, "check_compile", lambda *a, **kw: report)
    assert cli.main(cli_args(life, tmp_path / "cli", tmp_path)) == 1
    assert json.loads(capfd.readouterr().out) == report


def test_vacuous_branch_cli(worlds, tmp_path, fast_check, monkeypatch, capfd):
    from bicentennial.director.compiler import __main__ as cli

    life = life_directory(worlds["G1"], tmp_path / "life")
    path = life / "stream.B0.jsonl"
    rewrite(life, "B0", [json.loads(line) for line in path.read_bytes().splitlines()
                        if json.loads(line)["kind"] != "tool"])
    report = sandbox_check(life, tmp_path / "runs")
    assert not report["ok"] and report["branches"]["B0"] == dict(sessions=0, calls=0, mismatches=[])
    monkeypatch.setattr(cli, "check_compile", lambda *a, **kw: report)
    assert cli.main(cli_args(life, tmp_path / "cli", tmp_path)) == 1
    capfd.readouterr()


def test_cli_bad_input_and_pin(tmp_path, monkeypatch):
    from bicentennial.director.compiler import __main__ as cli
    from bicentennial.harness.hermes.adapter import PinMismatch

    args = cli_args(tmp_path / "missing", tmp_path / "runs", tmp_path)
    assert cli.main(args) == 2

    def mismatch(*args, **kwargs):
        raise PinMismatch("fixture")

    monkeypatch.setattr(cli, "check_compile", mismatch)
    assert cli.main(args) == 3


def test_cli_refused_system(tmp_path, monkeypatch):
    from bicentennial.director.compiler import __main__ as cli
    from bicentennial.systems.registry import SystemRefused

    def refused(*args, **kwargs):
        raise SystemRefused("fixture")

    monkeypatch.setattr(cli, "check_compile", refused)
    assert cli.main(cli_args(tmp_path / "missing", tmp_path / "runs", tmp_path)) == 3


def test_envwire_recovery(worlds, tmp_path):
    from bicentennial.harness.hermes.envwire import EnvWiring, derived_seed
    from bicentennial.sandbox.envserver.state import state_hash
    from bicentennial.sandbox.envserver.tools_g2 import G2State

    seed = probe_envseed(worlds["G2"][1], 22, 20).seed
    clock = SimClock(tmp_path / "clock.json", worlds["G2"][2].sessions[19].t_end, 60)
    wiring = EnvWiring(tmp_path, {22: seed}, clock.path)
    first = wiring(22, "session_start")
    path = tmp_path / "env/22/life-1"
    assert json.loads((path / "seed.json").read_bytes()) == seed
    state = G2State(seed)
    tool = worlds["G2"][4][1]["options"][0]["plan"]["steps"][0]["tool"]
    _, changed = state.call(tool["name"], tool["args"])
    row = dict(type="action", ok=True, state_changed=changed, tool=tool["name"], args=tool["args"],
               state_hash=state_hash(state.state))
    (path / "env_actions.jsonl").write_bytes(canon(row) + b"\n")  # killed before a session_end boundary
    second = wiring(22, "kill")
    resumed = json.loads((tmp_path / "env/22/life-2/seed.json").read_bytes())
    assert resumed == dict(seed, state=state.state) == derived_seed(seed, [path])
    assert first["env"]["PYTHONHASHSEED"] == "0" and "--clock" in second["args"]
    assert wiring.records(22) == [row]
    assert derived_seed(seed, [tmp_path / "env/22/life-2"]) == seed
    row["state_hash"] = "0" * 64
    (path / "env_actions.jsonl").write_bytes(canon(row) + b"\n")
    with pytest.raises(ValueError, match="resume refused"):
        wiring(22, "restart")
    assert not (tmp_path / "env/22/life-3").exists()


@pytest.mark.parametrize("mode", ["ok", "mismatch", "missing", "retry", "first-result", "stream"])
def test_check_comparison_receipts(tmp_path, mode):
    from types import SimpleNamespace

    from bicentennial.director.compiler.check import _compare
    from bicentennial.director.compiler.hermes import CheckCall
    from bicentennial.ledger import BlobStore, Guard

    root = tmp_path / "check"
    store = BlobStore(root / "ledger/blobs", Guard([]))
    call = {"name": "read_file", "args": {"path": "README.md"}}
    expected = {"content": "expected"}
    issued = dict(tool_calls=[dict(id="issued", function=dict(name="terminal", arguments='{"command":"cat"}'))])
    response = {"choices": [{"message": issued}]}
    if mode == "stream":
        response = {"sse": [{"choices": [{"delta": issued}]}]}
    rows = [dict(seq=1, cursor=dict(session=1, turn=1), served="script_tool_calls", type="request",
                 req=store.put({"messages": []}), resp=store.put(response))]
    if mode == "retry":
        rows.append(dict(rows[0], seq=2, served="script_tool_calls_retry"))
    if mode != "missing":
        text = "wrong" if mode in ("mismatch", "first-result") else "expected\n"
        req = dict(messages=[dict(role="tool", tool_call_id="issued", content=json.dumps(
            dict(output=text, exit_code=0)))])
        rows.append(dict(seq=3, cursor=dict(session=1, turn=1), type="request", req=store.put(req)))
        # A later repetition must never overwrite the first result.
        if mode == "first-result":
            rows.append(dict(seq=4, cursor=dict(session=1, turn=2), type="request", req=store.put(dict(messages=[
                dict(role="tool", tool_call_id="issued", content='{"output":"expected","exit_code":0}')]))))
    fake = SimpleNamespace(records=lambda: rows, paths=dict(root=root))
    mismatch = _compare(fake, [CheckCall("B0", 1, 1, 0, call, expected)])
    if mode in ("ok", "stream"):
        assert mismatch == []
    else:
        assert len(mismatch) == 1
        assert mismatch[0]["kind"] == {"missing": "no_result", "retry": "retried"}.get(mode, "result")
        assert mismatch[0]["call"] == call and mismatch[0]["expected_sha256"] == sha256_canon(expected)


def test_adapter_env_hook_on_each_spawn(worlds, tmp_path, monkeypatch):
    from types import SimpleNamespace

    from bicentennial.harness.hermes import adapter, config
    from bicentennial.harness.hermes.envwire import EnvWiring

    root = tmp_path / "run"
    paths = config.layout(root, tmp_path)
    seed = probe_envseed(worlds["G2"][1], 22, 20).seed
    wiring = EnvWiring(root, {22: seed}, root / "clock.json")
    reasons = []

    def hook(session, reason):
        reasons.append((session, reason))
        return wiring(session, reason)

    class Worker:
        def __init__(self, *args):
            self.proc = SimpleNamespace(pid=123)

        def call(self, **op):
            return dict(ok=True, history=0, session_id="session")

    monkeypatch.setattr(adapter, "_Worker", Worker)
    monkeypatch.setattr(adapter, "assert_niced", lambda pid: None)
    a = object.__new__(adapter.HermesAdapter)
    a.before_spawn, a._wiped, a._session_index, a._alias = None, False, 22, "bicentennial-main"
    a.paths, a.server, a.clock = paths, SimpleNamespace(port=4321), SimpleNamespace(path=root / "clock.json")
    a.env_server, a.toolsets, a.memory, a.window = hook, config.HERMES_TOOLSETS, False, None
    a.plugin, a.plugin_config, a.checkout = None, {}, None
    a.argv, a.egress, a.pids = [], None, []
    timings = dict(spawn=[], open=[])
    for reason, sid in (("session_start", None), ("kill", "session")):
        assert a._spawn_open(reason, sid, timings) == ("session", 0, False)
        cfg = json.loads((paths["hermes_home"] / "config.yaml").read_bytes())
        assert cfg["platform_toolsets"]["acp"] == ["todo", "terminal", "envserver"]
        assert cfg["mcp_servers"]["envserver"]["args"][-1] == str(root / "clock.json")
    assert reasons == [(22, "session_start"), (22, "kill")]
    assert [p.name for p in sorted((root / "env/22").iterdir())] == ["life-1", "life-2"]


@pytest.mark.parametrize("phase", ["start", "close"])
def test_check_compile_records_harness_failure_and_continues(worlds, tmp_path, monkeypatch, phase):
    from bicentennial.harness.hermes import adapter

    starts = []

    def failed(*args, **kwargs):
        starts.append(kwargs["branch"])
        if phase == "start":
            raise HarnessFailed("turn_timeout")

        class ClosingFailure:
            paths = dict(root=kwargs["root"])

            def run_session(self, *args, **kwargs):
                pass

            def records(self):
                return []

            def close(self):
                raise HarnessFailed("turn_timeout")

        return ClosingFailure()

    monkeypatch.setattr(adapter, "HermesAdapter", failed)
    report = check_life(life_directory(worlds["G2"], tmp_path / "life"), tmp_path / "runs")
    assert not report["ok"] and starts == ["B0", "B0", "B1", "B1"]
    assert all(sum(m["kind"] == "harness_failed:turn_timeout" for m in branch["mismatches"]) == 2
               for branch in report["branches"].values())
