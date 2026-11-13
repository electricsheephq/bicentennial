"""Template editions (#505, #506): v2 of four templates, swapped in by id, with every v1 pin unchanged."""

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
from bicentennial.packs import build
from bicentennial.packs.manifest import file_sha256
from bicentennial.packs.scoring import SCORING_FILES
from bicentennial.score.check_selftest import check_roles, mutant_roles

ROOT = Path(__file__).resolve().parents[2]
SWAPPED = {"G1": ("drift-chain-fault", "drift-config", "drift-quote"), "G2": ("recall-count",)}
NEW_FILES = ("items/editions.py", "items/templates/g1/drift_action_v2.py", "items/templates/g1/drift_chain_v2.py",
             "items/templates/g2_v2/__init__.py", "items/templates/g2_v2/recall_count.py")


def pairs():
    """(v1, v2) for each of the four swapped templates."""
    return [(BY_REF[f"{tid}-v1"], BY_REF[f"{tid}-v2"]) for ids in SWAPPED.values() for tid in ids]


def test_registries():
    assert len(g1.TEMPLATES) == 7 and len(g2.TEMPLATES) == 8
    assert EDITIONS[1] == {"G1": g1.TEMPLATES, "G2": g2.TEMPLATES}
    assert set(EDITIONS) == set(C7_FILES) == {1, 2}
    for genre in ("G1", "G2"):
        one, two = EDITIONS[1][genre], EDITIONS[2][genre]
        assert [t.template_id for t in two] == [t.template_id for t in one]
        assert len({t.template_id for t in two}) == len(two)
        for a, b in zip(one, two, strict=True):
            assert (b.version, b is a) == ((2, False) if a.template_id in SWAPPED[genre] else (1, True))
    assert {*g1.TEMPLATES_V2, *g2_v2.TEMPLATES_V2} == {v2 for _, v2 in pairs()}
    assert len(BY_REF) == 19 and all(ref == t.ref for ref, t in BY_REF.items())


def test_v2_keeps_v1_fields_tables_and_bindings():
    for v1, v2 in pairs():
        fields = {f.name for f in dataclasses.fields(v1)}
        assert {f.name for f in dataclasses.fields(v2)} == fields and isinstance(v2, type(v1))
        assert ({f: getattr(v2, f) for f in fields - {"version", "decision_tables"}}
                == {f: getattr(v1, f) for f in fields - {"version", "decision_tables"}})
        assert [dict(t, table_id=None) for t in v2.decision_tables] == [
            dict(t, table_id=None) for t in v1.decision_tables]
        assert [t["table_id"] for t in v2.decision_tables] == [
            t["table_id"].removesuffix("-v1") + "-v2" for t in v1.decision_tables]
        path = f"{type(v1).__module__}.{type(v1).__qualname__}"
        assert type(v2).BINDING_FIELDS == bindings.BINDING_FIELDS[path]
        assert f"{type(v2).__module__}.{type(v2).__qualname__}" not in bindings.BINDING_FIELDS


def test_v2_tables_have_v1_mutant_roles():
    roles = mutant_roles()
    for v1, v2 in pairs():
        for a, b in zip(v1.decision_tables, v2.decision_tables, strict=True):
            check_roles(b, roles)
            assert roles[b["table_id"]] == roles[a["table_id"]]
            with pytest.raises(ValueError):
                check_roles(b, {b["table_id"]: {"stale": ("wrong",)}} if a["disqualifiers"] else {})


def test_fault_chain_v2_requires_fault():
    template = BY_REF["drift-chain-fault-v2"]
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
    committed = (ROOT / C7_FILES[2]).read_text(encoding="utf-8")
    assert committed == c7.dumps(c7.freeze(ROOT, edition=2))
    one, two = (json.loads((ROOT / C7_FILES[e]).read_bytes())["entries"] for e in (1, 2))
    assert sorted(set(two) - set(one)) == sorted(v2.ref for _, v2 in pairs())
    assert sorted(set(one) - set(two)) == sorted(v1.ref for v1, _ in pairs())
    assert all(one[ref] == two[ref] for ref in set(one) & set(two))
    out = subprocess.run([sys.executable, "-m", "bicentennial.items.c7", str(ROOT), "--edition", "2"], cwd=ROOT,
                         check=True, capture_output=True, text=True, env={**os.environ, "PYTHONHASHSEED": "random"})
    assert out.stdout == committed


def life(genre):
    return SimpleNamespace(genre=genre, twin=SimpleNamespace(compiled=SimpleNamespace(
        items=[dict(item_id="i1", probe_point=5)])))


@pytest.mark.parametrize("edition, version, refused", [(1, 1, False), (2, 2, False), (2, 1, True), (1, 2, True),
                                                      (2, 9, True)])
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


@pytest.mark.parametrize("kwargs", [dict(edition=3), dict(edition=2, tier="T0"), dict(spec_path="x", tier="T0")])
def test_build_tier_refuses_an_edition_it_cannot_build(tmp_path, kwargs):
    tier = kwargs.pop("tier", "T2")
    with pytest.raises(ValueError, match="^edition$"):
        build.build_tier(tier, tmp_path, harness_artifacts=[], **kwargs)
    assert list(tmp_path.iterdir()) == []
