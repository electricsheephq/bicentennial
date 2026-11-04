"""Outside declarations, offline installers and runner preflight boundaries."""

import json
import re
import subprocess
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
import test_t0 as zero
import test_t1 as one

from bicentennial import cli
from bicentennial.canon import sha256_canon
from bicentennial.director.routes import RouteTable, route_table_hash
from bicentennial.harness.hermes import plugin_host
from bicentennial.runner import compare, t0, t1, t2, t2lite, units
from bicentennial.sandbox import fixedroot
from bicentennial.systems import hermes_plugin as hp
from bicentennial.systems import mapping, pins, registry
from bicentennial.systems.recipe import recipe, system_artifacts

installed = zero.installed
extra_rows = zero.extra_rows
fake_hosts = zero.fake_hosts


@pytest.fixture
def outside():
    return dict(name="outside-memory", licence="MIT", harness="hermes",
        artifact=dict(name="outside-provider", version="1.0.0", sha256="1" * 64),
        fresh_install_hash="2" * 64, write_tools=[], read_tools=["search"], recall=None,
        surfaces=[dict(root="HERMES_HOME", relative=".", volatile_paths=[])],
        own_model_routes=[], structured_formats={}, embedding_dim=None,
        settle=dict(kind="none", bound_s=0), machine_class="light", benchmark_operator_runs=True,
        recipe=dict(provider="outside-provider", archive_tree=dict(ref="HEAD"), enabled=True,
            worker_environment={"OFFLINE_MODE": "1"}, file_time_sites=["provider.py:now"],
            write=dict(tool="store", fixed={"action": "add"}, content_key="text"),
            forget=dict(search_tool="search", search_fixed={}, query_key="query", listing_key="rows",
                text_key="text", id_key="id", delete_tool="remove", delete_fixed={}, delete_key="id"),
            unscripted=[]))


def toml(value):
    if isinstance(value, dict):
        return "{" + ", ".join(json.dumps(k) + " = " + toml(v) for k, v in value.items() if v is not None) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(map(toml, value)) + "]"
    return json.dumps(value, ensure_ascii=False)


def write_entry(path, entry):
    path.write_text("\n".join(json.dumps(k) + " = " + toml(v) for k, v in entry.items() if v is not None))
    return path


@pytest.fixture(autouse=True)
def deterministic(monkeypatch):
    monkeypatch.setenv("PYTHONHASHSEED", "0")
    monkeypatch.delenv("BICENTENNIAL_OPERATOR", raising=False)
    monkeypatch.setattr(cli, "reexec_niced", lambda argv: None)
    monkeypatch.setattr(cli, "_source_checkout", lambda root: True)
    for module in (t0, t1):
        monkeypatch.setattr(module, "_commit", lambda: "f" * 40)
        monkeypatch.setattr(module, "read_marker", lambda: NS(exit=0))
        monkeypatch.setattr(module, "admit", lambda *a, **kw: NS(admitted=True, max_roots=4))


def arguments(command, tmp_path):
    if command == "pins":
        return [command]
    args = [command, "--packs", str(tmp_path / "packs"), "--pack-hash", "1" * 64,
            "--out", str(tmp_path / "out")]
    if command == "t0":
        args += ["--pack", "all"]
    if command in ("t2lite", "t2"):
        args += ["--login-home", str(tmp_path / "login"), "--max-sends", "0"]
    return args


@pytest.mark.parametrize("command", ["t0", "t1", "t2lite", "t2", "pins"])
def test_cli_selection(command, outside, tmp_path, monkeypatch):
    seen = []
    target = pins if command == "pins" else cli
    monkeypatch.setattr(target, "run_" + command, lambda **kw: seen.append(kw) or 0)
    args = arguments(command, tmp_path)
    for selection in ([], ["--system", "outside-memory", "--entry", "unused"]):
        with pytest.raises(SystemExit) as caught:
            cli.main(args + selection)
        assert caught.value.code == 3
    assert not seen
    path = write_entry(tmp_path / "entry.toml", outside)
    assert cli.main(args + ["--entry", str(path)]) == 0
    assert seen[-1]["system"] == outside["name"] and seen[-1]["entry"] == registry.load(path)
    assert cli.main(args + ["--system", "hermes-native"]) == 0
    assert seen[-1]["system"] == "hermes-native" and "entry" not in seen[-1]


