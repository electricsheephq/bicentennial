"""Synthetic bar-2 pipeline acceptance and mutation witnesses."""

import json
import os
import platform
import random
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.contracts.bundle import NONRESULTS
from bicentennial.ocsim import fitcheck, gaussian, inputs, locate, model, run
from bicentennial.stats import tcal
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
                        pairs = (([-250, 0, 125, 375, 875, 1000][life % 6], 1000),)
                    if cell == "unused":
                        pairs = ((1000, 1000), (1000, 1000))
                    for j, (b0, b1) in enumerate(pairs):
                        bid = f"{cell}-{life}-{j}"
                        ids = [bid + "-z", bid + "-a"]
                        for iid, branch, score in zip(ids, ("B0", "B1"), (b0, b1), strict=True):
                            data["branches"][iid] = branch
                            output["items"].append(dict(item_id=iid, cell_id=cell,
                                                        stage="remember" if cell == "unused" and j == 0 else "act",
                                                        track="Tuesday" if cell == "timing" else "Wake",
                                                        failure_class=None, score_milli=score))
                        output["bundles"].append(dict(bundle_id=bid, cell_id=cell,
                                                      life=f"life-{life}", items=sorted(ids)))
                        if cell in REQUIRED:
                            expected.append(vi.ControlRecord(label, name, f"life-{life}", cell,
                                                             0, bid, b0, b1))
            if extra and name == "A":
                output["items"].append(dict(item_id="unused-singleton", cell_id="unused",
                                            stage="remember", track="Wake", failure_class=None, score_milli=0))
                output["singleton_lives"]["unused-singleton"] = "life-0"
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
        document = inputs.build(records, base, root=ROOT, resamples=3)
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
    ("cross_life", "across arms/runs"), ("cross_cell", "across arms/runs"),
    ("cross_items", "across arms/runs"),
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
        target = next(b for b in other["bundles"] if b["life"] == "life-3")
        pair = [i for i in other["items"] if i["item_id"] in target["items"]]
        fresh = [dict(i, item_id=i["item_id"] + "-fresh") for i in pair]
        key, value = {"cross_life": ("life", "other"), "cross_cell": ("cell_id", "other"),
                      "cross_items": ("items", [i["item_id"] for i in fresh])}[case]
        target[key] = value
        if case == "cross_cell":
            for row in pair:
                row["cell_id"] = "other"
        if case == "cross_items":
            for old, new in zip(pair, fresh, strict=True):
                other["items"].remove(old)
                other["items"].append(new)
                data["branches"][new["item_id"]] = data["branches"][old["item_id"]]
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
    with pytest.raises(ValueError, match=message) as error:
        inputs.load(canon(data), required)
    if case == "singleton":
        assert "bad singleton" in str(error.value)


