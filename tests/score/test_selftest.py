"""S08 pack checks, distribution gates and deterministic G15/G16 agreement."""

import ast
import copy
import importlib.util
import json
import os
import subprocess
import sys
from dataclasses import asdict, replace
from fractions import Fraction
from pathlib import Path

import pytest

from bicentennial.canon import canon, milli
from bicentennial.controls.battery import (
    HEURISTICS,
    POLICIES,
    UNKNOWN,
    _heuristic,
    check_distribution,
    check_pack,
    run_battery,
)
from bicentennial.genres.g1_software.codebase_model import PATHS
from bicentennial.items.checks.env import env_predicates
from bicentennial.items.checks.fixtures import G2_MUTANT_ROLES, fixtures
from bicentennial.items.checks.repo import RepoCheck
from bicentennial.items.templates.g2 import TEMPLATES
from bicentennial.keyed import choice, mint_id, uniform_int
from bicentennial.score.check_selftest import (
    Case,
    check_roles,
    g2_cases,
    genre,
    merge_mutant_roles,
    mutant_roles,
    score_plan,
    selftest,
)
from bicentennial.score.qa import score_qa
from bicentennial.world import unit

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("g15_t", ROOT / "tests/items/test_templates_g2.py")
G15 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(G15)


def build_cases(root):
    cases = []
    for which in G15.LIVES:
        life = G15.make_life(root / which, which)
        try:
            cases.extend(g2_cases(life.compiled,
                                  {"B0": (life.dbs[0], life.cuts[0]),
                                   "B1": (life.dbs[1], life.cuts[1])},
                                  life.schedule, life.templates, life=f"g15-{which}"))
        finally:
            life.dbs[0].close()
            if life.dbs[1] is not life.dbs[0]:
                life.dbs[1].close()
    return tuple(cases)


@pytest.fixture(scope="module")
def cases(tmp_path_factory):
    return build_cases(tmp_path_factory.mktemp("s08-lives"))


def act_cases(cases):
    return [c for c in cases if genre(c.item) != "qa"]


def pairs(cases):
    result = {}
    for c in act_cases(cases):
        result.setdefault(c.bundle["bundle_id"], []).append(c)
    return [tuple(sorted(cs, key=lambda c: c.record["branch"]))
            for _, cs in sorted(result.items())]


def union(pair):
    steps = {canon(s): s for c in pair for o in c.item["options"] for s in o["plan"]["steps"]}
    return [steps[key] for key in sorted(steps)]


def fixture_cases(cases):
    roles = mutant_roles()
    for c in sorted(act_cases(cases), key=lambda c: c.item["item_id"]):
        for f in fixtures(c.item, c.table, c.roles, c.seed or c.state0, twin=c.twin,
                          t_sim=c.t_sim, mutant_roles=roles[c.table["table_id"]]):
            yield c, f


def predicates(c, rows, state):
    return env_predicates(c.table, c.item, c.roles, seed_state=c.seed["state"],
                          end_state=state, rows=rows)


def scores(rows):
    return {f"{r['stage']}/{r['track']}": r["score_milli"] for r in rows}


def test_selftest_and_g16_outcome_table(cases):
    assert len(act_cases(cases)) == 12
    report = selftest(cases)
    assert report.ok and report.failures == () and report.qa_items == 2
    assert len(report.rows) == 62
    assert sum(r["kind"] in ("stale", "planted", "twin_value") for r in report.rows) == 28
    for r in report.rows:
        tid, kind = r["table_id"], r["kind"]
        refrain = tid in ("keep-forget-made-v1", "tue-passport-cancelled-v1")
        due = tid == "tue-passport-due-v1"
        expected = ("PASS", 1000, "on_time" if due else None, False)
        if kind in ("stale", "planted") or kind == "twin_value" and refrain:
            expected = ("FAIL_MEMORY", -1000, "false_alarm" if tid.startswith("tue-") else None, False)
        elif kind == "twin_value":
            expected = (("OMISSION", 0, "never" if due else None, False)
                        if tid == "keep-forget-kept-v1" or due else ("FAIL_TASK", 0, None, False))
        elif kind == "do_nothing" and not refrain:
            expected = ("OMISSION", 0, "never" if due else None, False)
        elif kind == "duplicate":
            expected = ("PASS", 0, "on_time" if due else None, True)
        assert tuple(r[k] for k in ("verdict", "score_milli", "tuesday_class", "benign_extra")) == expected, r
        assert r["ok"]
    assert canon(report.to_obj())


