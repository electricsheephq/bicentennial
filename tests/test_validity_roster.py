"""The validity round's seed draw and roster placement (validity-1 declaration §2)."""

import hashlib
import importlib.util
import json
import secrets
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.canon import canon
from bicentennial.items.templates import g1, g2
from bicentennial.world import targeted as t

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("validity_roster", ROOT / "scripts/validity_roster.py")
roster = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(roster)
TEMPLATES = {"G1": g1.TEMPLATES, "G2": g2.TEMPLATES}  # edition-1 stand-in for EDITIONS[2]
PUBLIC = t.load_tier(ROOT / "tiers/life_specs/t2.toml")["lives"]


def _no_seed_printed(out, seeds):
    assert not any(str(seed) in out for seed in seeds)


def test_committed_seeds():
    seeds = roster.committed_seeds()
    assert set(range(1, 14)) <= seeds  # T0/T1 seeds 1-3, public T2 seeds 4-13, catalogue seeds and schedule seeds
    assert all(type(s) is int for s in seeds)


def test_draw(tmp_path, capsys):
    out = tmp_path / "DRAW.json"
    assert roster.main(["draw", "--out", str(out)]) == 0
    raw = out.read_bytes()
    data = json.loads(raw)
    assert raw == canon(data) + b"\n"
    assert set(data) == {"design", "spares", "drawn_at"} and data["drawn_at"].endswith("Z")
    seeds = [*data["design"], *data["spares"]]
    assert (len(data["design"]), len(data["spares"]), len(set(seeds))) == (10, 16, 26)
    assert all(type(s) is int and 0 <= s < 2 ** 63 for s in seeds)
    assert not set(seeds) & roster.committed_seeds()
    printed = capsys.readouterr().out
    assert printed.splitlines() == [f"sha256 {hashlib.sha256(raw).hexdigest()}", "design 10 spares 16"]
    _no_seed_printed(printed, seeds)

    assert roster.main(["draw", "--out", str(out)]) == 2  # never overwrite
    assert out.read_bytes() == raw


@pytest.mark.parametrize("values", [
    [4, *range(2 ** 62, 2 ** 62 + 25)],  # a committed public T2 seed
    [2 ** 62, *range(2 ** 62, 2 ** 62 + 25)],  # a duplicate within the draw
])
def test_draw_refusals_write_nothing(tmp_path, monkeypatch, capsys, values):
    drawn = iter(values)
    monkeypatch.setattr(secrets, "randbits", lambda bits: next(drawn))
    out = tmp_path / "DRAW.json"
    assert roster.main(["draw", "--out", str(out)]) == 2
    assert not out.exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    _no_seed_printed(captured.err, [v for v in values if v > 13])


def _draw(tmp_path):
    design = [2 ** 62 + i for i in range(10)]
    spares = [2 ** 61 + i for i in range(16)]
    path = tmp_path / "DRAW.json"
    path.write_bytes(canon(dict(design=design, spares=spares, drawn_at="2026-11-13T00:00:00Z")) + b"\n")
    return path, design, spares


def _stub(monkeypatch, fails):
    tried = []

    def fake(spec, row, templates, **kwargs):
        assert templates is TEMPLATES[row["genre"]]
        tried.append(row["seed"])
        if fails(row["seed"]):
            error = t.PlacementError("hostable")
            error.item_id = "drift-quote-v2"
            raise error
        compiled = SimpleNamespace(items=[], records=[])
        return SimpleNamespace(twin=SimpleNamespace(compiled=compiled, b1=SimpleNamespace(close=lambda: None)))

    monkeypatch.setattr(t, "t1_life", fake)
    monkeypatch.setattr(t, "_check_t1", lambda *args: None)
    monkeypatch.setattr(t, "_check_t2", lambda *args: None)
    return tried