@pytest.mark.parametrize("case", [
    "arm_list", "items_type", "bundles_type", "singletons_type", "item_object", "item_stage",
    "item_failure_class", "item_id", "item_cell", "bundle_object", "bundle_life", "bundle_id",
    "bundle_cell", "bundle_items", "bundle_member", "two_bundles", "inflated_life", "stray_branch",
    "singleton_unknown", "singleton_prime", "singleton_value", "prime_stage", "prime_track",
    "prime_cell", "duplicate_key", "prime_unbundled",
])
def test_container_refusals(case):
    data, _ = sample(extra=True)
    arm, prime = data["A"]["no_memory"], data["A_prime"]["no_memory"]
    item, bundle = arm["items"][0], arm["bundles"][0]
    where, message = "A no_memory", "malformed arm"
    if case == "arm_list":
        data["A"]["no_memory"] = []
    if case in ("items_type", "bundles_type", "singletons_type"):
        arm[{"items_type": "items", "bundles_type": "bundles", "singletons_type": "singleton_lives"}[case]] = None
    if case.startswith("item_"):
        where, message = where + " item " + item["item_id"], "malformed item"
        if case in ("item_stage", "item_failure_class"):
            del item[case.removeprefix("item_")]
        else:
            key = "item_id" if case == "item_id" else "cell_id"
            item[key] = 3
            if case in ("item_id", "item_object"):
                where = "A no_memory item #0"
            if case == "item_object":
                arm["items"][0] = None
    if case.startswith("bundle_"):
        where, message = where + " bundle " + bundle["bundle_id"], "malformed bundle"
        if case == "bundle_life":
            del bundle["life"]
        else:
            key = {"bundle_id": "bundle_id", "bundle_cell": "cell_id"}.get(case, "items")
            bundle[key] = [3] if case == "bundle_member" else 3
            if case in ("bundle_id", "bundle_object"):
                where = "A no_memory bundle #0"
            if case == "bundle_object":
                arm["bundles"][0] = None
    if case in ("two_bundles", "inflated_life"):
        message, where = "item in two bundles", "A no_memory item " + bundle["items"][0]
        for output in ([arm] if case == "two_bundles" else data["A"].values()):
            originals = [bundle] if case == "two_bundles" else [
                b for b in output["bundles"] if b["life"] == "life-0" and b["cell_id"] == "action"]
            output["bundles"].extend(dict(b, bundle_id=b["bundle_id"] + "-copy", life="life-9") for b in originals)
    if case == "stray_branch":
        data["branches"]["stray"] = "B0"
        where, message = "A/A_prime no_memory/oracle_evidence item stray", "branch for an item in no arm"
    if case.startswith("singleton_"):
        target = prime if case == "singleton_prime" else arm
        iid = item["item_id"] if case == "singleton_prime" else "unused-singleton" if case == "singleton_value" else "absent"
        target["singleton_lives"][iid] = 3 if case == "singleton_value" else "life-0"
        where, message = f"{'A_prime' if target is prime else 'A'} no_memory item {iid}", "bad singleton"
    if case in ("prime_stage", "prime_track", "prime_cell"):
        original = next(i for i in arm["items"] if i["item_id"] == "unused-singleton")
        key = case.removeprefix("prime_") + ("_id" if case == "prime_cell" else "")
        prime["items"].append(dict(original, **{key: {"stage": "survive", "track": "Drift"}.get(key, "different")}))
        where, message = "A_prime no_memory item unused-singleton", f"A′ item differs from A: {key}"
    if case == "prime_unbundled":
        prime["bundles"].pop(0)
        where, message = "A_prime no_memory item " + item["item_id"], "A′ required-cell item outside every A′ bundle"
    records = canon(data)
    if case == "duplicate_key":
        records = records.replace(b'"score_milli":-1000', b'"score_milli":-1000,"score_milli":-1000', 1)
        where, message = "container", "duplicate key score_milli"
    with pytest.raises(ValueError) as error:
        inputs.load(records, REQUIRED)
    assert str(error.value).startswith(where + ":")
    assert message in str(error.value)
    if case in ("two_bundles", "inflated_life"):
        assert bundle["bundle_id"] in str(error.value) and bundle["bundle_id"] + "-copy" in str(error.value)


def test_coverage_valid_in_both_arms():
    data, _ = sample()
    for name, lives in (("no_memory", {"life-0", "life-1"}), ("oracle_evidence", {"life-4", "life-5"})):
        arm = data["A"][name]
        ids = {b["items"][0] for b in arm["bundles"] if b["cell_id"] == "action" and b["life"] in lives}
        for item in arm["items"]:
            if item["item_id"] in ids:
                item.update(failure_class="BLOCKED", score_milli=None)
    with pytest.raises(ValueError, match="coverage action: 2 lives; need at least 4"):
        inputs.load(canon(data), REQUIRED)