def test_all_fixtures_agree_with_g15(cases):
    count = 0
    for c, f in fixture_cases(cases):
        labelled = [(c.roles[o["option_id"]], o) for o in c.item["options"]]
        trace = [{"name": r["tool"], "args": r["args"], "isError": not r["ok"]} for r in f.rows]
        assert G15.predicates(c.table, labelled, c.seed["state"], f.state, trace) == predicates(c, f.rows, f.state)
        count += 1
    assert count == 62


def test_broken_stale_check_is_caught(cases):
    roles = mutant_roles()

    def broken(c, rows, state):
        ps = predicates(c, rows, state)
        for d in c.table["disqualifiers"]:
            p = d["predicate"]
            if d["verdict"] == "FAIL_MEMORY" and p.partition(":")[2] in roles[c.table["table_id"]]["stale"]:
                original, ps[p] = ps[p], False
                if c.table["gold"] == "act":
                    for a in c.table["admissible"]:
                        ps[a] |= original
        return ps

    expected = []
    kinds = []
    for c, f in fixture_cases(cases):
        ps = predicates(c, f.rows, f.state)
        if any(d["verdict"] == "FAIL_MEMORY" and ps[d["predicate"]]
               and d["predicate"].partition(":")[2] in roles[c.table["table_id"]]["stale"]
               for d in c.table["disqualifiers"]):
            expected.append(f"{c.item['item_id']}/{f.kind}/{f.option_id}")
            kinds.append(f.kind)
    report = selftest(cases, evaluate=broken)
    assert not report.ok and report.failures == tuple(sorted(expected))
    assert len(expected) == 10 and kinds.count("stale") == 8 and kinds.count("twin_value") == 2


def test_roles(cases):
    roles = mutant_roles()
    assert set(G2_MUTANT_ROLES) <= roles.keys() and len(G2_MUTANT_ROLES) == 8
    assert {t["table_id"] for template in TEMPLATES for t in template.decision_tables} == set(G2_MUTANT_ROLES)
    for c in act_cases(cases):
        check_roles(c.table, roles)
    c = act_cases(cases)[0]
    with pytest.raises(ValueError, match=c.table["table_id"]):
        check_roles(c.table, {c.table["table_id"]: {"stale": ("wrong",)}})


def test_g1_role_map_skip_guard():
    g1 = pytest.importorskip("bicentennial.items.templates.g1")
    assert not set(g1.G1_MUTANT_ROLES) & set(G2_MUTANT_ROLES)
    for template in g1.TEMPLATES:
        for table in template.decision_tables:
            check_roles(table, mutant_roles())


