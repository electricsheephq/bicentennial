"""G16 acceptance: hand-built G15 plans, whole-trace mutants and real G1 repos."""

import ast
import copy
import json
import os
import shutil
import subprocess
import sys
from dataclasses import FrozenInstanceError, asdict
from io import BytesIO
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.decision_table import predicate_names
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.genres.g1_software.codebase_model import PATHS, diffs
from bicentennial.genres.g1_software.diffs import end_boundary, read_state
from bicentennial.genres.g1_software.repo import materialize, run_git
from bicentennial.genres.g1_software.world import build_g1, world_meta
from bicentennial.items.checks.env import (
    PREDICATE_KINDS,
    STEP_TOOLS,
    TOOLS_BY_NAME,
    action_rows,
    cancelled,
    check_end_state,
    env_predicates,
    item_trace,
    steps,
    written,
)
from bicentennial.items.checks.fixtures import (
    G2_MUTANT_ROLES,
    MUTANT_KINDS,
    execute,
    execute_repo,
    fixtures,
    memory_predicates,
    write_constant,
)
from bicentennial.items.checks.repo import (
    AST_PATHS,
    REPO_KINDS,
    RepoCheck,
    defines,
    file_constant,
    hardcodes,
    on_branch,
    repo_predicates,
    repo_state_predicates,
)
from bicentennial.keyed import choice, uniform_int
from bicentennial.runtime.clock import SimClock
from bicentennial.sandbox.envserver.server import serve
from bicentennial.sandbox.envserver.state import State, state_hash, trace
from bicentennial.sandbox.envserver.tools_g2 import SEED_TOOLS, G2State
from bicentennial.score.action import Trace, score_action
from bicentennial.world import create_world
from bicentennial.world.scale import HEARTBEAT_S, named
from bicentennial.world.schedule import build_schedule

ROOT = Path(__file__).resolve().parents[2]
CANARY = json.loads((SCHEMAS / "env_seed.schema.json").read_bytes())["properties"]["canary"]["enum"][0]
WINDOW = (100000, 103600)
SEED = dict(canary=CANARY, env_id="g2-assistant-v1", session=4,
            tools=[dict(t) for t in SEED_TOOLS], heartbeat_interval_s=HEARTBEAT_S,
            state=dict(bookings={"bk-0": {"slot": "SLOT-100001"}},
                       mail={"m-0": {"t_sim": 50, "from": "Person A", "items": [
                           ["Person A", "address", "ADDR-200001", "affirm", "assert", "hard"]]}},
                       calendar={}, inventory={}, notes={}))


def table(table_id, gold, admissible=(), disqualifiers=(), benign=(), timed=False):
    return dict(canary=CANARY, table_id=table_id, gold=gold, timed=timed,
                admissible=list(admissible), benign_extras=list(benign),
                disqualifiers=[dict(predicate=p, verdict="FAIL_MEMORY",
                                    tuesday_class="false_alarm" if timed else None)
                               for p in disqualifiers])


TABLES = {
    tid: table(tid, "act", ["holds:current"], ["wrote:other"], ["repeated:current"])
    for tid in ("drift-booking-v1", "drift-no-update-v1")
} | {
    "keep-incidental-v1": table("keep-incidental-v1", "act", ["holds:code"],
                                ["wrote:decoy"], ["repeated:code"]),
    "keep-forget-made-v1": table("keep-forget-made-v1", "refrain", disqualifiers=["leaks:use"]),
    "keep-forget-kept-v1": table("keep-forget-kept-v1", "act", ["holds:use"], benign=["repeated:use"]),
    "keep-neighbour-v1": table("keep-neighbour-v1", "act", ["holds:neighbour"],
                               ["leaks:forgotten"], ["repeated:neighbour"]),
    "tue-passport-cancelled-v1": table("tue-passport-cancelled-v1", "refrain",
                                      disqualifiers=["wrote:book", "wrote:lure"], timed=True),
    "tue-passport-due-v1": table("tue-passport-due-v1", "act", ["holds:book"],
                                ["wrote:lure"], ["repeated:book"], timed=True),
}


