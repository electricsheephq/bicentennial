"""Real-template, input-refusal, determinism and purity acceptance."""

import ast
import copy
import json
import os
import subprocess
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.run import SCHEMAS
from bicentennial.items.levers import LEVERS
from bicentennial.items.protocol import TRACK_BY_PREFIX
from bicentennial.packs.catalogue import (
    NOT_COVERED,
    TEMPLATES_BY_GENRE,
    generate,
    load_catalogue,
)
from bicentennial.packs.recipes import RECIPES
from bicentennial.render.stream import content
from bicentennial.world.targeted import micro_schedule

ROOT = Path(__file__).resolve().parents[2]
CATALOGUE = ROOT / "packs/catalogue-v0.toml"
C7 = ROOT / "specs/ring0/c7-partial.json"
TIER = ROOT / "tiers/life_specs/t0.toml"


@pytest.fixture(scope="module")
def catalogue():
    return load_catalogue(CATALOGUE, c7_path=C7, tier_path=TIER)


def test_inventory(catalogue):
    assert len(catalogue.rows) == 90
    assert catalogue.seeds() == (1, 2, 3)
    assert catalogue.not_covered == NOT_COVERED + (
        dict(genre="G1", track="Tuesday", reason="every INV row confounded at v0.1"),)
    assert catalogue.c7_sha256 == sha256(C7.read_bytes()).hexdigest()
    assert set(RECIPES) == {(g, t.template_id) for g, ts in TEMPLATES_BY_GENRE.items() for t in ts.values()}
    assert len(RECIPES) == 15
    expected = {
        ("G1", "Drift"): (10, 8, 6), ("G1", "Wake"): (2, 2, 2),
        ("G1", "Recall"): (3, 2, 2), ("G1", "Tuesday"): (2, 2, 0),
        ("G2", "Drift"): (9, 6, 6), ("G2", "Keep"): (5, 6, 6),
        ("G2", "Recall"): (3, 2, 2), ("G2", "Tuesday"): (2, 2, 0),
    }
    for genre in ("G1", "G2"):
        assert len(catalogue.rows_for(genre)) == (41 if genre == "G1" else 49)
        for track in TRACK_BY_PREFIX.values():
            counts = Counter(r.test for r in catalogue.rows_for(genre, track))
            assert tuple(counts[k] for k in ("MFT", "INV", "DIR")) == expected.get((genre, track), (0, 0, 0))
    assert all(1 <= r.sessions <= 3 for r in catalogue.rows)
    obj = catalogue.to_obj()
    assert obj["canary"] == json.loads((SCHEMAS / "item.schema.json").read_bytes())["properties"]["canary"]["enum"][0]
    assert [r.id for r in catalogue.rows] == sorted(catalogue.by_id())
    assert len(catalogue.no_baseline) == 3
    for row in catalogue.rows:
        assert row.lever_key == f"s{row.sessions}-d{row.distance}-{row.wake}"
        if row.wake != "none":
            intrinsic = getattr(TEMPLATES_BY_GENRE[row.genre][row.template], "fault", False)
            assert (row.baseline is None) == intrinsic


def _select(item, context):
    context = unicodedata.normalize("NFC", context)
    return next((o for o in item["options"] if o["tokens"] and all(
        unicodedata.normalize("NFC", t) in context for t in o["tokens"])), None)