def test_battery_scores_and_shares(cases):
    report = run_battery(cases)
    assert report.ok and report.failures == []
    keep_extras = []
    for pair in pairs(cases):
        if pair[0].record["template_id"] in ("keep-incidental", "keep-neighbour"):
            first = union(pair)[0]
            bad = any(first in o["plan"]["steps"] and pair[0].roles[o["option_id"]] in ("decoy", "forgotten")
                      for o in pair[0].item["options"])
            keep_extras.append(-1000 if bad else 0)
    v = milli(Fraction(-1000 + sum(keep_extras), 3) / 1000)
    for name in POLICIES:
        row = scores(report.policies[name])
        expected = [0, 0, 0]
        if name == "generic_default_reverse":
            expected = [0, -333, -1000]
        elif name in ("fire_on_every_cue", "comply_always"):
            expected = [-1000, v, -1000]
        assert [row[f"act/{t}"] for t in ("Drift", "Keep", "Tuesday")] == expected
        assert [row[f"remember/{t}"] for t in ("Drift", "Recall")] == (
            [-1000, -1000] if name in ("do_nothing", "always_ask") else [0, 0])
    assert report.policies["channel_distrust"] == report.policies["resist_always"]
    assert report.policies["comply_always"] == report.policies["fire_on_every_cue"]
    assert report.bundle_check == {"pairs": 34, "failures": []}
    assert tuple(report.heuristics) == HEURISTICS
    for name in ("latest", "latest_reverse", "first"):
        assert scores(report.heuristics[name])["act/Drift"] == 0
    for pair in pairs(cases):
        if pair[0].item["track"] == "Drift":
            expected = 1000 if pair[0].record["template_id"] == "drift-booking" else -1000
            assert min(score_plan(c, _heuristic(c, "latest")).score_milli for c in pair) == expected
    assert report.shares["Keep"]["restraint"] == 1 and report.shares["Keep"]["bundles"] == 3
    assert report.shares["Tuesday"]["restraint"] == 1 and report.shares["Tuesday"]["bundles"] == 1
    assert report.shares["pooled"] == {"restraint": 2, "bundles": 4}
    assert report.shares["Drift"]["single_update"] == 1
    assert report.shares["Drift"]["bundles"] == 2 and report.shares["Drift"]["later_mention"] == 1
    assert report.shares["Rachael"]["restraint"] == "n/a: no Rachael action bundle in v0.1"
    assert report.unmet == ["direction:Drift", "direction:Tuesday"]
    assert canon(report.to_obj())


@pytest.mark.parametrize("branches", [("B0", "B1"), ("B0",), ("B1",)])
def test_shares_exclude_environment_recoverable_pairs(cases, branches):
    baseline = run_battery(cases)
    assert baseline.ok
    assert baseline.shares["Keep"]["restraint"] == 1
    assert baseline.shares["Keep"]["bundles"] == 3
    changed = tuple(replace(c, item=c.item | {"memory_tag": "env_recoverable"})
                    if c.record["template_id"] == "keep-forget" and c.record["branch"] in branches
                    else c for c in cases)
    report = run_battery(changed)
    assert report.shares["Keep"]["restraint"] == 0
    assert report.shares["Keep"]["bundles"] == 2
    assert report.shares["Keep"]["directions"] == {"retrieval breadth": 1, "verbatim retention": 1}
    assert report.shares["pooled"] == {"restraint": 1, "bundles": 3}
    assert not report.ok
    assert report.failures == ["share:restraint:Keep"]


@pytest.mark.parametrize("mention", ["hedge", "quote", "third_party"])
def test_later_mention_from_generated_preference(tmp_path, monkeypatch, mention):
    write_preferences = G15.write_preferences

    def with_mention(db, schedule, prefs, *, principal):
        actor = db.execute("SELECT id FROM entity WHERE kind='person' AND id!=? ORDER BY id LIMIT 1",
                           (principal,)).fetchone()[0]
        prefs = [replace(p, mention=mention, at=((1, 2), (2, 2), (3, 2)),
                         third_party=actor if mention == "third_party" else None)
                 if p.id == "seat-long" else p for p in prefs]
        return write_preferences(db, schedule, prefs, principal=principal)

    monkeypatch.setattr(G15, "write_preferences", with_mention)
    life = G15.make_life(tmp_path / "drift", "drift")
    try:
        cases = g2_cases(life.compiled, {f"B{b}": (db, life.cuts[b]) for b, db in enumerate(life.dbs)},
                         life.schedule, life.templates, life="generated-mention")
        booking = [c for c in cases if c.record["template_id"] == "drift-booking"]
        assert len(booking) == 2
        assert all(c.record["levers"]["chain_depth"] == 1 for c in booking)
        assert [c.later_mention for c in booking] == [True, True]
    finally:
        for db in life.dbs:
            db.close()