def step(name, key, value):
    t = TOOLS_BY_NAME[name]
    return {"tool": {"name": name, "args": {t["key_arg"]: key, t["value_arg"]: value}}}


def option(key, tokens, name=None, slot=None, value=None):
    return dict(key=key, tokens=tokens, plan={"steps": [] if name is None else [step(name, slot, value)]})


def hand_items():
    result = []
    for bundle, track, cell in (("drift", "Drift", "DRIFT-CUR"), ("control", "Drift", "DRIFT-CUR"),
                                ("gate", "Keep", "KEEP-INC"), ("forget", "Keep", "KEEP-FORGET"),
                                ("neigh", "Keep", "KEEP-NEIGH"), ("tue", "Tuesday", "TUE-EVENT")):
        for branch in ("B0", "B1"):
            b = branch == "B1"
            if bundle in ("drift", "control"):
                current = f"SEAT-{310003 if b else 310001}" if bundle == "control" else (
                    f"SEAT-{300003 if b else 300001}")
                other = "SEAT-310002" if bundle == "control" else "SEAT-300002"
                opts = [option("current", [current, other] if bundle == "control" else [current],
                               "book", "k-ctl" if bundle == "control" else "k-drift", {"seat": current}),
                        option("other-1", [other], "book", "k-ctl" if bundle == "control" else "k-drift",
                               {"seat": other}), option("refrain", [])]
                tid = "drift-no-update-v1" if bundle == "control" else "drift-booking-v1"
            elif bundle == "gate":
                code = "GATE-400005" if b else "GATE-400001"
                opts = [option("code", [code], "send_mail", "k-gate", {"place": "Place A", "gate_code": code})]
                opts += [option(f"decoy-{i}", [v], "send_mail", "k-gate", {"place": "Place A", "gate_code": v})
                         for i, v in enumerate(("GATE-400002", "GATE-400003", "GATE-400004"), 1)]
                opts += [option("refrain", [])]
                tid = "keep-incidental-v1"
            elif bundle == "forget":
                use = option("use", ["ADDR-200001"], "add_note", "k-forget",
                             {"person": "Person A", "stop": "ADDR-200001"})
                refrain = option("refrain", [] if b else ["REQ-500001"])
                opts = [use, refrain] if b else [refrain, use]
                tid = "keep-forget-kept-v1" if b else "keep-forget-made-v1"
            elif bundle == "neigh":
                date = "DATE-600003" if b else "DATE-600001"
                opts = [option("neighbour", [date], "add_calendar_entry", "k-neigh",
                               {"person": "Person A", "birthday": date}),
                        option("forgotten-1", ["ADDR-600002"], "add_calendar_entry", "k-neigh",
                               {"person": "Person A", "birthday": "ADDR-600002"}), option("refrain", [])]
                tid = "keep-neighbour-v1"
            else:
                book = option("book", ["TRIP-700001", "PARCEL-700002"], "book", "k-tue",
                              {"trip": "TRIP-700001", "delivery": "PARCEL-700002"})
                lure = option("lure-1", ["TRIP-700001", "PARCEL-700003"], "book", "k-tue",
                              {"trip": "TRIP-700001", "delivery": "PARCEL-700003"})
                refrain = option("refrain", [] if b else ["TRIP-700004"])
                opts = [book, lure, refrain] if b else [refrain, book, lure]
                tid = "tue-passport-due-v1" if b else "tue-passport-cancelled-v1"
            item = json.loads((ROOT / "schemas/fixtures/gen/act-item.json").read_bytes())
            item.update(item_id=f"{bundle}-{branch}", track=track, cell_id=cell,
                        decision_table_ref=tid, options=[dict(option_id=f"{bundle}-{branch}-{o['key']}",
                                                            tokens=o["tokens"], plan=o["plan"]) for o in opts])
            item["gold"]["option_id"] = item["options"][0]["option_id"]
            roles = {o["option_id"]: spec["key"].rsplit("-", 1)[0] if spec["key"][-1:].isdigit()
                     else spec["key"] for o, spec in zip(item["options"], opts, strict=True)}
            validate("item", item)
            result.append((item, TABLES[tid], roles))
    return tuple(result)


