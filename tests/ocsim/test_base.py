"""Public synthetic witnesses for the staged OC base-document rules."""

import ast
import inspect
import json
import subprocess
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.ocsim import base, inputs, run

from .test_inputs import REQUIRED, sample

ROOT = Path(__file__).resolve().parents[2]
PENDING = {"probe_only": "B-8", "n_lives_floor": "B-9"}
REAL_C8 = base.c8_check
REAL_CAP = base.runner_cap


def dry_set(commit, cells):
    lives = []
    for i in range(48):
        fork = 1 + i % 20
        branches = {}
        for branch in ("B0", "B1"):
            branches[branch] = dict(est_tokens=[j + i + 1 for j in range(200)],
                                    probe_points=[20, 60, 120, 200], probe_tokens=[0, 2, 3, 4], swap=[150],
                                    content_sha256=[sha256(canon([i, j, branch if j >= fork else "shared"])).hexdigest()
                                                    for j in range(1, 21)])
        lives.append(dict(i=i, life=f"ocsim-dry-{i:03d}", genre="G1" if i % 2 == 0 else "G2",
                          seed=int.from_bytes(sha256(canon(["ocsim-dry", i])).digest()[:8], "big") >> 1,
                          generator_version="synthetic-v1", render_commit=commit, fork=fork,
                          branches=branches, bundles=[[c, k, 180] for c in cells for k in (20, 60, 120, 200)]))
    return {"status": "binding", "lives": lives}


class Fake:
    def __init__(self, root, monkeypatch, n=3, marker=True, extra_files=()):
        self.root, self.monkeypatch = root, monkeypatch
        self.roster = {"status": "binding", "systems": [
            {"id": "alpha", "lcmx": True}, {"id": "beta", "lcmx": False}]}
        self.c12 = {"status": "binding", "profile": "Text", "required": list(REQUIRED)}
        self.c11 = {"status": "binding", "lanes": {
            "pinned": dict(model="synthetic-pinned", concurrency=3, rate_per_min=None, accounts=2),
            "swap": dict(model="synthetic-swap", concurrency=2, rate_per_min=30, accounts=1)}}
        self.c1 = dict(status="binding", pinned_model="synthetic-pinned", extra="ignored")
        self.c2 = dict(status="binding", swap_model="synthetic-swap", effort="synthetic", extra="ignored")
        self.history = {"generator_version": "synthetic-v1", "lives": {}}
        for i in range(n):
            self.history["lives"][f"life-{i}"] = {branch: [dict(
                canary=base.CANARY, index=j, kind="work", wake_before=[], fault_points=[],
                long_sprint=False, est_tokens=10, probe_point=False,
                expected_state={"repo_tree_hash": "1" * 64, "env_state_hash": "2" * 64})
                for j in range(1, 5)] for branch in ("B0", "B1")}
        self.controls = sample(lives=n)[0]
        self.data = {"run_lock": {"benchmark_commit": "0" * 40, "generator_version": "synthetic-v1",
                                  "analysis_commit": "0" * 40,
                                  "generator_versions": dict(G1="synthetic-v1", G2="synthetic-v1"),
                                  "history_sha256": "0" * 64, "status": "complete",
                                  "account_pool": ["synthetic-account"]}, "arms": {}, "items": {}}
        for arm, rate in (("alpha", 2), ("beta", 4), *((("marker", 6),) if marker else ())):
            value = self.data["arms"][arm] = {"kind": "marker" if arm == "marker" else "system", "lives": {}}
            for life in self.history["lives"]:
                value["lives"][life] = {}
                for branch in ("B0", "B1"):
                    value["lives"][life][branch] = {}
                    for keep in ("K100", "K10"):
                        iid = f"probe-{life}-{branch}-{keep}"
                        self.data["items"][iid] = {"life": life, "prompt": "abcdefgh", "classes": {}}
                        sessions = [dict(index=j, kind="replay", checkpoint=None, wall_ms=rate * 10,
                                         gate_ms=1, egress_wait_ms=2, items=[]) for j in range(1, 5)]
                        sessions.append(dict(index=5, kind="probe", checkpoint=2, wall_ms=rate * 2,
                                             gate_ms=1, egress_wait_ms=2, items=[iid]))
                        value["lives"][life][branch][keep] = dict(attempt=2, stopped=None, sessions=sessions)
        for item in self.data["items"].values():
            item["classes"] = dict.fromkeys(self.data["arms"])
        self.stop("alpha", "life-0", "B0", "K100", "replay", 4, None, "SYSTEM_FAILURE")
        self.stop("beta", "life-1", "B0", "K100", "probe", 5, 2, "BLOCKED")
        self.block("no_memory", self.controls["A"]["no_memory"]["items"][0]["item_id"])
        monkeypatch.setattr(base, "marker_id", lambda root, commit: "marker")
        monkeypatch.setattr(base, "runner_cap", lambda context, lane: 4)
        monkeypatch.setattr(base, "c8_check", lambda context: None)
        for path in extra_files:
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / path).read_bytes())
        self.commit()
        self.data["run_lock"]["analysis_commit"] = self.data["run_lock"]["benchmark_commit"]
        self.dry = dry_set(self.data["run_lock"]["benchmark_commit"], REQUIRED)
        self.commit()

    def commit(self):
        artifacts = [(base.ROSTER, self.roster), (base.C12, self.c12),
                     (base.C11, self.c11), (base.C1, self.c1), (base.C2, self.c2)]
        if hasattr(self, "dry"):
            artifacts.append((base.DRY, self.dry))
        for path, data in artifacts:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(canon(data) + b"\n")
        for args in (("init",), ("add", "."), ("-c", "user.name=Synthetic", "-c",
                     "user.email=synthetic@example.invalid", "-c", "commit.gpgsign=false",
                     "commit", "--allow-empty", "-m", "synthetic fixture")):
            assert run._git(self.root, *args) is not None
        self.data["run_lock"]["benchmark_commit"] = run._git(self.root, "rev-parse", "HEAD")

    def chain(self, arm="alpha", life="life-0", branch="B0", keep="K100"):
        return self.data["arms"][arm]["lives"][life][branch][keep]

    def stop(self, arm, life, branch, keep, kind, session, checkpoint, failure):
        chain = self.chain(arm, life, branch, keep)
        chain["stopped"] = dict(
            kind=kind, session=session, checkpoint=checkpoint, label="synthetic-stop", **{"class": failure})
        chain["sessions"] = [s for s in chain["sessions"] if (
            (s["index"] <= session if s["kind"] == "replay" else s["checkpoint"] < session)
            if kind == "replay" else
            (s["index"] <= checkpoint if s["kind"] == "replay" else s["index"] <= session))]

    def clear_stops(self):
        for value in self.data["arms"].values():
            for branches in value["lives"].values():
                for keeps in branches.values():
                    for chain in keeps.values():
                        chain["stopped"] = None

    def block(self, arm, iid):
        for item in self.controls["A"][arm]["items"]:
            if item["item_id"] == iid:
                item.update(failure_class="BLOCKED", score_milli=None)

    def remove_arm(self, arm):
        self.data["arms"].pop(arm)
        for item in self.data["items"].values():
            item["classes"].pop(arm)

    def build(self, stamp=True):
        history = canon(self.history)
        if stamp:
            self.data["run_lock"]["history_sha256"] = sha256(history).hexdigest()
        return base.build_base(bar2=canon(self.data), controls=canon(self.controls), history=history, root=self.root)

    def document(self):
        return json.loads(self.build())