@pytest.mark.parametrize("lives", [3, 4])
def test_coverage(lives, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("estimate called before coverage/dirty checks")
    monkeypatch.setattr(vi, "estimate", unexpected)
    if lives == 3:
        with pytest.raises(ValueError, match="coverage action: 3 lives; need at least 4"):
            inputs.build(canon(sample(lives=lives)[0]), base_bytes(), root=ROOT, resamples=3)
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
    changed = json.loads(inputs.build(canon(data), base, root=ROOT, resamples=3))["params"]
    assert changed != original and changed["rho_t"] != original["rho_t"]


def test_round_trip_flags_timing(default):
    records, base, document = default
    parsed = run._parse_inputs(document, root=ROOT)
    rows, timing = inputs.load(records, REQUIRED)
    moments = vi.estimate(rows, timing_cells=timing)
    params, flags = vi.to_latent(moments)
    assert moments.flags and set(moments.flags) | set(flags) <= set(parsed.latent_flags)
    assert json.loads(document)["latent_flags"] == sorted(set(parsed.latent_flags))
    assert parsed.params == params and set(parsed.sensitivity_params) == {"inputs_low", "inputs_high"}
    assert parsed.c8_hash == run.c8_hash(ROOT)
    assert tuple(len(c.levels) for c in params.cells) == (3, 8)
    provenance = json.loads(document)["provenance"]
    assert provenance.pop("inputs_bootstrap")["failed"] == 0
    assert provenance == {
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
    actual = inputs.build(source, base, root=ROOT, resamples=3)
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
        inputs.build(records, base, root=ROOT, resamples=3)


def test_build_check_arguments(default, monkeypatch):
    records, base, document = default
    params = run._parse_inputs(document, root=ROOT).params
    tables, margins = [], []
    original_table, original_margin = locate.build_table, model.interpolation
    def table(cell, rho_t):
        tables.append((cell, rho_t))
        return original_table(cell, rho_t)
    def margin(cell, value):
        margins.append((cell.cell, value))
        return original_margin(cell, value)
    monkeypatch.setattr(locate, "build_table", table)
    monkeypatch.setattr(model, "interpolation", margin)
    assert inputs.build(records, base, root=ROOT, resamples=3) == document
    assert params.rho_t != 0.0
    ends = run._parse_inputs(document, root=ROOT).sensitivity_params
    assert tables == [(cell, p.rho_t) for p in (params, ends["inputs_low"], ends["inputs_high"]) for cell in p.cells]
    assert set(margins) == {(cell, value) for config in run.margin_grid(REQUIRED)
                            for cell, value in config.margins}


def test_c8():
    assert {"src/bicentennial/ocsim/inputs.py", "tests/ocsim/test_inputs.py"} <= set(run.c8_paths(ROOT))


def test_main(default, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(inputs, "RESAMPLES", 3)
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


@pytest.mark.parametrize("key,value", [("failure_class", "PASS"), ("failure_class", 5),
                         ("failure_class", "FAIL_TASK "), ("track", "tuesday"), ("stage", "acting")])
def test_enum_refusals(key, value):
    data, _ = sample()
    data["A"]["no_memory"]["items"][0].update({key: value, "score_milli": 1000})
    with pytest.raises(ValueError, match="A no_memory item .*: malformed item"):
        inputs.load(canon(data), REQUIRED)


def test_enum_copies():
    props = json.loads((ROOT / "schemas/card_ring0.schema.json").read_bytes())["properties"]["items"]["items"]["properties"]
    for key, values in (("failure_class", inputs.FAILURE_CLASSES), ("track", inputs.TRACKS), ("stage", inputs.STAGES)):
        assert list(values) == props[key]["enum"]


@pytest.mark.parametrize("case", ["track_A", "missing_A", "missing_prime", "changed_life", "bundled_in_A"])
def test_track_singleton_followups(case):
    data, _ = sample(extra=True)
    arm, prime = data["A"]["no_memory"], data["A_prime"]["no_memory"]
    where, message = "A no_memory item", "missing singleton"
    if case == "track_A":
        data["A"]["oracle_evidence"]["items"][-1]["track"] = "Drift"
        where, message = "A oracle_evidence item", "conflicting tracks"
    elif case == "missing_A":
        arm["singleton_lives"].clear()
    elif case in ("changed_life", "missing_prime"):
        prime["items"].append(deepcopy(arm["items"][-1]))
        if case == "changed_life":
            prime["singleton_lives"]["unused-singleton"] = "other-life"
        where = "A_prime no_memory item"
        if case == "changed_life":
            message = "A′ singleton differs from A"
    else:
        bundle = next(b for b in prime["bundles"] if b["cell_id"] == "unused")
        prime["bundles"].remove(bundle)
        prime["singleton_lives"].update((iid, bundle["life"]) for iid in bundle["items"])
        where, message = "A_prime no_memory item", "A′ singleton differs from A"
    with pytest.raises(ValueError) as error:
        inputs.load(canon(data), REQUIRED)
    assert str(error.value).startswith(where) and message in str(error.value)


def bootstrap_context(default, resamples=3):
    records, _, document = default
    rows, timing = inputs.load(records, REQUIRED)
    lives = tuple(sorted({row.life for row in rows}))
    return inputs._Context({life: tuple(row for row in rows if row.life == life) for life in lives},
                           fitcheck.draws(lives, resamples, inputs.UNIT), timing, REQUIRED,
                           run._parse_inputs(document, root=ROOT).alloc_by_b[150], {c: 0 for c in REQUIRED})


def test_relabelling_and_g(default, monkeypatch):
    context = bootstrap_context(default)
    context = replace(context, draws=(("life-0", "life-0", "life-1", "life-2", "life-3", "life-4"),))
    hand = [replace(row, life=f"boot-{j:03d}", bundle=f"{row.bundle}#{j}")
            for j, life in enumerate(context.draws[0]) for row in context.rows[life]]
    expected = vi.estimate(hand, timing_cells=context.timing)
    original = vi.estimate
    def estimate(rows, **kwargs):
        assert tuple(rows) == tuple(hand)
        actual = original(rows, **kwargs)
        assert actual == expected
        return actual
    monkeypatch.setattr(vi, "estimate", estimate)
    r, status, g, params, flags = inputs._resample(context, 0)
    assert status == "ok" and r == 0
    assert (params, tuple(sorted(set(flags)))) == (vi.to_latent(expected)[0], flags)
    _, covariance = gaussian.moments(params, context.alloc, context.margins)
    assert g == max(covariance[k][k] for k in range(len(params.cells)))


def test_bootstrap_unit(default):
    assert inputs.UNIT == ("ocsim", "inputs-bootstrap")
    assert inputs.UNIT != fitcheck.UNIT
    assert all(inputs.UNIT != ("ocsim", f"fitcheck-calibration-{d}") for d in range(200))
    for name, cell in (("normal", "action"), ("rule", "timing")):
        assert inputs.UNIT not in (("ocsim", "fitcheck-rule", name, cell),
                                   ("ocsim", "life", name), ("ocsim", "bundles", name, cell, 0))
    lives = tuple(bootstrap_context(default).rows)
    assert fitcheck.draws(lives, 50, inputs.UNIT) != fitcheck.draws(lives, 50, fitcheck.UNIT)


@pytest.mark.parametrize("failed", [0, 2, 4, 5])
def test_ends(failed):
    # Equal g on both sides of each selected rank witnesses tie direction at both ends.
    successes = [(r, "ok", float(r // 2), None, ()) for r in range(50 - failed)]
    results = list(reversed(successes)) + [(r, "raised", None, None, ()) for r in range(50 - failed, 50)]
    low, high = inputs._ends(results, 16, 50)
    assert tcal.index(50, 83092) == 4
    if failed > 4:
        assert low is high is None
    else:
        assert low == successes[4 - failed] and high == successes[45]


@pytest.mark.parametrize("kind", ["raised", "arithmetic", "validator", "cells", "rho_exact", "rho_band", "rho_ok", "g_raise", "g_inf", "bug"])
def test_resample_failure_kinds(default, monkeypatch, kind):
    context = bootstrap_context(default)
    params = run._parse_inputs(default[2], root=ROOT).params
    def raises(error):
        raise error("synthetic")
    original = vi.to_latent
    monkeypatch.setattr(vi, "to_latent", lambda _: (params, ("twin_default",)))
    if kind in ("raised", "arithmetic", "bug"):
        error = {"raised": ValueError, "arithmetic": ArithmeticError, "bug": TypeError}[kind]
        monkeypatch.setattr(vi, "estimate", lambda *a, **k: raises(error))
    if kind == "validator":
        monkeypatch.setattr(vi, "to_latent", lambda _: (replace(params, sigma_d2=2), ()))
    if kind == "cells":
        context = replace(context, rows={life: tuple(row for row in rows if row.cell == "action")
                                        for life, rows in context.rows.items()})
        monkeypatch.setattr(vi, "to_latent", original)
    if kind.startswith("rho_"):
        params = replace(params, sigma_d2=0.0, rho_t=-1 + {"rho_exact": 0, "rho_band": 1e-7, "rho_ok": 1e-5}[kind])
    monkeypatch.setattr(gaussian, "moments", lambda *a: ([], [[1.0, 0.0], [0.0, float("inf") if kind == "g_inf" else 2.0]]))
    if kind == "g_raise":
        monkeypatch.setattr(gaussian, "moments", lambda *a: raises(ValueError))
    if kind == "bug":
        with pytest.raises(TypeError):
            inputs._resample(context, 0)
    else:
        expected = {"arithmetic": "raised", "validator": "raised", "rho_exact": "rho_t", "rho_band": "rho_t", "rho_ok": "ok", "g_raise": "g", "g_inf": "g"}.get(kind, kind)
        assert inputs._resample(context, 0)[1] == expected


def test_bootstrap_flags_and_refusal(default, monkeypatch):
    records, base, _ = default
    successes = [inputs._resample(bootstrap_context(default), r) for r in range(3)]
    assert all(row[1] == "ok" for row in successes)
    results = [(r, "g" if r < 3 else "ok", float(r), successes[r % 3][3],
                ("twin_default",) if r < 3 else successes[r % 3][4]) for r in range(50)]
    monkeypatch.setattr(inputs, "_resample", lambda context, r: results[r])
    document = json.loads(inputs.build(records, base, root=ROOT, workers=1, resamples=50))
    assert document["sensitivity_params"] == {}
    flags = document["latent_flags"]
    assert "inputs_bootstrap_ends_refused" in flags and "inputs_bootstrap_failed=3/50" in flags
    assert "inputs_bootstrap_failed:g=3/50" in flags
    union = set().union(*(set(row[4]) for row in results))
    expected = {f"inputs_bootstrap:{flag}={sum(flag in row[4] for row in results if row[1] == 'ok')}/50"
                for flag in union if any(flag in row[4] for row in results if row[1] == "ok")}
    assert {flag for flag in flags if flag.startswith("inputs_bootstrap:")} == expected
    proof = document["provenance"]["inputs_bootstrap"]
    assert proof == dict(resamples=50, unit=list(inputs.UNIT), seed=fitcheck.SEED, level_ppm=52966,
                        index=2, failed=3, low_resample=None, high_resample=None, low_g=None, high_g=None)
    assert "inputs_bootstrap_failed=0/3" in json.loads(default[2])["latent_flags"]


@pytest.mark.parametrize("flag", ["inputs_bootstrap:unknown=1/3", "inputs_bootstrap:twin_default=1/4",
                         "inputs_bootstrap_failed:other=1/3", "inputs_bootstrap:twin_default=01/3"])
def test_bootstrap_flag_vocabulary(flag):
    inputs._check_flags(["inputs_bootstrap:anova_undefined:F:cell-000=1/3"], 3)
    with pytest.raises(ValueError, match="unknown flag"):
        inputs._check_flags([flag], 3)


def test_zero_allocation(default, monkeypatch):
    records, base, _ = default
    base = json.loads(base)
    base["alloc_by_b"]["150"] = [[cell, ckpt, 0 if cell == "action" else n]
                                  for cell, ckpt, n in base["alloc_by_b"]["150"]]
    monkeypatch.setattr(inputs, "_resample", lambda *a: pytest.fail("resampled before allocation check"))
    with pytest.raises(ValueError, match="alloc: zero count for cell action"):
        inputs.build(records, canon(base), root=ROOT, resamples=3)


@pytest.mark.parametrize("end", ["inputs_low", "inputs_high"])
def test_end_prerun(default, monkeypatch, end):
    records, base, document = default
    params = replace(run._parse_inputs(document, root=ROOT).params, rho_t=0.123, sigma_d2=0.0)
    row = (0, "ok", 1.0, params, ())
    other = inputs._resample(bootstrap_context(default), 0)
    monkeypatch.setattr(inputs, "_ends", lambda *a: (row, other) if end == "inputs_low" else (other, row))
    original = locate.build_table
    def table(cell, rho):
        if rho == 0.123:
            raise ValueError("end table refusal")
        return original(cell, rho)
    monkeypatch.setattr(locate, "build_table", table)
    with pytest.raises(ValueError, match=end + " cell action margin table"):
        inputs.build(records, base, root=ROOT, workers=1, resamples=3)


def test_real_ends(default):
    parsed = run._parse_inputs(default[2], root=ROOT)
    proof = json.loads(default[2])["provenance"]["inputs_bootstrap"]
    assert proof["failed"] == 0 and proof["level_ppm"] == 52966 and proof["index"] == 0
    assert set(parsed.sensitivity_params) == {"inputs_low", "inputs_high"}
    context = bootstrap_context(default)
    for name in ("low", "high"):
        r, status, g, params, _ = inputs._resample(context, proof[name + "_resample"])
        assert status == "ok" and proof[name + "_g"] == g.hex()
        hand = [replace(row, life=f"boot-{j:03d}", bundle=f"{row.bundle}#{j}")
                for j, life in enumerate(context.draws[r]) for row in context.rows[life]]
        assert parsed.sensitivity_params["inputs_" + name] == params == vi.to_latent(vi.estimate(hand, timing_cells=context.timing))[0]
        assert tuple(c.cell for c in params.cells) == REQUIRED


@pytest.mark.skipif((os.cpu_count() or 1) < 2, reason="needs two workers")
def test_bootstrap_workers(default):
    records, base, document = default
    assert json.loads(document)["provenance"]["inputs_bootstrap"]["failed"] == 0
    assert inputs.build(records, base, root=ROOT, workers=2, resamples=3) == document


@pytest.mark.skipif((os.cpu_count() or 1) < 2, reason="needs two workers")
def test_bootstrap_reverse_completion_and_cli(default, monkeypatch, tmp_path):
    records, base, document = default
    class Future:
        def __init__(self, value): self.value = value
        def result(self): return self.value
    class Executor:
        def __init__(self, *, max_workers, mp_context):
            assert max_workers == 2 and mp_context.get_start_method() == "spawn"
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def submit(self, fn, *args): return Future(fn(*args))
    monkeypatch.setattr(inputs, "ProcessPoolExecutor", Executor)
    monkeypatch.setattr(inputs, "as_completed", lambda futures: reversed(futures))
    assert inputs.build(records, base, root=ROOT, workers=2, resamples=3) == document
    paths = [tmp_path / name for name in ("records", "base", "out")]
    paths[0].write_bytes(records)
    paths[1].write_bytes(base)
    monkeypatch.setattr(inputs, "RESAMPLES", 3)
    argv = [part for name, path in zip(("records", "base", "out"), paths, strict=True) for part in ("--" + name, str(path))]
    inputs.main(argv + ["--workers", "2"])
    assert paths[2].read_bytes() == document
    paths[2].unlink()
    with pytest.raises(ValueError, match="workers must be an int"):
        inputs.main(argv + ["--workers", "0"])
    with pytest.raises(SystemExit) as error:
        inputs.main(argv + ["--workers", "x"])
    assert error.value.code == 2