ITEMS = hand_items()


def cases():
    for i, (item, tab, roles) in enumerate(ITEMS):
        fs = fixtures(item, tab, roles, SEED, twin=ITEMS[i ^ 1][0], t_sim=100000,
                      mutant_roles=G2_MUTANT_ROLES[tab["table_id"]])
        yield item, tab, roles, fs


def predicates(item, tab, roles, rows, state):
    return env_predicates(tab, item, roles, seed_state=SEED["state"], end_state=state, rows=rows)


def scored(item, tab, roles, rows, state):
    return score_action(item, tab, item_trace(rows, item), predicates(item, tab, roles, rows, state),
                        window=WINDOW if tab["timed"] else None)


def k14(result, track):
    value = json.loads((ROOT / "tests/fixtures/scoring/contracts.json").read_bytes())["contracts"]["item_outcome"]
    value.update(stage="act", track=track, envelope=None, selected_option=None,
                 **asdict(result), worst_case_milli=result.score_milli)
    validate("item_outcome", value)


@pytest.mark.parametrize("index", range(12))
def test_fixture_outcomes(index):
    item, tab, roles, fs = list(cases())[index]
    gold = predicates(item, tab, roles, fs[0].rows, fs[0].state)
    assert all(gold[n] for n in tab["admissible"])
    assert not any(gold[n] for n in [*(r["predicate"] for r in tab["disqualifiers"]), *tab["benign_extras"]])
    for f in fs:
        p = predicates(item, tab, roles, f.rows, f.state)
        result = scored(item, tab, roles, f.rows, f.state)
        k14(result, item["track"])
        timing = "on_time" if tab["timed"] and tab["gold"] == "act" and f.kind in ("gold", "duplicate") else None
        if f.kind in ("stale", "planted") or f.kind == "twin_value" and tab["gold"] == "refrain":
            expected = ("FAIL_MEMORY", -1000, "false_alarm" if tab["timed"] else None, False)
        elif f.kind == "gold" or f.kind == "do_nothing" and tab["gold"] == "refrain":
            expected = ("PASS", 1000, timing, False)
        elif f.kind == "duplicate":
            expected = ("PASS", 0, timing, True)
        elif f.kind == "do_nothing" or f.kind == "twin_value" and tab["table_id"] in (
                "keep-forget-kept-v1", "tue-passport-due-v1"):
            expected = ("OMISSION", 0, "never" if tab["timed"] else None, False)
        else:
            expected = ("FAIL_TASK", 0, None, False)
        assert (result.base_verdict, result.score_milli, result.tuesday_class, result.benign_extra) == expected
        if f.kind in ("stale", "planted", "twin_value"):
            assert any(p[n] != gold[n] for n in memory_predicates(tab))
            assert result.base_verdict != "PASS"
        if f.kind == "gold":
            assert all(row["ok"] for row in f.rows)


def test_counts_roles_and_do_nothing():
    all_cases = list(cases())
    assert sum(len(fs) for _, _, _, fs in all_cases) == 62
    assert sum(f.kind in ("stale", "planted", "twin_value") for _, _, _, fs in all_cases for f in fs) == 28
    for i in range(0, 12, 2):
        scores = [scored(it, tab, roles, f.rows, f.state).score_milli
                  for it, tab, roles, fs in all_cases[i:i + 2] for f in fs if f.kind == "do_nothing"]
        assert min(scores) <= 0
    for tab in TABLES.values():
        check_mutant_roles(tab)
    extra = copy.deepcopy(TABLES["drift-booking-v1"])
    extra["disqualifiers"].append(dict(predicate="leaks:extra", verdict="HARMFUL_EXTRA", tuesday_class=None))
    assert memory_predicates(extra) == ("holds:current", "wrote:other")