def allow_pending(monkeypatch):
    for field in PENDING:
        monkeypatch.setitem(base.RULES, field, replace(base.RULES[field], function=lambda context: None))


@pytest.fixture
def fake(tmp_path, monkeypatch):
    result = Fake(tmp_path, monkeypatch)
    allow_pending(monkeypatch)
    return result


def test_registry_and_pending(tmp_path, monkeypatch):
    tree = ast.parse(inspect.getsource(run._parse_inputs))
    fields = next(ast.literal_eval(node.value) for node in ast.walk(tree)
                  if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "fields"
                                                         for t in node.targets))
    assert set(base.BASE_FIELDS) == set(fields) - {"params", "latent_flags", "sensitivity_params", "c8_hash"}
    assert set(base.RULES) == set(base.BASE_FIELDS)
    fixture = Fake(tmp_path, monkeypatch)
    with pytest.raises(base.BaseRefused) as error:
        fixture.build()
    assert error.value.refusals == tuple(sorted((f, f"pending:{r}") for f, r in PENDING.items()))
    for field in base.BASE_FIELDS:
        with monkeypatch.context() as patch:
            patch.delitem(base.RULES, field)
            with pytest.raises(base.BaseRefused) as error:
                fixture.build()
            assert (field, "rule_missing") in error.value.refusals
            assert all(f in str(error.value) and r in str(error.value) for f, r in error.value.refusals)


def test_history_schema_constant():
    schema = json.loads((ROOT / "schemas/session.schema.json").read_bytes())
    assert base.SESSION_REQUIRED == set(schema["required"])
    assert base.SESSION_ALLOWED == set(schema["properties"])


def test_complete(fake):
    document = fake.document()
    assert document["rows"] == [{"row": "alpha", "rate": "2/1"}, {"row": "beta", "rate": "4/1"},
                                 {"row": "marker", "rate": "6/1"}]
    assert document["passover"] == {"failed": "1/6", "blocked": "1/6"}
    assert document["control_failure"] == "1/6"
    assert document["checkpoints"] == [20, 60, 120, 200]
    assert document["required"] == list(REQUIRED) and document["planning"] is False
    assert fake.build() == canon(document)
    provenance = document["base_provenance"]
    assert provenance["account_pool"] == ["synthetic-account"]
    assert provenance["a_prime"] == {a: {"items": 30, "bundles": 15} for a in inputs.ARMS}
    assert provenance["waits"]["alpha"] == {"gate": "59/988", "egress_wait": "59/494", "untimed_sessions": 0}
    assert provenance["containers"] == {k: sha256(canon(v)).hexdigest() for k, v in
                                        (("bar2", fake.data), ("controls", fake.controls), ("history", fake.history))}
    for artifact in provenance["artifacts"]:
        assert artifact == {"path": artifact["path"], "commit": fake.data["run_lock"]["benchmark_commit"],
                            "sha256": sha256((fake.root / artifact["path"]).read_bytes()).hexdigest()}
    assert provenance["pending_disclosures"] == [
        "B-4 recovered INFRA attempts: stage c, with the probe-only arms' bar-2 records"]
    paths = {"rows": {base.ROSTER}, "required": {base.C12}, "lanes": {base.C11, base.C1, base.C2},
             "alloc_by_b": {base.DRY, base.C12}, "lives": {base.DRY}}
    for field, rule in base.RULES.items():
        assert provenance[field] == {"rule": rule.rule, "sources": list(rule.sources),
                                     "artifacts": [a for a in provenance["artifacts"]
                                                   if a["path"] in paths.get(field, set())]}


