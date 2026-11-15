"""The validity round's seed draw and roster placement (validity-1 declaration §2).

PYTEST_DONT_REWRITE: keep seed values out of assertion failure messages.
"""

import hashlib
import importlib.util
import json
import os
import secrets
import subprocess
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


@pytest.fixture
def draw_tree(tmp_path, monkeypatch):
    """Keep draw's real collision scan inside a small, deterministic repository."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / "seeds.txt").write_text("4 6101 7401\n")
    original = roster.collisions
    # draw passes its own root positionally; ignore every root a caller passes and scan only this repository.
    monkeypatch.setattr(roster, "collisions", lambda seeds, *_, **__: original(seeds, root=root))
    return root


def test_draw_scans_only_the_fixture_repository(tmp_path, monkeypatch, draw_tree):
    unique = 2 ** 62 + 4242  # written only into the fixture repository
    (draw_tree / "seeds.txt").write_text(f"{unique}\n")
    drawn = iter([unique, *range(2 ** 62 + 1, 2 ** 62 + 26)])
    monkeypatch.setattr(secrets, "randbits", lambda bits: next(drawn))
    out = tmp_path / "DRAW.json"
    assert roster.main(["draw", "--out", str(out)]) == 2
    assert not out.exists()


def _no_seed_printed(out, seeds):
    assert not any(str(seed) in out for seed in seeds)


def test_collisions_are_whole_numbers_outside_git(tmp_path):
    long, inner = 1234567890123456789, 234567890123456
    (tmp_path / "a.json").write_bytes(b'{"seed": 1234567890123456789, "seat": "WINDOW-7401"}')
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "objects").write_bytes(b"6101")
    assert roster.collisions([long, inner, 7401, 6101, 740], root=tmp_path) == {long, 7401}


@pytest.mark.parametrize("seed", [6101, 7401])
def test_fixture_repository_seeds_collide(seed, draw_tree):
    assert roster.collisions([seed, 2 ** 62]) == {seed}


def test_draw(tmp_path, monkeypatch, capsys, draw_tree):
    drawn = iter(range(2 ** 62, 2 ** 62 + 26))
    monkeypatch.setattr(secrets, "randbits", lambda bits: next(drawn))
    out = tmp_path / "DRAW.json"
    assert roster.main(["draw", "--out", str(out)]) == 0
    raw = out.read_bytes()
    data = json.loads(raw)
    assert raw == canon(data) + b"\n"
    assert set(data) == {"design", "spares", "drawn_at"} and data["drawn_at"].endswith("Z")
    seeds = [*data["design"], *data["spares"]]
    assert (len(data["design"]), len(data["spares"]), len(set(seeds))) == (10, 16, 26)
    assert all(type(s) is int and 0 <= s < 2 ** 63 for s in seeds)
    assert not roster.collisions(seeds)
    printed = capsys.readouterr().out
    assert printed.splitlines() == [f"sha256 {hashlib.sha256(raw).hexdigest()}", "design 10 spares 16"]
    _no_seed_printed(printed, seeds)

    assert roster.main(["draw", "--out", str(out)]) == 2  # never overwrite
    assert out.read_bytes() == raw


@pytest.mark.parametrize("values", [
    [4, *range(2 ** 62, 2 ** 62 + 25)],  # a committed public T2 seed
    [*range(2 ** 62, 2 ** 62 + 25), 6101],  # a collision in the fixture repository
    [7401, *range(2 ** 62, 2 ** 62 + 25)],  # another fixture collision
    [2 ** 62, *range(2 ** 62, 2 ** 62 + 25)],  # a duplicate within the draw
])
def test_draw_refusals_write_nothing(tmp_path, monkeypatch, capsys, values, draw_tree):
    drawn = iter(values)
    monkeypatch.setattr(secrets, "randbits", lambda bits: next(drawn))
    out = tmp_path / "DRAW.json"
    assert roster.main(["draw", "--out", str(out)]) == 2
    assert not out.exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    _no_seed_printed(captured.err, [v for v in values if v > 13])


def test_draw_seed_inside_longer_number_is_free(tmp_path, monkeypatch, capsys):
    seeds = [2 ** 62 + i for i in range(26)]
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "numbers.txt").write_text(" ".join(f"9{n}0" for n in seeds))
    drawn = iter(seeds)
    monkeypatch.setattr(secrets, "randbits", lambda bits: next(drawn))
    assert roster.draw(tmp_path / "DRAW.json", root=repo) == 0
    assert json.loads((tmp_path / "DRAW.json").read_bytes())["spares"] == seeds[10:]
    _no_seed_printed(capsys.readouterr().out, seeds)


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


@pytest.mark.parametrize("case", ["same-path", "missing-spec-dir", "missing-table-dir"])
def test_place_refuses_stranded_outputs(tmp_path, monkeypatch, case):
    tried = _stub(monkeypatch, lambda seed: False)
    draw, _, _ = _draw(tmp_path)
    spec_out, table_out = tmp_path / "SPEC.toml", tmp_path / "TABLE.json"
    if case == "same-path":
        spec_out, table_out = tmp_path / "OUT", tmp_path / "sub" / ".." / "OUT"  # one file, two spellings
    elif case == "missing-spec-dir":
        spec_out = tmp_path / "missing" / "SPEC.toml"
    else:
        table_out = tmp_path / "missing" / "TABLE.json"
    before = sorted(tmp_path.rglob("*"))
    assert roster.main(["place", "--draw", str(draw), "--work", str(tmp_path / "work"),
                        "--spec-out", str(spec_out), "--table-out", str(table_out)]) == 2
    assert tried == [] and sorted(tmp_path.rglob("*")) == before


@pytest.mark.parametrize("edit", ["design-null", "spares-string", "spares-int", "nested-list", "not-json"])
def test_malformed_draw_exits_refused(tmp_path, monkeypatch, capsys, edit):
    tried = _stub(monkeypatch, lambda seed: False)
    draw, design, spares = _draw(tmp_path)
    data = dict(design=design, spares=spares, drawn_at="2026-11-13T00:00:00Z")
    if edit == "design-null":
        data["design"] = None
    elif edit == "spares-string":
        data["spares"] = "x"
    elif edit == "spares-int":
        data["spares"] = 5
    elif edit == "nested-list":
        data["design"] = [[design[0]], *design[1:]]
    draw.write_bytes(b"\xff{" if edit == "not-json" else canon(data))
    before = sorted(tmp_path.rglob("*"))
    assert roster.main(["place", "--draw", str(draw), "--work", str(tmp_path / "work"),
                        "--spec-out", str(tmp_path / "SPEC.toml"), "--table-out", str(tmp_path / "TABLE.json")]) == 2
    assert capsys.readouterr().err == "refused: malformed draw\n"
    assert tried == [] and sorted(tmp_path.rglob("*")) == before


def test_failed_table_write_leaves_no_spec(tmp_path, monkeypatch, capsys):
    draw, _, _ = _draw(tmp_path)
    _stub(monkeypatch, lambda seed: False)
    spec_out, table_out = tmp_path / "SPEC.toml", tmp_path / "TABLE.json"
    write_new = roster._write_new

    def full_disk(path, data):
        if Path(path) == table_out:
            raise OSError("disk full")
        return write_new(path, data)

    monkeypatch.setattr(roster, "_write_new", full_disk)
    with pytest.raises(OSError, match="^disk full$"):
        roster.place(draw, tmp_path / "work", spec_out, table_out, templates=TEMPLATES)
    assert not spec_out.exists() and not table_out.exists()
    monkeypatch.setattr(roster, "_write_new", write_new)
    assert roster.place(draw, tmp_path / "work", spec_out, table_out, templates=TEMPLATES) == 0
    assert spec_out.exists() and table_out.exists()
    _no_seed_printed(capsys.readouterr().out, json.loads(draw.read_bytes())["design"])


def test_failed_write_removes_only_its_own_file(tmp_path):
    ours, theirs = tmp_path / "ours.json", tmp_path / "theirs.json"
    theirs.write_bytes(b"keep")
    with pytest.raises(TypeError):
        roster._write_new(ours, "not bytes")  # the file is created, then the write fails
    assert not ours.exists()
    with pytest.raises(FileExistsError):
        roster._write_new(theirs, b"new")
    assert theirs.read_bytes() == b"keep"


@pytest.mark.parametrize("where", ["whole-file", "design", "parser-recursion"])
def test_deeply_nested_draw_exits_refused(tmp_path, monkeypatch, capsys, where):
    tried = _stub(monkeypatch, lambda seed: False)
    if where == "parser-recursion":  # 3.11-3.13 raise RecursionError on deep nesting; 3.14's parser does not

        def too_deep(*args, **kwargs):
            raise RecursionError("maximum recursion depth exceeded while decoding a JSON array")

        monkeypatch.setattr(json, "loads", too_deep)
    draw, _, spares = _draw(tmp_path)
    deep = b"[" * 100_000 + b"]" * 100_000
    draw.write_bytes(deep if where == "whole-file" else
                     b'{"design": ' + deep + b', "spares": ' + canon(spares) + b', "drawn_at": "2026-11-13T00:00:00Z"}')
    before = sorted(tmp_path.rglob("*"))
    assert roster.main(["place", "--draw", str(draw), "--work", str(tmp_path / "work"),
                        "--spec-out", str(tmp_path / "SPEC.toml"), "--table-out", str(tmp_path / "TABLE.json")]) == 2
    assert capsys.readouterr().err == "refused: malformed draw\n"
    assert tried == [] and sorted(tmp_path.rglob("*")) == before


def test_spec_check_raising_leaves_no_spec(tmp_path, monkeypatch, capsys):
    draw, _, _ = _draw(tmp_path)
    _stub(monkeypatch, lambda seed: False)
    spec_out, table_out = tmp_path / "SPEC.toml", tmp_path / "TABLE.json"
    load_tier = t.load_tier

    def refusing(path):
        if Path(path) == spec_out:
            raise t.PlacementError("composition")
        return load_tier(path)

    monkeypatch.setattr(t, "load_tier", refusing)
    with pytest.raises(t.PlacementError, match="^composition$"):
        roster.place(draw, tmp_path / "work", spec_out, table_out, templates=TEMPLATES)
    assert not spec_out.exists() and not table_out.exists()
    monkeypatch.setattr(t, "load_tier", load_tier)
    assert roster.place(draw, tmp_path / "work", spec_out, table_out, templates=TEMPLATES) == 0
    assert t.load_tier(spec_out)["tier"] == "T2" and table_out.exists()
    _no_seed_printed(capsys.readouterr().out, json.loads(draw.read_bytes())["design"])


def _stub_round2(monkeypatch, fails):
    tried = _stub(monkeypatch, fails)
    fake = t.t1_life

    def only_g1(spec, row, templates, **kwargs):
        assert row["genre"] == "G1"
        assert templates is TEMPLATES["G1"]
        return fake(spec, row, templates, **kwargs)

    monkeypatch.setattr(t, "t1_life", only_g1)
    return tried


@pytest.mark.parametrize("replace", [False, True])
def test_round2_spec_round_trips(tmp_path, monkeypatch, capsys, replace):
    from bicentennial.runner.units import T2_SPEC

    draw, design, spares = _draw(tmp_path)
    tried = _stub_round2(monkeypatch, lambda seed: replace and seed in (design[3], spares[0]))
    spec_out, table_out = tmp_path / "SPEC.toml", tmp_path / "TABLE.json"
    assert roster.place(draw, tmp_path / "work", spec_out, table_out, round_=2, templates=TEMPLATES) == 0
    first = next(row for row in PUBLIC if row["genre"] == "G1")
    lives = [dict(first, life=f"t2-g1-{n}", seed=seed) for n, seed in enumerate(design, 1)]
    replacements = []
    if replace:
        lives[3]["seed"] = spares[1]
        replacements = [
            dict(life="t2-g1-4", seed=design[3], replacement_seed=spares[0], rule="hostable",
                 item_id="drift-quote-v2"),
            dict(life="t2-g1-4", seed=spares[0], replacement_seed=spares[1], rule="hostable",
                 item_id="drift-quote-v2")]
    assert tried == ([*design[:4], spares[0], spares[1], *design[4:]] if replace else design)
    expected = t._tier_source("T2", lives=lives, replacements=replacements)
    assert t.load_tier(spec_out) == tomllib.loads(spec_out.read_text()) == expected
    assert len(lives) == len({row["life"] for row in lives}) == 10
    assert all(row["genre"] == "G1" for row in lives)
    assert any(sorted(row["genre"] for row in lives) == sorted(composition)
               for composition in T2_SPEC.control_compositions)
    table = json.loads(table_out.read_bytes())
    assert table_out.read_bytes() == canon(table) + b"\n"
    assert [row["seed"] for row in table] == tried
    assert [row["result"] for row in table] == (
        ["pass"] * 3 + ["PlacementError"] * 2 + ["pass"] * 7 if replace else ["pass"] * 10)
    draw_sha = hashlib.sha256(draw.read_bytes()).hexdigest()
    assert spec_out.read_text().splitlines()[0] == (
        f"# Validity round 2 validation spec, placed from draw sha256 {draw_sha}.")
    printed = capsys.readouterr().out
    assert printed.splitlines() == [
        f"draw_sha256 {draw_sha}", f"spec_sha256 {hashlib.sha256(spec_out.read_bytes()).hexdigest()}",
        f"table_sha256 {hashlib.sha256(table_out.read_bytes()).hexdigest()}",
        f"lives 10 replacements {len(replacements)} table_rows {len(tried)}"]
    _no_seed_printed(printed, [*design, *spares])


def test_round2_void_receipt(tmp_path, monkeypatch, capsys):
    draw, design, spares = _draw(tmp_path)
    _stub_round2(monkeypatch, lambda seed: seed in (design[1], design[6]))
    spec_out, table_out = tmp_path / "SPEC.toml", tmp_path / "TABLE.json"
    assert roster.place(draw, tmp_path / "work", spec_out, table_out, round_=2, templates=TEMPLATES) == 1
    assert not spec_out.exists()
    receipt = json.loads(table_out.read_bytes())
    assert table_out.read_bytes() == canon(receipt) + b"\n"
    draw_sha = hashlib.sha256(draw.read_bytes()).hexdigest()
    assert {k: receipt[k] for k in ("void", "rule", "draw_sha256")} == dict(
        void=True, rule="design_failures", draw_sha256=draw_sha)
    assert [(r["seed"], r["result"]) for r in receipt["table"]] == [
        (design[0], "pass"), (design[1], "PlacementError"), (spares[0], "pass"),
        *((s, "pass") for s in design[2:6]), (design[6], "PlacementError")]
    assert receipt["replacements"] == [dict(life="t2-g1-2", seed=design[1], replacement_seed=spares[0],
                                            rule="hostable", item_id="drift-quote-v2")]
    printed = capsys.readouterr().out
    assert printed.splitlines() == [
        "void design_failures", f"draw_sha256 {draw_sha}",
        f"receipt_sha256 {hashlib.sha256(table_out.read_bytes()).hexdigest()}",
        "table_rows 8 replacements 1"]
    _no_seed_printed(printed, [*design, *spares])


def test_round_cli_and_default(tmp_path, monkeypatch, capsys):
    from bicentennial.items import editions

    draw, design, spares = _draw(tmp_path)
    monkeypatch.setitem(editions.EDITIONS, 2, TEMPLATES)
    monkeypatch.setitem(editions.EDITIONS, 3, TEMPLATES)
    _stub_round2(monkeypatch, lambda seed: False)
    spec_out, table_out = tmp_path / "SPEC.toml", tmp_path / "TABLE.json"
    args = ["place", "--draw", str(draw), "--work", str(tmp_path / "work"),
            "--spec-out", str(spec_out), "--table-out", str(table_out)]
    assert roster.main([*args, "--round", "2"]) == 0
    assert [row["genre"] for row in t.load_tier(spec_out)["lives"]] == ["G1"] * 10
    with pytest.raises(SystemExit) as caught:
        roster.main([*args, "--round", "3"])
    assert caught.value.code == 2
    captured = capsys.readouterr()
    assert "argument --round: invalid choice:" in captured.err
    _no_seed_printed(captured.out + captured.err, [*design, *spares])
    _stub(monkeypatch, lambda seed: False)
    default = tmp_path / "default.toml"
    explicit = tmp_path / "explicit.toml"
    assert roster.main([*args, "--spec-out", str(default), "--table-out", str(tmp_path / "default.json")]) == 0
    assert roster.main([*args, "--round", "1", "--spec-out", str(explicit),
                        "--table-out", str(tmp_path / "explicit.json")]) == 0
    assert default.read_bytes() == explicit.read_bytes()
    assert (tmp_path / "default.json").read_bytes() == (tmp_path / "explicit.json").read_bytes()
    assert t.load_tier(default) == t._tier_source(
        "T2", lives=[dict(row, seed=seed) for row, seed in zip(PUBLIC, design, strict=True)])
    _no_seed_printed(capsys.readouterr().out, [*design, *spares])


def test_round2_uses_edition3(tmp_path, monkeypatch, capsys):
    from bicentennial.items import editions

    draw, design, spares = _draw(tmp_path)
    monkeypatch.setitem(editions.EDITIONS, 2, {})
    monkeypatch.setitem(editions.EDITIONS, 3, TEMPLATES)
    tried = _stub_round2(monkeypatch, lambda seed: False)
    assert roster.place(draw, tmp_path / "work", tmp_path / "SPEC.toml", tmp_path / "TABLE.json", round_=2) == 0
    assert tried == design
    _no_seed_printed(capsys.readouterr().out, [*design, *spares])


@pytest.mark.parametrize("has_g1", [False, True])
def test_round2_uses_first_public_g1_or_refuses(tmp_path, monkeypatch, capsys, has_g1):
    draw, design, spares = _draw(tmp_path)
    root = tmp_path / "repo"
    source = root / "tiers/life_specs/t2.toml"
    source.parent.mkdir(parents=True)
    rows = [PUBLIC[-1], PUBLIC[1]] if has_g1 else PUBLIC[5:]
    source.write_text(roster.toml_text(t._tier_source("T2", lives=rows), "test public roster"))
    tried = _stub_round2(monkeypatch, lambda seed: False)
    spec_out, table_out = tmp_path / "SPEC.toml", tmp_path / "TABLE.json"
    if has_g1:
        assert roster.place(draw, tmp_path / "work", spec_out, table_out,
                            round_=2, templates=TEMPLATES, root=root) == 0
        assert t.load_tier(spec_out)["lives"] == [
            dict(PUBLIC[1], life=f"t2-g1-{n}", seed=seed) for n, seed in enumerate(design, 1)]
        assert tried == design
    else:
        with pytest.raises(roster.Refused, match="G1"):
            roster.place(draw, tmp_path / "work", spec_out, table_out, round_=2, templates=TEMPLATES, root=root)
        assert tried == [] and not spec_out.exists() and not table_out.exists()
        assert not (tmp_path / "work").exists()
    _no_seed_printed(capsys.readouterr().out, [*design, *spares])


def test_round2_uses_the_real_edition3(tmp_path, monkeypatch, capsys):
    """Round 2 reads edition 3 from the real registry (#551), with no stand-in for EDITIONS."""
    from bicentennial.items.editions import EDITIONS

    draw, design, spares = _draw(tmp_path)
    _stub(monkeypatch, lambda seed: False)  # keeps its check stubs; its fake expects the edition-1 stand-in
    tried, seen = [], []

    def record(spec, row, templates, **kwargs):
        tried.append(row["seed"])
        seen.append(templates)
        compiled = SimpleNamespace(items=[], records=[])
        return SimpleNamespace(twin=SimpleNamespace(compiled=compiled, b1=SimpleNamespace(close=lambda: None)))

    monkeypatch.setattr(t, "t1_life", record)
    assert roster.place(draw, tmp_path / "work", tmp_path / "SPEC.toml", tmp_path / "TABLE.json", round_=2) == 0
    assert tried == design and len(seen) == 10
    assert all(templates is EDITIONS[3]["G1"] for templates in seen)
    refs = {f"{x.template_id}-v{x.version}" for x in EDITIONS[3]["G1"]}
    assert {"drift-chain-fault-v3", "drift-config-v3", "drift-quote-v3", "wake-loop-v1"} <= refs
    _no_seed_printed(capsys.readouterr().out, [*design, *spares])


# Fresh-seed follow-up: all fixtures below are invented, not taken from a pack.
def _three_draw(tmp_path):
    design = list(range(2 ** 62 + 100, 2 ** 62 + 130))
    spares = list(range(2 ** 61 + 100, 2 ** 61 + 148))
    path = tmp_path / "DRAW.json"
    path.write_bytes(canon(dict(design=design, spares=spares, drawn_at="2026-11-15T00:00:00Z")) + b"\n")
    return path, design, spares


def _three_args(draw, tmp_path):
    return ["place", "--packs", "3", "--draw", str(draw), "--work", str(tmp_path / "work"),
            "--out-dir", str(tmp_path / "out")]


def _expected_pack(design, index):
    chunk = design[index * 10:(index + 1) * 10]
    seeds = {f"t2-g{genre}-{i}": chunk[2 * (i - 1) + genre - 1]
             for genre in (1, 2) for i in range(1, 6)}
    return [dict(row, seed=seeds[row["life"]]) for row in PUBLIC]



def test_three_rehearsal_draw(tmp_path, monkeypatch, capsys, draw_tree):
    seeds = list(range(2001, 2079))
    (draw_tree / "seeds.txt").write_text(" ".join(map(str, seeds)))

    def forbidden(*args, **kwargs):
        pytest.fail("rehearsal must not scan or draw random integers")

    monkeypatch.setattr(roster, "collisions", forbidden)
    monkeypatch.setattr(secrets, "randbits", forbidden)
    expected = canon(dict(design=seeds[:30], spares=seeds[30:], drawn_at="rehearsal: public integers")) + b"\n"
    for name in ("one.json", "two.json"):
        out = tmp_path / name
        assert roster.main(["draw", "--packs", "3", "--rehearsal", "--out", str(out)]) == 0
        assert out.read_bytes() == expected
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [f"sha256 {hashlib.sha256(expected).hexdigest()}",
                                         "design 30 spares 48", "rehearsal draw: public integers"] * 2
    assert captured.err == ""
    assert roster.main(["draw", "--rehearsal", "--out", str(tmp_path / "no.json")]) == 2
    assert not (tmp_path / "no.json").exists()
    refused = capsys.readouterr()
    assert refused.out == "" and refused.err.startswith("refused: ")
    _no_seed_printed(captured.out + captured.err + refused.out + refused.err, seeds)


def test_three_mapping_and_walk(tmp_path, monkeypatch, capsys):
    from bicentennial.runner.units import T2_SPEC

    draw, design, spares = _three_draw(tmp_path)
    tried = _stub(monkeypatch, lambda seed: False)
    roots = []
    dry_run = t.t2_dry_run

    def record(*args, **kwargs):
        roots.append(Path(kwargs["root"]))
        return dry_run(*args, **kwargs)

    monkeypatch.setattr(t, "t2_dry_run", record)
    out = tmp_path / "out"
    assert roster.place_packs(draw, tmp_path / "work", out, templates=TEMPLATES) == 0
    assert roots == [tmp_path / "work" / label for label in "ABC"]
    expected_tried = []
    draw_sha = hashlib.sha256(draw.read_bytes()).hexdigest()
    lines = [f"draw_sha256 {draw_sha}"]
    assert {p.name for p in out.iterdir()} == {f"{stem}-{label}.{ext}" for label in "ABC"
                                             for stem, ext in (("pack", "toml"), ("placement", "json"))}
    for index, label in enumerate("ABC"):
        rows = _expected_pack(design, index)
        expected_tried.extend(row["seed"] for row in rows)
        spec, table = out / f"pack-{label}.toml", out / f"placement-{label}.json"
        expected = t._tier_source("T2", lives=rows, replacements=[])
        assert t.load_tier(spec) == tomllib.loads(spec.read_text()) == expected
        assert sorted(row["genre"] for row in rows) == sorted(T2_SPEC.composition)
        assert spec.read_text().splitlines()[0] == (
            f"# Fresh-seed follow-up pack {label} (positions {index * 10 + 1}-{index * 10 + 10}), "
            f"placed from draw sha256 {draw_sha}.")
        data = json.loads(table.read_bytes())
        assert table.read_bytes() == canon(data) + b"\n"
        assert [r["seed"] for r in data] == [r["seed"] for r in rows]
        assert all(r["result"] == "pass" for r in data)
        lines.append(f"pack {label} spec_sha256 {hashlib.sha256(spec.read_bytes()).hexdigest()} "
                     f"table_sha256 {hashlib.sha256(table.read_bytes()).hexdigest()} "
                     "lives 10 replacements 0 table_rows 10")
    assert tried == expected_tried
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [*lines, "spares_used 0 of 48"] and captured.err == ""
    _no_seed_printed(captured.out + captured.err, [*design, *spares])


@pytest.mark.parametrize("case", ["shared", "per-pack"])
def test_three_shared_spares_and_pack_limit(tmp_path, monkeypatch, capsys, case):
    draw, design, spares = _three_draw(tmp_path)
    failures = {design[2], spares[0], design[11]} if case == "shared" else {design[0], design[10], design[20]}
    tried = _stub(monkeypatch, lambda seed: seed in failures)
    out = tmp_path / "out"
    assert roster.place_packs(draw, tmp_path / "work", out, templates=TEMPLATES) == 0
    specs = [t.load_tier(out / f"pack-{label}.toml") for label in "ABC"]
    used = [r["replacement_seed"] for spec in specs for r in spec["replacements"]]
    assert used == spares[:3]
    assert all(tried.count(seed) == 1 for seed in spares[:3])
    if case == "shared":
        assert specs[0]["lives"][1]["seed"] == spares[1]
        assert specs[1]["lives"][5]["seed"] == spares[2]
        assert [len(s["replacements"]) for s in specs] == [2, 1, 0]
    else:
        assert [len(s["replacements"]) for s in specs] == [1, 1, 1]
    captured = capsys.readouterr()
    assert captured.out.splitlines()[-1] == "spares_used 3 of 48" and not captured.err
    _no_seed_printed(captured.out + captured.err, [*design, *spares])


@pytest.mark.parametrize("rule", ["design_failures", "replacements", "pool"])
def test_three_void_rules(tmp_path, monkeypatch, capsys, rule):
    draw, design, spares = _three_draw(tmp_path)
    if rule == "design_failures":
        failures = {design[0], design[10], design[12]}
    else:
        failures = {design[10], *spares[:8]}
    tried = _stub(monkeypatch, lambda seed: seed in failures)
    if rule == "pool":
        place_three = roster._place_three

        def short_pool(rows, design, pool, work, templates):
            return place_three(rows, design, pool[:1], work, templates)

        monkeypatch.setattr(roster, "_place_three", short_pool)
    out = tmp_path / "out"
    assert roster.place_packs(draw, tmp_path / "work", out, templates=TEMPLATES) == 1
    assert [p.name for p in out.iterdir()] == ["void.json"] and not list(out.rglob("*.toml"))
    raw = (out / "void.json").read_bytes()
    receipt = json.loads(raw)
    assert raw == canon(receipt) + b"\n"
    draw_sha = hashlib.sha256(draw.read_bytes()).hexdigest()
    assert set(receipt) == {"void", "rule", "pack", "draw_sha256", "packs"}
    assert {key: receipt[key] for key in ("void", "rule", "pack", "draw_sha256")} == dict(
        void=True, rule=rule, pack="B", draw_sha256=draw_sha)
    assert list(receipt["packs"]) == ["A", "B"]
    a, b = (receipt["packs"][label] for label in "AB")
    assert all(set(pack) == {"table", "replacements"} for pack in (a, b))
    assert len(a["table"]) == (11 if rule == "design_failures" else 10)
    assert len(b["table"]) == {"design_failures": 3, "replacements": 9, "pool": 2}[rule]
    assert [r["seed"] for p in (a, b) for r in p["table"]] == tried
    assert [r["replacement_seed"] for p in (a, b) for r in p["replacements"]] == (
        spares[:2] if rule == "design_failures" else spares[:8] if rule == "replacements" else spares[:1])
    lines = [f"void {rule} pack B", f"draw_sha256 {draw_sha}",
             f"receipt_sha256 {hashlib.sha256(raw).hexdigest()}"]
    lines.extend(f"pack {label} table_rows {len(p['table'])} replacements {len(p['replacements'])}"
                 for label, p in receipt["packs"].items())
    captured = capsys.readouterr()
    assert captured.out.splitlines() == lines and not captured.err
    _no_seed_printed(captured.out + captured.err, [*design, *spares])


@pytest.mark.parametrize("edit", ["legacy", "short", "duplicate", "negative", "extra-key", "design-null",
                                  "spares-string", "spares-int", "nested-list", "not-json", "bool", "large",
                                  "whole-file", "design-deep", "parser-recursion", "utf16"])
def test_three_malformed_draw(tmp_path, monkeypatch, capsys, edit):
    draw, design, spares = _three_draw(tmp_path)
    data = json.loads(draw.read_bytes())
    if edit == "legacy":
        data["design"], data["spares"] = design[:10], spares[:16]
    elif edit == "short":
        data["spares"] = spares[:-1]
    elif edit == "duplicate":
        data["spares"][0] = design[0]
    elif edit == "negative":
        data["design"][0] = -1
    elif edit == "extra-key":
        data["note"] = "x"
    elif edit == "design-null":
        data["design"] = None
    elif edit == "spares-string":
        data["spares"] = "x"
    elif edit == "spares-int":
        data["spares"] = 5
    elif edit == "nested-list":
        data["design"][0] = [design[0]]
    elif edit == "bool":
        data["design"][0] = True
    elif edit == "large":
        data["design"][0] = 2 ** 63
    raw = canon(data)
    if edit == "utf16":
        raw = raw.decode("utf-8").encode("utf-16")
    elif edit == "not-json":
        raw = b"\xff{"
    elif edit in ("whole-file", "design-deep"):
        deep = b"[" * 100_000 + b"]" * 100_000
        raw = deep if edit == "whole-file" else b'{"design":' + deep + b',"spares":[],"drawn_at":"x"}'
    elif edit == "parser-recursion":
        def too_deep(*args, **kwargs):
            raise RecursionError("nested input")
        monkeypatch.setattr(json, "loads", too_deep)
    draw.write_bytes(raw)
    tried = _stub(monkeypatch, lambda seed: False)
    assert roster.main(_three_args(draw, tmp_path)) == 2
    assert not (tmp_path / "out").exists() and not (tmp_path / "work").exists() and tried == []
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "refused: malformed draw\n"
    _no_seed_printed(captured.out + captured.err, [*design, *spares])


@pytest.mark.parametrize("round_", [1, 2])
def test_three_draw_refused_by_legacy_modes(tmp_path, monkeypatch, capsys, round_):
    assert roster.main(["draw", "--packs", "3", "--rehearsal", "--out", str(tmp_path / "public.json")]) == 0
    rehearsal_output = capsys.readouterr()
    draw, design, spares = _three_draw(tmp_path)
    tried = _stub(monkeypatch, lambda seed: False)
    assert roster.main(["place", "--round", str(round_), "--draw", str(draw), "--work", str(tmp_path / "work"),
                        "--spec-out", str(tmp_path / "spec.toml"), "--table-out", str(tmp_path / "table.json")]) == 2
    assert tried == [] and not (tmp_path / "work").exists()
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "refused: malformed draw\n"
    _no_seed_printed(rehearsal_output.out + rehearsal_output.err + captured.out + captured.err,
                     [*design, *spares, *range(2001, 2079)])


@pytest.mark.parametrize("edit", ["short", "genre", "name", "duplicate"])
def test_three_public_roster_refused(tmp_path, monkeypatch, capsys, edit):
    draw, design, spares = _three_draw(tmp_path)
    rows = [dict(row) for row in PUBLIC]
    if edit == "short":
        rows.pop()
    elif edit == "genre":
        rows[-1]["genre"] = "G1"
    elif edit == "name":
        rows[-1]["life"] = "synthetic-life"
    else:
        rows[-1] = dict(rows[-2])
    root = tmp_path / "repo"
    source = root / "tiers/life_specs/t2.toml"
    source.parent.mkdir(parents=True)
    source.write_text(roster.toml_text(t._tier_source("T2", lives=rows), "synthetic public roster"))
    tried = _stub(monkeypatch, lambda seed: False)
    with pytest.raises(roster.Refused):
        roster.place_packs(draw, tmp_path / "work", tmp_path / "out", templates=TEMPLATES, root=root)
    assert tried == [] and not (tmp_path / "out").exists() and not (tmp_path / "work").exists()
    captured = capsys.readouterr()
    _no_seed_printed(captured.out + captured.err, [*design, *spares])


@pytest.mark.parametrize("case", ["existing", "missing-parent", "write", "load", "load-mismatch", "toml"])
def test_three_all_or_nothing(tmp_path, monkeypatch, capsys, case):
    draw, design, spares = _three_draw(tmp_path)
    tried = _stub(monkeypatch, lambda seed: False)
    out = tmp_path / "out"
    if case == "existing":
        out.mkdir()
        (out / "keep").write_bytes(b"keep")
    elif case == "missing-parent":
        out = tmp_path / "missing" / "out"
    elif case == "write":
        original = roster._write_new
        calls = []

        def fail_second(path, data):
            calls.append(path)
            assert len(tried) == 30  # all placements precede the first write
            if len(calls) == 2:
                raise OSError("synthetic write failure")
            return original(path, data)

        monkeypatch.setattr(roster, "_write_new", fail_second)
    elif case in ("load", "load-mismatch"):
        original = t.load_tier

        def reject(path):
            if Path(path).parent == out:
                if case == "load":
                    raise ValueError("synthetic spec failure")
                return {}
            return original(path)

        monkeypatch.setattr(t, "load_tier", reject)
    else:
        monkeypatch.setattr(roster, "toml_text", lambda *args: "tier = 'wrong'\n")
    with pytest.raises((roster.Refused, OSError, ValueError)):
        roster.place_packs(draw, tmp_path / "work", out, templates=TEMPLATES)
    if case == "existing":
        assert [p.name for p in out.iterdir()] == ["keep"] and (out / "keep").read_bytes() == b"keep"
    else:
        assert not out.exists()
    if case in ("existing", "missing-parent"):
        assert tried == [] and not (tmp_path / "work").exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    _no_seed_printed(captured.out + captured.err, [*design, *spares])


def test_three_real_edition(tmp_path, monkeypatch, capsys):
    from bicentennial.items.editions import EDITIONS

    draw, design, spares = _three_draw(tmp_path)
    _stub(monkeypatch, lambda seed: False)
    seen = []

    def record(spec, row, templates, **kwargs):
        seen.append((row["genre"], templates))
        compiled = SimpleNamespace(items=[], records=[])
        return SimpleNamespace(twin=SimpleNamespace(compiled=compiled, b1=SimpleNamespace(close=lambda: None)))

    monkeypatch.setattr(t, "t1_life", record)
    assert roster.place_packs(draw, tmp_path / "work", tmp_path / "out") == 0
    assert len(seen) == 30 and {genre for genre, _ in seen} == {"G1", "G2"}
    assert all(templates is EDITIONS[3][genre] for genre, templates in seen)
    captured = capsys.readouterr()
    _no_seed_printed(captured.out + captured.err, [*design, *spares])


@pytest.mark.parametrize("args", [["draw", "--packs", "2", "--out", "unused"],
                                  ["place", "--packs", "2"], ["place", "--packs", "3"],
                                  ["place", "--packs", "3", "--round", "2"],
                                  ["place", "--packs", "3", "--round", "1"],
                                  ["place", "--packs", "3", "--spec-out", "unused"],
                                  ["place", "--packs", "3", "--table-out", "unused"],
                                  ["place"], ["place", "--out-dir", "unused"]])
def test_three_cli_rejects_mixed_modes(tmp_path, monkeypatch, capsys, draw_tree, args):
    drawn = iter(range(2 ** 62 + 500, 2 ** 62 + 578))
    monkeypatch.setattr(secrets, "randbits", lambda bits: next(drawn))
    args = [str(tmp_path / "unused") if arg == "unused" else arg for arg in args]
    complete = [*args, "--draw", str(tmp_path / "unused"), "--work", str(tmp_path / "work")]
    if len(args) > 3:
        complete += ["--out-dir", str(tmp_path / "out")]
    three = "--packs" in args and args[args.index("--packs") + 1] == "3"
    if args[0] == "place" and three:
        assert roster.main(complete) == 2
        captured = capsys.readouterr()
        reason = ("--packs cannot be combined with --round, --spec-out or --table-out"
                  if any(flag in args for flag in ("--round", "--spec-out", "--table-out")) else
                  "--packs requires --out-dir")
        assert captured.out == "" and captured.err == f"refused: {reason}\n"
    else:
        with pytest.raises(SystemExit) as caught:
            roster.main(complete if args[0] == "place" else args)
        assert caught.value.code == 2
        captured = capsys.readouterr()
        if "--packs" in args:
            assert "invalid choice" in captured.err
    assert not (tmp_path / "work").exists() and not (tmp_path / "out").exists()
    assert roster.main(["draw", "--packs", "3", "--rehearsal", "--out", str(tmp_path / "public.json")]) == 0
    more = capsys.readouterr()
    _no_seed_printed(captured.out + captured.err + more.out + more.err,
                     [*range(2001, 2079), *range(2 ** 62 + 500, 2 ** 62 + 578)])


def test_three_cli_round_trip(tmp_path, monkeypatch, capsys):
    from bicentennial.items import editions

    monkeypatch.setitem(editions.EDITIONS, 3, TEMPLATES)
    tried = _stub(monkeypatch, lambda seed: False)
    draw = tmp_path / "DRAW.json"
    assert roster.main(["draw", "--packs", "3", "--rehearsal", "--out", str(draw)]) == 0
    assert roster.main(_three_args(draw, tmp_path)) == 0
    design = list(range(2001, 2031))
    assert tried == [row["seed"] for index in range(3) for row in _expected_pack(design, index)]
    assert len(list((tmp_path / "out").iterdir())) == 6
    captured = capsys.readouterr()
    assert captured.err == ""
    _no_seed_printed(captured.out + captured.err, range(2001, 2079))


@pytest.mark.parametrize("case", ["read", "placement", "unannotated", "write", "exists", "void-write"])
def test_three_cli_failure_is_private(tmp_path, monkeypatch, capsys, case):
    from bicentennial.items import editions

    draw, design, spares = _three_draw(tmp_path)
    monkeypatch.setitem(editions.EDITIONS, 3, TEMPLATES)
    _stub(monkeypatch, lambda seed: case == "void-write" and seed in (design[0], design[2]))
    if case == "read":
        draw = tmp_path / str(design[0])
    else:
        error_type = FileExistsError if case == "exists" else t.PlacementError if case == "unannotated" else OSError

        def reject(*args, **kwargs):
            raise error_type(f"synthetic failure {design[0]}")

        if case in ("placement", "unannotated"):
            monkeypatch.setattr(t, "t2_dry_run", reject)
        else:
            monkeypatch.setattr(roster, "_write_new", reject)
    assert roster.main(_three_args(draw, tmp_path)) == 2
    assert not (tmp_path / "out").exists()
    captured = capsys.readouterr()
    assert captured.out == ""
    error_name = "FileNotFoundError" if case == "read" else "PlacementError" if case == "unannotated" else "OSError"
    assert captured.err == ("refused: output exists\n" if case == "exists" else
                            f"refused: three-pack operation failed ({error_name})\n")
    _no_seed_printed(captured.out + captured.err, [*design, *spares])


@pytest.mark.parametrize("case", ["same", "inside", "pack-root"])
def test_three_work_output_collision(tmp_path, monkeypatch, capsys, case):
    draw, design, spares = _three_draw(tmp_path)
    tried = _stub(monkeypatch, lambda seed: False)
    out = tmp_path / "out"
    work = out if case == "same" else out / "work"
    if case == "pack-root":
        work = tmp_path / "work"
        work.mkdir()
        out = work / "A"
    with pytest.raises(roster.Refused):
        roster.place_packs(draw, work, out, templates=TEMPLATES)
    assert not out.exists() and tried == []
    if case == "pack-root":
        assert list(work.iterdir()) == []
    captured = capsys.readouterr()
    _no_seed_printed(captured.out + captured.err, [*design, *spares])


# Public quicknet record; candidate answers stay hex so they cannot collide as decimal text.
BEACON = dict(
    round=33965389,
    randomness="6d39b70b3784b75426f8224fb33407cede1d9effe43407b6db1e013faeacbde4",
    signature="827beb753f65fd8207d45238bedd316aafc2105494fdbe170824a53dc666dc0764b"
              "42e862fe11613da074f0f548e1e44",
)
FIRST_FIVE_HEX = ("1f7c3dede7aa176a", "5ed306cfe83f462b", "600be0dc69165736",
                  "039343fad7c4a0ae", "1e485bcc6a31ff3b")


def _fixture_git(root, *args):
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args], check=True, capture_output=True).stdout


