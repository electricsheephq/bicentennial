"""Generic context-engine acceptance; the only engine here is an offline fixture."""

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from bicentennial.canon import sha256_canon
from bicentennial.director.routes import RouteTable
from bicentennial.director.scripted import WRITE_ARGS, ScriptedResponder
from bicentennial.harness.hermes import adapter
from bicentennial.harness.hermes.adapter import HarnessFailed, HermesAdapter
from bicentennial.harness.hermes.config import HERMES_TOOLSETS, hermes_config, layout, worker_env
from bicentennial.items.protocol import CANARY
from bicentennial.ledger import BlobStore, Guard
from bicentennial.runner import compare, t0, t1
from bicentennial.runtime.clock import SimClock
from bicentennial.runtime.faultlite import FaultLite
from bicentennial.systems import hermes_plugin as hp
from bicentennial.systems.registry import REGISTRY, load

ROOT = Path(__file__).resolve().parents[2]
ENGINE = "bicentennial_fixture_engine"
NAME = "fixture-engine"


@pytest.fixture
def mapped(monkeypatch):
    monkeypatch.setitem(hp.ENGINES, NAME, ENGINE)
    monkeypatch.setitem(hp.TREES, NAME, ("HEAD",))
    monkeypatch.setitem(WRITE_ARGS, NAME, WRITE_ARGS["hermes-native"])
    entry = load(REGISTRY / "hermes-native.toml")
    entry["name"] = NAME
    return entry


@pytest.fixture
def archive(monkeypatch, tmp_path):
    """A deterministic pinned archive, substituting only the source Git transport."""
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode="w") as tar:
        source = ROOT / "tests/fixtures/context_engine" / ENGINE / "__init__.py"
        payload = source.read_bytes()
        info = tarfile.TarInfo("__init__.py")
        info.size, info.mode = len(payload), 0o644
        tar.addfile(info, io.BytesIO(payload))
    source = tmp_path / "fixture-source"
    real_popen, real_run = subprocess.Popen, subprocess.run

    class Archive:
        returncode = 0

        def __enter__(self):
            self.stdout = io.BytesIO(data.getvalue())
            return self

        def __exit__(self, *args):
            self.stdout.close()

    def popen(cmd, **kw):
        return Archive() if cmd[:3] == ["git", "-C", str(source)] else real_popen(cmd, **kw)

    def run(cmd, **kw):
        if cmd[:3] == ["git", "-C", str(source)]:
            return SimpleNamespace(returncode=0, stdout=b"")
        return real_run(cmd, **kw)

    monkeypatch.setattr(subprocess, "Popen", popen)
    monkeypatch.setattr(subprocess, "run", run)
    return source, sha256(data.getvalue()).hexdigest()


def make(tmp_path, entry, *, checkout=None, **kw):
    script = dict(canary=CANARY, life_id="fixture", genre="t0", harness="hermes", sessions=[
        dict(index=1, kind="replay", turns=[dict(n=1, kind="replay", user="hello", assistant="hello", tool_calls=[])])])
    table = t1._routes(entry["name"])
    root = tmp_path / "run"
    root.mkdir()
    if checkout is None:
        kw.setdefault("worker_argv", [sys.executable, str(ROOT / "tests/harness/fake_worker.py")])
    return HermesAdapter(entry, script=script, route_table=RouteTable.load(table),
        schedule=FaultLite.load([], script), responder=ScriptedResponder(entry),
        clock=SimClock(root / "clock.json", 1_600_000_000, 60), root=root, scratch=tmp_path,
        life="fixture", branch="B0", run="fixture", checkout=checkout,
        harness_pin=load(REGISTRY / "hermes-native.toml")["artifact"], **kw)