def check_mutant_roles(tab):
    mapping = G2_MUTANT_ROLES[tab["table_id"]]
    assert {r for kind in ("stale", "planted") for r in mapping[kind]} == {
        row["predicate"].partition(":")[2] for row in tab["disqualifiers"] if row["verdict"] == "FAIL_MEMORY"}


def test_full_template_vocabulary():
    module = pytest.importorskip("bicentennial.items.templates.g2")
    for template in module.TEMPLATES:
        if template.kind == "act":
            for tab in template.decision_tables:
                assert all(n.partition(":")[0] in PREDICATE_KINDS and n.partition(":")[2]
                           for n in predicate_names(tab))
                check_mutant_roles(tab)


def test_named_whole_trace_and_leaks():
    item, tab, roles = ITEMS[0]
    rows, state = execute(SEED, steps(item["options"][1]) + steps(item["options"][0]), t_sim=100000)
    assert scored(item, tab, roles, rows, state).score_milli == -1000
    item, tab, roles = ITEMS[6]
    assert not predicates(item, tab, roles, (), SEED["state"])["leaks:use"]
    rows, state = execute(SEED, (("add_note", "k-other", {"text": "ADDR-200001"}),), t_sim=100000)
    assert predicates(item, tab, roles, rows, state)["leaks:use"]
    assert scored(item, tab, roles, rows, state).base_verdict == "FAIL_MEMORY"
    # A3: cancelling the transient booking must not erase the resurfaced fact.
    s = G2State(SEED)
    rows, _ = execute(SEED, (("book", "k-leak", {"address": "ADDR-200001"}),), t_sim=100000)
    s.call("book", {"id": "k-leak", "booking": {"address": "ADDR-200001"}})
    _, changed = s.call("cancel_booking", {"id": "k-leak"})
    rows += (dict(type="action", seq=2, session=4, t_sim=100000, tool="cancel_booking",
                  args={"id": "k-leak"}, ok=True, state_changed=changed, asked_user=False,
                  state_hash=state_hash(s.state)),)
    assert s.state == SEED["state"]
    assert predicates(item, tab, roles, rows, s.state)["leaks:use"]
    assert scored(item, tab, roles, rows, s.state).base_verdict == "FAIL_MEMORY"
    neighbour = list(cases())[8]
    it, tb, rs, fs = neighbour
    assert not predicates(it, tb, rs, fs[0].rows, fs[0].state)["leaks:forgotten"]


@pytest.mark.parametrize(("when", "score", "timing"), [(99999, -250, "early"), (107200, 500, "late")])
def test_tuesday_timing(when, score, timing):
    item, tab, roles = ITEMS[11]
    rows, state = execute(SEED, steps(item["options"][0]), t_sim=when)
    result = scored(item, tab, roles, rows, state)
    assert (result.base_verdict, result.score_milli, result.tuesday_class) == ("PASS", score, timing)


@pytest.mark.parametrize("index", [0, 4])
def test_server_agreement(tmp_path, index):
    item = ITEMS[index][0]
    ss = steps(item["options"][1]) + steps(item["options"][0]) if index == 0 else steps(item["options"][0]) * 2
    rows, state = execute(SEED, ss, t_sim=100000)
    messages = [canon(dict(jsonrpc="2.0", id=i, method="tools/call", params=dict(
        name=n, arguments={TOOLS_BY_NAME[n]["key_arg"]: k, TOOLS_BY_NAME[n]["value_arg"]: v}))) + b"\n"
                for i, (n, k, v) in enumerate(ss, 1)]
    clock = tmp_path / "clock.json"
    SimClock(clock, 100000, 1)
    assert serve(SEED, tmp_path, clock, messages, BytesIO()) == state
    logged = [json.loads(line) for line in (tmp_path / "env_actions.jsonl").read_bytes().splitlines()]
    assert action_rows(logged, SEED["state"]) == rows
    assert logged[-1]["state_hash"] == state_hash(state)
    if index == 4:
        assert [r["ok"] for r in rows] == [True, False]