@pytest.fixture
def beacon_tree(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    root.mkdir()
    _fixture_git(root, "init", "-q")
    (root / "tracked file\nname").write_bytes(b"synthetic committed text\n")
    _fixture_git(root, "add", ".")
    _fixture_git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    monkeypatch.setattr(roster, "ROOT", root)
    original_collisions = roster.collisions
    monkeypatch.setattr(roster, "collisions", lambda seeds, *_, **kwargs:
                        original_collisions(seeds, root=root, **kwargs))
    drawn = iter(range(2 ** 62 + 700, 2 ** 62 + 1000))
    monkeypatch.setattr(secrets, "randbits", lambda _: next(drawn))
    beacon = tmp_path / "beacon.json"
    beacon.write_bytes(canon(BEACON))
    return root, beacon


def _beacon_args(command, path, beacon):
    return [command, "--packs", "3", "--beacon", str(beacon),
            "--out" if command == "draw" else "--draw", str(path)]


def _raw_candidates(count=80):
    randomness = bytes.fromhex(BEACON["randomness"])
    return [int.from_bytes(hashlib.sha256(randomness + k.to_bytes(8, "big")).digest()[:8], "big") >> 1
            for k in range(count)]


def test_beacon_known_answer(capsys):
    candidates = roster._candidates(bytes.fromhex(BEACON["randomness"]))
    actual = [next(candidates) for _ in FIRST_FIVE_HEX]
    assert tuple(f"{n:016x}" for n in actual) == FIRST_FIVE_HEX
    captured = capsys.readouterr()
    _no_seed_printed(captured.out + captured.err, actual)


@pytest.mark.parametrize("case", ["ok", "collision", "repeat"])
def test_three_real_draw(tmp_path, monkeypatch, capsys, beacon_tree, case):
    root, beacon = beacon_tree
    raw = _raw_candidates()
    expected = raw[:78]
    if case == "collision":
        original = roster.collisions

        def collision(seeds, *args, **kwargs):
            return original(seeds, *args, **kwargs) | ({raw[3]} & set(seeds))

        monkeypatch.setattr(roster, "collisions", collision)
        expected = [*raw[:3], *raw[4:79]]
    elif case == "repeat":
        monkeypatch.setattr(roster, "_candidates", lambda _: iter([*raw[:3], raw[1], *raw[3:]]))
    def forbidden(*args):
        pytest.fail("beacon draw must not use entropy")
    monkeypatch.setattr(secrets, "randbits", forbidden)
    out = tmp_path / "draw.json"
    assert roster.main(_beacon_args("draw", out, beacon)) == 0
    raw_bytes = out.read_bytes()
    data = json.loads(raw_bytes)
    assert data["design"] == expected[:30] and data["spares"] == expected[30:]
    assert len({*data["design"], *data["spares"]}) == 78
    assert all(0 <= n < 2 ** 63 for n in expected)
    captured = capsys.readouterr()
    assert not captured.err
    assert captured.out.splitlines() == [f"sha256 {hashlib.sha256(out.read_bytes()).hexdigest()}",
                                         "design 30 spares 48", f"round {BEACON['round']}"]
    assert roster.main(_beacon_args("draw", out, beacon)) == 2
    refused = capsys.readouterr()
    assert out.read_bytes() == raw_bytes
    assert refused.out == "" and refused.err.startswith("refused: ")
    assert roster.main(_beacon_args("draw", tmp_path / "missing" / "draw.json", beacon)) == 2
    more = capsys.readouterr()
    assert more.out == "" and more.err.startswith("refused: ")
    _no_seed_printed(captured.out + captured.err + refused.out + refused.err + more.out + more.err, raw)


def test_beacon_tracked_only(tmp_path, capsys, beacon_tree):
    root, beacon = beacon_tree
    seeds = _raw_candidates()
    untracked = root / "untracked"
    untracked.write_text(str(seeds[3]))
    tracked = root / "tracked file\nname"
    # A longer decimal number is not a whole-number collision.
    tracked.write_text(f"9{seeds[2]}0")
    _fixture_git(root, "add", ".")
    _fixture_git(root, "reset", "--", "untracked")
    _fixture_git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "longer number")
    out = tmp_path / "one.json"
    assert roster.main(_beacon_args("draw", out, beacon)) == 0
    assert json.loads(out.read_bytes())["design"] == seeds[:30]
    tracked.write_text(str(seeds[3]))
    _fixture_git(root, "add", "--", tracked.name)
    _fixture_git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", "whole number")
    out = tmp_path / "two.json"
    assert roster.main(_beacon_args("draw", out, beacon)) == 0
    data = json.loads(out.read_bytes())
    expected = [*seeds[:3], *seeds[4:79]]
    assert data["design"] + data["spares"] == expected
    captured = capsys.readouterr()
    assert not captured.err
    _no_seed_printed(captured.out + captured.err, seeds)


