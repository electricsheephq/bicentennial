"""The committed C-7 freeze matches the template build, entry by entry and byte for byte."""

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bicentennial.canon import sha256_canon
from bicentennial.items import c7
from bicentennial.items.templates import g1, g2

ROOT = Path(__file__).resolve().parents[2]


def committed():
    return (ROOT / c7.FREEZE).read_text(encoding="utf-8")


def test_committed_freeze_matches_the_template_build():
    assert committed() == c7.dumps(c7.freeze(ROOT))


def test_every_template_has_an_entry_whose_hash_recomputes():
    frozen = json.loads(committed())
    refs = sorted(t.ref for t in (*g1.TEMPLATES, *g2.TEMPLATES))
    assert sorted(frozen["entries"]) == refs and len(refs) == len(set(refs)) == 15
    for ref, e in frozen["entries"].items():
        body = {k: v for k, v in e.items() if k != "entry_sha256"}
        assert e["ref"] == ref and e["entry_sha256"] == sha256_canon(body)
        assert e["lever_mix"] == {"primary": e["cell"]["primary_lever"], "value": "uncalibrated (v0.2)",
                                  "other_levers": "neutral"}
    assert frozen["file_sha256_of_entries"] == sha256_canon(frozen["entries"])


@pytest.mark.parametrize("field, value", [("direction", "verbatim retention"), ("depth", 3), ("version", 2)])
def test_a_template_change_changes_its_entry(field, value):
    template, cells = g1.TEMPLATES[0], c7.cells(ROOT)
    assert getattr(template, field) != value
    changed = c7.entry(dataclasses.replace(template, **{field: value}), "g1", cells)
    assert changed["entry_sha256"] != c7.entry(template, "g1", cells)["entry_sha256"]


def test_same_bytes_under_any_hash_seed():
    outs = {subprocess.run([sys.executable, "-m", "bicentennial.items.c7", str(ROOT)], cwd=ROOT, check=True,
                           capture_output=True, text=True, env={**os.environ, "PYTHONHASHSEED": seed}).stdout
            for seed in ("0", "1", "random")}
    assert outs == {committed()}
