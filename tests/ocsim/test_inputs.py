"""Synthetic bar-2 pipeline acceptance and mutation witnesses."""

import json
import platform
import random
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.bundle import NONRESULTS
from bicentennial.ocsim import inputs, locate, model, run
from bicentennial.stats import variance_inputs as vi

ROOT = Path(__file__).resolve().parents[2]
REQUIRED = ("action", "timing")


def sample(extra=False, lives=6):
    data, expected = {"A": {}, "A_prime": {}, "branches": {}}, []
    for name in ("A", "A_prime"):
        for arm, label in inputs.ARMS.items():
            output = data[name][arm] = dict(items=[], bundles=[], singleton_lives={}, reports=[])
            for life in range(lives if name == "A" else min(3, lives)):
                for cell in (*REQUIRED, *(("unused",) if extra else ())):
                    pairs = ((-1000, -1000), (0, 1000), (1000, 0), (1000, 1000))
                    if cell == "timing":
                        pairs = (([-250, 0, 125, 375, 875, 1000][life], 1000),)
                    if cell == "unused":
                        pairs = ((1000, 1000), (1000, 1000))
                    for j, (b0, b1) in enumerate(pairs):
                        bid = f"{cell}-{life}-{j}"
                        ids = [bid + "-z", bid + "-a"]
                        for iid, branch, score in zip(ids, ("B0", "B1"), (b0, b1), strict=True):
                            data["branches"][iid] = branch
                            output["items"].append(dict(item_id=iid, cell_id=cell, stage="act",
                                                        track="Tuesday" if cell == "timing" else "Wake",
                                                        failure_class=None, score_milli=score))
                        output["bundles"].append(dict(bundle_id=bid, cell_id=cell,
                                                      life=f"life-{life}", items=sorted(ids)))
                        if cell in REQUIRED:
                            expected.append(vi.ControlRecord(label, name, f"life-{life}", cell,
                                                             0, bid, b0, b1))
    return data, tuple(sorted(expected, key=lambda r: (r.run, r.arm, r.bundle)))


def base_bytes():
    base = json.loads((ROOT / "tests/fixtures/ocsim/planning.json").read_bytes())
    for key in ("params", "latent_flags", "sensitivity_params", "c8_hash"):
        base.pop(key)
    base["required"] = list(REQUIRED)
    base["alloc_by_b"] = {str(b): [[c, k, 1] for c in REQUIRED for k in base["checkpoints"]]
                          for b in sorted({b for _, b in run.LADDER})}
    return canon(base) + b"\n"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(run, "c8_dirty", lambda root: False)


@pytest.fixture(scope="module")
def default():
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(run, "c8_dirty", lambda root: False)
        records, base = b"\n" + canon(sample()[0]) + b" \n", base_bytes()
        document = inputs.build(records, base, root=ROOT)
    return records, base, document


def test_mapping():
    data, expected = sample(extra=True)
    rows, timing = inputs.load(canon(data), REQUIRED)
    assert rows == expected and timing == frozenset({"timing"})
    assert vi.estimate(rows, timing_cells=timing) == vi.estimate(expected, timing_cells=timing)


@pytest.mark.parametrize("failure,score", [(f, None) for f in NONRESULTS]
                         + [("SYSTEM_FAILURE", 0), ("FAIL_TASK", 0)])
def test_item_rules(failure, score):
    assert inputs.NONRESULTS == NONRESULTS
    data, _ = sample()
    data["A"]["no_memory"]["items"][0].update(failure_class=failure, score_milli=score)
    rows, timing = inputs.load(canon(data), REQUIRED)
    assert vi.estimate(rows, timing_cells=timing).n_nonresult == (1 if score is None else 0)