def test_config_engine_and_owned_keys():
    cfg = hermes_config(4321, "main", context_engine="e", plugins_enabled=("d",))
    assert cfg["context"] == {"engine": "e"} and cfg["plugins"] == {"enabled": ["d"]}
    # Canonical bytes measured from 1dc7e4a for the existing argument combinations.
    goldens = [({}, "07c67908f77ab8ba698125be5a2b344d52b0d909d9419adfb8a9c2303da79e6a"),
        ({"plugin": "holographic"}, "6ad0309e7ec1495bfd850a4402248930d70eecd36d16ef34a6c1f5e2f5e20389"),
        ({"plugin": "mem0"}, "6f5ba59657108040e58a31bbdd318973fb3f8e677d6ccbbfc27c398195e07250"),
        ({"memory": False}, "e494b980cd94a27d71cf2b5b4f1867bddd8544fab26c6540844b7450075a49d0"),
        ({"window": 131072}, "9db70944fa384b3f3be3105b1318300285113a2ec9bfc011663b40deb8e39e34"),
        ({"toolsets": HERMES_TOOLSETS + ("envserver",), "memory": False,
          "mcp_servers": {"envserver": {"command": "python"}}},
         "a548e66ae82c3a9251befab4d467dbb9925d90f02f48776921765cddafb23c00"),
        ({"plugin_config": {"custom": {"offline": True}}},
         "09c0b12fde0c2fbd39cd068d30edbe75e4b936d0d55f05c3f9902ac723b0275b")]
    for kw, digest in goldens:
        assert sha256_canon(hermes_config(4321, "bicentennial-main", **kw)) == digest
    for kw in (dict(context_engine="compressor"), dict(context_engine="bad/name"),
               dict(context_engine="e", memory=False), dict(plugins_enabled=("d",), memory=False),
               dict(plugins_enabled=("bad/name",)), dict(plugin_config={"context": {}}),
               dict(plugin_config={"plugins": {}})):
        with pytest.raises(ValueError):
            hermes_config(4321, "main", **kw)


@pytest.mark.parametrize("provider,directory,enabled", [(None, ENGINE, False), (None, "other-dir", True),
                                                       ("fixture-provider", "fixture-provider", False)])
def test_install_slots(tmp_path, monkeypatch, mapped, archive, provider, directory, enabled):
    if provider:
        monkeypatch.setitem(hp.PROVIDERS, NAME, provider)
    if directory != (provider or ENGINE):
        monkeypatch.setitem(hp.PLUGIN_DIRS, NAME, directory)
    if enabled:
        monkeypatch.setattr(hp, "ENABLED", frozenset((NAME,)))
    mapped["artifact"]["sha256"] = archive[1]
    a = make(tmp_path, mapped)
    try:
        hp.PluginCell(mapped, a).install(archive[0], alias="main")
        cfg = json.loads((a.paths["hermes_home"] / "config.yaml").read_bytes())
        assert (a.paths["hermes_home"] / "plugins" / directory / "__init__.py").exists()
        assert cfg["memory"]["provider"] == (provider or "") and cfg["context"]["engine"] == ENGINE
        assert cfg.get("plugins") == ({"enabled": [directory]} if enabled else None)
    finally:
        a.close()


@pytest.mark.parametrize("active,configured", [(None, ENGINE), ("other", ENGINE), (ENGINE, ENGINE), (None, None)])
def test_active_guard(tmp_path, monkeypatch, mapped, active, configured):
    a = make(tmp_path, mapped, context_engine=configured)
    class Worker:
        proc = SimpleNamespace(pid=1)

        def __init__(self, *args):
            pass

        def call(self, **kw):
            return dict(ok=True, session_id="s", history=0, active_context_engine=active)
    monkeypatch.setattr(adapter, "_Worker", Worker)
    monkeypatch.setattr(adapter, "assert_niced", lambda pid: None)
    a._alias, a._session_index, a._wiped = "main", 1, False
    try:
        timings = dict(spawn=[], open=[])
        if configured and active != configured:
            with pytest.raises(HarnessFailed, match="^engine_inactive$"):
                a._spawn_open("start", None, timings)
        else:
            a._spawn_open("start", None, timings)
            assert a.harness_record().get("active_context_engine") == active
    finally:
        a._worker = None
        a.close()