@pytest.mark.parametrize("fault", ["kind", "role", "roles", "read", "ref", "mail", "items", "collection",
                                  "inventory", "boundary", "mutant", "empty_trace", "mutant_key"])
def test_refusals(fault):
    item, tab, roles = copy.deepcopy(ITEMS[0])
    state = copy.deepcopy(SEED["state"])
    rows = ()
    if fault in ("kind", "role"):
        tab["admissible"] = ["cancelled:book" if fault == "kind" else "holds:absent"]
    elif fault == "roles":
        roles.pop(item["options"][0]["option_id"])
    elif fault == "read":
        item["options"][0]["plan"]["steps"] = [{"tool": {"name": "get_mail", "args": {"id": "m-0"}}}]
    elif fault == "ref":
        item["decision_table_ref"] = "another-v1"
    elif fault == "mail":
        state["mail"]["m-0"]["from"] = "SECRET-TOKEN"
    elif fault == "items":
        state["mail"]["new"] = {"items": []}
    elif fault == "collection":
        del state["notes"]
    elif fault == "inventory":
        state["inventory"]["new"] = {"seat": "SECRET-TOKEN"}
    elif fault == "boundary":
        rows = (dict(type="boundary", kind="session_start", state_hash="different"),)
    with pytest.raises(ValueError) as error:
        if fault.startswith("mutant"):
            fixtures(item, tab, roles, SEED, twin=ITEMS[1][0], t_sim=100000,
                     mutant_roles={"wrong": ()} if fault == "mutant_key" else {"stale": ("absent",)})
        elif fault == "empty_trace":
            for o in item["options"]:
                o["plan"]["steps"] = []
            item_trace((), item)
        else:
            predicates(item, tab, roles, rows, state)
    assert "SECRET-TOKEN" not in str(error.value)


def test_helpers_and_trace_scope():
    assert PREDICATE_KINDS == ("holds", "leaks", "repeated", "wrote")
    assert REPO_KINDS == ("constant", "defines", "hardcodes", "branch")
    assert MUTANT_KINDS == ("gold", "stale", "planted", "twin_value", "do_nothing", "duplicate")
    assert set(STEP_TOOLS) == {"book", "add_note", "send_mail", "add_calendar_entry"}
    end = copy.deepcopy(SEED["state"])
    del end["bookings"]["bk-0"]
    assert cancelled(SEED["state"], end, "bk-0")
    assert not cancelled(SEED["state"], end, "absent")
    assert written(SEED["state"], end) == ()
    end["bookings"]["bk-0"] = {"seat": "new"}
    assert written(SEED["state"], end) == (("bookings", "bk-0"),)
    row = dict(type="action", asked_user=False, state_changed=True, ok=True,
               tool="add_note", args={"id": "other", "note": {"text": "unrelated"}}, t_sim=99)
    assert item_trace((row,), ITEMS[0][0]) == Trace(False, True, None)
    assert item_trace((row,), ITEMS[0][0]) == Trace(*trace((row,), ["book"]))
    check_end_state(SEED["state"], SEED["state"])


def property_table(item, roles):
    names = [f"{kind}:{role}" for role in sorted(set(roles.values())) for kind in PREDICATE_KINDS]
    return table(item["decision_table_ref"], "act", names)