@pytest.mark.parametrize("case,message", [
    ("singleton", "twin-only"), ("unbundled", "twin-only"), ("stage", "twin-only"),
    ("orientation", "B0 and B1"), ("branch", "missing branch"), ("bad_branch", "bad branch"),
    ("prime_id", "A′ bundle"), ("prime_life", "A′ bundle"), ("prime_cell", "A′ bundle"),
    ("prime_items", "A′ bundle"), ("prime_item", "A′ item"),
    ("top", "run/key"), ("run", "run/key"), ("arm", "arm"), ("track", "tracks"),
    ("duplicate_item", "duplicate item"), ("duplicate_bundle", "duplicate bundle"),
    ("cross_life", "identity"), ("cross_cell", "identity"), ("cross_items", "identity"),
    ("null", "non-result"), ("blocked", "non-result"), ("failure", "score 0"),
    ("null_task", "non-result"),
    ("range", "out of range"), ("unsorted", "sorted"),
])
def test_refusals(case, message):
    data, _ = sample(extra=True)
    arm = data["A"]["no_memory"]
    item, bundle = arm["items"][0], arm["bundles"][0]
    prime = data["A_prime"]["no_memory"]
    required = REQUIRED
    if case == "singleton":
        arm["singleton_lives"][item["item_id"]] = "life-0"
    if case == "unbundled":
        arm["bundles"].pop(0)
    if case == "stage":
        item["stage"] = "remember"
    if case == "orientation":
        data["branches"][item["item_id"]] = "B1"
    if case == "branch":
        del data["branches"][item["item_id"]]
    if case == "bad_branch":
        data["branches"]["unused-id"] = "B2"
    if case.startswith("prime_") and case != "prime_item":
        key, value = {"prime_id": ("bundle_id", "absent"), "prime_life": ("life", "other"),
                      "prime_cell": ("cell_id", "other"),
                      "prime_items": ("items", prime["bundles"][1]["items"])}[case]
        prime["bundles"][0][key] = value
        if case == "prime_cell":
            for row in prime["items"][:2]:
                row["cell_id"] = "other"
    if case == "prime_item":
        prime["items"][0]["item_id"] = "absent"
    if case == "top":
        data["reports"] = []
    if case == "run":
        data["B"] = data.pop("A_prime")
    if case == "arm":
        data["A"]["keep"] = arm
    if case == "track":
        data["A_prime"]["oracle_evidence"]["items"][-1]["track"] = "Drift"
    if case == "duplicate_item":
        arm["items"].append(deepcopy(item))
    if case == "duplicate_bundle":
        arm["bundles"].append(deepcopy(bundle))
    if case.startswith("cross_"):
        other = data["A"]["oracle_evidence"]
        key, value = {"cross_life": ("life", "other"), "cross_cell": ("cell_id", "other"),
                      "cross_items": ("items", other["bundles"][1]["items"])}[case]
        other["bundles"][0][key] = value
        if case == "cross_cell":
            for row in other["items"][:2]:
                row["cell_id"] = "other"
    if case == "null":
        item.update(failure_class=None, score_milli=None)
    if case == "null_task":
        item.update(failure_class="FAIL_TASK", score_milli=None)
    if case == "blocked":
        item.update(failure_class="BLOCKED", score_milli=0)
    if case == "failure":
        item.update(failure_class="FAIL_TASK", score_milli=1000)
    if case == "range":
        item["score_milli"] = 1001
    if case == "unsorted":
        required = tuple(reversed(REQUIRED))
    with pytest.raises(ValueError, match=message):
        inputs.load(canon(data), required)


