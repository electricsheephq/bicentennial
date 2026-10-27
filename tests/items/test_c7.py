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
from bicentennial.items.levers import LEVERS
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
        mix = e["lever_mix"]
        assert mix["primary"] == e["cell"]["primary_lever"] and mix["value"] == "uncalibrated (v0.2)"
        assert mix["primary_key"] in (*LEVERS, None) and (mix["primary_key"] is None) == (e["cell_id"] == "RECALL-AGG")
        assert (mix["template"] is None) == (e["genre"] == "g2")
        assert f"items/templates/{e['genre']}/common.py" in e["source_sha256"]
        assert "items/protocol.py" in e["source_sha256"]
    assert frozen["file_sha256_of_entries"] == sha256_canon(frozen["entries"])


@pytest.mark.parametrize("field, value", [("direction", "verbatim retention"), ("depth", 3), ("version", 2)])
def test_a_template_change_changes_its_entry(field, value):
    template, cells = g1.TEMPLATES[0], c7.cells(ROOT)
    assert getattr(template, field) != value
    changed = c7.entry(dataclasses.replace(template, **{field: value}), "g1", cells)
    assert changed["entry_sha256"] != c7.entry(template, "g1", cells)["entry_sha256"]


def test_every_inventory_cell_row_parses():
    table = [line for line in (ROOT / "docs/inventory/CELLS-v0.md").read_text(encoding="utf-8").splitlines()
             if c7._CELL_ID.match(line)]
    rows = c7.cells(ROOT)
    assert len(rows) == len(table) and rows["WAKE-SWAP"]["stage"] == "A"


def test_an_unparsed_cell_row_is_refused(tmp_path):
    (tmp_path / "docs/inventory").mkdir(parents=True)
    (tmp_path / "docs/inventory/CELLS-v0.md").write_text("| WAKE-LOOP | Wake | broken |\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unparsed cell row"):
        c7.cells(tmp_path)


def test_source_hash_ignores_crlf(tmp_path):
    lf, crlf = tmp_path / "lf.py", tmp_path / "crlf.py"
    lf.write_bytes(b"x = 1\ny = 2\n")
    crlf.write_bytes(b"x = 1\r\ny = 2\r\n")
    assert c7.source_sha256(lf) == c7.source_sha256(crlf)


def test_same_bytes_under_any_hash_seed():
    outs = {subprocess.run([sys.executable, "-m", "bicentennial.items.c7", str(ROOT)], cwd=ROOT, check=True,
                           capture_output=True, text=True, env={**os.environ, "PYTHONHASHSEED": seed}).stdout
            for seed in ("0", "1", "random")}
    assert outs == {committed()}