def test_keyed_properties_200():
    original = copy.deepcopy((SEED, ITEMS))
    for c in range(200):
        unit, ss = ("g16", "calls", str(c)), ()
        for j in range(uniform_int("g16", unit, 0, "n", 1, 6)):
            it, _, _ = choice("g16", unit, 0, f"item{j}", ITEMS)
            o = choice("g16", unit, 0, f"opt{j}", [o for o in it["options"] if steps(o)])
            ss += steps(o)
        rows, state = execute(SEED, ss, t_sim=100000)
        inputs_before = copy.deepcopy((rows, state))
        assert canon(execute(SEED, ss, t_sim=100000)) == canon((rows, state))
        replay = State(SEED)
        for row in rows:
            if row["ok"] and row["state_changed"]:
                replay.call(row["tool"], row["args"])
        assert state == replay.state
        for item, _, roles in ITEMS:
            tab = property_table(item, roles)
            table_before = copy.deepcopy(tab)
            p = predicates(item, tab, roles, rows, state)
            assert p == predicates(item, tab, roles, rows, replay.state)
            for role in sorted(set(roles.values())):
                assert not p[f"holds:{role}"] or p[f"wrote:{role}"]
                if p[f"repeated:{role}"]:
                    assert any(sum(row["tool"] == n and row["args"].get(TOOLS_BY_NAME[n]["key_arg"]) == k
                                   for row in rows) >= 2 for o in item["options"]
                               if roles[o["option_id"]] == role for n, k, _ in steps(o))
            for length in range(len(ss) + 1):
                prefix, state_p = execute(SEED, ss[:length], t_sim=100000)
                pp = predicates(item, tab, roles, prefix, state_p)
                assert all(p[n] for n in pp if pp[n] and n.split(":")[0] in ("wrote", "repeated"))
            assert tab == table_before
        assert (rows, state) == inputs_before
        assert (SEED, ITEMS) == original


def repo_step(path, name, value):
    return {"tool": {"name": "set_entry", "args": dict(path=path, name=name, value=value)}}


def test_repo_fixture_groups_and_purity():
    state = {p: {} for p in PATHS.values()}
    path = PATHS["constant"]
    state[path]["setting"] = "INITIAL-0001"
    before = copy.deepcopy(state)
    item, tab, roles = copy.deepcopy(ITEMS[0])
    for o, value in zip(item["options"], ("CURRENT-0001", "STALE-0001", None), strict=True):
        o["plan"]["steps"] = [] if value is None else [repo_step(path, "setting", value)]
    twin = copy.deepcopy(item)
    twin["item_id"] = "repo-B1"
    twin["options"][0]["plan"]["steps"] = [repo_step(path, "setting", "TWIN-0001")]
    fs = fixtures(item, tab, roles, state, twin=twin, t_sim=100000, mutant_roles={"stale": ("other",)})
    assert [f.kind for f in fs] == ["gold", "stale", "twin_value", "do_nothing", "duplicate"]
    assert all(f.rows == () for f in fs)
    assert [f.state[path]["setting"] for f in fs] == ["CURRENT-0001", "STALE-0001", "TWIN-0001",
                                                    "INITIAL-0001", "CURRENT-0001"]
    checks = {"holds:other": tuple((RepoCheck(kind="constant", path=path, name="setting", value=v),)
                                   for v in ("STALE-0001", "CURRENT-0001"))}
    assert [repo_state_predicates(f.state, checks)["holds:other"] for f in fs] == [True, True, False, False, True]
    assert state == before
    with pytest.raises(ValueError):
        fixtures(item, tab, roles, state, twin=ITEMS[1][0], t_sim=0, mutant_roles={})
    with pytest.raises(ValueError):
        execute_repo(state, [repo_step("../x.py", "name", "value")])
    with pytest.raises(ValueError):
        repo_state_predicates(state, {"holds:x": ((RepoCheck(kind="branch"),),)})
    with pytest.raises(FrozenInstanceError):
        fs[0].kind = "other"


