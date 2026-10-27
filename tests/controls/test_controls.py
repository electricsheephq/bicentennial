"""S07 cached API controls: independent hand fixture and integrity acceptance."""

import ast
import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.api.contract import answer
from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.items import reader_view
from bicentennial.contracts.run import SCHEMAS, validate
from bicentennial.controls import cache, full_history, no_memory, oracle_evidence
from bicentennial.controls.common import ControlInput, check
from bicentennial.keyed import uniform_int
from bicentennial.sandbox.envserver.state import State, trace
from bicentennial.score import aggregate
from bicentennial.score.classes import score_act
from bicentennial.score.qa import score_qa
from bicentennial.world.tokens import estimate_tokens

ROOT = Path(__file__).resolve().parents[2]
CANARY = json.loads((SCHEMAS / "pack.schema.json").read_bytes())["properties"]["canary"]["enum"][0]
PIN = "a" * 64
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



def fixture_input(only=None):
    items, keys, tables = fixtures()
    pairs = (("qa-fork", ("qf0", "qf1"), "fork"), ("act-fork", ("af0", "af1"), "fork"),
             ("act-lure", ("al0", "al1"), "lure"), ("qa-forget", ("kf0", "kf1"), "trigger"))
    wanted = set(items) if only is None else set(only)
    pack = dict(canary=CANARY, pack_id="pack-s07", tier="T0", genre="G2", seeds=[1],
                lives=["life-s04"], items=[items[i] for i in sorted(wanted)],
                bundles=[dict(canary=CANARY, bundle_id=bid, cell_id=items[pair[0]]["cell_id"],
                              twin_type=twin, items=list(pair), decisive_fact_id=f"fact-{bid}")
                         for bid, pair, twin in pairs if set(pair) <= wanted],
                qa_order=sorted(i for i in wanted if items[i]["stage"] != "act"),
                controls={n: "not run in v0.1" for n in
                          ("no_memory", "oracle_evidence", "full_history", "naive_rag")}, hashes={})
    streams = {"B0": ["e-old", "e-new0", "e-task", "e-gate", "e-request"],
               "B1": ["e-old", "e-new1", "e-task", "e-cancel", "e-gate"]}
    inp = ControlInput(pack, tuple(keys[i] for i in sorted(wanted)),
                       {"life-s04": {b: [copy(EVENTS[e]) for e in streams[b]] for b in sorted(streams)}},
                       {i: 1000 for i in sorted(wanted)}, "0" * 64)

    def score(item, result):
        if result.kind == "qa":
            return score_qa(item, result.envelope,
                            evidence_texts=[EVENTS[e]["text"] for e in item["gold_spans"]])
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
        return score_act(item, table, trace(rows, ("book_seat", "add_reminder")),
                         {n: predicates[n] for n in names},
                         commitment={"window_open_t": 100, "window_close_t": 200}
                         if item["track"] == "Tuesday" else None)

    return inp, score


def computed(*, only=None, window=16384):
    inp, score = fixture_input(only)
    return cache.compute(inp, score=score, harness_pin=PIN, window=window)