@pytest.mark.parametrize("command", ["t0", "t1", "t2lite", "t2", "pins"])
@pytest.mark.parametrize("fault,code", [("missing", "entry_unreadable"), ("toml", "entry_unreadable"),
    ("schema", "entry_invalid"), ("contract", "entry_invalid"), ("recipe", "entry_recipe_missing")])
def test_cli_loader_refuses_before_runner(command, fault, code, outside, tmp_path, monkeypatch, capsys):
    target = pins if command == "pins" else cli
    monkeypatch.setattr(target, "run_" + command, lambda **kw: pytest.fail("runner started"))
    path = tmp_path / "entry.toml"
    if fault == "toml":
        path.write_text("[")
    elif fault != "missing":
        if fault == "schema":
            del outside["licence"]
        elif fault == "contract":
            outside["recall"] = dict(tool="undeclared", argument_template={})
        else:
            del outside["recipe"]
        write_entry(path, outside)
    assert cli.main(arguments(command, tmp_path) + ["--entry", str(path)]) == 3
    assert capsys.readouterr().err.strip() == code
    assert not (tmp_path / "out").exists()


def prepare(entry, tmp_path):
    return t1.prepare(system=entry["name"], entry=entry, packs=tmp_path, pack_hash="1" * 64,
                      hermes=tmp_path, plugin_source=tmp_path, worker_argv=[])


def change(entry, path, value):
    target = entry
    parts = path.split("/")
    for part in parts[:-1]:
        target = target[part]
    if value is None:
        target.pop(parts[-1])
    else:
        target[parts[-1]] = value


@pytest.mark.parametrize("path,value,code", [
    ("name", "HERMES_NATIVE", "entry_shadows_builtin"),
    ("name", "ｈｅｒｍｅｓ-native", ("entry_name_invalid", "entry_shadows_builtin")),
    ("name", "reference_store", "entry_shadows_builtin"),
    ("name", "outside memory", "entry_name_invalid"),
    ("name", "-outside", "entry_name_invalid"),
    ("name", ".", "entry_name_invalid"),
    ("name", "..", "entry_name_invalid"),
    ("recipe/provider", None, "entry_recipe_invalid:provider"),
    ("recipe/engine", "other", "entry_recipe_invalid:provider"),
    ("recipe/provider", "../provider", "entry_recipe_invalid:provider"),
    ("recipe/plugin_directory", "../x", "entry_recipe_invalid:plugin_directory"),
    ("recipe/archive_tree/ref", "--output=x", "entry_recipe_invalid:archive_tree.ref"),
    ("recipe/archive_tree/ref", "A" * 40, "entry_recipe_invalid:archive_tree.ref"),
    ("recipe/archive_tree/subdirectory", "../x", "entry_recipe_invalid:archive_tree.subdirectory"),
    ("recipe/archive_tree/subdirectory", "x/../y", "entry_recipe_invalid:archive_tree.subdirectory"),
    ("recipe/archive_tree/subdirectory", "/x", "entry_recipe_invalid:archive_tree.subdirectory"),
    ("recipe/archive_tree/subdirectory", "x\\y", "entry_recipe_invalid:archive_tree.subdirectory"),
    ("recipe/archive_tree/subdirectory", "-x", "entry_recipe_invalid:archive_tree.subdirectory"),
    ("recipe/worker_environment", {"PYTHONPATH": "x"}, "entry_recipe_invalid:worker_environment"),
    ("recipe/worker_environment", {"OFFLINE_MODE": "/x"}, "entry_recipe_invalid:worker_environment"),
    ("recipe/forget/delete_key", None, "entry_recipe_invalid:forget"),
    ("recipe/archive_tree", [], "entry_recipe_invalid:archive_tree"),
    ("recipe/enabled", None, "entry_recipe_invalid:enabled"),
    ("recipe/enabled", "yes", "entry_recipe_invalid:enabled"),
    ("recipe/extra", True, "entry_recipe_invalid:extra"),
    ("structured_formats", {"extraction": {"kind": "text", "schema": None}},
        "entry_recipe_unsupported:structured_formats"),
    ("write_tools", [dict(tool="store", actions=[])], "entry_scripted_writes_unsupported"),
    ("recipe/write", None, "t0_mapping_missing"),
    ("recipe/forget", None, "t0_mapping_missing"),
])
def test_runner_outside_refusals(outside, tmp_path, path, value, code):
    change(outside, path, value)
    with pytest.raises(registry.SystemRefused) as caught:
        prepare(outside, tmp_path)
    assert caught.value.reasons == (code if isinstance(code, tuple) else (code,))