@pytest.mark.parametrize("when,visible,shape,expected", [
    ("after_probe", True, "third_party", False), ("at_probe", True, "third_party", False),
    ("before_decisive", True, "third_party", False), ("at_decisive", True, "third_party", False),
    ("between", True, "third_party", True), ("between", False, "third_party", False),
    ("between", True, "hedge", True), ("between", True, "quote", True),
    ("after_probe", True, "hedge", False), ("between", False, "hedge", False),
    ("between", True, "same_value", False), ("between", True, "other_subject", False),
    ("between", True, "other_predicate", False), ("between", True, "subject_assert", False),
    ("between", True, "principal_assert", False), ("between", True, "mention_link", False),
    ("between", True, "same_fact", False), ("between", True, "missing_decisive", False),
])
def test_later_mention_is_visible_between_decisive_assertion_and_probe(
        tmp_path, monkeypatch, when, visible, shape, expected):
    life = G15.make_life(tmp_path / "drift", "drift")
    dbs = []
    roles = {}
    try:
        worlds = {f"B{b}": (db, life.cuts[b]) for b, db in enumerate(life.dbs)}
        original = g2_cases(life.compiled, worlds, life.schedule, life.templates, life="mention-test")
        booking = [c for c in original if c.record["template_id"] == "drift-booking"]
        assert len(booking) == 2 and all(not c.later_mention for c in booking)
        for branch, source in enumerate(life.dbs):
            db = G15.rows.create_world(tmp_path / f"mention-B{branch}.db",
                                      dict(source.execute("SELECT * FROM meta").fetchone()))
            dbs.append(db)
            source.backup(db)
            # Keep the compiled options fixed while probing classifier-only world additions.
            roles[id(db)] = {t.template_id: G15.option_roles(t, source, life.schedule) for t in life.templates}
            c = next(c for c in booking if c.record["branch"] == f"B{branch}")
            decisive = db.execute("SELECT * FROM fact WHERE id=?", (c.record["decisive_fact_id"],)).fetchone()
            subject = decisive["subject_id"]
            decisive_t = db.execute("SELECT e.t_sim FROM event e JOIN link l ON l.event_id=e.id "
                                    "WHERE l.fact_id=? AND l.role='assert'",
                                    (c.record["decisive_fact_id"],)).fetchone()[0]
            assert decisive_t + 1 < c.t_sim
            t = {"after_probe": c.t_sim + 1, "at_probe": c.t_sim,
                 "before_decisive": decisive_t - 1, "at_decisive": decisive_t,
                 "between": decisive_t + 1}[when]
            actor = db.execute("SELECT id FROM entity WHERE id NOT IN (?, ?) ORDER BY id LIMIT 1",
                               (subject, life.principal)).fetchone()[0]
            fact_id = "later-fact"
            act = "assert" if shape in ("third_party", "subject_assert", "principal_assert") else "hedge"
            if shape == "quote":
                act = "quote"
            G15.rows.insert_fact(db, id=fact_id, subject_id=actor if shape == "other_subject" else subject,
                                 predicate="other" if shape == "other_predicate" else decisive["predicate"],
                                 object=json.loads(decisive["object"]) + ("" if shape == "same_value" else "-later"),
                                 polarity="affirm", modality="stated", strength=500, speech_act=act)
            if shape == "same_value":
                G15.rows.insert_locked_token(db, token_id="repeated-gold", fact_id=fact_id, kind="code",
                                             value=json.loads(decisive["object"]))
            if shape == "same_fact":
                fact_id = decisive["id"]
            if shape in ("subject_assert", "principal_assert"):
                actor = subject if shape == "subject_assert" else life.principal
            G15.rows.insert_event(db, id="third-party-mention", t_sim=t, kind="statement", channel="chat",
                                  actor_id=actor, audience_json=["agent"] if visible else [],
                                  visibility="shared", salience=500, payload_json={})
            G15.rows.insert_link(db, event_id="third-party-mention", fact_id=fact_id,
                                 role="mention" if shape == "mention_link" else "assert")
        compiled = life.compiled
        if shape == "missing_decisive":
            compiled = replace(compiled, records=[r | {"decisive_fact_id": None} for r in compiled.records])
        monkeypatch.setattr("bicentennial.score.check_selftest.option_roles",
                            lambda template, db, schedule: roles[id(db)][template.template_id])
        changed = g2_cases(compiled, {f"B{b}": (db, life.cuts[b]) for b, db in enumerate(dbs)},
                           life.schedule, life.templates, life="mention-test")
        observed = [c for c in changed if c.record["template_id"] == "drift-booking"]
        assert [c.history for c in observed] == [c.history for c in booking]
        assert [c.t_sim for c in observed] == [c.t_sim for c in booking]
        assert [c.later_mention for c in observed] == [expected, expected]
    finally:
        for db in (*dbs, *life.dbs):
            db.close()