def test_hand_table_and_diagnostics():
    entry = computed()
    inp, _ = fixture_input()
    expected = dict(qf0=0, qf1=0, af0=0, af1=0, al0=0, al1=1000, kf0=0, kf1=0, na=1000)
    order = [("act", "Drift"), ("act", "Tuesday"), ("remember", "Keep"),
             ("remember", "Recall"), ("remember", "Wake")]
    for name, arm in entry["arms"].items():
        assert {i["item_id"]: i["score_milli"] for i in arm["items"]} == (
            expected if name == "no_memory" else dict.fromkeys(expected, 1000))
        assert [(r["stage"], r["track"]) for r in arm["aggregates"]] == order
        assert [r["score_milli"] for r in arm["aggregates"]] == (
            [0, 0, 0, 1000, 0] if name == "no_memory" else [1000] * 5)
        assert all(i["stage_attribution"] is None for i in arm["items"])
        assert all(r["stage_attribution"] is None for r in arm["reports"])
        assert arm["singleton_lives"] == {"na": "life-s04"}
        assert [i["item_id"] for i in arm["items"]] == sorted(expected)
        assert [b["bundle_id"] for b in arm["bundles"]] == sorted(b["bundle_id"] for b in inp.pack["bundles"])
    for report in entry["arms"]["no_memory"]["reports"]:
        item = next(i for i in inp.pack["items"] if i["item_id"] == report["item_id"])
        assert report["selected_option"] is None or not next(
            o["tokens"] for o in reader_view(item)["options"] if o["option_id"] == report["selected_option"])
        assert report["in_context"] is not True
    oracle = next(r for r in entry["arms"]["oracle_evidence"]["reports"] if r["item_id"] == "kf0")
    history = next(r for r in entry["arms"]["full_history"]["reports"] if r["item_id"] == "kf0")
    assert oracle["forget"] == dict(in_context=False, in_store=None, held=None)
    assert history["forget"]["in_context"] is True
    assert history["competing_present"] == ["kf0-use"]
    assert entry["broken"] == [dict(stage="remember", track="Recall")]
    assert computed(only=set(expected) - {"na"})["broken"] == []


def test_window_boundary_and_history_order():
    inp, _ = fixture_input()
    for branch, expected in (("B0", 41), ("B1", 39)):
        adapter = full_history.FullHistory()
        for event in inp.events["life-s04"][branch]:
            adapter.ingest(event)
        assert adapter.history(1000) == inp.events["life-s04"][branch]
        assert adapter.history(9) == []
        assert estimate_tokens(answer(adapter.history(1000))["output"]) == expected
        assert full_history.fits(adapter, 1000, expected)
        assert not full_history.fits(adapter, 1000, expected - 1)
    assert computed(window=41)["arms"]["full_history"]["fits"] == dict(run=9, of=9)
    small = computed(window=40)
    diagnostic = small["arms"]["full_history"]
    assert diagnostic["fits"] == dict(run=0, of=9)
    assert diagnostic["items"] == diagnostic["reports"] == diagnostic["bundles"] == diagnostic["aggregates"] == []
    assert diagnostic["singleton_lives"] == {}
    assert cache.card_controls(small)["full_history"] is None


def test_projections():
    entry = computed()
    assert cache.card_controls(entry) == dict(no_memory_floor=None, oracle_evidence=None,
                                            full_history=None, naive_rag="not run in v0.1")
    single = computed(only=("af0", "af1"))
    controls = cache.card_controls(single)
    assert controls == dict(no_memory_floor=0, oracle_evidence=1000, full_history=1000,
                            naive_rag="not run in v0.1")
    card = json.loads((ROOT / "tests/fixtures/scoring/contracts.json").read_bytes())["contracts"]["card_ring0"]
    card["controls"] = dict(controls, wiped_store="FAIL")
    validate("card_ring0", card)
    pack = copy(fixture_input()[0].pack)
    pack["controls"] = cache.pack_controls(entry)
    validate("pack", pack)
    assert pack["controls"] == {
        "no_memory": {"aggregates": entry["arms"]["no_memory"]["aggregates"]},
        "oracle_evidence": {"aggregates": entry["arms"]["oracle_evidence"]["aggregates"]},
        "full_history": {k: entry["arms"]["full_history"][k] for k in ("aggregates", "fits")},
        "naive_rag": "not run in v0.1"}
    assert cache.display_rows(entry, [dict(stage="act", track="Drift", score_milli=500),
        dict(stage="remember", track="Recall", score_milli=1000),
        dict(stage="survive", track="Faults", score_milli=0)]) == [
            dict(stage="act", track="Drift", normalised_milli=500),
            dict(stage="remember", track="Recall", normalised_milli="n/a"),
            dict(stage="survive", track="Faults", normalised_milli=None)]