HOME = dict(root="HERMES_HOME", relative=".", volatile_paths=[])


@pytest.mark.parametrize("surfaces", [
    [dict(root="SANDBOX_HOME", relative=".outside", volatile_paths=[])],
    [],
    [dict(HOME, relative="store")],
    [HOME, dict(HOME, relative="plugins/outside-provider/state")],
    [HOME, dict(root="SERVER_DATA", relative="db", volatile_paths=[])],
], ids=["sandbox-only", "none", "narrower", "in-plugin-directory", "server-data"])
def test_outside_surfaces_cover_the_whole_hermes_home(outside, tmp_path, surfaces):
    # The life runners hash, clone and wipe the whole home and run only these two roots, as every built-in declares.
    outside["surfaces"] = surfaces
    with pytest.raises(registry.SystemRefused) as caught:
        prepare(outside, tmp_path)
    assert caught.value.reasons == ("entry_surfaces_unsupported",)
    with pytest.raises(registry.SystemRefused) as caught:
        pins._validate(outside, tmp_path, tmp_path, None)
    assert caught.value.reasons == ("entry_surfaces_unsupported",)


def test_outside_sandbox_surfaces_beside_the_home(outside):
    outside["surfaces"].append(dict(root="SANDBOX_HOME", relative=".outside", volatile_paths=[]))
    assert registry.outside_reasons(outside, None) == []
    del outside["surfaces"]
    assert registry.outside_reasons(outside, None) == ["entry_surfaces_unsupported"]


@pytest.mark.parametrize("field,path,shadowed", [
    ("provider", "memory/outside-provider/__init__.py", True),
    ("provider", "memory/outside-provider/notes.txt", False),
    ("provider", "context_engine/outside-provider/engine.py", False),
    ("engine", "context_engine/outside-engine/engine.py", True),
    ("engine", "memory/outside-engine/__init__.py", False),
])
def test_hermes_bundled_names(outside, tmp_path, field, path, shadowed):
    # Hermes looks in its own plugins first: a provider directory with __init__.py, or any engine directory.
    (tmp_path / "plugins" / path).parent.mkdir(parents=True)
    (tmp_path / "plugins" / path).write_text("")
    if field == "engine":
        outside["recipe"]["engine"] = outside["recipe"].pop("provider").replace("provider", "engine")
    assert registry.hermes_shadow_reasons(outside, tmp_path) == (["entry_shadows_hermes_plugin"] if shadowed else [])
    assert registry.hermes_shadow_reasons(outside, None) == []
    assert registry.hermes_shadow_reasons(registry.load(registry.REGISTRY / "hermes-native.toml"), tmp_path) == []


def test_hermes_bundled_provider_refused_before_install(outside, tmp_path, monkeypatch):
    (tmp_path / "plugins/memory/outside-provider").mkdir(parents=True)
    (tmp_path / "plugins/memory/outside-provider/__init__.py").write_text("")
    with pytest.raises(registry.SystemRefused) as caught:
        prepare(outside, tmp_path)
    assert caught.value.reasons == ("entry_shadows_hermes_plugin",)
    with pytest.raises(registry.SystemRefused) as caught:
        pins._validate(outside, tmp_path, tmp_path, None)
    assert caught.value.reasons == ("entry_shadows_hermes_plugin",)
    with pytest.raises(registry.SystemRefused) as caught:
        t0._preflight(system=outside["name"], packs=[], selected=[], pack_hash="1" * 64, hermes=tmp_path,
                      plugin_source=tmp_path, entry=outside)
    assert caught.value.reasons == ("entry_shadows_hermes_plugin",)