@pytest.mark.parametrize("key,value", [("HOME", "x"), ("HERMES_X", "x"), ("PYTHONPATH", "x"),
    ("HTTP_PROXY", "x"), ("PATH", "x"), ("BAD", "{model_cache}/../escape"),
    ("BAD", "/absolute"), ("BAD", "{model_cache}//absolute"), ("BAD", "a\\b")])
def test_env_recipe_refusals(monkeypatch, key, value):
    monkeypatch.setitem(hp.WORKER_ENV, NAME, {key: value})
    with pytest.raises(ValueError):
        hp.resolve_worker_env(NAME)


def test_cache_digest_and_env(tmp_path, monkeypatch, mapped):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "model").write_bytes(b"weights")
    monkeypatch.setitem(hp.WORKER_ENV, NAME, {"MODEL_HOME": "{model_cache}/models", "OFFLINE": "1"})
    with pytest.raises(t1.T1Refused, match="missing_input"):
        hp.prepare_cache(NAME, None, t1.T1Refused)
    directory, digest = hp.prepare_cache(NAME, cache, t1.T1Refused)
    expected = sha256(f"model\0{7}\0{sha256(b'weights').hexdigest()}\n".encode()).hexdigest()
    assert digest == expected
    extra = hp.resolve_worker_env(NAME, directory)
    paths = layout(tmp_path / "env", tmp_path)
    assert worker_env(paths, 1, tmp_path / "clock", None, extra)["MODEL_HOME"] == str(cache / "models")
    assert "MODEL_HOME" not in worker_env(paths, 1, tmp_path / "clock", None)
    (cache / "model").write_bytes(b"changed")
    assert hp.cache_digest(cache, t1.T1Refused) != digest
    (cache / "link").symlink_to("model")
    with pytest.raises(t1.T1Refused, match="model_cache_invalid"):
        hp.cache_digest(cache, t1.T1Refused)
    with pytest.raises(t1.T1Refused, match="missing_input"):
        hp.prepare_cache("hermes-native", cache, t1.T1Refused)


def test_prepare_engine_missing_source(mapped):
    with pytest.raises(t1.T1Refused, match="^missing_input$"):
        t1.prepare(system=NAME, packs="unused", pack_hash="unused", entry=mapped, worker_argv=["fake"])


def test_t0_engine_refused(monkeypatch, mapped):
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    with pytest.raises(t0.T0Refused, match="^no_t0_surface:context_engine$"):
        t0._preflight(system=NAME, packs="unused", selected=["all"], pack_hash="unused", entry=mapped)


def test_corpus_native_mapping(tmp_path, monkeypatch, mapped):
    seen = []
    def host(entry, **kw):
        seen.append((entry, kw))
        return SimpleNamespace()
    monkeypatch.setattr(compare, "HermesMemoryHost", host)
    ctx = SimpleNamespace(entry=mapped, table=t1._routes(NAME), run_id="run", lock={}, hermes=None,
                          harness_pin={}, plugin_source="unused", model_cache=tmp_path / "cache")
    monkeypatch.setitem(hp.WORKER_ENV, NAME, {"MODEL_HOME": "{model_cache}"})
    factory = compare.CorpusFactory(ctx, "system", SimpleNamespace(case_id="case"), tmp_path,
                                    [], [], None)
    factory()
    entry, kw = seen[0]
    assert entry == load(REGISTRY / "hermes-native.toml")
    assert kw["plugin_source"] is None and kw["extra_env"]["MODEL_HOME"] == str(ctx.model_cache)
    assert ctx.entry["name"] == NAME


