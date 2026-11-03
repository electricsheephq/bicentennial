"""The public compile check accepts and executes item-specific probe compilation."""

import runpy
from pathlib import Path

import pytest

from bicentennial.director.compiler import hermes as compiler
from bicentennial.harness.hermes import adapter

HELPERS = runpy.run_path(str(Path(__file__).with_name("test_compiler.py")))
worlds = HELPERS["worlds"]


@pytest.mark.parametrize("genre", ["G1", "G2"])
def test_check_compile_per_item(worlds, tmp_path, monkeypatch, genre):
    from types import SimpleNamespace

    monkeypatch.setattr(adapter, "serve", lambda d, p: (d.bind_port(1234) or SimpleNamespace(port=1234)))
    monkeypatch.setattr(adapter, "shutdown", lambda server: None)
    monkeypatch.setattr(adapter, "Egress", lambda: SimpleNamespace(
        start=lambda: None, stop=lambda: None, summary=lambda: {}))
    seen = []
    compile_script = compiler.compile_script

    def compile_items(*args, **kwargs):
        compiled = compile_script(*args, **kwargs)
        assert kwargs["probe_mode"] == "per_item"
        assert all(len(p.item_ids) == 1 for p in compiled.probes)
        seen.append(compiled)
        return compiled

    def session(self, index, **kwargs):
        # The check's result comparison is covered separately; this test reaches both branch compilers offline.
        raise adapter.HarnessFailed("turn_failed")

    monkeypatch.setattr(compiler, "compile_script", compile_items)
    monkeypatch.setattr(adapter.HermesAdapter, "run_session", session)
    life = HELPERS["life_directory"](worlds[genre], tmp_path / "life")
    report = HELPERS["check_life"](life, tmp_path / "runs", probe_mode="per_item")
    assert len(seen) == 2
    assert not report["ok"]
    assert all(b["sessions"] > 0 for b in report["branches"].values())
