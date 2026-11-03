"""Public T2 packs: deterministic build, controls, receipts and compiled templates."""

import json
import re
from dataclasses import asdict
from pathlib import Path

import pytest

from bicentennial import cli
from bicentennial.canon import canon
from bicentennial.items.compile import compile_branch
from bicentennial.packs import build
from bicentennial.packs import manifest as mf
from bicentennial.world import targeted as t
from bicentennial.world.db import open_world

from .test_build import A

ROOT = Path(__file__).resolve().parents[2]


def build_pair(tmp_path, monkeypatch):
    spec = t.load_tier(ROOT / "tiers/life_specs/t2.toml")
    spec["lives"] = [spec["lives"][0], spec["lives"][5]]
    monkeypatch.setattr(build, "load_tier", lambda path: spec)
    return build.build_tier("T2", tmp_path, harness_artifacts=A)


@pytest.fixture(scope="module")
def built_t2(tmp_path_factory):
    out = tmp_path_factory.mktemp("t2")
    compiled_templates, packaged_templates = [], []
    original_twin, original_templates = t.twin_life, build._templates

    def capture_twin(db, schedule, templates, **kwargs):
        compiled_templates.append([asdict(v) for v in templates])
        return original_twin(db, schedule, templates, **kwargs)

    def capture_templates(life, records, spec=None):
        assigned = original_templates(life, records, spec)
        packaged_templates.append([asdict(v) for v in assigned])
        return assigned

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(t, "twin_life", capture_twin)
        mp.setattr(build, "_templates", capture_templates)
        first = build_pair(out / "first", mp)
        second = build_pair(out / "second", mp)
    assert packaged_templates == compiled_templates
    return out, first, second


def test_t2_deterministic_controls_receipt(built_t2):
    out, first, second = built_t2
    assert first == second
    assert mf.file_manifest(out / "first/T2") == mf.file_manifest(out / "second/T2")
    assert len(first["index"]["packs"]) == 2
    for rel in first["index"]["packs"]:
        path = out / "first/T2" / rel
        pack = json.loads((path / "sealed/pack.json").read_bytes())
        manifest = json.loads((path / "manifest.json").read_bytes())
        assert manifest["labels"] == mf.labels("T2")
        assert isinstance(pack["controls"]["naive_rag"], dict)
        assert pack["controls"]["naive_rag"]["aggregates"]
        assert pack["controls"]["naive_rag"]["entry_sha256"] == mf.file_sha256(path / "sealed/naive_rag.json")
        sessions = (path / "sealed/life/sessions.B0.jsonl").read_bytes().splitlines()
        assert len(sessions) == 10
        assert {i["probe_point"] for i in pack["items"]} == {5, 10}
        receipt = build.validate_t2_receipt(path)
        assert receipt["check_pack"]["ok"]
        assert "build_receipt.json" in manifest["files"]
        assert receipt["controls_broken"] == json.loads((path / "sealed/controls.json").read_bytes())["broken"]


def test_receipt_required_to_finish(tmp_path, monkeypatch):
    original = build._normalise_sqlite_headers

    def remove(root):
        original(root)
        (root.parent.parent / "build_receipt.json").unlink(missing_ok=True)

    monkeypatch.setattr(build, "_normalise_sqlite_headers", remove)
    with pytest.raises(build.PackRefused, match="^build_receipt$"):
        build_pair(tmp_path, monkeypatch)
    assert not (tmp_path / "T2").exists()


@pytest.mark.parametrize("change", ["remove", "alter"])
def test_receipt_validates_beside_pack(built_t2, change):
    out, first, _ = built_t2
    rel = next(iter(first["index"]["packs"]))
    path = out / "first/T2" / rel
    receipt = path / "build_receipt.json"
    before = receipt.read_bytes()
    try:
        if change == "remove":
            receipt.unlink()
        else:
            value = json.loads(before)
            value["competing"] = []
            value["check_pack"]["ok"] = False
            receipt.write_bytes(canon(value))
        with pytest.raises(build.PackRefused, match="^build_receipt$"):
            build.validate_t2_receipt(path)
    finally:
        receipt.write_bytes(before)


@pytest.mark.parametrize("genre,index", [("G1", 0), ("G2", 5)])
def test_pack_templates_equal_compiled_life(tmp_path, monkeypatch, genre, index):
    spec = t.load_tier(ROOT / "tiers/life_specs/t2.toml")
    row = spec["lives"][index]
    captured = []
    original = t.twin_life

    def capture(db, schedule, templates, **kwargs):
        captured.extend(templates)
        return original(db, schedule, templates, **kwargs)

    monkeypatch.setattr(t, "twin_life", capture)
    life = t.t1_life(spec, row, (build.g1 if genre == "G1" else build.g2).TEMPLATES, out_dir=tmp_path / "work")
    try:
        assigned = build._templates(life, life.twin.compiled.records, spec)
        assert [asdict(v) for v in assigned] == [asdict(v) for v in captured]
        with open_world(life.out_dir / "world.B0.db", readonly=True) as db:
            branch = compile_branch(db, life.schedule, life.twin.cuts[0], assigned)
        records = {r["item_id"] for r in life.twin.compiled.records if r["branch"] == "B0"}
        assert {item["item_id"] for item, _ in branch.entries} == records
    finally:
        life.twin.b1.close()


def write_spec(path, rows):
    text = (ROOT / "tiers/life_specs/t2.toml").read_text()
    text = re.sub(r'\[\[lives\]\].*?(?=\[\[lives\]\]|\[selection\])', '', text, flags=re.S)
    for row in rows:
        text += '\n[[lives]]\n' + ''.join(f'{key} = {json.dumps(value)}\n' for key, value in row.items())
    path.write_text(text)


@pytest.mark.parametrize("count", [1, 10, 12])
def test_t2_spec_roster_lengths(tmp_path, count):
    rows = [dict(life=f"draw-{i}", genre="G2", seed=100 + i) for i in range(count)]
    path = tmp_path / "tier.toml"
    write_spec(path, rows)
    assert t.load_tier(path)["lives"] == rows


@pytest.mark.parametrize("before,after", [("checkpoints = [5, 10]", "checkpoints = [10, 20]"),
                                         ("session = 6", "session = 5")])
def test_t2_spec_rejects_wrong_shape(tmp_path, before, after):
    path = tmp_path / "tier.toml"
    path.write_text((ROOT / "tiers/life_specs/t2.toml").read_text().replace(before, after))
    with pytest.raises(t.PlacementError, match="^composition$"):
        t.load_tier(path)


def test_t2_cli_reaches_builder(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.setattr(cli, "reexec_niced", lambda argv: None)
    monkeypatch.setattr(build, "build_tier", lambda tier, out, **kwargs:
                        seen.append((tier, out)) or dict(pack_hash="a" * 64, sqlite_version="test"))
    assert cli.main(["build", "--tier", "T2", "--out", str(tmp_path)]) == 0
    assert seen == [("T2", str(tmp_path))]