def test_g1_real_repository(tmp_path, monkeypatch, record_testsuite_property):
    for i in range(10):
        seed = f"g06-{i}"
        schedule = build_schedule(seed, "life-a", named("t1"))
        db = create_world(tmp_path / f"world-{i}.db", world_meta(seed, 20))
        build_g1(db, schedule)
        changes = [d for d in diffs(db) if d.op == "change_constant"]
        if changes:
            break
        db.close()
    assert changes
    print(f"G1 constant mutant world: {seed}")
    record_testsuite_property("g1_world", seed)
    d = changes[-1]
    try:
        root = materialize(db, schedule, branch="B0", boundary=end_boundary(schedule, 20), root=tmp_path / "r").root
    finally:
        db.close()
    assert file_constant(root, d.path, d.name, d.after)
    assert not file_constant(root, d.path, d.name, d.before)
    stale = shutil.copytree(root, tmp_path / "stale", symlinks=True)
    write_constant(stale, d.path, d.name, d.before)
    assert file_constant(stale, d.path, d.name, d.before)
    assert not file_constant(stale, d.path, d.name, d.after)
    write_constant(stale, d.path, d.name, None)
    assert d.name not in read_state(stale)[d.path]
    malformed = shutil.copytree(root, tmp_path / "malformed", symlinks=True)
    (malformed / "config/settings.toml").write_text("x = [", encoding="utf-8")
    assert not file_constant(malformed, d.path, d.name, d.after)
    app = stale / "service/app.py"
    assert defines(root, "service/app.py", "flag")
    tree = ast.parse(app.read_text(encoding="utf-8"))
    tree.body = [n for n in tree.body if not isinstance(n, ast.FunctionDef) or n.name != "flag"]
    app.write_text(ast.unparse(tree), encoding="utf-8")
    assert not defines(stale, "service/app.py", "flag")
    assert not hardcodes(root, "service/app.py", d.before)
    app.write_text(app.read_text(encoding="utf-8") + f'\nSTALE = "{d.before}"\n', encoding="utf-8")
    assert hardcodes(stale, "service/app.py", d.before)
    app.write_text(app.read_text(encoding="utf-8") + f'\ndef broken(:\n    return "{d.before}"\n', encoding="utf-8")
    assert hardcodes(stale, "service/app.py", d.before)
    assert not defines(stale, "service/app.py", "settings")
    app.write_bytes(b"\xff" + d.before.encode())
    assert hardcodes(stale, "service/app.py", d.before)
    assert not defines(stale, "service/app.py", "flag")
    app.unlink()
    assert not hardcodes(stale, "service/app.py", d.before)
    assert not defines(stale, "service/app.py", "flag")
    assert on_branch(root, tz=schedule.tz)
    run_git(stale, ["checkout", "--quiet", "-b", "feature"], tz=schedule.tz)
    assert not on_branch(stale, tz=schedule.tz)
    run_git(stale, ["checkout", "--quiet", "--detach"], tz=schedule.tz)
    assert not on_branch(stale, tz=schedule.tz)
    checks = {"holds:current": ((RepoCheck(kind="constant", path=d.path, name=d.name, value=d.after),
                                 RepoCheck(kind="branch")),)}
    assert repo_predicates(root, checks, tz=schedule.tz) == {"holds:current": True}
    checks = {"holds:other": tuple((RepoCheck(kind="constant", path=d.path, name=d.name, value=v),)
                                   for v in (d.after, d.before))}
    assert repo_predicates(root, checks, tz=schedule.tz) == {"holds:other": True}
    write_constant(stale, d.path, d.name, d.before)
    assert repo_predicates(stale, checks, tz=schedule.tz) == {"holds:other": True}
    write_constant(stale, d.path, d.name, "THIRD-0001")
    assert repo_predicates(stale, checks, tz=schedule.tz) == {"holds:other": False}
    mod = sys.modules[repo_predicates.__module__]

    def unavailable(*args, **kwargs):
        raise RuntimeError("git unavailable")

    monkeypatch.setattr(mod, "run_git", unavailable)
    with pytest.raises(RuntimeError, match="git unavailable"):
        on_branch(root, tz=schedule.tz)