BEACON_BAD_CASES = ["missing", "not-json", "utf16", "list", "extra", "absent-key", "round-bool",
                    "round-string", "round-zero", "round-negative", "randomness-type", "randomness-short",
                    "randomness-upper", "randomness-nonhex", "signature-type", "signature-empty",
                    "signature-upper", "signature-odd", "signature-nonhex", "signature-space", "hash", "unstaged", "staged",
                    "deleted", "rehearsal", "io"]


@pytest.mark.parametrize("command", ["draw", "verify"])
@pytest.mark.parametrize("case", BEACON_BAD_CASES)
def test_beacon_refusals(tmp_path, monkeypatch, capsys, beacon_tree, command, case):
    root, beacon = beacon_tree
    data = dict(BEACON)
    if case == "list":
        data = []
    elif case == "extra":
        data["extra"] = True
    elif case == "absent-key":
        del data["signature"]
    elif case.startswith("round-"):
        data["round"] = {"bool": True, "string": "1", "zero": 0, "negative": -1}[case[6:]]
    elif case.startswith("randomness-"):
        data["randomness"] = {"type": 1, "short": "ab", "upper": BEACON["randomness"].upper(),
                              "nonhex": "g" * 64}[case[11:]]
    elif case.startswith("signature-"):
        data["signature"] = {"type": 1, "empty": "", "upper": BEACON["signature"].upper(),
                             "odd": "abc", "nonhex": "gg", "space": " " + BEACON["signature"]}[case[10:]]
    elif case == "hash":
        data["randomness"] = "ab" * 32
    elif case in ("unstaged", "staged", "deleted"):
        tracked = root / "tracked file\nname"
        if case == "deleted":
            tracked.unlink()
        else:
            tracked.write_text(str(_raw_candidates()[0]))
        if case == "staged":
            _fixture_git(root, "add", ".")
    beacon.write_bytes(b"{" if case == "not-json" else canon(data).decode().encode("utf-16")
                       if case == "utf16" else canon(data))
    out = tmp_path / "draw.json"
    before = canon(dict(design=_raw_candidates()[:30], spares=_raw_candidates()[30:78],
                        drawn_at="2026-11-14T23:38:51Z")) + b"\n"
    if command == "verify":
        out.write_bytes(before)
    args = _beacon_args(command, out, beacon)
    if case == "missing":
        args = [command, "--packs", "3", "--out" if command == "draw" else "--draw", str(out)]
    elif case == "rehearsal":
        if command == "verify":
            # Verify still validates its beacon; rehearsal is a draw-only switch.
            beacon.write_bytes(b"null")
        else:
            args.append("--rehearsal")
    elif case == "io":
        def fail(*args, **kwargs):
            raise OSError(str(_raw_candidates()[0]))
        monkeypatch.setattr(Path, "read_bytes", fail)
    assert roster.main(args) == 2
    if command == "verify":
        with out.open("rb") as stream:
            assert stream.read() == before
    else:
        assert not out.exists()
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.startswith("refused: ")
    _no_seed_printed(captured.out + captured.err, _raw_candidates())