def test_real_templates(catalogue, tmp_path, record_property):
    records, timings, deltas, confounded_counts = {}, [], {}, Counter()
    largest_token_difference = 0
    for row in catalogue.rows:
        started = time.process_time()
        life = generate(row, out_dir=tmp_path / row.id)
        elapsed = time.process_time() - started
        timings.append(elapsed)
        try:
            compiled = life.twin.compiled
            assert elapsed < 1, row.id
            assert len(life.schedule.sessions) == row.sessions
            assert len(compiled.records) == 2
            assert len(compiled.bundles) == int(row.twin)
            by_branch = {r["branch"]: r for r in compiled.records}
            if row.twin:
                indexed = {r["item_id"]: r for r in compiled.records}
                assert [indexed[i]["branch"] for i in compiled.bundles[0]["items"]] == ["B0", "B1"]
            else:
                assert len(life.singleton_lives) == 2
            assert by_branch["B0"]["levers"]["distance_sessions"] == row.distance, row.id
            assert all((i["cell_id"], i["track"], i["stage"]) == (row.cell, row.track, row.stage)
                       for i in compiled.items)
            records[row.id] = by_branch
            if row.test == "MFT":
                cuts = {c.branch: c for c in life.twin.cuts}
                metas = {r["item_id"]: r for r in compiled.records}
                for item in compiled.items:
                    context = "".join(content(r) for r in cuts[metas[item["item_id"]]["branch"]].rows)
                    assert _select(item, context) == item["options"][0], row.id
                    assert _select(item, "") != item["options"][0], row.id
        finally:
            life.twin.b1.close()
    record_property("micro_cpu_max_s", str(max(timings)))
    record_property("micro_cpu_total_s", str(sum(timings)))
    for row in catalogue.rows:
        if row.test == "MFT":
            continue
        actual, base = records[row.id], records[row.base]
        if row.test == "INV":
            deltas[row.id] = {}
            confounded = False
            for branch in ("B0", "B1"):
                a, b = actual[branch]["levers"], base[branch]["levers"]
                assert a.keys() == b.keys()
                deltas[row.id][branch] = {lever: dict(base=b[lever], inv=a[lever]) for lever in sorted(a)}
                for lever in sorted(a):
                    if lever == "distance_tokens_est":
                        confounded |= abs(a[lever] - b[lever]) > max(4, (b[lever] + 19) // 20)
                    else:
                        confounded |= a[lever] != b[lever]
                assert actual[branch]["crossed"] == base[branch]["crossed"]
            assert row.lever_delta == deltas[row.id], row.id
            assert row.confounded is confounded, row.id
            if confounded:
                confounded_counts[row.genre, row.track] += 1
            else:
                largest_token_difference = max(largest_token_difference, *(abs(
                    actual[b]["levers"]["distance_tokens_est"] - base[b]["levers"]["distance_tokens_est"])
                    for b in ("B0", "B1")))
        else:
            a, b = actual["B0"]["levers"], base["B0"]["levers"]
            if row.vary == "distance":
                assert a["distance_sessions"] == b["distance_sessions"] + 1
            elif row.wake == "kill":
                assert a["wake_events"] == b["wake_events"] + 1
                assert "crash" in actual["B0"]["crossed"]
            elif row.wake == "compaction":
                assert "compaction" in actual["B0"]["crossed"] and "compaction" not in base["B0"]["crossed"]
            else:
                assert a["distance_s"] > b["distance_s"]
    record_property("inv_token_deltas", json.dumps(deltas, sort_keys=True))
    record_property("confounded_counts", json.dumps({f"{g}/{t}": n for (g, t), n in sorted(confounded_counts.items())}))
    record_property("largest_unconfounded_token_difference", largest_token_difference)
    assert confounded_counts == {("G1", "Tuesday"): 2, ("G2", "Keep"): 1, ("G2", "Tuesday"): 1}
    assert not catalogue.by_id()["g1-drift-chain-inv-1"].confounded


def test_plain_seed_changes_distance(catalogue, tmp_path, record_property):
    base = catalogue.by_id()["g1-drift-chain-mft-1"]
    template = TEMPLATES_BY_GENRE[base.genre][base.template]
    first = micro_schedule(base.micro_spec(), template)
    plain = micro_schedule(replace(base.micro_spec(), seed=2), template)
    pinned = micro_schedule(replace(base.micro_spec(), seed=2, schedule_seed=1), template)
    assert first.sessions == pinned.sessions
    assert first.sessions[2].gap_before_s != plain.sessions[2].gap_before_s
    assert catalogue.by_id()["g1-drift-chain-inv-1"].micro_spec().schedule_seed == 1
    distances = []
    for row in (base, replace(base, seed=2)):
        life = generate(row, out_dir=tmp_path / str(row.seed))
        try:
            distances.append(next(r["levers"]["distance_s"] for r in life.twin.compiled.records
                                  if r["branch"] == "B0"))
        finally:
            life.twin.b1.close()
    assert distances == [12437, 39336]
    record_property("plain_seed_distance_s", json.dumps(distances))


def _toml(value):
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{k} = {_toml(v)}" for k, v in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(_toml(v) for v in value) + "]"
    return json.dumps(value)