@pytest.mark.parametrize("lives", [3, 4])
def test_coverage(lives, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("estimate called before coverage/dirty checks")
    monkeypatch.setattr(vi, "estimate", unexpected)
    if lives == 3:
        with pytest.raises(ValueError, match="coverage action: 3 lives; need at least 4"):
            inputs.build(canon(sample(lives=lives)[0]), base_bytes(), root=ROOT)
    else:
        assert inputs.load(canon(sample(lives=lives)[0]), REQUIRED)[0]


def test_orientation(default):
    records, base, document = default
    data = json.loads(records)
    for index in (1, 6):
        for iid in data["A"]["no_memory"]["bundles"][index]["items"]:
            data["branches"][iid] = "B1" if data["branches"][iid] == "B0" else "B0"
    original = json.loads(document)["params"]
    assert -1 < float.fromhex(original["rho_t"]) < 1
    changed = json.loads(inputs.build(canon(data), base, root=ROOT))["params"]
    assert changed != original and changed["rho_t"] != original["rho_t"]


def test_round_trip_flags_timing(default):
    records, base, document = default
    parsed = run._parse_inputs(document, root=ROOT)
    rows, timing = inputs.load(records, REQUIRED)
    moments = vi.estimate(rows, timing_cells=timing)
    params, flags = vi.to_latent(moments)
    assert moments.flags and parsed.latent_flags == tuple(sorted(set(moments.flags) | set(flags)))
    assert parsed.params == params and parsed.sensitivity_params == {}
    assert parsed.c8_hash == run.c8_hash(ROOT)
    assert tuple(len(c.levels) for c in params.cells) == (3, 8)
    assert json.loads(document)["provenance"] == {
        "records_sha256": sha256(records).hexdigest(), "base_sha256": sha256(base).hexdigest(),
        "platform": platform.platform(), "python": platform.python_version()}


@pytest.mark.parametrize("kind", ["repeat", "shuffle", "extra"])
def test_determinism_filter(default, kind):
    records, base, document = default
    data = sample(extra=True)[0] if kind == "extra" else json.loads(records)
    if kind == "shuffle":
        rng = random.Random(42)
        for name in ("A", "A_prime"):
            for arm in data[name].values():
                rng.shuffle(arm["items"])
                rng.shuffle(arm["bundles"])
    source = records if kind == "repeat" else canon(data)
    actual = inputs.build(source, base, root=ROOT)
    if kind == "repeat":
        assert actual == document
    left, right = json.loads(actual), json.loads(document)
    assert left["provenance"].pop("records_sha256") == sha256(source).hexdigest()
    right["provenance"].pop("records_sha256")
    assert left == right


@pytest.mark.parametrize("case", ["cells", "flag", "dirty", "table", "margin", "roundtrip"])
def test_build_refusals(default, monkeypatch, case):
    records, base, document = default
    params = run._parse_inputs(document, root=ROOT).params
    monkeypatch.setattr(vi, "to_latent", lambda _: (params, ()))
    message = {"cells": "latent cells", "flag": "unknown flag", "dirty": "C-8: dirty",
               "table": "cell timing margin table", "margin": "cell timing margin 0",
               "roundtrip": "round trip"}[case]
    if case == "cells":
        monkeypatch.setattr(vi, "to_latent", lambda _: (replace(params, cells=params.cells[:1]), ()))
    if case == "flag":
        monkeypatch.setattr(vi, "to_latent", lambda _: (params, ("unknown",)))
    if case == "dirty":
        monkeypatch.setattr(run, "c8_dirty", lambda root: True)
        monkeypatch.setattr(vi, "estimate", lambda *a, **k: pytest.fail("estimate before dirty check"))
    if case in ("table", "margin"):
        module, name = (locate, "build_table") if case == "table" else (model, "interpolation")
        original = getattr(module, name)
        def check(cell, value):
            if cell.cell == "timing":
                raise ValueError("synthetic refusal")
            return original(cell, value)
        monkeypatch.setattr(module, name, check)
    if case == "roundtrip":
        original = run._parse_inputs
        monkeypatch.setattr(run, "_parse_inputs", lambda *a, **k: replace(original(*a, **k), params=replace(params, rho_t=1.0)))
    with pytest.raises(ValueError, match=message):
        inputs.build(records, base, root=ROOT)


def test_c8():
    assert {"src/bicentennial/ocsim/inputs.py", "tests/ocsim/test_inputs.py"} <= set(run.c8_paths(ROOT))


def test_main(default, tmp_path, capsys):
    records, base, document = default
    paths = [tmp_path / name for name in ("records", "base", "out")]
    paths[0].write_bytes(records)
    paths[1].write_bytes(base)
    argv = [part for name, path in zip(("records", "base", "out"), paths, strict=True)
            for part in (f"--{name}", str(path))]
    inputs.main(argv)
    assert paths[2].read_bytes() == document
    assert capsys.readouterr().out.strip() == f"{paths[2]} {sha256(document).hexdigest()}"
    with pytest.raises(ValueError, match="output already exists"):
        inputs.main(argv)
    assert paths[2].read_bytes() == document
