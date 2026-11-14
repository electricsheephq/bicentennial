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