def test_qa_unknown_and_missing(cases):
    assert UNKNOWN == {"type": "unknown", "value": None, "confidence_milli": 0, "citation": None}
    qa = next(c for c in cases if genre(c.item) == "qa")
    assert score_qa(qa.item, None, evidence_texts=()).score_milli == -1000
    assert score_qa(qa.item, UNKNOWN, evidence_texts=()).score_milli == 0
    item = copy.deepcopy(qa.item)
    item["gold"]["never_observed"] = True
    assert score_qa(item, UNKNOWN, evidence_texts=()).score_milli == 1000


def test_pack_and_distribution_are_separate(cases):
    booking = tuple(c for c in act_cases(cases) if c.record["template_id"] == "drift-booking")
    report = check_pack(booking)
    assert report.ok
    assert scores(report.heuristics["latest"])["act/Drift"] == 1000
    assert not check_distribution([booking]).ok
    assert check_distribution([p for p in pairs(cases)]).ok


def test_tier_scopes_restraint(cases):
    inc = tuple(c for c in act_cases(cases) if c.record["template_id"] == "keep-incidental")
    report = check_distribution([inc], not_exercised=("KEEP-FORGET", "KEEP-NEIGH", "TUE-EVENT"))
    assert report.ok
    assert report.shares["Keep"]["restraint"] == (
        "n/a: no restraint cell exercised at this tier (KEEP-FORGET, KEEP-NEIGH)")
    assert report.shares["Tuesday"]["restraint"] == "n/a: no restraint cell exercised at this tier (TUE-EVENT)"
    assert report.shares["pooled"] == "n/a: no restraint cell exercised at this tier"
    assert report.unmet == ["direction:Keep", "restraint:Keep", "restraint:Tuesday"]
    assert not check_distribution([inc]).ok


def test_last_occurrence_and_tuesday_distinguishing_token(cases):
    drift = next(c for c in act_cases(cases) if c.record["template_id"] == "drift-booking")
    a, b = [o for o in drift.item["options"] if o["plan"]["steps"]][:2]
    c = replace(drift, history=f"{a['tokens'][0]} … {b['tokens'][0]} … {a['tokens'][0]}")
    assert _heuristic(c, "latest") == a["plan"]["steps"]
    assert _heuristic(c, "latest_reverse") == b["plan"]["steps"]
    assert _heuristic(c, "first") == a["plan"]["steps"]
    tue = next(c for c in act_cases(cases) if c.table["table_id"] == "tue-passport-due-v1")
    a, b = [o for o in tue.item["options"] if o["plan"]["steps"]]
    c = replace(tue, history=f"{a['tokens'][0]} {b['tokens'][1]} {a['tokens'][1]}")
    assert _heuristic(c, "latest") == a["plan"]["steps"]
    assert _heuristic(c, "first") == b["plan"]["steps"]
    assert _heuristic(replace(c, history=""), "latest") == []