@pytest.mark.parametrize("a,f,c,expected", [(500, 0, 1000, 500), (1, 0, 3, 333), (2, 0, 3, 667),
    (-1000, 0, 1000, -1000), (250, 1000, 1000, "n/a"), (0, 1000, 0, "n/a"),
    (None, 0, 1000, None), (1, None, 1000, None), (1, 0, None, None)])
def test_normalised_exact(a, f, c, expected):
    assert cache.normalised_milli(a, f, c) == expected


def test_normalised_keyed_properties():
    for case in range(200):
        unit = ("s07", "norm", str(case))
        a, floor, ceiling = [uniform_int("s07", unit, 0, n, -1000, 1000) for n in ("a", "f", "c")]
        value = cache.normalised_milli(a, floor, ceiling)
        assert (value == "n/a") == (ceiling <= floor)
        if ceiling > floor:
            assert cache.normalised_milli(floor, floor, ceiling) == 0
            assert cache.normalised_milli(ceiling, floor, ceiling) == 1000
            assert cache.normalised_milli(a - 1, floor, ceiling) <= value <= cache.normalised_milli(a + 1, floor, ceiling)


def test_cache_hit_and_atomic_bytes(tmp_path):
    inp, score = fixture_input()
    calls = []

    def counted(item, result):
        calls.append(item["item_id"])
        return score(item, result)

    path = tmp_path / "controls.json"
    assert cache.read_entry(path, {}) is None
    first = cache.ensure(inp, path, score=counted, harness_pin=PIN)
    assert len(calls) == 27
    calls.clear()
    second = cache.ensure(inp, path, score=counted, harness_pin=PIN)
    assert calls == [] and first == second
    assert path.read_bytes() == canon(first)
    assert cache.write_entry(path, first) == sha256(canon(first)).hexdigest()
    assert cache.read_entry(path, first["key"], expected_sha256=sha256(canon(first)).hexdigest()) == first
    assert sorted(p.name for p in tmp_path.iterdir()) == ["controls.json"]


@pytest.mark.parametrize("change", ["harness", "scoring", "event", "window"])
def test_pin_changes_recompute(tmp_path, change):
    inp, score = fixture_input()
    path = tmp_path / "controls.json"
    first = cache.ensure(inp, path, score=score, harness_pin=PIN)
    pin, window = PIN, 16384
    if change == "harness":
        pin = "b" + PIN[1:]
    elif change == "scoring":
        inp = replace(inp, scoring_sha256="1" + inp.scoring_sha256[1:])
    elif change == "event":
        inp.events["life-s04"]["B0"][0]["text"] = "seat" + inp.events["life-s04"]["B0"][0]["text"][4:]
    else:
        window += 1
    key = cache.cache_key(inp, harness_pin=pin, window=window)
    assert key != first["key"] and cache.read_entry(path, key) is None
    calls = []

    def counted(item, result):
        calls.append(item["item_id"])
        return score(item, result)

    second = cache.ensure(inp, path, score=counted, harness_pin=pin, window=window)
    assert len(calls) == 27 and second["arms"] == first["arms"]
    assert cache.read_entry(path, key) == second


@pytest.mark.parametrize("field", ["reader_sha256", "scorer_sha256", "controls_sha256"])
def test_stale_code_misses_before_live_validation(tmp_path, monkeypatch, field):
    entry = computed()
    path = tmp_path / "controls.json"
    cache.write_entry(path, entry)

    def unexpected(*args, **kwargs):
        raise AssertionError("stale code must not validate or recompute")

    monkeypatch.setattr(cache, "validate", unexpected)
    monkeypatch.setattr(cache, "_aggregates", unexpected)
    key = dict(entry["key"], **{field: "f" * 64})
    assert cache.read_entry(path, key) is None