def test_round_trip(tmp_path, monkeypatch):
    fixture = Fake(tmp_path, monkeypatch, n=6)
    fixture.controls = sample()[0]
    def probe_only(context):
        return dict(rates={}, anchor_tokens=[[f"ocsim-dry-{i:03d}", 1] for i in range(48)],
                    tokens=[[arm, f"ocsim-dry-{i:03d}", branch, k, 1]
                            for arm in ("C", "F") for i in range(48)
                            for branch in ("B0", "B1") for k in (20, 60, 120, 200)])
    monkeypatch.setitem(base.RULES, "probe_only", replace(base.RULES["probe_only"], function=probe_only))
    monkeypatch.setitem(base.RULES, "n_lives_floor", replace(base.RULES["n_lives_floor"], function=lambda context: 1))
    monkeypatch.setattr(run, "c8_dirty", lambda root: False)
    built = fixture.build()
    merged = inputs.build(canon(sample()[0]), built, root=ROOT, resamples=3)
    parsed = run.parse_inputs(merged)
    assert parsed.planning is False and len(parsed.lives) == 48
    assert json.loads(merged)["base_provenance"] == json.loads(built)["base_provenance"]


@pytest.mark.parametrize("case,field,reason", [
    *[(f"reserved-{arm}", "rows", f"row_id_reserved:{arm}") for arm in ("C", "CEIL", "F", "RAG", "S", "anchor", "no_memory", "oracle_evidence")],
    ("marker-pending", "rows", "pending:C-14"), ("marker-mismatch", "rows", "rows:marker_mismatch:marker"),
    ("unmatched", "rows", "rows:unmatched_session:alpha/life-0/B0/5"),
    ("zero-tokens", "rows", "rows:zero_tokens:alpha"), ("zero-wall", "rows", "rows:zero_wall:alpha"),
    ("untimed", "rows", "rows:no_timed_arm"), ("no-real", "passover", "passover:no_real_arm"),
    ("control-lives", "control_failure", "control_failure:lives_mismatch"),
    ("status", "planning", "bar2_not_run_of_record"), ("kind", "rows", "bar2:arm_kind:alpha"),
    ("markers", "rows", "bar2:two_markers:arms"), ("roster", "rows", "bar2:not_on_roster:alpha"),
    ("chain", "rows", "bar2:chain_missing:alpha/life-0/B0/K100"),
    ("lives", "rows", "bar2:lives_mismatch:alpha"),
    ("classes", "rows", "bar2:classes_incomplete:probe-life-0-B0-K100"),
    ("item-life", "rows", "bar2:item_life:alpha/life-0/B0/K100"),
    ("item-twice", "rows", "bar2:item_twice:alpha/life-0/B0/K100"),
    ("stop", "rows", "bar2:stop_mismatch:alpha/life-0/B0/K100"),
    ("stop-probe", "rows", "bar2:stop_mismatch:alpha/life-0/B0/K100"),
    ("stop-listed", "rows", "bar2:stop_mismatch:alpha/life-0/B0/K100"),
    ("duplicate-index", "rows", "bar2:duplicate_session:alpha/life-0/B0/K100"),
    ("replay-index", "rows", "bar2:session_index:alpha/life-0/B0/K100"),
    ("probe-index", "rows", "bar2:session_index:alpha/life-0/B0/K100"),
    ("account", "rows", "bar2:account_pool:run_lock"), ("hash", "planning", "history_mismatch"),
    ("version", "planning", "history_mismatch"), ("history", "rows", "history:bad_session:life-0/B0/1"),
    ("history-order", "rows", "history:bad_session:life-0/B0/1"),
    ("controls", "control_failure", "controls:branches: must be an object"),
    ("missing", "required", f"source_missing:{base.C12}"),
    ("provisional", "required", f"source_provisional:{base.C12}"),
    ("required", "required", "required:not_sorted_unique"),
    ("unknown", "rows", "bar2:shape:root"),
    ("unknown-history", "rows", "history:shape:root"),
    ("unknown-controls", "control_failure", "controls:unknown_key:arm"),
    *[(case, "rows", "bar2:chain_shape:alpha/life-0/B0/K100") for case in ("attempt", "chain-unknown")],
    *[(case, "rows", "bar2:session_shape:alpha/life-0/B0/K100")
      for case in ("wall", "gate", "egress", "empty-probe", "replay-items", "session-unknown")],
    *[(case, "rows", "history:bad_session:life-0/B0/1")
      for case in ("history-keys", "history-canary", "history-fault", "history-state", "history-bool")],
    *[(case, "rows", "bar2:account_pool:run_lock")
      for case in ("account-sorted", "account-duplicate", "account-empty")],
    ("commit", "rows", "bar2:shape:run_lock"),
    ("roster-unknown", "rows", f"source_shape:{base.ROSTER}"),
    ("c12-unknown", "required", f"source_shape:{base.C12}"),
    ("roster-provisional", "rows", f"source_provisional:{base.ROSTER}"),
    ("unmatched-untimed", "rows", "rows:unmatched_session:alpha/life-0/B0/5"),
    ("duplicate-bar2", "rows", "bar2:duplicate_key:arms"),
    ("duplicate-history", "rows", "history:duplicate_key:generator_version"),
    ("duplicate-controls", "control_failure", "controls:container: duplicate key A"),
    ("raised-rule", "planning", "synthetic rule failure"),
    ("git-failure", "rows", f"source_missing:{base.ROSTER}"),
    ("b-route", "lanes", "lanes:c11_route"),
    ("b-route-equal", "lanes", "lanes:c11_route"),
    ("b-rate-only", "lanes", "pending:B-15 rate-only concurrency"),
    ("b-runner", "lanes", "pending:bar-2 runner"),
    ("b-lock-analysis", "rows", "bar2:shape:run_lock"),
    ("b-lock-versions", "rows", "bar2:shape:run_lock"),
    ("b-lock-join", "rows", "bar2:shape:run_lock"),
    ("b-below", "alloc_by_b", "alloc_by_b:dry_below"),
    *[(f"b-{case}", "lives", f"lives:{reason}") for case, reason in (
        ("identity", "dry_identity"), ("seed", "dry_identity"), ("genre", "dry_identity"),
        ("order", "dry_identity"), ("count", "dry_identity"), ("version", "generator_version"),
        ("swapped-versions", "generator_version"), ("tokens", "dry_shape"), ("probe-tokens", "dry_shape"),
        ("hashes", "dry_shape"), ("render-shape", "dry_shape"), ("fork-shape", "dry_shape"),
        ("bundle-shape", "dry_shape"), ("dry-keys", "dry_shape"), ("probes", "probe_points"),
        ("swap-diff", "swap_differs"), ("swap", "swap"), ("late", "fork_late"),
        ("no-fork", "no_fork"), ("fork", "fork_mismatch"), ("render-unknown", "git"),
        ("render-unrelated", "render_commit"),
        *((f"render-{path}", "render_code") for path in ("src/bicentennial/items", "tiers", "specs/ring0", "schemas"))
    )],
    *[(f"b-{kind}-{path}", "lanes" if path != base.DRY else "lives",
       f"{path}:{reason}" if kind == "json" else f"{reason}:{path}")
      for path in (base.C11, base.C1, base.C2, base.DRY)
      for kind, reason in (("missing", "source_missing"), ("provisional", "source_provisional"),
                           ("json", "invalid_json"), ("shape", "source_shape"))
      if not (kind == "shape" and path == base.DRY)],
    *[(f"b-after-{kind}", "rows", "bar2:after_stop:alpha/life-0/B0/K100")
      for kind in ("replay", "checkpoint", "probe", "probe-replay")],
])
def test_refusals(fake, monkeypatch, case, field, reason):
    chain = fake.chain()
    session, probe = chain["sessions"][0], chain["sessions"][-1]
    item = fake.data["items"][probe["items"][0]]
    if case.startswith("b-"):
        stage_b_refusal(fake, monkeypatch, case[2:])
    if case.startswith("reserved-"):
        monkeypatch.setattr(base, "marker_id", lambda root, commit: case.removeprefix("reserved-"))
    if case == "marker-pending":
        monkeypatch.undo()
    if case == "marker-mismatch":
        monkeypatch.setattr(base, "marker_id", lambda root, commit: "other-marker")
    if case == "unmatched":
        fake.data["items"].pop(probe["items"][0])
    if case in ("zero-tokens", "zero-wall", "untimed"):
        for value in fake.data["arms"].values():
            for branches in value["lives"].values():
                for keeps in branches.values():
                    for entry in keeps.values():
                        for s in entry["sessions"]:
                            s["wall_ms"] = None if case == "untimed" else (0 if case == "zero-wall" else s["wall_ms"])
        if case == "zero-tokens":
            for branches in fake.history["lives"].values():
                for records in branches.values():
                    for record in records:
                        record["est_tokens"] = 0
            for entry in fake.data["items"].values():
                entry["prompt"] = ""
    if case == "no-real":
        fake.remove_arm("alpha")
        fake.remove_arm("beta")
    if case == "control-lives":
        fake.controls = sample(lives=2)[0]
    if case == "status":
        fake.data["run_lock"]["status"] = "running"
    if case == "kind":
        fake.data["arms"]["alpha"]["kind"] = "probe_only"
    if case == "markers":
        fake.data["arms"]["alpha"]["kind"] = "marker"
    if case == "roster":
        fake.roster["systems"].pop(0)
        fake.commit()
    if case == "chain":
        fake.data["arms"]["alpha"]["lives"]["life-0"]["B0"].pop("K100")
    if case == "lives":
        fake.data["arms"]["alpha"]["lives"].pop("life-0")
    if case == "classes":
        item["classes"].pop("beta")
    if case == "item-life":
        item["life"] = "life-1"
    if case == "item-twice":
        probe["items"] *= 2
    if case == "stop":
        chain["stopped"]["session"] = 5
    if case == "stop-probe":
        chain["stopped"].update(kind="probe", session=6, checkpoint=None)
    if case == "stop-listed":
        chain["stopped"].update(kind="probe", session=5, checkpoint=3)
    if case == "duplicate-index":
        chain["sessions"].append(deepcopy(session))
    if case == "replay-index":
        session["index"] = 6
    if case == "probe-index":
        probe["index"] = 2
    if case == "account":
        fake.data["run_lock"]["account_pool"] = ["Not Public"]
    if case == "hash":
        fake.data["run_lock"]["history_sha256"] = "f" * 64
    if case == "version":
        fake.data["run_lock"]["generator_version"] = "other-version"
    if case == "history":
        fake.history["lives"]["life-0"]["B0"][0]["kind"] = "probe"
    if case == "history-order":
        fake.history["lives"]["life-0"]["B0"].reverse()
    if case == "controls":
        fake.controls["branches"] = []
    if case == "missing":
        target = fake.root / base.C12
        target.unlink()
        assert run._git(fake.root, "add", "-u") is not None
        assert run._git(fake.root, "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
                        "-c", "commit.gpgsign=false", "commit", "-m", "synthetic missing") is not None
        fake.data["run_lock"]["benchmark_commit"] = run._git(fake.root, "rev-parse", "HEAD")
    if case in ("provisional", "required"):
        fake.c12.update({"status": "provisional"} if case == "provisional" else {"required": ["z", "a", "a"]})
        fake.commit()
    if case == "unknown":
        fake.data["unknown"] = 1
    if case == "unknown-history":
        fake.history["unknown"] = 1
    if case == "unknown-controls":
        fake.controls["A"]["no_memory"]["unknown"] = 1
    if case == "attempt":
        chain["attempt"] = True
    if case == "chain-unknown":
        chain["unknown"] = 1
    if case in ("wall", "gate", "egress"):
        session[{"wall": "wall_ms", "gate": "gate_ms", "egress": "egress_wait_ms"}[case]] = -1
    if case == "empty-probe":
        probe["items"] = []
    if case == "replay-items":
        session["items"] = ["synthetic"]
    if case == "session-unknown":
        session["unknown"] = 1
    record = fake.history["lives"]["life-0"]["B0"][0]
    if case == "history-keys":
        record["unknown"] = 1
    if case == "history-canary":
        record["canary"] = "synthetic-invalid"
    if case == "history-fault":
        record["fault_points"] = [{"kind": "kill", "session": 1, "turn": 0}]
    if case == "history-state":
        record["expected_state"]["env_state_hash"] = "invalid"
    if case == "history-bool":
        record["est_tokens"] = True
    if case.startswith("account-"):
        fake.data["run_lock"]["account_pool"] = {"account-sorted": ["z", "a"],
                                                 "account-duplicate": ["a", "a"], "account-empty": []}[case]
    if case == "commit":
        fake.data["run_lock"]["benchmark_commit"] = "invalid"
    if case in ("roster-unknown", "c12-unknown", "roster-provisional"):
        target = fake.c12 if case == "c12-unknown" else fake.roster
        target["status" if case == "roster-provisional" else "unknown"] = "provisional"
        fake.commit()
    if case == "unmatched-untimed":
        probe["wall_ms"] = None
        fake.data["items"].pop(probe["items"][0])
    if case == "raised-rule":
        def refuse(context):
            raise RuntimeError("synthetic rule failure")
        monkeypatch.setitem(base.RULES, "planning", replace(base.RULES["planning"], function=refuse))
    if case == "git-failure":
        def unavailable(*args, **kwargs):
            raise OSError("synthetic git failure")
        monkeypatch.setattr(base.subprocess, "run", unavailable)
    payloads = None
    if case in ("duplicate-bar2", "duplicate-controls", "duplicate-history"):
        fake.build()
        payloads = {"bar2": canon(fake.data), "controls": canon(fake.controls), "history": canon(fake.history)}
        container = case.removeprefix("duplicate-")
        key = next(iter(json.loads(payloads[container])))
        payloads[container] = b'{"' + key.encode() + b'":null,' + payloads[container][1:]
    with pytest.raises(base.BaseRefused) as error:
        if payloads is None:
            fake.build(stamp=case != "hash")
        else:
            base.build_base(**payloads, root=fake.root)
    assert (field, reason) in error.value.refusals
    if case in ("status", "hash", "version"):
        assert {f for f, _ in error.value.refusals} == set(base.BASE_FIELDS)