@pytest.mark.parametrize(("ident", "case"), (
    ("g2-keep-neighbour-inv-2", "false-flag"),
    ("g1-drift-chain-inv-1", "true-flag"),
    *(("g1-drift-chain-inv-1", case) for case in (
        "null", "[]", "{}", "missing-B1", "extra-branch",
        *(f"{branch}:{case}" for branch in ("B0", "B1") for case in (
            "missing-lever", "extra-lever", "true-lever", "missing-side", "extra-side",
            "bool-base", "bool-inv", "float-value", "null-distance", "string-distance",
        )),
    )),
))
def test_inv_delta_refusals(monkeypatch, ident, case):
    import tomllib

    data = tomllib.loads(CATALOGUE.read_text())
    row = next(r for r in data["rows"] if r["id"] == ident)
    delta = json.loads(row["lever_delta"])
    if case in ("false-flag", "true-flag"):
        row["confounded"] = case == "true-flag"
    elif case in ("null", "[]", "{}"):
        delta = json.loads(case)
    elif case == "missing-B1":
        del delta["B1"]
    elif case == "extra-branch":
        delta["B2"] = copy.deepcopy(delta["B0"])
    else:
        branch, mutation = case.split(":")
        lever = next(name for name in LEVERS if name != "distance_tokens_est")
        values = delta[branch][lever]
        if mutation == "missing-lever":
            del delta[branch][lever]
        elif mutation == "extra-lever":
            delta[branch]["extra"] = dict(base=0, inv=0)
        elif mutation == "true-lever":
            delta[branch][lever] = True
        elif mutation == "missing-side":
            del values["inv"]
        elif mutation == "extra-side":
            values["extra"] = 0
        elif mutation in ("bool-base", "bool-inv"):
            values[mutation.removeprefix("bool-")] = True
        elif mutation == "float-value":
            values["inv"] = float(values["base"])  # equal value: only the int-type rule can refuse it
        elif mutation == "null-distance":
            delta[branch]["distance_tokens_est"]["base"] = None
        elif mutation == "string-distance":
            delta[branch]["distance_tokens_est"]["inv"] = "139"
    row["lever_delta"] = json.dumps(delta)
    edited = "\n".join(f"{k} = {_toml(v)}" for k, v in data.items())
    read_text = Path.read_text

    def edited_read_text(path, *args, **kwargs):
        return edited if path == CATALOGUE else read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", edited_read_text)
    with pytest.raises(ValueError, match=f"^{ident}$"):
        load_catalogue(CATALOGUE, c7_path=C7, tier_path=TIER)


def test_shipped_confounded_rows(catalogue):
    assert {r.id for r in catalogue.rows if r.confounded} == {
        "g1-tue-ticket-inv-1", "g1-tue-ticket-inv-2",
        "g2-keep-neighbour-inv-2", "g2-tue-passport-inv-2",
    }