def test_changed_scorer_misses_and_ensure_overwrites(tmp_path, monkeypatch):
    inp, score = fixture_input()
    path = tmp_path / "controls.json"
    first = cache.ensure(inp, path, score=score, harness_pin=PIN)
    original_rows, original_key = aggregate._rows, cache.cache_key

    def changed_rows(*args, **kwargs):
        return [dict(row, score_milli=None if row["score_milli"] is None else row["score_milli"] - 1)
                for row in original_rows(*args, **kwargs)]

    def changed_key(*args, **kwargs):
        return dict(original_key(*args, **kwargs), scorer_sha256="f" * 64)

    monkeypatch.setattr(aggregate, "_rows", changed_rows)
    monkeypatch.setattr(cache, "cache_key", changed_key)
    key = cache.cache_key(inp, harness_pin=PIN)
    assert key != first["key"] and cache.read_entry(path, key) is None
    calls = []

    def counted(item, result):
        calls.append(item["item_id"])
        return score(item, result)

    second = cache.ensure(inp, path, score=counted, harness_pin=PIN)
    assert len(calls) == 27 and second["key"] == key
    assert second["arms"]["no_memory"]["aggregates"] != first["arms"]["no_memory"]["aggregates"]
    assert path.read_bytes() == canon(second) != canon(first)
    assert cache.read_entry(path, key) == second


@pytest.mark.parametrize("change", ["digest", "key-digest", "canary", "shape", "canonical", "expected"])
def test_code_stale_still_checks_integrity(tmp_path, change):
    entry = computed()
    key = dict(entry["key"], scorer_sha256="f" * 64)
    expected = None
    if change == "digest":
        entry["digest"] = "f" * 64
    elif change == "key-digest":
        entry["key_sha256"] = "f" * 64
        reseal(entry)
    elif change == "canary":
        entry["canary"] = "wrong"
        reseal(entry)
    elif change == "shape":
        entry["extra"] = None
        reseal(entry)
    elif change == "expected":
        expected = "f" * 64
    data = canon(entry) + (b"\n" if change == "canonical" else b"")
    path = tmp_path / "controls.json"
    path.write_bytes(data)
    with pytest.raises(cache.ControlsTampered):
        cache.read_entry(path, key, expected_sha256=expected)


def test_code_hashes_read_contents_and_self_exclusion(tmp_path):
    inp, _ = fixture_input()
    root = tmp_path / "package"
    shutil.copytree(cache.PACKAGE_ROOT, root, ignore=shutil.ignore_patterns("__pycache__"))
    key = cache.cache_key(inp, harness_pin=PIN, root=root)
    assert key == cache.cache_key(inp, harness_pin=PIN)
    path = tmp_path / "controls.json"
    cache.write_entry(path, computed())
    for relative, field in (("probe/__init__.py", "reader_sha256"),
                            ("score/__init__.py", "scorer_sha256"),
                            ("api/contract.py", "controls_sha256"),
                            ("contracts/items.py", "controls_sha256")):
        source = root / relative
        source.write_bytes(source.read_bytes() + b" ")
        changed = cache.cache_key(inp, harness_pin=PIN, root=root)
        assert changed[field] != key[field]
        assert cache.read_entry(path, changed) is None
        key = changed
    inp.pack["controls"] = cache.pack_controls(computed())
    inp.pack["hashes"]["controls"] = "f" * 64
    assert cache.cache_key(inp, harness_pin=PIN) == computed()["key"]
    assert cache.code_sha256(["api/contract.py"], root=root) == sha256_canon([
        ["api/contract.py", sha256((root / "api/contract.py").read_bytes()).hexdigest()]])
    with pytest.raises(FileNotFoundError):
        cache.code_sha256(["missing.py"], root=root)


def reseal(entry):
    entry["digest"] = sha256_canon({k: v for k, v in entry.items() if k != "digest"})


@pytest.mark.parametrize("change", ["score", "resealed-score", "newline", "pretty", "expected", "stale",
    "invalid-json", "canary", "key-digest", "shape", "bundle", "aggregate", "broken", "singleton", "item",
    "hidden-item"])