@pytest.mark.parametrize("case,failed,blocked", [
    ("replay-N", "1/6", "0/1"), ("probe-before-N", "1/6", "0/1"),
    ("probe-at-N", "0/1", "0/1"), ("mixed", "1/6", "0/1"),
    ("K10", "0/1", "0/1"), ("absent-system", "1/3", "0/1"),
    ("irrelevant-class", "0/1", "1/6"),
])
def test_passover(fake, case, failed, blocked):
    fake.clear_stops()
    keep = "K10" if case == "K10" else "K100"
    if case.startswith("probe-"):
        checkpoint = 4 if case == "probe-at-N" else 2
        fake.chain()["sessions"][-1]["checkpoint"] = checkpoint
        fake.stop("alpha", "life-0", "B0", keep, "probe", 5, checkpoint, "SYSTEM_FAILURE")
    else:
        fake.stop("alpha", "life-0", "B0", keep, "replay", 4, None, "SYSTEM_FAILURE")
    if case == "mixed":
        fake.stop("alpha", "life-0", "B1", keep, "replay", 3, None, "BLOCKED")
    if case == "irrelevant-class":
        fake.chain()["sessions"][-1]["checkpoint"] = 4
        fake.stop("alpha", "life-0", "B0", keep, "probe", 5, 4, "SYSTEM_FAILURE")
        fake.stop("alpha", "life-0", "B1", keep, "replay", 4, None, "BLOCKED")
    if case == "absent-system":
        fake.remove_arm("beta")
    assert fake.document()["passover"] == {"failed": failed, "blocked": blocked}