def test_live_fixture_engine(tmp_path, monkeypatch, mapped, archive):
    given = os.environ.get("BICENTENNIAL_HERMES")
    if not given or not (Path(given) / ".venv/bin/python").exists():
        pytest.skip("BICENTENNIAL_HERMES is unset or has no .venv/bin/python")
    from bicentennial.runner.guard import admit, read_marker
    if not admit(read_marker(), heavy=False, roots=1).admitted:
        pytest.skip("busy marker")
    monkeypatch.setattr(adapter, "DRAIN_QUIET_S", 0.01)
    mapped["artifact"]["sha256"] = archive[1]
    a = make(tmp_path, mapped, checkout=given, context_engine=ENGINE)
    try:
        hp.PluginCell(mapped, a).install(archive[0], alias="bicentennial-main")
        result = a.run_session(1, sim_t_s=1_600_000_000, lock_hash="ab" * 32, attempt_id="fixture")
        assert result.turns_ok == 1 and a.active_context_engine == ENGINE
        store = BlobStore(a.paths["root"] / "ledger/blobs", Guard([]))
        row = next(r for r in a.records() if r.get("role") == "main" and r.get("type") == "request")
        body = json.loads(store.get(row["req"]))
        assert "fixture_engine_probe" in [t["function"]["name"] for t in body["tools"]]
        cfg = json.loads((a.paths["hermes_home"] / "config.yaml").read_bytes())
        assert cfg["platform_toolsets"]["acp"] == ["memory", "session_search", "todo"]
        shutil.rmtree(a.paths["hermes_home"] / "plugins" / ENGINE)
        with pytest.raises(HarnessFailed, match="^engine_inactive$"):
            a.run_session(1, sim_t_s=1_600_000_060, lock_hash="ab" * 32, attempt_id="missing")
        assert a.egress.summary()["non_loopback"] == []
    finally:
        a.close()


@pytest.mark.parametrize("bad", ["compressor", "bad/name", "Bad", ""])
def test_map_validation(mapped, monkeypatch, bad):
    monkeypatch.setitem(hp.ENGINES, NAME, bad)
    with pytest.raises(ValueError):
        hp.validate_maps()


def test_missing_tree_and_settle_mapping(mapped, monkeypatch):
    monkeypatch.delitem(hp.TREES, NAME)
    with pytest.raises(ValueError, match="missing tree"):
        hp.validate_maps()
    monkeypatch.setitem(hp.TREES, NAME, ("HEAD",))
    mapped["settle"] = dict(kind="hook", bound_s=5)
    with pytest.raises(t1.T1Refused, match="^settle_unmapped$"):
        t1.prepare(system=NAME, entry=mapped, packs="unused", pack_hash="unused",
                   plugin_source="unused", worker_argv=["fake"])


def test_t0_both_slots_installs_without_engine_and_passes_env(tmp_path, monkeypatch, archive):
    from bicentennial.harness.hermes import plugin_host

    entry = load(REGISTRY / "hermes-native.toml")
    name = entry["name"]
    entry["artifact"]["sha256"] = archive[1]
    monkeypatch.setitem(hp.PROVIDERS, name, "fixture-provider")
    monkeypatch.setitem(hp.ENGINES, name, ENGINE)
    monkeypatch.setitem(hp.TREES, name, ("HEAD",))
    captured = []

    class Worker:
        proc = SimpleNamespace(pid=1)

        def __init__(self, argv, env, *args):
            captured.append(env)

        def call(self, **kw):
            return dict(ok=True, active_memory_providers=["fixture-provider"], schemas=[])

    monkeypatch.setattr(plugin_host, "_Worker", Worker)
    monkeypatch.setattr(plugin_host, "assert_niced", lambda pid: None)
    root = tmp_path / "host"
    root.mkdir()
    host = plugin_host.HermesMemoryHost(entry, route_table=RouteTable.load(t1._routes(name)),
        responder=ScriptedResponder(entry), clock=SimClock(root / "clock.json", 1_600_000_000, 60),
        root=root, scratch=tmp_path, life="fixture", branch="B0", run="fixture", lock_hash="ab" * 32,
        worker_argv=["fake"], plugin_source=archive[0], extra_env={"MODEL_HOME": str(tmp_path / "models")})
    try:
        host._start()
        cfg = json.loads((host.paths["hermes_home"] / "config.yaml").read_bytes())
        assert cfg["memory"]["provider"] == "fixture-provider" and "context" not in cfg
        assert (host.paths["hermes_home"] / "plugins/fixture-provider/__init__.py").exists()
        assert captured[0]["MODEL_HOME"] == str(tmp_path / "models")
    finally:
        host._worker = None
        host.close()