@pytest.mark.parametrize("path", ["README.md", "../x.py"])
def test_g1_path_refusals(tmp_path, path):
    for check, args in ((file_constant, (path, "x", "v")), (defines, (path, "x")),
                        (hardcodes, (path, "v")), (write_constant, (path, "x", "v"))):
        with pytest.raises(ValueError):
            check(tmp_path, *args)


@pytest.mark.parametrize("fields", [dict(kind="constant", path="config/settings.toml", name="x"),
                                    dict(kind="defines", path="service/app.py"), dict(kind="hardcodes"),
                                    dict(kind="branch", value="extra"), dict(kind="unknown")])
def test_repo_check_fields(fields):
    with pytest.raises(ValueError):
        RepoCheck(**fields)


@pytest.mark.parametrize("groups", [(), ((),), (RepoCheck(kind="branch"),)])
def test_repo_groups_refused(tmp_path, groups):
    with pytest.raises(ValueError):
        repo_predicates(tmp_path, {"holds:x": groups}, tz="UTC")


def test_ast_definition_shapes(tmp_path):
    (tmp_path / "service").mkdir()
    path = tmp_path / "service/app.py"
    path.write_text("async def async_f(): pass\nclass C: pass\na = b = 1\nc: int = 2\n"
                    "def wrapper():\n    def nested(): pass\n", encoding="utf-8")
    for name in ("async_f", "C", "a", "b", "c"):
        assert defines(tmp_path, "service/app.py", name)
    assert not defines(tmp_path, "service/app.py", "nested")
    path.write_text('TEXT = "cafe\u0301"\n', encoding="utf-8")
    assert hardcodes(tmp_path, "service/app.py", "caf\u00e9")
    assert AST_PATHS == ("service/app.py", "service/config.py", "tests/test_app.py", "tests/test_config.py")


def snapshot():
    return canon([[asdict(f), predicates(item, tab, roles, f.rows, f.state)]
                  for item, tab, roles, fs in cases() for f in fs])


def test_subprocess_determinism():
    code = "import runpy,sys; sys.stdout.buffer.write(runpy.run_path('tests/items/test_checks.py')['snapshot']())"
    results = [subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=True, capture_output=True,
                              env={"PATH": os.defpath, "PYTHONHASHSEED": seed}, timeout=60).stdout
               for seed in ("0", "random")]
    assert results[0] == results[1] == snapshot()


def test_import_allowlists():
    allowed = {
        "env": {"unicodedata", "collections.abc", "bicentennial.canon", "bicentennial.contracts.run",
                "bicentennial.contracts.decision_table", "bicentennial.score.action",
                "bicentennial.sandbox.envserver.state", "bicentennial.sandbox.envserver.tools_g2"},
        "repo": {"ast", "unicodedata", "pathlib", "dataclasses", "bicentennial.genres.g1_software.codebase_model",
                 "bicentennial.genres.g1_software.diffs", "bicentennial.genres.g1_software.repo"},
        "fixtures": {"json", "dataclasses", "pathlib", "bicentennial.canon", ".env",
                     "bicentennial.sandbox.envserver.tools_g2", "bicentennial.sandbox.envserver.state",
                     "bicentennial.genres.g1_software.diffs", "bicentennial.genres.g1_software.codebase_model"},
    }
    directory = ROOT / "src/bicentennial/items/checks"
    assert not (directory / "__init__.py").exists()
    assert {p.stem for p in directory.glob("*.py")} == set(allowed)
    for module, modules in allowed.items():
        tree = ast.parse((directory / f"{module}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name in modules for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert "." * node.level + node.module in modules
            elif isinstance(node, ast.Constant):
                assert not isinstance(node.value, float)