@pytest.mark.parametrize("command", ["t0", "t1", "t2lite", "t2", "pins"])
def test_cli_entry_in_a_sandbox_slot(command, outside, tmp_path, monkeypatch, capsys):
    # A lease sweeps its slot, so the entry file is refused before it is read, as the runners refuse their inputs.
    target = pins if command == "pins" else cli
    monkeypatch.setattr(target, "run_" + command, lambda **kw: pytest.fail("runner started"))
    path = write_entry(tmp_path / "entry.toml", outside)
    monkeypatch.setattr(fixedroot, "overlaps", lambda p: Path(p) == path)
    monkeypatch.setattr(registry, "load_entry", lambda p: pytest.fail("entry read"))
    assert cli.main(arguments(command, tmp_path) + ["--entry", str(path)]) == 3
    assert capsys.readouterr().err.strip() == "sandbox_overlap"
    assert path.exists() and not (tmp_path / "out").exists()


@pytest.mark.parametrize("field", ["provider", "engine", "plugin_directory"])
def test_engine_and_directory_rules(outside, tmp_path, field):
    if field == "engine":
        outside["recipe"].pop("provider")
    outside["recipe"][field] = "compressor" if field == "engine" else "bad/id"
    with pytest.raises(registry.SystemRefused, match="entry_recipe_invalid:" + field):
        prepare(outside, tmp_path)


@pytest.mark.parametrize("table", ["PROVIDERS", "TREES", "ENGINES", "PLUGIN_DIRS", "ENABLED",
    "WORKER_ENV", "DEPENDENCIES", "FILE_TIME_SITES", "SETTLE_THREADS", "FORGET", "WRITE_ARGS",
    "UNSCRIPTED", "REFERENCE_SYSTEMS", "FORMATS"])
def test_shadowing_covers_every_table(outside, tmp_path, monkeypatch, table):
    from bicentennial.director import scripted

    module = next(m for m in (hp, plugin_host, scripted, mapping, t0) if hasattr(m, table))
    name = outside["name"]
    if table == "ENABLED":
        monkeypatch.setattr(module, table, frozenset((*getattr(module, table), name)))
    else:
        monkeypatch.setitem(getattr(module, table), (name, "extraction") if table == "FORMATS" else name, ())
    with pytest.raises(registry.SystemRefused, match="entry_shadows_builtin"):
        prepare(outside, tmp_path)


@pytest.mark.parametrize("field", ["name", "artifact/name", "recipe/provider", "recipe/engine", "recipe/plugin_directory"])
def test_operator_gate_ignores_own_permission(outside, tmp_path, monkeypatch, field):
    if field == "recipe/engine":
        del outside["recipe"]["provider"]
    change(outside, field, "lcm-copy")
    registry.admit_system(outside, operator="owner")
    monkeypatch.setenv("BICENTENNIAL_OPERATOR", "benchmark")
    with pytest.raises(registry.SystemRefused, match="benchmark_operator_forbidden"):
        prepare(outside, tmp_path)


@pytest.mark.parametrize("name", ["L.C.M", "ＬＣＭ", "l_c_m", "other-lcm-memory"])
def test_operator_normalization(outside, tmp_path, monkeypatch, name):
    outside["name"] = name
    assert registry.operator_forbidden(outside)
    monkeypatch.setenv("BICENTENNIAL_OPERATOR", "benchmark")
    with pytest.raises(registry.SystemRefused, match="benchmark_operator_forbidden"):
        prepare(outside, tmp_path)