def test_tampering_voids_before_stale_miss(tmp_path, change):
    entry = computed()
    key, expected = entry["key"], None
    if change in ("score", "resealed-score", "stale"):
        # One digit; valid items/bundles leave aggregate recomputation as the detector.
        entry["arms"]["no_memory"]["aggregates"][0]["score_milli"] = 1
        if change != "score":
            reseal(entry)
        if change == "stale":
            key = dict(key, harness_pin="b" * 64)
    elif change == "expected":
        expected = "f" * 64
    elif change == "canary":
        entry["canary"] = "wrong"
        reseal(entry)
    elif change == "key-digest":
        entry["key_sha256"] = "f" * 64
        reseal(entry)
    elif change == "shape":
        entry["extra"] = None
        reseal(entry)
    elif change == "bundle":
        entry["arms"]["no_memory"]["bundles"][0]["score_milli"] = 1
        reseal(entry)
    elif change == "aggregate":
        entry["arms"]["no_memory"]["aggregates"][0]["score_milli"] = 1
        reseal(entry)
    elif change == "broken":
        entry["broken"] = []
        reseal(entry)
    elif change == "singleton":
        entry["arms"]["no_memory"]["singleton_lives"] = {}
        reseal(entry)
    elif change == "item":
        entry["arms"]["no_memory"]["items"][0]["score_milli"] = "0"
        reseal(entry)
    elif change == "hidden-item":
        items = entry["arms"]["no_memory"]["items"]
        items.insert(0, dict(items[0], score_milli="0"))
        reseal(entry)
    data = canon(entry)
    if change == "newline":
        data += b"\n"
    elif change == "pretty":
        data = json.dumps(entry, indent=2).encode()
    elif change == "invalid-json":
        data = b"{"
    path = tmp_path / "controls.json"
    path.write_bytes(data)
    with pytest.raises(cache.ControlsTampered) as caught:
        cache.read_entry(path, key, expected_sha256=expected)
    assert caught.value.code == "pinned_artifact_changed"


@pytest.mark.parametrize("change", ["pack", "key-missing", "key-extra", "key-duplicate", "key-invalid",
    "now-missing", "now-extra", "now-negative", "now-string", "now-bool", "stream", "event", "event-type",
    "bundle-life", "bundle-branch", "digest"])
def test_input_refusals(change):
    inp, _ = fixture_input()
    if change == "pack":
        inp.pack["tier"] = "T9"
    elif change == "key-missing":
        inp = replace(inp, keys=inp.keys[:-1])
    elif change == "key-extra":
        inp = replace(inp, keys=(*inp.keys, dict(inp.keys[0], item_id="extra")))
    elif change == "key-duplicate":
        inp = replace(inp, keys=(*inp.keys, inp.keys[0]))
    elif change == "key-invalid":
        inp.keys[0]["branch"] = "B2"
    elif change == "now-missing":
        inp.now.pop("na")
    elif change == "now-extra":
        inp.now["extra"] = 1000
    elif change.startswith("now-"):
        inp.now["na"] = {"now-negative": -1, "now-string": "1000", "now-bool": True}[change]
    elif change == "stream":
        inp.events["life-s04"].pop("B0")
    elif change == "event":
        inp.events["life-s04"]["B0"][0]["kind"] = "invalid"
    elif change == "event-type":
        inp.events["life-s04"]["B0"][0]["text"] = 1
    elif change == "bundle-life":
        inp.keys[0]["life"] = "other-life"
        inp.events["other-life"] = copy(inp.events["life-s04"])
    elif change == "bundle-branch":
        inp.keys[0]["branch"] = "B1"
    else:
        inp = replace(inp, scoring_sha256="A" * 64)
    with pytest.raises(ValueError):
        check(inp)


def test_no_memory_self_check(monkeypatch):
    class Echo(no_memory.NoMemory):
        def ingest(self, event):
            self.events[event["event_id"]] = event

        def query(self, task, now):
            return answer(list(self.events.values()))

    monkeypatch.setattr(no_memory, "NoMemory", Echo)
    inp, score = fixture_input()
    with pytest.raises(ValueError, match="no-memory context carries evidence"):
        no_memory.run(inp, score=score)


