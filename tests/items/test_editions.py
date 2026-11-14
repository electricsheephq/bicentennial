"""Template editions: v2 repairs and round 2's v3 finalists preserve the earlier editions and pins."""

import dataclasses
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial import cue_words
from bicentennial.controls.cache import CONTROL_FILES
from bicentennial.items import bindings, c7
from bicentennial.items.editions import BY_REF, C7_FILES, EDITIONS
from bicentennial.items.templates import g1, g2, g2_v2
from bicentennial.items.templates.g1.common import LEVER_MIX_LABEL
from bicentennial.packs import build
from bicentennial.packs.manifest import file_sha256
from bicentennial.packs.scoring import SCORING_FILES
from bicentennial.score.check_selftest import check_roles, mutant_roles

ROOT = Path(__file__).resolve().parents[2]
SWAPPED = {"G1": ("drift-chain-fault", "drift-config", "drift-quote"), "G2": ("recall-count",)}
NEW_FILES = ("items/editions.py", "items/templates/g1/drift_action_v2.py", "items/templates/g1/drift_chain_v2.py",
             "items/templates/g2_v2/__init__.py", "items/templates/g2_v2/recall_count.py",
             "items/templates/g1/drift_action_v3.py", "items/templates/g1/drift_chain_v3.py")
DEPARTURE = ("validity round 2 (results/validity-2/PLAN.md §4): varies lever 1, no cue in the prompt, "
             "instead of the cell's primary lever (chain_depth)")


def pairs(version=2):
    """(v1, replacement) for each template swapped in by an edition."""
    ids = (*SWAPPED["G1"], *SWAPPED["G2"]) if version == 2 else SWAPPED["G1"]
    return [(BY_REF[f"{tid}-v1"], BY_REF[f"{tid}-v{version}"]) for tid in ids]


def test_registries():
    assert len(g1.TEMPLATES) == 7 and len(g2.TEMPLATES) == 8
    assert EDITIONS[1] == {"G1": g1.TEMPLATES, "G2": g2.TEMPLATES}
    assert set(EDITIONS) == set(C7_FILES) == {1, 2, 3}
    for edition in (2, 3):
        for genre in ("G1", "G2"):
            one, newer = EDITIONS[1][genre], EDITIONS[edition][genre]
            assert [t.template_id for t in newer] == [t.template_id for t in one]
            assert len({t.template_id for t in newer}) == len(newer)
            swapped = SWAPPED[genre] if edition == 2 or genre == "G1" else ()
            for a, b in zip(one, newer, strict=True):
                assert (b.version, b is a) == ((edition, False) if a.template_id in swapped else (1, True))
    assert {*g1.TEMPLATES_V2, *g2_v2.TEMPLATES_V2} == {v2 for _, v2 in pairs()}
    assert set(g1.TEMPLATES_V3) == {v3 for _, v3 in pairs(3)}
    assert EDITIONS[3]["G2"] is EDITIONS[1]["G2"]
    assert len(BY_REF) == 22 and all(ref == t.ref for ref, t in BY_REF.items())


@pytest.mark.parametrize("version", [2, 3])
def test_new_versions_keep_v1_fields_tables_and_bindings(version):
    for v1, v2 in pairs(version):
        fields = {f.name for f in dataclasses.fields(v1)}
        assert {f.name for f in dataclasses.fields(v2)} == fields and isinstance(v2, type(v1))
        assert ({f: getattr(v2, f) for f in fields - {"version", "decision_tables"}}
                == {f: getattr(v1, f) for f in fields - {"version", "decision_tables"}})
        assert [dict(t, table_id=None) for t in v2.decision_tables] == [
            dict(t, table_id=None) for t in v1.decision_tables]
        assert [t["table_id"] for t in v2.decision_tables] == [
            t["table_id"].removesuffix("-v1") + f"-v{version}" for t in v1.decision_tables]
        path = f"{type(v1).__module__}.{type(v1).__qualname__}"
        assert type(v2).BINDING_FIELDS == bindings.BINDING_FIELDS[path]
        assert f"{type(v2).__module__}.{type(v2).__qualname__}" not in bindings.BINDING_FIELDS


@pytest.mark.parametrize("version", [2, 3])
def test_new_tables_have_v1_mutant_roles(version):
    roles = mutant_roles()
    for v1, v2 in pairs(version):
        for a, b in zip(v1.decision_tables, v2.decision_tables, strict=True):
            check_roles(b, roles)
            assert roles[b["table_id"]] == roles[a["table_id"]]
            with pytest.raises(ValueError):
                check_roles(b, {b["table_id"]: {"stale": ("wrong",)}} if a["disqualifiers"] else {})


def test_v3_tables_keep_the_screening_roles():
    for template in g1.TEMPLATES_V3:
        for table in template.decision_tables:
            tid = table["table_id"]
            assert g1.G1_MUTANT_ROLES[tid] == g1.G1_MUTANT_ROLES[tid.removesuffix("-v3") + "-v2"]