@pytest.mark.parametrize("case,rate,untimed", [
    ("stopped", "2/1", 0), ("null", "2/1", 1), ("K10", "47/6", 0), ("prompt", "504/253", 0),
])
def test_rates(fake, case, rate, untimed):
    fake.clear_stops()
    if case in ("stopped", "null"):
        fake.chain()["sessions"][0]["wall_ms"] = None if case == "null" else 9999
        if case == "stopped":
            fake.stop("alpha", "life-0", "B0", "K100", "replay", 1, None, "SYSTEM_FAILURE")
    if case == "K10":
        for s in fake.chain(keep="K10")["sessions"]:
            s["wall_ms"] *= 36
    if case == "prompt":
        fake.data["items"][fake.chain()["sessions"][-1]["items"][0]]["prompt"] = "abcdefghijklmnop"
    document = fake.document()
    assert document["rows"][0]["rate"] == rate
    assert document["base_provenance"]["waits"]["alpha"]["untimed_sessions"] == untimed


def test_marker_fallback(tmp_path, monkeypatch):
    fake = Fake(tmp_path, monkeypatch, marker=False)
    allow_pending(monkeypatch)
    assert fake.document()["rows"][-1] == {"row": "marker", "rate": "4/1"}


def test_control_exclusion_and_neutrality(fake):
    iid = fake.controls["A"]["no_memory"]["items"][0]["item_id"]
    fake.block("oracle_evidence", iid)
    fake.data["items"][iid] = {"life": "life-0", "prompt": "synthetic", "classes":
                               {"alpha": None, "beta": "BLOCKED", "marker": "BLOCKED"}}
    document = fake.document()
    assert document["control_failure"] == "1/3"
    neutrality = document["base_provenance"]["neutrality"]
    assert neutrality["all"]["control_failure"] == "1/3"
    assert neutrality["without_lcmx"]["control_failure"] == "0/1"
    assert neutrality["all"]["passover_counts"]["alpha"] == {"units": 3, "failed": 1, "blocked": 0}
    assert neutrality["without_lcmx"]["passover"] == {"failed": "0/1", "blocked": "1/3"}
    fake.data["items"][iid]["classes"]["alpha"] = "BLOCKED"
    assert fake.document()["control_failure"] == "0/1"
    fake.data["items"].pop(iid)
    assert fake.document()["control_failure"] == "0/1"