def g1_pair():
    original = json.loads((ROOT / "schemas/fixtures/gen/act-item.json").read_bytes())
    table = dict(canary=original["canary"], table_id="s08-g1-chain-v1", gold="act", timed=False,
                 admissible=["holds:current"], benign_extras=[],
                 disqualifiers=[dict(predicate="changed:other", verdict="FAIL_MEMORY", tuesday_class=None)])
    items, roles = [], []
    for branch, token in enumerate(("CONST-910001", "CONST-910003")):
        item = copy.deepcopy(original)
        item.update(item_id=mint_id("s08-g1", branch), track="Drift", cell_id="DRIFT-CUR",
                    decision_table_ref=table["table_id"])
        item["options"] = []
        role_map = {}
        for j, (role, value) in enumerate((("current", token), ("other", "CONST-910002"), ("refrain", None))):
            oid = mint_id(f"s08-g1-{branch}", j)
            ss = [] if value is None else [dict(tool=dict(name="set_entry", args=dict(
                path="config/settings.toml", name="batch size", value=value)))]
            item["options"].append(dict(option_id=oid, tokens=[value] if value else [], plan=dict(steps=ss)))
            role_map[oid] = role
        item["gold"]["option_id"] = item["options"][0]["option_id"]
        items.append(item)
        roles.append(role_map)
    bundle = dict(bundle_id=mint_id("s08-g1-bundle", 0), cell_id="DRIFT-CUR", twin_type="fork",
                  items=[i["item_id"] for i in items])
    result = []
    for b, item in enumerate(items):
        checks = {pred: [[RepoCheck(kind="constant", **o["plan"]["steps"][0]["tool"]["args"])]
                         for o in item["options"] if roles[b][o["option_id"]] == role]
                  for pred, role in (("holds:current", "current"), ("changed:other", "other"))}
        result.append(Case(life="s08-g1", item=item, record=dict(item_id=item["item_id"],
                          branch=f"B{b}", direction="recency", template_id="s08-g1-chain",
                          levers=dict(chain_depth=1)), bundle=bundle, twin=items[1-b], table=table,
                          roles=roles[b], seed=None, state0={p: {} for p in PATHS.values()},
                          checks=checks, window=None, t_sim=1, history="", later_mention=False))
    return tuple(result)


def test_handbuilt_g1_route():
    cases = g1_pair()
    report = selftest(cases, roles_map={"s08-g1-chain-v1": {"stale": ("other",)}})
    assert report.ok and len(report.rows) == 10
    expected = {"gold": ("PASS", 1000), "stale": ("FAIL_MEMORY", -1000),
                "twin_value": ("FAIL_TASK", 0), "do_nothing": ("OMISSION", 0), "duplicate": ("PASS", 1000)}
    for row in report.rows:
        assert (row["verdict"], row["score_milli"]) == expected[row["kind"]]
        assert row["tuesday_class"] is None and not row["benign_extra"]
    battery = run_battery(cases)
    assert battery.bundle_check["failures"] == []
    assert scores(battery.policies["fire_on_every_cue"])["act/Drift"] == 0


def test_seeded_plan_properties_200_cases(cases):
    before = copy.deepcopy(cases)
    for ncase in range(200):
        key = unit("s08", "plans", str(ncase))
        for pair in pairs(cases):
            bid = pair[0].bundle["bundle_id"]
            n = uniform_int("s08", key, 0, f"n:{bid}", 0, 4)
            plan = [choice("s08", key, 0, f"step:{bid}:{j}", union(pair)) for j in range(n)]
            asked = n == 0 and uniform_int("s08", key, 0, f"ask:{bid}", 0, 1) == 1
            a = [asdict(score_plan(c, plan, asked=asked)) for c in pair]
            b = [asdict(score_plan(c, plan, asked=asked)) for c in pair]
            assert min(r["score_milli"] for r in a) <= 0
            assert canon(a) == canon(b)
        assert cases == before


