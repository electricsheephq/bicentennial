"""The public G1 screening roster builds and reads without a model or sockets."""

import json
import socket
from pathlib import Path

import pytest

from bicentennial import cli
from bicentennial.anchors import report
from bicentennial.canon import sha256_canon
from bicentennial.controls import battery, cache
from bicentennial.packs import build, install, scoring
from bicentennial.world.targeted import _tier_source, load_tier

from .test_t2_build import write_spec

ROOT = Path(__file__).resolve().parents[2]
SCREEN = ROOT / "results/validity-2/screening"


def load(path):
    return json.loads(path.read_bytes())


def test_screening_roster_and_placement():
    spec = load_tier(SCREEN / "t2-screen.toml")
    rows = [dict(life=f"screen-g1-{i}", genre="G1", seed=2000 + i, reads_session=1)
            for i in range(1, 21)]
    assert spec == _tier_source("T2", lives=rows, replacements=[])
    table = load(SCREEN / "placement.json")
    assert len(table) == 20
    for row, placed in zip(rows, table, strict=True):
        assert {k: placed[k] for k in row} == row
        assert placed["placement"] is True and placed["result"] == "pass"
        assert placed["early_bundles"] >= spec["min_early_bundles"]
        assert placed["checkpoint_5"]
        assert all(n <= spec[f"{key.rsplit('/', 1)[1]}_per_checkpoint"] for key, n in placed["caps"].items())
    previous = [ROOT / "tiers/life_specs/t2.toml",
                ROOT / "results/validity-1/2026-11-13-control-trials/t2-validity.toml"]
    assert not {r["seed"] for r in rows} & {r["seed"] for p in previous for r in load_tier(p)["lives"]}


@pytest.mark.parametrize("tier,spec_tier", [("T1", "T2"), ("T2", "T1")])
def test_spec_tier_mismatch_refused_before_construction(tmp_path, monkeypatch, tier, spec_tier):
    def unexpected(*args, **kwargs):
        pytest.fail("mismatched spec reached catalogue or life construction")

    monkeypatch.setattr(build, "c7_entries", unexpected)
    monkeypatch.setattr(build, "t1_lives", unexpected)
    with pytest.raises(build.PackRefused, match="^tier$"):
        build.build_tier(tier, tmp_path, harness_artifacts=[],
                         spec_path=ROOT / f"tiers/life_specs/{spec_tier.lower()}.toml")
    assert list(tmp_path.iterdir()) == []


def test_cli_spec_tier_mismatch(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setattr(cli, "reexec_niced", lambda argv: None)
    assert cli.main(["build", "--tier", "T1", "--spec", str(SCREEN / "t2-screen.toml"),
                     "--out", str(tmp_path)]) == 70
    assert "PackRefused: tier" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_g1_only_screening_pack_builds_and_reads_offline(tmp_path, monkeypatch, capsys):
    def no_socket(*args, **kwargs):
        pytest.fail("screening proof attempted network access")

    monkeypatch.setattr(socket, "socket", no_socket)
    monkeypatch.setattr(socket, "getaddrinfo", no_socket)
    # Two of the committed lives keep this regression small; the lane records a full 20-life build.
    spec = load_tier(SCREEN / "t2-screen.toml")
    subset = tmp_path / "two-g1.toml"
    write_spec(subset, spec["lives"][:2])
    result = build.build_tier("T2", tmp_path / "build", harness_artifacts=[], spec_path=subset, edition=1)
    root = tmp_path / "installed"
    assert install.install(tmp_path / "build/T2", root) == result["pack_hash"]
    index = install.verify(root, pack_hash=result["pack_hash"])
    assert index == result["index"]
    assert index["generator_versions"].keys() == {"G1"}
    assert len(index["packs"]) == 2
    all_cases, items = [], []
    for rel in index["packs"]:
        path = root / rel
        pack = load(path / "sealed/pack.json")
        assert pack["genre"] == "G1"
        inp = scoring.control_input(path)
        obj = load(path / "sealed/scoring.json")
        key = cache.cache_key(inp, harness_pin=sha256_canon([]))
        entry = cache.read_entry(path / "sealed/controls.json", key,
                                 expected_sha256=pack["hashes"]["controls"])
        assert entry == cache.compute(inp, score=scoring.make_score(obj), harness_pin=sha256_canon([]))
        assert set(entry["arms"]) == {"no_memory", "oracle_evidence", "full_history"}
        ids = {i["item_id"] for i in pack["items"]}
        assert all({r["item_id"] for r in entry["arms"][name]["items"]} == ids
                   for name in ("no_memory", "oracle_evidence"))
        history = entry["arms"]["full_history"]
        assert {r["item_id"] for r in history["items"]} <= ids
        assert history["fits"] == dict(run=len(history["items"]), of=len(ids))
        all_cases.extend(scoring.case_from_obj(c) for c in obj["cases"])
        items.extend(pack["items"])
    policies = battery.run_battery(all_cases)
    assert policies.ok, policies.failures
    assert set(policies.policies) == set(battery.POLICIES)
    assert all(rows for rows in policies.policies.values())
    output = tmp_path / "anchors.json"
    report.main(["--packs", str(root), "--out", str(output)])
    anchors = load(output)
    assert {r["item_id"] for r in anchors["items"]} == {i["item_id"] for i in items}
    printed = capsys.readouterr().out
    fields = ("pairs", "right", "confidently_wrong", "no_credit", "net_pair_points_milli")
    expected = [ref + " " + " ".join(name + ":" + ",".join(f"{k}={arms[name][k]}" for k in fields)
                for name in ("naive_rag", *report.ANCHORS)) for ref, arms in sorted(anchors["templates"].items())]
    assert printed.splitlines() == expected
    assert "seed" not in printed
    assert all(i["item_id"] not in printed and i["prompt"] not in printed for i in items)