def test_locked_artifacts_and_environment(fake, monkeypatch):
    expected = fake.document()
    for path in (base.ROSTER, base.C12):
        (fake.root / path).write_bytes(b'{"status":"provisional"}\n')
    original = subprocess.run
    calls = []

    def sanitized(*args, **kwargs):
        calls.append(kwargs["env"])
        return original(*args, **kwargs)

    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        monkeypatch.setenv(key, "synthetic-invalid")
    monkeypatch.setattr(base.subprocess, "run", sanitized)
    assert fake.document() == expected
    assert calls and all(not set(env) & {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"}
                         for env in calls)


def test_neutrality_rename_permute(fake):
    def comparable(document):
        provenance = document["base_provenance"]
        provenance.pop("containers")
        provenance.pop("artifacts")
        for field in base.RULES:
            provenance[field].pop("artifacts")
        return document

    expected = comparable(fake.document())
    renames = {"alpha": "zeta", "beta": "delta"}
    fake.data["arms"] = {renames.get(k, k): v for k, v in reversed(list(fake.data["arms"].items()))}
    for item in fake.data["items"].values():
        item["classes"] = {renames.get(k, k): v for k, v in reversed(list(item["classes"].items()))}
    fake.roster["systems"] = [{**s, "id": renames[s["id"]]} for s in reversed(fake.roster["systems"])]
    fake.commit()
    actual = comparable(fake.document())
    text = json.dumps(actual)
    for old, new in renames.items():
        text = text.replace(new, old)
    actual = json.loads(text)
    actual["rows"].sort(key=lambda row: row["row"])
    assert actual == expected


def test_neutrality_empty_without_lcmx(fake):
    fake.remove_arm("beta")
    fake.remove_arm("marker")
    disclosure = fake.document()["base_provenance"]["neutrality"]
    assert disclosure["without_lcmx"]["passover"] is None
    assert disclosure["without_lcmx"]["fallback_row_rate"] is None
    assert disclosure["all"]["fallback_row_rate"] == "2/1"


def stage_b_refusal(fake, monkeypatch, case):
    life = fake.dry["lives"][0]
    b0, b1 = (life["branches"][b] for b in ("B0", "B1"))
    if case == "route":
        fake.c2["swap_model"] = "synthetic-wrong"
    if case == "route-equal":
        fake.c11["lanes"]["swap"]["model"] = fake.c2["swap_model"] = fake.c1["pinned_model"]
    if case == "rate-only":
        fake.c11["lanes"]["swap"]["concurrency"] = None
    if case == "runner":
        monkeypatch.setattr(base, "runner_cap", REAL_CAP)
    if case.startswith("lock-"):
        key, value = {"lock-analysis": ("analysis_commit", "invalid"),
                      "lock-versions": ("generator_versions", {"G1": "bad+version"}),
                      "lock-join": ("generator_versions", {"G1": "other"})}[case]
        fake.data["run_lock"][key] = value
    changes = {"identity": ("life", "wrong-id"), "seed": ("seed", life["seed"] + 1),
               "genre": ("genre", "G2"), "version": ("generator_version", "other"),
               "render-shape": ("render_commit", "bad"), "fork-shape": ("fork", 0),
               "late": ("fork", 21), "fork": ("fork", 2)}
    if case in changes:
        key, value = changes[case]
        life[key] = value
    if case == "order":
        fake.dry["lives"].reverse()
    if case == "count":
        fake.dry["lives"].pop()
    if case == "swapped-versions":
        fake.data["run_lock"]["generator_versions"] = dict(G1="synthetic-v2", G2="synthetic-v1")
        fake.data["run_lock"]["generator_version"] = fake.history["generator_version"] = "synthetic-v1+synthetic-v2"
    if case == "below":
        life["bundles"] = []
    if case == "bundle-shape":
        life["bundles"].append(deepcopy(life["bundles"][0]))
    if case == "dry-keys":
        life["extra"] = 1
    if case in ("tokens", "probe-tokens", "hashes"):
        b0[{"tokens": "est_tokens", "probe-tokens": "probe_tokens", "hashes": "content_sha256"}[case]].pop()
    if case == "probes":
        b0["probe_points"] = [20, 60, 120, 199]
    if case in ("swap-diff", "swap"):
        b1["swap"] = [149]
        if case == "swap":
            b0["swap"] = [149]
    if case == "no-fork":
        b1["content_sha256"] = b0["content_sha256"][:]
    if case == "render-unknown":
        life["render_commit"] = "f" * 40
    if case == "render-unrelated":
        benchmark = fake.data["run_lock"]["benchmark_commit"]
        assert run._git(fake.root, "checkout", "--orphan", "synthetic-unrelated") is not None
        fake.commit()
        life["render_commit"] = fake.data["run_lock"]["benchmark_commit"]
        assert run._git(fake.root, "checkout", "--detach", benchmark) is not None
    if case.startswith("render-") and case[7:] in ("src/bicentennial/items", "tiers", "specs/ring0", "schemas"):
        target = fake.root / case[7:] / "synthetic.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("changed code\n")
    for kind in ("missing", "provisional", "shape", "json"):
        prefix = kind + "-"
        if case.startswith(prefix):
            path = case.removeprefix(prefix)
            data = {base.C11: fake.c11, base.C1: fake.c1, base.C2: fake.c2, base.DRY: fake.dry}[path]
            if kind == "provisional":
                data["status"] = "provisional"
            if kind == "shape":
                data.pop("lanes" if path == base.C11 else "pinned_model" if path == base.C1 else "effort")
            if kind in ("missing", "json"):
                fake.commit()
                if kind == "missing":
                    (fake.root / path).unlink()
                else:
                    (fake.root / path).write_bytes(b"{invalid")
                assert run._git(fake.root, "add", path) is not None
                assert run._git(fake.root, "-c", "user.name=Synthetic", "-c", "user.email=synthetic@example.invalid",
                                "-c", "commit.gpgsign=false", "commit", "-m", "synthetic missing") is not None
                fake.data["run_lock"]["benchmark_commit"] = run._git(fake.root, "rev-parse", "HEAD")
                return
    if case.startswith("after-"):
        chain = fake.chain()
        replay, probe = deepcopy(chain["sessions"][3]), deepcopy(chain["sessions"][-1])
        kind = "replay" if case in ("after-replay", "after-checkpoint") else "probe"
        if kind == "probe":
            chain["sessions"][-1]["checkpoint"] = 3
        fake.stop("alpha", "life-0", "B0", "K100", kind, 3 if kind == "replay" else 5,
                  None if kind == "replay" else 3, "SYSTEM_FAILURE")
        if case in ("after-replay", "after-probe-replay"):
            chain["sessions"].append(replay)
        else:
            probe.update(checkpoint=3, index=6)
            iid = "synthetic-later-probe"
            fake.data["items"][iid] = deepcopy(fake.data["items"][probe["items"][0]])
            probe["items"] = [iid]
            chain["sessions"].append(probe)
    fake.commit()


def test_lanes(fake):
    replication = dict(model="synthetic-replication", concurrency=None, rate_per_min=10, accounts=3)
    fake.c11["lanes"]["replication"] = replication
    fake.commit()
    document = fake.document()
    assert document["lanes"] == [dict(name="pinned", concurrency=3, accounts=2, runner_cap=4),
                                 dict(name="swap", concurrency=2, accounts=1, rate_per_min=30, runner_cap=4)]
    assert document["base_provenance"]["lanes_not_drawn"] == replication


def test_allocation(fake):
    cells = [f"synthetic-cell-{i:02d}" for i in range(14)]
    fake.c12["required"] = cells
    fake.dry = dry_set(fake.dry["lives"][0]["render_commit"], cells)
    fake.commit()
    document = fake.document()
    expected = sorted(cells, key=lambda cell: sha256(canon(["ocsim-alloc", 150, cell])).hexdigest())[:6]
    assert set(expected) != set(cells[:6])
    for b, rows in document["alloc_by_b"].items():
        assert [(c, k) for c, k, _ in rows] == [(c, k) for c in cells for k in (20, 60, 120, 200)]
        assert sum(n for _, _, n in rows) == {"150": 90, "200": 120, "250": 150, "300": 180}[b]
    rows = document["alloc_by_b"]["150"]
    totals = {c: sum(n for cell, _, n in rows if cell == c) for c in cells}
    assert totals == {c: 7 if c in expected else 6 for c in cells}
    assert [sum(n for _, checkpoint, n in rows if checkpoint == k) for k in (20, 60, 120, 200)] == [23, 23, 22, 22]
    assert document["base_provenance"]["alloc"]["150"] == dict(
        cells=totals, checkpoints={"20": 23, "60": 23, "120": 22, "200": 22})
    assert [base.alloc_total(b) for b in (150, 200, 250, 300, 151)] == [90, 120, 150, 180, 91]


def test_allocation_dry_cover_every_budget(fake):
    # b=250 gives (cell-05, 20) 4 bundles and b=300 gives it 3, so b=300's counts alone fall short.
    cells = [f"cell-{i:02d}" for i in range(12)]
    commit = fake.dry["lives"][0]["render_commit"]
    fake.c12["required"] = cells
    fake.dry = dry_set(commit, cells)
    fake.commit()
    alloc = {b: {(c, k): n for c, k, n in rows} for b, rows in fake.document()["alloc_by_b"].items()}
    assert alloc["250"]["cell-05", 20] == 4 and alloc["300"]["cell-05", 20] == 3
    need = {pair: max(counts[pair] for counts in alloc.values()) for pair in alloc["300"]}
    for counts, refused in ((alloc["300"], True), (need, False)):
        fake.dry = dry_set(commit, cells)
        for life in fake.dry["lives"]:
            life["bundles"] = [[c, k, n] for (c, k), n in counts.items()]
        fake.commit()
        if refused:
            with pytest.raises(base.BaseRefused) as error:
                fake.build()
            assert ("alloc_by_b", "alloc_by_b:dry_below") in error.value.refusals
        else:
            assert fake.document()["alloc_by_b"]["250"] == [[c, k, alloc["250"][c, k]] for c in cells
                                                           for k in (20, 60, 120, 200)]


def test_lives(fake):
    document = fake.document()
    assert len(document["lives"]) == 48
    for source, life in zip(fake.dry["lives"], document["lives"], strict=True):
        assert life == dict(life=source["life"], fork=source["fork"], swap=150,
                            b0_tokens=source["branches"]["B0"]["est_tokens"],
                            b1_tokens=source["branches"]["B1"]["est_tokens"][source["fork"] - 1:],
                            b0_probe_tokens=[0, 2, 3, 4], b1_probe_tokens=[0, 2, 3, 4])
    assert document["base_provenance"]["swaps"] == {f"ocsim-dry-{i:03d}": 150 for i in range(48)}


@pytest.mark.parametrize("case,reason", [("same", None), ("changed", "c8:bar2_mismatch"),
                                        ("missing", "c8:bar2_mismatch"), ("unknown", "c8:git"),
                                        ("git-failure", "c8:git")])
def test_c8(tmp_path, monkeypatch, case, reason):
    fake = Fake(tmp_path, monkeypatch, extra_files=run.c8_paths(ROOT))
    allow_pending(monkeypatch)
    monkeypatch.setattr(base, "c8_check", REAL_C8)
    if case in ("changed", "missing"):
        target = fake.root / "src/bicentennial/world/scale.py"
        if case == "changed":
            target.write_bytes(target.read_bytes() + b"\n# synthetic change\n")
        else:
            target.unlink()
        benchmark = fake.data["run_lock"]["benchmark_commit"]
        fake.commit()
        fake.data["run_lock"]["benchmark_commit"] = benchmark
    if case == "unknown":
        fake.data["run_lock"]["analysis_commit"] = "f" * 40
    if case == "git-failure":
        original = subprocess.run
        def fail_listing(args, **kwargs):
            if "ls-tree" in args:
                raise OSError("synthetic git failure")
            return original(args, **kwargs)
        monkeypatch.setattr(base.subprocess, "run", fail_listing)
    if case == "same":
        original = subprocess.run
        calls = []
        def sanitized(*args, **kwargs):
            calls.append(kwargs["env"])
            return original(*args, **kwargs)
        for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
            monkeypatch.setenv(key, "synthetic-invalid")
        monkeypatch.setattr(base.subprocess, "run", sanitized)
    if reason:
        with pytest.raises(base.BaseRefused) as error:
            fake.build()
        assert error.value.refusals == (("C-8", reason),)
    else:
        hashes = fake.document()["base_provenance"]["c8"]
        assert hashes["analysis"] == hashes["head"] == run.c8_hash(fake.root)
        assert calls and all(not set(env) & {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"}
                             for env in calls)


def test_render_outside_and_after_stop(fake):
    target = fake.root / "outside.txt"
    target.write_text("outside code\n")
    fake.commit()
    fake.stop("alpha", "life-0", "B0", "K100", "replay", 3, None, "SYSTEM_FAILURE")
    assert any(s["kind"] == "probe" and s["checkpoint"] == 2 for s in fake.chain()["sessions"])
    assert fake.document()["lives"]


def test_rule_sources_and_programming_errors(fake, monkeypatch):
    for field in ("lanes", "alloc_by_b", "lives"):
        assert set(base.STAGE_B) <= set(base.RULES[field].sources)
    assert all(name in base.RULES["lives"].rule for name in ("B-7", "B-17", "B-17a", "B-17b", "B-18", "B-19"))
    assert {"src/bicentennial/world/scale.py", "tests/world/test_schedule.py"} <= set(run._C8_FIXED)
    context = base._Context(canon(fake.data), canon(fake.controls), canon(fake.history), fake.root)
    with pytest.raises(AssertionError, match="unknown artifact"):
        context.artifact("synthetic-unknown.json")
    monkeypatch.setattr(base, "_checkpoints", lambda context: [1])
    with pytest.raises(AssertionError):
        fake.build()