def test_beacon_shape_time_verify(tmp_path, capsys, beacon_tree):
    root, beacon = beacon_tree
    commit = _fixture_git(root, "rev-parse", "HEAD").decode().strip()
    out = tmp_path / "draw.json"
    assert roster.main(_beacon_args("draw", out, beacon)) == 0
    raw = out.read_bytes()
    data = json.loads(raw)
    assert set(data) == {"design", "spares", "drawn_at"}
    assert data["drawn_at"] == "2026-11-14T23:38:51Z"
    assert raw == canon(data) + b"\n"
    digest = hashlib.sha256(raw).hexdigest()
    assert roster.main(_beacon_args("verify", out, beacon)) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines()[-1] == f"verified sha256 {digest} at {commit}" and not captured.err
    out.write_bytes(raw + b" ")
    assert roster.main(_beacon_args("verify", out, beacon)) == 1
    mismatch = capsys.readouterr()
    assert mismatch.out == f"mismatch at {commit}\n" and not mismatch.err
    out.write_bytes(raw)
    beacon.write_bytes(canon(dict(BEACON, round=BEACON["round"] + 1)))
    assert roster.main(_beacon_args("verify", out, beacon)) == 1
    changed_round = capsys.readouterr()
    assert changed_round.out == f"mismatch at {commit}\n" and not changed_round.err
    with pytest.raises(SystemExit) as caught:
        roster.main(["verify", "--beacon", str(beacon), "--draw", str(out)])
    assert caught.value.code == 2
    missing_packs = capsys.readouterr()
    _no_seed_printed(captured.out + captured.err + mismatch.out + mismatch.err +
                     changed_round.out + changed_round.err + missing_packs.out + missing_packs.err,
                     data["design"] + data["spares"])