@pytest.mark.parametrize("identity", ["name", "artifact", "digest"])
def test_operator_registry_identities(outside, tmp_path, monkeypatch, identity):
    original = registry.load
    forbidden = original(registry.REGISTRY / "lcm-x.toml")
    forbidden.update(name="excluded-memory")
    forbidden["artifact"].update(name="excluded-artifact", sha256="a" * 64)
    monkeypatch.setattr(registry, "load", lambda path: forbidden if path.stem == "lcm-x" else original(path))
    if identity == "digest":
        outside["artifact"]["sha256"] = "a" * 64
    elif identity == "artifact":
        outside["artifact"]["name"] = "EXCLUDED.ARTIFACT"
    else:
        outside["name"] = "EXCLUDED_Memory"
    registry.admit_system(outside, operator="owner")
    monkeypatch.setenv("BICENTENNIAL_OPERATOR", "benchmark")
    with pytest.raises(registry.SystemRefused, match="benchmark_operator_forbidden"):
        prepare(outside, tmp_path)
    forbidden["artifact"]["sha256"] = registry.ZERO_HASH
    outside["artifact"]["sha256"] = registry.ZERO_HASH
    if identity == "digest":
        assert not registry.operator_forbidden(outside)


def test_operator_builtin_results():
    for name in registry._builtin_names():
        assert registry.operator_forbidden({"name": name}) == (name == "lcm-x")


@pytest.mark.parametrize("tier", ["t0", "t1", "pins"])
def test_recipe_in_builtin(outside, tmp_path, monkeypatch, tier, capsys):
    for path in registry.REGISTRY.glob("*.toml"):
        assert "recipe" not in registry.load(path)
    entry = registry.load(registry.REGISTRY / "hermes-native.toml")
    entry["recipe"] = outside["recipe"]
    write_entry(tmp_path / "hermes-native.toml", entry)
    module = {"t0": t0, "t1": t1, "pins": pins}[tier]
    monkeypatch.setattr(module, "REGISTRY", tmp_path)
    if tier == "pins":
        assert pins.run_pins(system=entry["name"]) == 3
        assert capsys.readouterr().err.strip() == "recipe_in_builtin"
    elif tier == "t0":
        with pytest.raises(t0.T0Refused, match="recipe_in_builtin"):
            t0._preflight(system=entry["name"], packs=tmp_path, selected=["all"], pack_hash="1" * 64)
    else:
        with pytest.raises(t1.T1Refused, match="recipe_in_builtin"):
            t1.prepare(system=entry["name"], packs=tmp_path, pack_hash="1" * 64)


def test_recipe_detached_and_read_only(outside):
    outside["recipe"]["write"]["fixed"]["nested"] = {"items": ["original"]}
    outside["recipe"]["forget"]["search_fixed"]["nested"] = {"items": ["original"]}
    resolved = recipe(outside)
    outside["recipe"]["worker_environment"]["OFFLINE_MODE"] = "changed"
    outside["recipe"]["file_time_sites"].append("changed.py:now")
    outside["recipe"]["archive_tree"]["ref"] = "0" * 40
    outside["recipe"]["write"]["fixed"]["nested"]["items"].append("changed")
    outside["recipe"]["forget"]["delete_fixed"]["changed"] = True
    assert resolved.worker_environment == {"OFFLINE_MODE": "1"}
    assert resolved.file_time_sites == ("provider.py:now",) and resolved.archive_tree == ("HEAD",)
    assert resolved.write.fixed["nested"] == {"items": ["original"]}
    assert resolved.forget.delete_fixed == {}
    before = deepcopy(outside)
    for values in (resolved.worker_environment, resolved.write.fixed, resolved.forget.search_fixed,
                   resolved.forget.delete_fixed):
        with pytest.raises(TypeError):
            values["new"] = "value"
    resolved.write.fixed["nested"]["items"].append("detached")
    resolved.forget.search_fixed["nested"]["items"].append("detached")
    assert resolved.write.fixed["nested"] == {"items": ["original"]}
    assert resolved.forget.search_fixed["nested"] == {"items": ["original"]}
    assert outside == before
    with pytest.raises(TypeError):
        resolved.file_time_sites[0] = "changed"