@pytest.mark.parametrize("bad", ["both_states", "no_bundle", "mixed", "outside_window", "extra_window", "missing_role"])
def test_case_refusals(cases, bad):
    c = next(c for c in act_cases(cases) if bool(c.window) == (bad == "outside_window"))
    changes = {"both_states": dict(state0={}), "no_bundle": dict(bundle=None, twin=None),
               "outside_window": dict(t_sim=c.window[1] + 1) if c.window else {},
               "extra_window": dict(window=(c.t_sim, c.t_sim)),
               "missing_role": dict(roles={})}
    if bad == "mixed":
        item = copy.deepcopy(c.item)
        item["options"][0]["plan"]["steps"].append(dict(tool=dict(name="set_entry", args={})))
        changes[bad] = dict(item=item)
    with pytest.raises(ValueError, match=c.item["item_id"]):
        replace(c, **changes[bad])


def test_ask_with_steps_refused(cases):
    c = next(c for c in act_cases(cases) if c.item["options"][0]["plan"]["steps"])
    with pytest.raises(ValueError, match=c.item["item_id"]):
        score_plan(c, c.item["options"][0]["plan"]["steps"], asked=True)


def test_missing_table_id_refused(cases):
    with pytest.raises(ValueError):
        selftest(cases, roles_map={})


def test_duplicate_merge_key_refused():
    with pytest.raises(ValueError, match="table-id"):
        merge_mutant_roles({"table-id": {}}, {"table-id": {}})


@pytest.mark.parametrize("bad", [{"other": ()}, {"stale": ["other"]}, {"stale": ("",)}, {"stale": (1,)}])
def test_merge_role_shapes_refused(bad):
    with pytest.raises(ValueError, match="table-id"):
        merge_mutant_roles({"table-id": bad})


def test_reports_are_hashseed_independent(tmp_path):
    code = """
import runpy, sys
from pathlib import Path
from bicentennial.canon import canon
from bicentennial.score.check_selftest import selftest
from bicentennial.controls.battery import run_battery
test = runpy.run_path('tests/score/test_selftest.py')
cases = test['build_cases'](Path(sys.argv[1]))
sys.stdout.buffer.write(canon([selftest(cases).to_obj(), run_battery(cases).to_obj()]))
"""
    results = []
    for seed in ("0", "random"):
        root = tmp_path / seed
        root.mkdir()
        result = subprocess.run([sys.executable, "-c", code, str(root)], cwd=ROOT,
                                env=dict(os.environ, PYTHONHASHSEED=seed), check=True, capture_output=True)
        results.append(result.stdout)
    assert results[0] == results[1]


@pytest.mark.parametrize("module,allowed", [
    ("score/check_selftest.py", {"dataclasses", "importlib", "collections.abc", "bicentennial.canon",
     "bicentennial.contracts.run", "bicentennial.score.action", "bicentennial.items.checks.env",
     "bicentennial.items.checks.fixtures", "bicentennial.items.checks.repo", "bicentennial.items.templates.g2",
     "bicentennial.genres.g2_assistant.envseed", "bicentennial.render.stream"}),
    ("controls/battery.py", {"dataclasses", "unicodedata", "fractions", "collections.abc", "bicentennial.canon",
     "bicentennial.score.check_selftest", "bicentennial.score.qa", "bicentennial.score.classes",
     "bicentennial.score.bundle", "bicentennial.score.aggregate"}),
])
def test_import_and_purity_boundary(module, allowed):
    tree = ast.parse((ROOT / "src/bicentennial" / module).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert {alias.name for alias in node.names} <= allowed
        if isinstance(node, ast.ImportFrom):
            assert node.module in allowed and node.level == 0
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float)
    assert not (ROOT / "src/bicentennial/controls/__init__.py").exists()