@pytest.mark.parametrize("command", ["draw", "verify"])
@pytest.mark.parametrize("stage", ["git", "scan", "write", "draw-read"])
def test_beacon_private_failures(tmp_path, monkeypatch, capsys, beacon_tree, command, stage):
    _, beacon = beacon_tree
    out = tmp_path / "draw.json"
    assert roster.main(_beacon_args("draw", out, beacon)) == 0
    seeds = _raw_candidates()
    if command == "draw":
        out.unlink()
    before = out.read_bytes() if out.exists() else None

    def fail(*args, **kwargs):
        raise OSError(str(seeds[0]))

    if stage == "git":
        monkeypatch.setattr(roster.subprocess, "run", fail)
    elif stage == "scan":
        monkeypatch.setattr(roster, "collisions", fail)
    elif stage == "write":
        if command == "verify":
            monkeypatch.setattr(roster, "_beacon_draw", fail)
        else:
            monkeypatch.setattr(roster, "_write_new", fail)
    else:
        original = Path.read_bytes

        def fail_draw(path):
            return fail() if path == out else original(path)

        if command == "draw":
            monkeypatch.setattr(roster, "_read_beacon", fail)
        else:
            monkeypatch.setattr(Path, "read_bytes", fail_draw)
    success = capsys.readouterr()
    assert roster.main(_beacon_args(command, out, beacon)) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "refused: three-pack operation failed (OSError)\n"
    if command == "draw":
        assert not out.exists()
    else:
        assert out.exists()
        # The draw-read mutant deliberately replaces read_bytes; read through an independent handle.
        with out.open("rb") as stream:
            assert stream.read() == before
    _no_seed_printed(success.out + success.err + captured.out + captured.err, seeds)