def test_helpers_use_outside_recipe(outside, tmp_path, monkeypatch):
    assert hp.is_plugin(outside)
    assert hp.plugin_dir(outside) == "outside-provider"
    assert hp.resolve_worker_env(outside) == {"OFFLINE_MODE": "1"}
    outside["recipe"]["worker_environment"]["MODEL_FOLDER"] = "{model_cache}"
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "weights").write_text("synthetic")
    assert hp.prepare_cache(outside, cache, t0.T0Refused) == (cache.resolve(), hp.cache_digest(cache, t0.T0Refused))
    monkeypatch.setattr(hp.subprocess, "run", lambda *a, **kw:
        NS(returncode=0, stdout=json.dumps(dict(invalid=False, applicable={}, installed={}, dists=[]))))
    props = dict(hp.worker_properties(outside, tmp_path, tmp_path, "t0", t0.T0Refused))
    assert "provider.py:now" in json.loads(props["t0.file_time_sites"])
    assert mapping.resolve_mapping(outside) == dict(write=dict(tool="store", fixed={"action": "add"}),
        forget=dict(search_tool="search", delete_tool="remove", delete_fixed={}), unscripted=())


def test_recipe_optional_fields_and_no_table_fallback(outside, monkeypatch):
    raw = outside["recipe"]
    del raw["forget"]["search_tool"]
    raw.update(settle_threads=["worker"], unscripted=["feedback"])
    result = recipe(outside)
    assert result.forget.search_tool is None and result.settle_threads == ("worker",)
    assert result.unscripted == ("feedback",) and result.dependency_lock is result.reference_adapter is None
    raw.pop("provider")
    raw.update(engine="outside-engine", plugin_directory="outside-directory")
    assert recipe(outside).plugin_directory == "outside-directory"
    del raw["plugin_directory"]
    assert recipe(outside).plugin_directory == "outside-engine"
    monkeypatch.setitem(hp.DEPENDENCIES, outside["name"], "unreachable")
    monkeypatch.setitem(t0.REFERENCE_SYSTEMS, outside["name"], object)
    assert recipe(outside).dependency_lock is recipe(outside).reference_adapter is None


@pytest.fixture
def offline(monkeypatch):
    observed = []
    def serve(director, port):
        assert port == 0
        port = 19000 + len(observed)
        director.bind_port(port)
        observed.append(director)
        return NS(port=port)
    monkeypatch.setattr(pins, "serve", serve)
    monkeypatch.setattr(pins, "shutdown", lambda server: None)
    monkeypatch.setattr(pins, "verify_pin", lambda *a: "synthetic")
    monkeypatch.setattr(plugin_host, "serve", serve)
    monkeypatch.setattr(plugin_host, "shutdown", lambda server: None)
    monkeypatch.setattr(plugin_host, "verify_pin", lambda *a: "synthetic")
    monkeypatch.setattr(plugin_host, "Egress", lambda: NS(start=lambda: None, stop=lambda: None, summary=dict))
    monkeypatch.setattr(plugin_host.HermesMemoryHost, "_start", lambda self: pytest.fail("worker started"))
    return observed