@pytest.mark.parametrize("version", [2, 3])
def test_fault_chain_requires_fault(version):
    template = BY_REF[f"drift-chain-fault-v{version}"]
    with pytest.raises(ValueError):
        dataclasses.replace(template, fault=False)


def test_cue_words_pass_on_the_source(capsys):
    assert cue_words.main([]) == 0
    assert capsys.readouterr().out == ""


def test_new_files_stay_outside_the_pinned_sets():
    assert not set(NEW_FILES) & set(CONTROL_FILES) and not set(NEW_FILES) & set(SCORING_FILES)
    package = ROOT / "src/bicentennial"
    assert all((package / p).is_file() for p in NEW_FILES)


def test_c7_partial_unchanged_and_edition2_committed():
    pinned = tomllib.loads((ROOT / "packs/catalogue-v0.toml").read_text(encoding="utf-8"))["c7_sha256"]
    assert file_sha256(ROOT / C7_FILES[1]) == pinned
    assert file_sha256(ROOT / C7_FILES[2]) == "e06abd451a1912ba518095da7e50b86b277e2c4439f9ac3aa38a0dd92aa36a31"
    committed = (ROOT / C7_FILES[2]).read_text(encoding="utf-8")
    assert committed == c7.dumps(c7.freeze(ROOT, edition=2))
    one, two = (json.loads((ROOT / C7_FILES[e]).read_bytes())["entries"] for e in (1, 2))
    assert sorted(set(two) - set(one)) == sorted(v2.ref for _, v2 in pairs())
    assert sorted(set(one) - set(two)) == sorted(v1.ref for v1, _ in pairs())
    assert all(one[ref] == two[ref] for ref in set(one) & set(two))
    out = subprocess.run([sys.executable, "-m", "bicentennial.items.c7", str(ROOT), "--edition", "2"], cwd=ROOT,
                         check=True, capture_output=True, text=True, env={**os.environ, "PYTHONHASHSEED": "random"})
    assert out.stdout == committed


def test_c7_edition3_committed_and_shared_entries_unchanged():
    committed = (ROOT / C7_FILES[3]).read_text(encoding="utf-8")
    assert committed == c7.dumps(c7.freeze(ROOT, edition=3))
    one, three = (json.loads((ROOT / C7_FILES[e]).read_bytes())["entries"] for e in (1, 3))
    assert set(three) - set(one) == {v3.ref for _, v3 in pairs(3)}
    assert set(one) - set(three) == {v1.ref for v1, _ in pairs(3)}
    assert all(one[ref] == three[ref] for ref in set(one) & set(three))
    for v1, v3 in pairs(3):
        assert v3.lever_mix == dict(v1.lever_mix, departure=DEPARTURE)
        assert three[v3.ref]["lever_mix"]["template"] == dict(v1.lever_mix, departure=DEPARTURE)
        assert three[v3.ref]["lever_mix"]["template"]["label"] == LEVER_MIX_LABEL
    out = subprocess.run([sys.executable, "-m", "bicentennial.items.c7", str(ROOT), "--edition", "3"], cwd=ROOT,
                         check=True, capture_output=True, text=True, env={**os.environ, "PYTHONHASHSEED": "random"})
    assert out.stdout == committed


def life(genre):
    return SimpleNamespace(genre=genre, twin=SimpleNamespace(compiled=SimpleNamespace(
        items=[dict(item_id="i1", probe_point=5)])))


@pytest.mark.parametrize("edition, version, refused", [(1, 1, False), (2, 2, False), (2, 1, True), (1, 2, True),
                                                      (2, 9, True), (3, 3, False), (3, 1, True), (3, 2, True),
                                                      (1, 3, True), (2, 3, True)])
def test_templates_resolve_within_the_edition(edition, version, refused):
    records = [dict(item_id="i1", template_id="drift-quote", template_version=version)]
    if refused:
        with pytest.raises(build.PackRefused, match="^edition$"):
            build._templates(life("G1"), records, edition=edition)
    else:
        template, = build._templates(life("G1"), records, edition=edition)
        assert (template.ref, template.checkpoint) == (f"drift-quote-v{version}", 5)


def test_templates_refuse_another_genre():
    records = [dict(item_id="i1", template_id="recall-count", template_version=2)]
    with pytest.raises(build.PackRefused, match="^edition$"):
        build._templates(life("G1"), records, edition=2)


@pytest.mark.parametrize("kwargs", [dict(edition=4), dict(edition=2, tier="T0"), dict(edition=3, tier="T0"),
                                    dict(spec_path="x", tier="T0")])
def test_build_tier_refuses_an_edition_it_cannot_build(tmp_path, kwargs):
    tier = kwargs.pop("tier", "T2")
    with pytest.raises(ValueError, match="^edition$"):
        build.build_tier(tier, tmp_path, harness_artifacts=[], **kwargs)
    assert list(tmp_path.iterdir()) == []