def test_beacon_requires_three(tmp_path, capsys, beacon_tree):
    _, beacon = beacon_tree
    out = tmp_path / "draw.json"
    assert roster.main(["draw", "--beacon", str(beacon), "--out", str(out)]) == 2
    assert not out.exists()
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.startswith("refused: ")
    _no_seed_printed(captured.out + captured.err, _raw_candidates())


def _commit(root, message):
    _fixture_git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "commit", "-qm", message)


@pytest.mark.parametrize("changed", [False, True], ids=["verified", "mismatch"])
def test_verify_names_recomputed_commit(tmp_path, capsys, beacon_tree, changed):
    root, beacon = beacon_tree
    commit = _fixture_git(root, "rev-parse", "HEAD").decode().strip()
    out = tmp_path / "draw.json"
    assert roster.main(_beacon_args("draw", out, beacon)) == 0
    raw = out.read_bytes()
    if changed:
        out.write_bytes(raw + b" ")
    capsys.readouterr()
    assert roster.main(_beacon_args("verify", out, beacon)) == int(changed)
    captured = capsys.readouterr()
    expected = f"mismatch at {commit}\n" if changed else (
        f"verified sha256 {hashlib.sha256(raw).hexdigest()} at {commit}\n")
    assert captured.out == expected and captured.err == ""
    _no_seed_printed(captured.out + captured.err, _raw_candidates())


def test_verify_after_committing_draw_names_later_commit(tmp_path, capsys, beacon_tree):
    root, beacon = beacon_tree
    out = tmp_path / "draw.json"
    assert roster.main(_beacon_args("draw", out, beacon)) == 0
    (root / "published-draw.json").write_bytes(out.read_bytes())
    _fixture_git(root, "add", ".")
    _commit(root, "publish fixture draw")
    commit = _fixture_git(root, "rev-parse", "HEAD").decode().strip()
    capsys.readouterr()
    assert roster.main(_beacon_args("verify", out, beacon)) == 1
    captured = capsys.readouterr()
    assert captured.out == f"mismatch at {commit}\n" and captured.err == ""
    _no_seed_printed(captured.out + captured.err, _raw_candidates(200))


def test_verify_help_names_run_commit(capsys):
    with pytest.raises(SystemExit) as caught:
        roster.main(["verify", "--help"])
    assert caught.value.code == 0
    captured = capsys.readouterr()
    help_text = " ".join(captured.out.split())
    assert "checkout of the run commit named in the counted first post on #394" in help_text
    assert "at another commit the result can be mismatch, as at any commit that holds the drawn list" in help_text
    assert captured.err == ""
    _no_seed_printed(captured.out + captured.err, _raw_candidates())


@pytest.mark.parametrize("kind", ["runtime", "git", "missing"])
def test_three_failure_names_kind_without_message(tmp_path, monkeypatch, capsys, kind):
    private = 876543210987654321
    errors = {
        "runtime": RuntimeError(f"synthetic failure {private}"),
        "git": subprocess.CalledProcessError(128, ["git", "ls-tree"], output=str(private), stderr=str(private)),
        "missing": FileNotFoundError(f"synthetic failure {private}"),
    }
    labels = {"runtime": "RuntimeError", "git": "CalledProcessError, git exit 128", "missing": "FileNotFoundError"}

    def fail(*args, **kwargs):
        raise errors[kind]

    monkeypatch.setattr(roster, "_beacon_draw", fail)
    out = tmp_path / "draw.json"
    assert roster.main(_beacon_args("draw", out, tmp_path / "beacon.json")) == 2
    captured = capsys.readouterr()
    _no_seed_printed(captured.out + captured.err, [private])
    assert captured.out == "" and captured.err == f"refused: three-pack operation failed ({labels[kind]})\n"
    assert not out.exists()