def test_oracle_self_check():
    inp, score = fixture_input()
    key = next(k for k in inp.keys if k["item_id"] == "kf0")
    key["oracle_spans"].insert(0, "e-gate")
    with pytest.raises(ValueError, match="oracle context carries a forbidden token"):
        oracle_evidence.run(inp, score=score)


@pytest.mark.parametrize("change", ["missing", "future"])
def test_oracle_span_unavailable(change):
    inp, score = fixture_input()
    if change == "missing":
        inp.events["life-s04"]["B0"].pop(1)
    else:
        inp.events["life-s04"]["B0"][1]["t_sim"] = 1001
    with pytest.raises(ValueError, match="oracle evidence unavailable"):
        oracle_evidence.run(inp, score=score)


@pytest.mark.parametrize("pin,window", [("bad", 16384), ("A" * 64, 16384), (PIN, 0), (PIN, True)])
def test_key_refusals(pin, window):
    with pytest.raises(ValueError):
        cache.cache_key(fixture_input()[0], harness_pin=pin, window=window)


def test_exceptions_propagate_and_write_nothing(tmp_path):
    inp, _ = fixture_input()
    path = tmp_path / "controls.json"

    def failing(item, result):
        raise RuntimeError("scoring defect")

    with pytest.raises(RuntimeError, match="scoring defect"):
        cache.ensure(inp, path, score=failing, harness_pin=PIN)
    assert not path.exists()


def test_determinism():
    outputs = [subprocess.check_output([sys.executable, __file__],
               env=dict(os.environ, PYTHONHASHSEED=seed)) for seed in ("0", "random")]
    assert outputs[0] == outputs[1] == canon(computed())


def assert_pure(tree):
    allowed = {"json", "os", "tempfile", "hashlib", "re", "fractions", "pathlib", "dataclasses",
               "collections.abc", "bicentennial.canon", "bicentennial.contracts.run",
               "bicentennial.contracts.items", "bicentennial.api.contract",
               "bicentennial.api.adapters.nomemory", "bicentennial.api.adapters.oracle_evidence",
               "bicentennial.api.adapters.reference_store", "bicentennial.probe.scripted_reader",
               "bicentennial.score.classes", "bicentennial.score.bundle", "bicentennial.score.aggregate",
               "bicentennial.world.scale", "bicentennial.world.tokens"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert all(n.name in allowed for n in node.names)
        if isinstance(node, ast.ImportFrom):
            assert node.level == 1 or node.module in allowed
        if isinstance(node, ast.Name):
            assert "gold" not in node.id.lower()
        if isinstance(node, ast.Attribute):
            assert "gold" not in node.attr.lower()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assert "gold" not in node.name.lower()
        if isinstance(node, (ast.arg, ast.keyword)) and node.arg is not None:
            assert "gold" not in node.arg.lower()
        if isinstance(node, ast.alias):
            assert "gold" not in node.name.lower()
            assert node.asname is None or "gold" not in node.asname.lower()
        if isinstance(node, ast.Constant):
            assert type(node.value) is not float
            assert not isinstance(node.value, str) or "gold" not in node.value.lower()


def test_purity():
    for path in sorted((cache.PACKAGE_ROOT / "controls").glob("*.py")):
        assert_pure(ast.parse(path.read_text()))


@pytest.mark.parametrize("source", [
    "def gold(): pass",
    "async def gold(): pass",
    "class gold: pass",
    "def allowed(gold): pass",
    "def allowed(*, gold): pass",
    "allowed(gold=1)",
    "from . import gold",
    "import json as gold",
    "from . import allowed as gold",
])
def test_purity_rejects_identifier_positions(source):
    with pytest.raises(AssertionError):
        assert_pure(ast.parse(source))


def test_purity_allows_optional_identifier_names():
    assert_pure(ast.parse("allowed(**options)\nfrom . import allowed"))


if __name__ == "__main__":
    sys.stdout.buffer.write(canon(computed()))