@pytest.mark.parametrize("case", (
    "extra", "duplicate-id", "duplicate-vector", "canary", "label", "hash", "template", "cell", "stage",
    "missing-c7", "direction", "inv-distance", "dir-distance", "kill-base", "dir-base", "gate", "zero-wake",
    "covered", "baseline-dangling", "baseline-self", "baseline-faulted", "baseline-null", "baseline-intrinsic",
    "baseline-missing", "baseline-unfaulted", "schedule-seed", "schedule-seed-missing", "top-key", "no-baseline",
    "confounded-missing", "delta-missing", "confounded-type", "delta-json", "confounded-coverage",
))
def test_catalogue_refusals(tmp_path, case):
    import tomllib

    data = tomllib.loads(CATALOGUE.read_text())
    rows = {r["id"]: r for r in data["rows"]}
    mft = rows["g1-recall-value-mft-1"]
    inv = rows["g1-recall-value-inv-1"]
    direction = rows["g1-recall-value-dir-1"]
    kill = rows["g1-recall-value-dir-2"]
    c7 = json.loads(C7.read_bytes())
    if case == "extra":
        mft["extra"] = 1
    elif case == "duplicate-id":
        data["rows"].append(copy.deepcopy(mft))
    elif case == "duplicate-vector":
        data["rows"].append(mft | {"id": "g1-recall-value-mft-99"})
    elif case == "canary":
        data["canary"] = "invalid"
    elif case == "label":
        data["levers_label"] = "other"
    elif case == "hash":
        data["c7_sha256"] = "0" * 64
    elif case == "template":
        mft["template"] = "missing"
    elif case == "cell":
        mft["cell"] = "DRIFT-CUR"
    elif case == "stage":
        kill["stage"] = "remember"
    elif case == "missing-c7":
        del c7["entries"]["recall-value-v1"]
    elif case == "direction":
        c7["entries"]["recall-value-v1"]["direction"] = "none"
    elif case == "inv-distance":
        inv["distance"] = 0
    elif case == "dir-distance":
        direction["distance"] = mft["distance"] + 2
    elif case == "kill-base":
        kill["base"] = "g1-drift-chain-fault-mft-1"
    elif case == "dir-base":
        inv["base"] = direction["id"]
    elif case == "gate":
        del rows["g1-tue-ticket-mft-1"]["gate"]
    elif case == "zero-wake":
        kill["distance"] = 0
    elif case == "covered":
        data["not_covered"][0]["track"] = "Drift"
    elif case == "baseline-dangling":
        kill["baseline"] = "absent"
    elif case == "baseline-self":
        kill["baseline"] = kill["id"]
    elif case == "baseline-faulted":
        kill["baseline"] = "g1-drift-chain-fault-mft-1"
    elif case == "baseline-null":
        kill["baseline"] = ""
    elif case == "baseline-intrinsic":
        rows["g1-drift-chain-fault-mft-1"]["baseline"] = mft["id"]
    elif case == "baseline-missing":
        del kill["baseline"]
    elif case == "baseline-unfaulted":
        mft["baseline"] = inv["id"]
    elif case == "schedule-seed":
        inv["schedule_seed"] = 2
    elif case == "schedule-seed-missing":
        del inv["schedule_seed"]
    elif case == "top-key":
        data["extra"] = 1
    elif case == "no-baseline":
        data["no_baseline"] = []
    elif case == "confounded-missing":
        del inv["confounded"]
    elif case == "delta-missing":
        del inv["lever_delta"]
    elif case == "confounded-type":
        inv["confounded"] = 1
    elif case == "delta-json":
        inv["lever_delta"] = "invalid-json"
    elif case == "confounded-coverage":
        data["not_covered"].pop()
    c7_path = tmp_path / "c7.json"
    c7_path.write_bytes(canon(c7))
    if case != "hash":
        data["c7_sha256"] = sha256(c7_path.read_bytes()).hexdigest()
    path = tmp_path / "catalogue.toml"
    path.write_text("\n".join(f"{k} = {_toml(v)}" for k, v in data.items()))
    with pytest.raises(ValueError) as refused:
        load_catalogue(path, c7_path=c7_path, tier_path=TIER)
    if case == "delta-json":
        assert str(refused.value) == "catalogue-v0"


def test_passport_manifest_determinism(catalogue, tmp_path):
    row = catalogue.by_id()["g2-tue-passport-mft-1"]
    manifests = []
    for i in range(2):
        life = generate(row, out_dir=tmp_path / str(i))
        try:
            manifests.append(canon(life.manifest))
        finally:
            life.twin.b1.close()
    assert manifests[0] == manifests[1]


def test_hash_seed_determinism():
    script = '''from pathlib import Path
from bicentennial.canon import canon
from bicentennial.packs.catalogue import load_catalogue
from bicentennial.packs.relations import check
c = load_catalogue(Path("packs/catalogue-v0.toml"), c7_path=Path("specs/ring0/c7-partial.json"), tier_path=Path("tiers/life_specs/t0.toml"))
o = {r.id: {b: dict(failure_class=None, score_milli=1000) for b in (("B0", "B1") if r.twin else ("B0",))} for r in c.rows}
print(canon([c.to_obj(), check(c.rows, o).to_obj()]).decode())
'''
    outputs = [subprocess.check_output([sys.executable, "-c", script], cwd=ROOT,
                                      env=os.environ | {"PYTHONHASHSEED": seed}) for seed in ("0", "random")]
    assert outputs[0] == outputs[1]


def test_purity():
    forbidden = ("random", "time", "socket", "ssl", "http", "urllib", "subprocess", "bicentennial.sandbox",
                 "bicentennial.director", "bicentennial.genres.g1_software.repo",
                 "bicentennial.genres.g1_software.diffs", "spikes")
    allowed = {"bicentennial.canon", "bicentennial.score.bundle", "bicentennial.contracts.bundle"}
    for path in sorted((ROOT / "src/bicentennial/packs").glob("*.py")):
        tree = ast.parse(path.read_text())
        modules = [name.name for n in ast.walk(tree) if isinstance(n, ast.Import) for name in n.names]
        modules += [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        assert not any(m == bad or m.startswith(bad + ".") for m in modules for bad in forbidden)
        assert not any(isinstance(n, ast.Constant) and type(n.value) is float for n in ast.walk(tree))
        if path.name == "relations.py":
            assert set(modules) == allowed
