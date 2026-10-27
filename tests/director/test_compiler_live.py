"""Pinned Hermes check-compile, gated by its checkout, R15 and the optional MCP SDK."""

import json
import os
import runpy
import subprocess
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.director.compiler.check import check_compile
from bicentennial.harness.hermes import adapter
from bicentennial.ledger import BlobStore, Guard
from bicentennial.runner.guard import admit, read_marker
from bicentennial.systems.registry import REGISTRY, load

ROOT = Path(__file__).resolve().parents[2]
HELPERS = runpy.run_path(str(ROOT / "tests/director/test_compiler.py"))


@pytest.mark.parametrize("genre", ["G1", "G2"])
def test_live_check_compile(tmp_path, monkeypatch, genre):
    given = os.environ.get("BICENTENNIAL_HERMES")
    if not given or not (Path(given) / ".venv/bin/python").exists():
        pytest.skip("BICENTENNIAL_HERMES is unset or has no .venv/bin/python")
    checkout = Path(given)
    admission = admit(read_marker(), heavy=False, roots=1)
    if not admission.admitted:
        pytest.skip(f"busy marker: {admission.reason}")
    entry = load(REGISTRY / "hermes-native.toml")
    adapter.verify_pin(checkout, entry["artifact"])
    if genre == "G2":
        sdk = subprocess.run([str(checkout / ".venv/bin/python"), "-c",
                              "import importlib.util; raise SystemExit(importlib.util.find_spec('mcp') is None)"],
                             check=False, capture_output=True)
        if sdk.returncode == 1:
            pytest.skip("mcp SDK not in the pinned install (spec-inputs l.14)")
        assert sdk.returncode == 0
    world = HELPERS["fixture"](tmp_path / "world", genre)
    try:
        life = HELPERS["life_directory"](world, tmp_path / "life")
    finally:
        world[1].close()
    seen, summaries = [], []
    real = adapter.HermesAdapter

    class Capture(real):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            seen.append(self)

        def close(self):
            summary = super().close()
            summaries.append(summary)
            return summary

    monkeypatch.setattr(adapter, "HermesAdapter", Capture)
    helper = runpy.run_path(str(ROOT / "tests/harness/test_hermes_adapter.py"))
    report = check_compile(life, entry=entry, route_table=helper["ROUTES"], harness_pin=entry["artifact"],
                           checkout=checkout, scratch=tmp_path / "runs")
    assert report["ok"], report
    assert all(b["calls"] == (15 if genre == "G1" else 2) for b in report["branches"].values())
    overhead = []
    for a in seen:
        assert not [r for r in a.records() if r.get("role") == "unknown"]
        row = next(r for r in a.records() if r.get("path", "").startswith("/main/"))
        store = BlobStore(a.paths["root"] / "ledger/blobs", Guard([]))
        req = json.loads(store.get(row["req"]))
        offered = {t["function"]["name"] for t in req["tools"]}
        assert "terminal" in offered
        if genre == "G2":
            assert "tool_call" in offered
        overhead.append(dict(system_prompt_chars=sum(len(m["content"]) for m in req["messages"]
                                                     if m.get("role") == "system"),
                             tool_schema_chars=len(canon(req["tools"]).decode())))
    assert all(s["non_loopback"] == [] for s in summaries)
    (tmp_path / "live-report.json").write_bytes(canon(dict(report=report, overhead=overhead, egress=summaries)))
    print(json.dumps(dict(genre=genre, first_main=overhead[0])))