def test_verify_reads_the_commit_it_names(tmp_path, monkeypatch, capsys, beacon_tree):
    root, beacon = beacon_tree
    out = tmp_path / "draw.json"
    assert roster.main(_beacon_args("draw", out, beacon)) == 0
    commit = _fixture_git(root, "rev-parse", "HEAD").decode().strip()
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    original = roster._git
    calls = []

    def advance(root, *args, **kwargs):
        calls.append(args)
        if args[0] == "ls-tree":
            (root / "published-draw.json").write_bytes(out.read_bytes())
            _fixture_git(root, "add", ".")
            _commit(root, "advance fixture HEAD before tree read")
        return original(root, *args, **kwargs)

    monkeypatch.setattr(roster, "_git", advance)
    capsys.readouterr()
    assert roster.main(_beacon_args("verify", out, beacon)) == 0
    captured = capsys.readouterr()
    assert captured.out == f"verified sha256 {digest} at {commit}\n" and captured.err == ""
    assert calls.count(("rev-parse", "--verify", "HEAD^{commit}")) == 1
    assert ("ls-tree", "-r", "-z", "--full-tree", commit) in calls
    _no_seed_printed(captured.out + captured.err, _raw_candidates(200))


def _clean_draw(tmp_path, root, beacon):
    """The bytes a third party draws from a fresh clone of the same commit."""
    clone = tmp_path / "fresh-clone"
    _fixture_git(root, "clone", "-q", ".", str(clone))
    out = tmp_path / "clean.json"
    assert roster.draw(out, root=clone, packs=3, beacon=beacon) == 0
    return out.read_bytes()


def _skipped_draw(clean, skipped):
    """The list a checkout would publish if it skipped one more candidate."""
    data = json.loads(clean)
    kept = [n for n in [*data["design"], *data["spares"]] if n != skipped]
    kept.append(next(n for n in _raw_candidates(200) if n not in kept and n != skipped))
    return canon(dict(design=kept[:30], spares=kept[30:], drawn_at=data["drawn_at"])) + b"\n"


def _draw_and_verify(tmp_path, capsys, beacon, clean, skipped):
    commit = _fixture_git(roster.ROOT, "--git-dir=.git", "rev-parse", "HEAD").decode().strip()
    out = tmp_path / "draw.json"
    assert roster.main(_beacon_args("draw", out, beacon)) == 0
    assert out.read_bytes() == clean
    assert roster.main(_beacon_args("verify", out, beacon)) == 0
    out.write_bytes(_skipped_draw(clean, skipped))
    assert roster.main(_beacon_args("verify", out, beacon)) == 1
    captured = capsys.readouterr()
    assert captured.out.splitlines()[-2:] == [f"verified sha256 {hashlib.sha256(clean).hexdigest()} at {commit}",
                                            f"mismatch at {commit}"]
    assert not captured.err
    _no_seed_printed(captured.out + captured.err, _raw_candidates(200))


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_beacon_reads_commit_not_hidden_working_copy(tmp_path, capsys, beacon_tree, flag):
    root, beacon = beacon_tree
    seeds = _raw_candidates()
    clean = _clean_draw(tmp_path, root, beacon)
    tracked = root / "tracked file\nname"
    _fixture_git(root, "update-index", flag, "--", tracked.name)
    tracked.write_bytes(tracked.read_bytes() + f"{seeds[3]}\n".encode())
    _draw_and_verify(tmp_path, capsys, beacon, clean, seeds[3])


@pytest.mark.parametrize("variable", ["GIT_DIR", "GIT_INDEX_FILE"])
def test_beacon_ignores_inherited_git_environment(tmp_path, monkeypatch, capsys, beacon_tree, variable):
    root, beacon = beacon_tree
    seeds = _raw_candidates()
    clean = _clean_draw(tmp_path, root, beacon)
    other = tmp_path / "other"
    _fixture_git(root, "clone", "-q", ".", str(other))
    planted = f"{seeds[3]}\n".encode()
    (other / "planted").write_bytes(planted)
    _fixture_git(other, "add", "planted")
    _commit(other, "planted")
    (root / "planted").write_bytes(planted)  # the same bytes, untracked in the checkout itself
    monkeypatch.setenv(variable, str(other / ".git" / "index" if variable == "GIT_INDEX_FILE" else other / ".git"))
    _draw_and_verify(tmp_path, capsys, beacon, clean, seeds[3])


@pytest.mark.parametrize("working_copy", ["committed", "replaced"])
def test_beacon_ignores_replace_refs(tmp_path, capsys, beacon_tree, working_copy):
    root, beacon = beacon_tree
    seeds = _raw_candidates()
    clean = _clean_draw(tmp_path, root, beacon)
    tracked = root / "tracked file\nname"
    original = _fixture_git(root, "hash-object", "--", tracked.name).decode().strip()
    swapped = tmp_path / "swapped"
    swapped.write_bytes(tracked.read_bytes() + f"{seeds[3]}\n".encode())
    planted = _fixture_git(root, "hash-object", "-w", "--", str(swapped)).decode().strip()
    _fixture_git(root, "replace", original, planted)
    if working_copy == "committed":
        _draw_and_verify(tmp_path, capsys, beacon, clean, seeds[3])
        return
    # A working copy matching the replacement differs from the commit's own blob: both commands refuse.
    tracked.write_bytes(swapped.read_bytes())
    capsys.readouterr()  # drop the clean draw's lines
    out = tmp_path / "draw.json"
    assert roster.main(_beacon_args("draw", out, beacon)) == 2
    assert not out.exists()
    out.write_bytes(_skipped_draw(clean, seeds[3]))
    assert roster.main(_beacon_args("verify", out, beacon)) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "refused: checkout differs from HEAD\n" * 2
    _no_seed_printed(captured.out + captured.err, _raw_candidates(200))


def test_beacon_scan_counts_committed_blobs_only(tmp_path, capsys, beacon_tree):
    root, beacon = beacon_tree
    seeds = _raw_candidates(90)
    (root / "tracked").write_text(f"{seeds[2]}\n")  # committed whole number: skipped
    (root / "nested" / "deeper").mkdir(parents=True)
    (root / "nested" / "deeper" / "file").write_text(f"{seeds[6]}\n")  # committed in a subtree: skipped
    (root / "link").symlink_to(str(seeds[3]))  # dangling link; its blob is the decimal text: skipped
    (root / "untracked").write_text(f"{seeds[4]}\n")  # never committed: kept
    # A gitlink to a commit whose message holds a candidate: a submodule entry, never scanned.
    holder = _fixture_git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                          "commit-tree", "HEAD^{tree}", "-m", str(seeds[5])).decode().strip()
    (root / "sub").mkdir()
    _fixture_git(root, "add", "--", "tracked", "link", "nested")
    _fixture_git(root, "update-index", "--add", "--cacheinfo", f"160000,{holder},sub")
    _commit(root, "what counts")
    out = tmp_path / "draw.json"
    assert roster.main(_beacon_args("draw", out, beacon)) == 0
    data = json.loads(out.read_bytes())
    assert data["design"] + data["spares"] == [*seeds[:2], *seeds[4:6], *seeds[7:81]]
    captured = capsys.readouterr()
    assert not captured.err
    _no_seed_printed(captured.out + captured.err, seeds)


@pytest.mark.parametrize("command", ["draw", "verify"])
@pytest.mark.parametrize("case", ["missing", "type", "id", "short-last", "missing-lf", "leftover",
                                  "size", "signed-size", "header-lf", "wrong-lf", "size-limit"])
def test_beacon_refuses_malformed_blob_reply(tmp_path, monkeypatch, capsys, beacon_tree, command, case):
    root, beacon = beacon_tree
    clean = _clean_draw(tmp_path, root, beacon)
    original = roster._git
    listing = original(root, "ls-tree", "-r", "-z", "--full-tree", "HEAD").stdout
    oid = listing.split(b"\t", 1)[0].split(b" ")[2]
    good = original(root, "cat-file", "--batch", stdin=oid + b"\n").stdout
    replies = {
        "missing": oid + b" missing\n",
        "type": oid + b" tree 1\nx\n",
        "id": b"0" * len(oid) + b" blob 1\nx\n",
        "short-last": oid + b" blob 20\nx\n",
        "missing-lf": good[:-1],
        "leftover": good + b"extra",
        "size": oid + b" blob x\nx\n",
        "signed-size": oid + b" blob +1\nx\n",
        "header-lf": oid + b" blob 1",
        "wrong-lf": good[:-1] + b"x",
        "size-limit": oid + b" blob " + b"9" * 5000 + b"\nx\n",
    }

    def reply(root, *args, **kwargs):
        if args == ("cat-file", "--batch"):
            assert kwargs["stdin"] == oid + b"\n"  # listing is real; replace only this call
            return subprocess.CompletedProcess(args, 0, stdout=replies[case])
        return original(root, *args, **kwargs)

    monkeypatch.setattr(roster, "_git", reply)
    out = tmp_path / "draw.json"
    if command == "verify":
        out.write_bytes(clean)
    capsys.readouterr()
    assert roster.main(_beacon_args(command, out, beacon)) == 2
    assert out.read_bytes() == clean if command == "verify" else not out.exists()
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "refused: invalid commit blob reply\n"
    assert oid.decode() not in captured.err
    _no_seed_printed(captured.out + captured.err, _raw_candidates())