def test_place_spec_round_trips(tmp_path, monkeypatch, capsys):
    draw, design, spares = _draw(tmp_path)
    tried = _stub(monkeypatch, lambda seed: seed in (design[3], spares[0]))
    spec_out, table_out = tmp_path / "SPEC.toml", tmp_path / "TABLE.json"
    assert roster.place(draw, tmp_path / "work", spec_out, table_out, templates=TEMPLATES) == 0
    assert tried == [*design[:4], spares[0], spares[1], *design[4:]]
    lives = [dict(row, seed=seed) for row, seed in zip(PUBLIC, design, strict=True)]
    lives[3]["seed"] = spares[1]
    expected = t._tier_source("T2", lives=lives, replacements=[
        dict(life=PUBLIC[3]["life"], seed=design[3], replacement_seed=spares[0], rule="hostable",
             item_id="drift-quote-v2"),
        dict(life=PUBLIC[3]["life"], seed=spares[0], replacement_seed=spares[1], rule="hostable",
             item_id="drift-quote-v2")])
    assert t.load_tier(spec_out) == expected
    assert tomllib.loads(spec_out.read_text()) == expected
    table = json.loads(table_out.read_bytes())
    assert table_out.read_bytes() == canon(table) + b"\n"
    assert [r["result"] for r in table] == ["pass"] * 3 + ["PlacementError"] * 2 + ["pass"] * 7
    printed = capsys.readouterr().out
    draw_sha = hashlib.sha256(draw.read_bytes()).hexdigest()
    assert printed.splitlines() == [
        f"draw_sha256 {draw_sha}", f"spec_sha256 {hashlib.sha256(spec_out.read_bytes()).hexdigest()}",
        f"table_sha256 {hashlib.sha256(table_out.read_bytes()).hexdigest()}",
        "lives 10 replacements 2 table_rows 12"]
    _no_seed_printed(printed, [*design, *spares])
    assert draw_sha in spec_out.read_text().splitlines()[0]

    before = spec_out.read_bytes(), table_out.read_bytes()
    assert roster.main(["place", "--draw", str(draw), "--work", str(tmp_path / "again"),
                        "--spec-out", str(spec_out), "--table-out", str(tmp_path / "other.json")]) == 2
    assert (spec_out.read_bytes(), table_out.read_bytes()) == before
    assert not (tmp_path / "other.json").exists() and not (tmp_path / "again").exists()


def test_place_void_receipt(tmp_path, monkeypatch, capsys):
    draw, design, spares = _draw(tmp_path)
    _stub(monkeypatch, lambda seed: seed in (design[1], design[6]))
    spec_out, table_out = tmp_path / "SPEC.toml", tmp_path / "TABLE.json"
    assert roster.place(draw, tmp_path / "work", spec_out, table_out, templates=TEMPLATES) == 1
    assert not spec_out.exists()
    receipt = json.loads(table_out.read_bytes())
    assert table_out.read_bytes() == canon(receipt) + b"\n"
    draw_sha = hashlib.sha256(draw.read_bytes()).hexdigest()
    assert {k: receipt[k] for k in ("void", "rule", "draw_sha256")} == dict(
        void=True, rule="design_failures", draw_sha256=draw_sha)
    assert [(r["seed"], r["result"]) for r in receipt["table"]] == [
        (design[0], "pass"), (design[1], "PlacementError"), (spares[0], "pass"),
        *((s, "pass") for s in design[2:6]), (design[6], "PlacementError")]
    assert receipt["replacements"] == [dict(life=PUBLIC[1]["life"], seed=design[1], replacement_seed=spares[0],
                                            rule="hostable", item_id="drift-quote-v2")]
    printed = capsys.readouterr().out
    assert printed.splitlines() == [
        "void design_failures", f"draw_sha256 {draw_sha}",
        f"receipt_sha256 {hashlib.sha256(table_out.read_bytes()).hexdigest()}",
        "table_rows 8 replacements 1"]
    _no_seed_printed(printed, [*design, *spares])


@pytest.mark.parametrize("edit", ["short", "duplicate", "negative", "extra-key"])
def test_place_refuses_malformed_draw(tmp_path, monkeypatch, edit):
    tried = _stub(monkeypatch, lambda seed: False)
    draw, design, spares = _draw(tmp_path)
    data = dict(design=design, spares=spares, drawn_at="2026-11-13T00:00:00Z")
    if edit == "short":
        data["spares"] = spares[:-1]
    elif edit == "duplicate":
        data["spares"] = [design[0], *spares[1:]]
    elif edit == "negative":
        data["design"] = [-1, *design[1:]]
    else:
        data["note"] = "x"
    draw.write_bytes(canon(data))
    with pytest.raises(roster.Refused):
        roster.place(draw, tmp_path / "work", tmp_path / "SPEC.toml", tmp_path / "TABLE.json", templates=TEMPLATES)
    assert tried == [] and not (tmp_path / "SPEC.toml").exists() and not (tmp_path / "TABLE.json").exists()