@pytest.fixture
def source(outside, tmp_path, git_checkouts):
    root = tmp_path / "source"
    root.mkdir()
    (root / "provider.py").write_text("def now():\n    return 0\n")
    for args in (["init", "-q", "--template="], ["add", "."],
                 ["-c", "core.hooksPath=", "commit", "--no-gpg-sign", "-qm", "fixture"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return root


@pytest.fixture
def measured(outside, source, offline, tmp_path):
    result = pins.measure(outside, hermes=tmp_path, plugin_source=source)
    outside["artifact"]["sha256"] = result["artifact.sha256"]
    outside["fresh_install_hash"] = result["fresh_install_hash"]
    return outside


def test_pins_entry_and_t0_complete(measured, source, offline, fake_hosts, installed,
                                   tmp_path, monkeypatch, capsys):
    path = write_entry(tmp_path / "entry.toml", measured)
    assert cli.main(["pins", "--entry", str(path), "--hermes", str(tmp_path),
                     "--plugin-source", str(source)]) == 0
    assert "fresh_install_hash " + measured["fresh_install_hash"] in capsys.readouterr().out
    base, hashes = t0.HermesMemoryHost, []
    class Host(base):
        def __init__(self, entry, **options):
            check = options | {"root": options["root"] / "install"}
            host = plugin_host.HermesMemoryHost(entry, **check)
            hashes.append(host.fresh_install_hash)
            assert options["extra_env"] == {"OFFLINE_MODE": "1"}
            host.close()
            super().__init__(entry, **options)
            self.paths["root"] = options["root"]
            self.gate, self.pids, self.growth = [], [], 0
            self.server, self.director = host.server, host.director
    monkeypatch.setattr(t0, "HermesMemoryHost", Host)
    out = tmp_path / "out"
    assert zero.run(installed, out, system=measured["name"], entry=registry.load(path),
                    hermes=tmp_path, plugin_source=source, host_overrides={"worker_argv": []}) == 0
    assert hashes and set(hashes) == {measured["fresh_install_hash"]}
    cards = list(out.rglob("card.json"))
    assert cards
    for path in cards:
        card = json.loads(path.read_bytes())
        assert measured["name"] in path.read_text()
        assert card["pins"]["route_table_hash"] == route_table_hash(RouteTable.load(pins._routes(measured["name"])))


@pytest.fixture(scope="module")
def t1_installed(tmp_path_factory):
    yield from one.installed.__wrapped__(tmp_path_factory)


def test_t1_prepare_install_and_artifact_sites(measured, source, offline, installed, t1_installed, tmp_path):
    pack = t1_installed
    ctx = t1.prepare(system=measured["name"], entry=measured, packs=pack.root,
        pack_hash=pack.digest, hermes=tmp_path, plugin_source=source, worker_argv=[])
    with fixedroot.lease(0, t1.T1Refused) as scratch:
        t1.check_install(ctx, scratch)
    expected = [measured["artifact"], dict(name=measured["name"], version="entry", sha256=sha256_canon(measured))]
    assert ctx.lock["system_artifacts"] == expected == system_artifacts(measured)
    first = zero.packs(installed)[0]
    assert t0._lock(installed[1], first, measured, installed[2], True)["system_artifacts"] == expected
    arm = object.__new__(units._ArmContext)
    arm.entry = measured
    assert arm._entry_lock(ctx.lock)["system_artifacts"] == expected
    other = deepcopy(measured)
    other["recipe"]["enabled"] = False
    assert sha256_canon(system_artifacts(other)) != ctx.pins["system_hash"]
    assert ctx.pins["system_hash"] == sha256_canon(expected)
    builtin = registry.load(registry.REGISTRY / "hermes-native.toml")
    assert system_artifacts(builtin) == [builtin["artifact"]]


def test_compare_passes_entry(outside, tmp_path, monkeypatch):
    seen = []
    def prepared(**kwargs):
        seen.append(kwargs["entry"])
        raise registry.SystemRefused(["synthetic_stop"])
    monkeypatch.setattr(t1, "prepare", prepared)
    assert compare.run_t1(system=outside["name"], entry=outside, packs_dir=tmp_path / "packs",
                          pack_hash="1" * 64, out=tmp_path / "out") == 3
    assert seen == [outside]
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("module", [t2lite, t2], ids=["t2lite", "t2"])
def test_live_preflight_reaches_shared_install(module, measured, source, offline, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "auth.json").write_text("{}")
    monkeypatch.setattr(module, "LIVE_ENV", ())
    seen = []
    def shared(**kw):
        registry.admit_system(kw["entry"])
        with fixedroot.lease(0, t1.T1Refused) as scratch:
            pins.measure_once(kw["entry"], scratch, hermes=tmp_path, plugin_source=source, worker_argv=[])
        seen.append(kw["entry"])
        raise t1.T1Refused("synthetic_stop")
    monkeypatch.setattr(t1, "prepare", shared)
    out = tmp_path / "out"
    run = module.run_t2lite if module is t2lite else module.run_t2
    assert run(system=measured["name"], entry=measured, packs_dir=tmp_path / "packs", pack_hash="1" * 64,
               out=out, login_home=home, max_sends=0) == 3
    assert seen == [measured]
    assert json.loads((out / "refusal.json").read_bytes())["code"] == "synthetic_stop"


@pytest.mark.parametrize("module", [t2lite, t2], ids=["t2lite", "t2"])
def test_renamed_artifact_operator_identity(module, outside, tmp_path, monkeypatch):
    outside.update(name="my-memory")
    outside["artifact"]["name"] = "lcm-x"
    home = tmp_path / "home"
    home.mkdir()
    (home / "auth.json").write_text("{}")
    (home / ".bicentennial-operator").touch()
    monkeypatch.setattr(module, "LIVE_ENV", ())
    monkeypatch.setattr(t1, "prepare", lambda **kw: pytest.fail("prepared forbidden identity"))
    out = tmp_path / "out"
    run = module.run_t2lite if module is t2lite else module.run_t2
    assert run(system=outside["name"], entry=outside, packs_dir=tmp_path / "packs", pack_hash="1" * 64,
               out=out, login_home=home, max_sends=0) == 3
    assert json.loads((out / "refusal.json").read_bytes())["code"] == "operator_identity"


def test_pins_forbidden_before_install(outside, tmp_path, monkeypatch, capsys):
    outside["artifact"]["name"] = "lcm-x"
    outside["fresh_install_hash"] = registry.ZERO_HASH
    path = write_entry(tmp_path / "entry.toml", outside)
    monkeypatch.setenv("BICENTENNIAL_OPERATOR", "benchmark")
    monkeypatch.setattr(pins, "HermesMemoryHost", lambda *a, **kw: pytest.fail("installed forbidden identity"))
    assert cli.main(["pins", "--entry", str(path), "--hermes", str(tmp_path),
                     "--plugin-source", str(tmp_path)]) == 3
    assert capsys.readouterr().err.strip() == "benchmark_operator_forbidden"


def test_entry_guide_codes():
    guide = Path(__file__).resolve().parents[2] / "docs/developers/entry.md"
    rows = re.findall(r"^\| `([^`]+)` \|", guide.read_text().split("| Code | Cause |", 1)[1], re.M)
    assert len(rows) == len(set(rows))
    assert set(rows) == {"entry_unreadable", "entry_invalid", "entry_recipe_missing", "entry_name_invalid",
        "recipe_in_builtin",
        "entry_recipe_invalid:<field>", "entry_shadows_builtin", "entry_recipe_unsupported:structured_formats",
        "entry_scripted_writes_unsupported", "t0_mapping_missing", "benchmark_operator_forbidden",
        "licence_not_osi", "artifact_unpinned", "route_unroutable", "compaction_alias_mismatch",
        "state_path_undeclared", "recall_placeholder", "schema_invalid",
        "unmeasured:artifact.sha256", "unmeasured:fresh_install_hash", "entry_surfaces_unsupported",
        "entry_shadows_hermes_plugin", "sandbox_overlap"}


@pytest.mark.parametrize("subdirectory", [False, True])
def test_engine_pins_use_installer(outside, source, offline, tmp_path, t1_installed, subdirectory):
    raw = outside["recipe"]
    del raw["provider"]
    raw.update(engine="outside-engine", plugin_directory="engine-directory")
    del raw["write"], raw["forget"]
    if subdirectory:
        raw["archive_tree"] = dict(ref=subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True).stdout.strip(), subdirectory=".")
    outside["artifact"]["sha256"] = outside["fresh_install_hash"] = registry.ZERO_HASH
    result = pins.measure(outside, hermes=tmp_path, plugin_source=source)
    assert len(result["fresh_install_hash"]) == 64
    outside["artifact"]["sha256"] = result["artifact.sha256"]
    outside["fresh_install_hash"] = result["fresh_install_hash"]
    with fixedroot.lease(0, pins.PinsRefused) as scratch:
        assert pins.measure_once(outside, scratch, hermes=tmp_path, plugin_source=source,
                                 worker_argv=[])["fresh_install_hash"] == result["fresh_install_hash"]
    with pytest.raises(t0.T0Refused, match="no_t0_surface:context_engine"):
        t0._preflight(system=outside["name"], entry=outside, packs=tmp_path, selected=["all"], pack_hash="1" * 64)
    ctx = t1.prepare(system=outside["name"], entry=outside, packs=t1_installed.root,
        pack_hash=t1_installed.digest, hermes=tmp_path, plugin_source=source, worker_argv=[])
    assert recipe(ctx.entry).engine == "outside-engine"