@pytest.mark.parametrize("command", ["draw", "verify"])
@pytest.mark.parametrize("case", ["type", "malformed", "mode", "commit-mode", "empty-path", "no-nul", "empty-entry", "object"])
def test_beacon_refuses_malformed_tree_listing(tmp_path, monkeypatch, capsys, beacon_tree, command, case):
    root, beacon = beacon_tree
    clean = _clean_draw(tmp_path, root, beacon)
    original = roster._git
    entries = original(root, "ls-tree", "-r", "-z", "--full-tree", "HEAD").stdout
    oid = entries.split(b"\t", 1)[0].split(b" ")[2]
    listings = {
        "type": b"040000 tree " + oid + b"\tsynthetic\0",
        "malformed": b"100644 blob " + oid + b" synthetic\0",
        "mode": b"invalid blob " + oid + b"\tsynthetic\0",
        "commit-mode": b"100644 commit " + oid + b"\tsynthetic\0",
        "empty-path": b"100644 blob " + oid + b"\t\0",
        "no-nul": b"100644 blob " + oid + b"\tsynthetic",
        "empty-entry": b"\0",
        "object": b"100644 blob " + oid[:-1] + b"\tsynthetic\0",
    }

    def listing(root, *args, **kwargs):
        if args == ("ls-tree", "-r", "-z", "--full-tree", _fixture_git(root, "rev-parse", "HEAD").decode().strip()):
            return subprocess.CompletedProcess(args, 0, stdout=listings[case])
        if case == "object" and args == ("cat-file", "--batch"):
            # Echo the requested short id, so only the listing's id-length check can refuse.
            assert kwargs["stdin"] == oid[:-1] + b"\n"
            reply = original(root, *args, stdin=oid + b"\n").stdout
            return subprocess.CompletedProcess(args, 0, stdout=oid[:-1] + reply[len(oid):])
        return original(root, *args, **kwargs)

    monkeypatch.setattr(roster, "_git", listing)
    out = tmp_path / "draw.json"
    if command == "verify":
        out.write_bytes(clean)
    capsys.readouterr()
    assert roster.main(_beacon_args(command, out, beacon)) == 2
    assert out.read_bytes() == clean if command == "verify" else not out.exists()
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "refused: invalid commit blob reply\n"
    assert oid.decode() not in captured.err
    _no_seed_printed(captured.out + captured.err, _raw_candidates())


def test_beacon_accepts_exact_blob_replies_and_omits_commits(tmp_path, monkeypatch, capsys, beacon_tree):
    root, beacon = beacon_tree
    (root / "empty").touch()
    (root / "binary").write_bytes(b"x\0\nx\n")
    (root / "duplicate").write_bytes(b"x\0\nx\n")
    _fixture_git(root, "add", ".")
    _commit(root, "multiple blobs")
    clean = _clean_draw(tmp_path, root, beacon)
    original = roster._git
    commit = _fixture_git(root, "rev-parse", "HEAD").strip()

    def exact(root, *args, **kwargs):
        result = original(root, *args, **kwargs)
        if args[:4] == ("ls-tree", "-r", "-z", "--full-tree"):
            assert args[4] in ("HEAD", commit.decode())
            result.stdout += b"160000 commit " + commit + b"\tsub\0"
        elif args == ("cat-file", "--batch"):
            assert commit + b"\n" not in kwargs["stdin"]
            # Return the real, exact reply through the same stand-in used for corrupt replies.
            return subprocess.CompletedProcess(args, 0, stdout=result.stdout)
        return result

    monkeypatch.setattr(roster, "_git", exact)
    assert roster._commit_blobs(root) == [b"x\0\nx\n", b"x\0\nx\n", b"", b"synthetic committed text\n"]
    out = tmp_path / "draw.json"
    assert roster.main(_beacon_args("draw", out, beacon)) == 0
    assert out.read_bytes() == clean
    assert roster.main(_beacon_args("verify", out, beacon)) == 0
    captured = capsys.readouterr()
    assert not captured.err
    _no_seed_printed(captured.out + captured.err, _raw_candidates())


@pytest.mark.parametrize("command", ["draw", "verify"])
def test_beacon_refuses_export_inside_another_repository(tmp_path, monkeypatch, capsys, beacon_tree, command):
    root, beacon = beacon_tree
    clean = _clean_draw(tmp_path, root, beacon)
    enclosing = tmp_path / "enclosing"
    enclosing.mkdir()
    _fixture_git(enclosing, "init", "-q")
    (enclosing / "planted").write_text(str(_raw_candidates()[3]))
    exported = enclosing / "export"
    exported.mkdir()
    # This fixture commit holds one ordinary file; export only its committed bytes, never .git.
    name = "tracked file\nname"
    (exported / name).write_bytes(_fixture_git(root, "show", f"HEAD:{name}"))
    _fixture_git(enclosing, "add", ".")
    _commit(enclosing, "enclosing tree")
    assert _fixture_git(enclosing, "diff", "--quiet", "HEAD", "--") == b""
    original = roster._git

    calls = []

    def before_clean(root, *args, **kwargs):
        calls.append(args[0])
        return original(root, *args, **kwargs)

    monkeypatch.setattr(roster, "_git", before_clean)
    monkeypatch.setattr(roster, "ROOT", exported)
    out = tmp_path / "draw.json"
    if command == "verify":
        out.write_bytes(clean)
    capsys.readouterr()
    assert roster.main(_beacon_args(command, out, beacon)) == 2
    assert out.read_bytes() == clean if command == "verify" else not out.exists()
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "refused: root is not the repository top level\n"
    assert "diff" not in calls  # top-level refusal precedes the clean-checkout check
    _no_seed_printed(captured.out + captured.err, _raw_candidates())


@pytest.mark.parametrize("command", ["draw", "verify"])
@pytest.mark.parametrize("case", ["exit", "extra-output"])
def test_beacon_refuses_invalid_top_level_reply(tmp_path, monkeypatch, capsys, beacon_tree, command, case):
    root, beacon = beacon_tree
    clean = _clean_draw(tmp_path, root, beacon)
    original = roster._git

    def top(root, *args, **kwargs):
        if args == ("rev-parse", "--show-toplevel"):
            return subprocess.CompletedProcess(args, 1 if case == "exit" else 0,
                                               stdout=str(root.resolve()).encode() + b"\n" +
                                               (b"extra\n" if case == "extra-output" else b""))
        return original(root, *args, **kwargs)

    monkeypatch.setattr(roster, "_git", top)
    out = tmp_path / "draw.json"
    if command == "verify":
        out.write_bytes(clean)
    capsys.readouterr()
    assert roster.main(_beacon_args(command, out, beacon)) == 2
    assert out.read_bytes() == clean if command == "verify" else not out.exists()
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == "refused: root is not the repository top level\n"
    _no_seed_printed(captured.out + captured.err, _raw_candidates())


@pytest.mark.parametrize("command", ["draw", "verify"])
@pytest.mark.parametrize("case", ["symlink", "other", "missing", "two-lines", "no-lf"])
def test_beacon_top_level_directory_identity(tmp_path, monkeypatch, capsys, beacon_tree, command, case):
    root, beacon = beacon_tree
    clean = _clean_draw(tmp_path, root, beacon)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    other = tmp_path / "other"
    other.mkdir()
    replies = {
        "symlink": os.fsencode(alias) + b"\n",
        "other": os.fsencode(other) + b"\n",
        "missing": os.fsencode(tmp_path / "missing") + b"\n",
        "two-lines": os.fsencode(root) + b"\nextra\n",
        "no-lf": os.fsencode(root),
    }
    original = roster._git

    def top(root, *args, **kwargs):
        if args == ("rev-parse", "--show-toplevel"):
            return subprocess.CompletedProcess(args, 0, stdout=replies[case])
        return original(root, *args, **kwargs)

    monkeypatch.setattr(roster, "_git", top)
    out = tmp_path / "draw.json"
    if command == "verify":
        out.write_bytes(clean)
    capsys.readouterr()
    assert roster.main(_beacon_args(command, out, beacon)) == (0 if case == "symlink" else 2)
    assert out.read_bytes() == clean if command == "verify" or case == "symlink" else not out.exists()
    captured = capsys.readouterr()
    if case == "symlink":
        digest = hashlib.sha256(clean).hexdigest()
        commit = _fixture_git(root, "rev-parse", "HEAD").decode().strip()
        assert captured.out == (f"sha256 {digest}\ndesign 30 spares 48\nround {BEACON['round']}\n"
                                if command == "draw" else f"verified sha256 {digest} at {commit}\n")
        assert not captured.err
    else:
        assert captured.out == "" and captured.err == "refused: root is not the repository top level\n"
    _no_seed_printed(captured.out + captured.err, _raw_candidates())


def test_beacon_accepts_case_swapped_root(tmp_path, monkeypatch, capsys, beacon_tree):
    root, beacon = beacon_tree
    swapped = root.with_name(root.name.swapcase())
    if not swapped.exists() or not os.path.samefile(swapped, root):
        pytest.skip("fixture volume is case-sensitive")
    clean = _clean_draw(tmp_path, root, beacon)
    monkeypatch.setattr(roster, "ROOT", swapped)
    out = tmp_path / "draw.json"
    capsys.readouterr()
    assert roster.main(_beacon_args("draw", out, beacon)) == 0
    assert out.read_bytes() == clean
    captured = capsys.readouterr()
    assert not captured.err
    _no_seed_printed(captured.out + captured.err, _raw_candidates())
