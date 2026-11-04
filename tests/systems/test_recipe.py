"""The resolver preserves table values, absence, and runtime predicate boundaries."""

import ast
import json
from pathlib import Path

import pytest
from bicentennial.systems.recipe import recipe

from bicentennial.canon import canon, sha256_canon
from bicentennial.director import scripted
from bicentennial.director.responder import Call
from bicentennial.director.routes import RouteTable, route_table_hash
from bicentennial.harness.hermes import plugin_host
from bicentennial.runner import life, t0, t1
from bicentennial.systems import hermes_plugin as hp
from bicentennial.systems import mapping, pins
from bicentennial.systems.registry import REGISTRY, load

ENTRIES = tuple(load(path) for path in sorted(REGISTRY.glob("*.toml")))


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["name"])
def test_recipe_fields_and_helpers(entry):
    name = entry["name"]
    resolved = recipe(entry)
    expected = dict(name=name, provider=hp.PROVIDERS.get(name), archive_tree=hp.TREES.get(name),
        engine=hp.ENGINES.get(name),
        plugin_directory=hp.PLUGIN_DIRS.get(name, hp.PROVIDERS.get(name, hp.ENGINES.get(name))),
        enabled=name in hp.ENABLED, worker_environment=hp.WORKER_ENV.get(name, {}),
        dependency_lock=hp.DEPENDENCIES.get(name), file_time_sites=hp.FILE_TIME_SITES.get(name, ()),
        settle_threads=plugin_host.SETTLE_THREADS.get(name), forget=plugin_host.FORGET.get(name),
        write=scripted.WRITE_ARGS.get(name), unscripted=mapping.UNSCRIPTED.get(name, ()),
        reference_adapter=t0.REFERENCE_SYSTEMS.get(name))
    assert vars(resolved) == expected
    assert hp.is_plugin(name) == (name in hp.PROVIDERS or name in hp.ENGINES)
    assert hp.plugin_dir(name) == expected["plugin_directory"]
    assert hp.resolve_worker_env(name, Path("model-cache")) == {
        k: v.replace("{model_cache}", "model-cache") for k, v in expected["worker_environment"].items()}
    write, forget = scripted.WRITE_ARGS.get(name), plugin_host.FORGET.get(name)
    assert mapping.resolve_mapping(name) == dict(
        write=None if write is None else dict(tool=write[0], fixed=write[1]),
        forget=None if forget is None else dict(search_tool=forget[0], delete_tool=forget[6],
                                                delete_fixed=forget[7]),
        unscripted=mapping.UNSCRIPTED.get(name, ()))
    with pytest.raises(AttributeError):
        resolved.provider = "other"


def test_recipe_looks_up_replaced_tables(monkeypatch):
    entry = {"name": "synthetic"}
    replacements = (
        (hp, "PROVIDERS", "provider", "slot"),
        (hp, "TREES", "archive_tree", ("HEAD", "tree")),
        (hp, "ENGINES", "engine", "engine"),
        (hp, "PLUGIN_DIRS", "plugin_directory", "directory"),
        (hp, "WORKER_ENV", "worker_environment", {"OFFLINE": "1"}),
        (hp, "DEPENDENCIES", "dependency_lock", "lock"),
        (hp, "FILE_TIME_SITES", "file_time_sites", ("file:function",)),
        (plugin_host, "SETTLE_THREADS", "settle_threads", ("thread",)),
        (plugin_host, "FORGET", "forget", plugin_host.FORGET["hermes-native"]),
        (scripted, "WRITE_ARGS", "write", scripted.WRITE_ARGS["hermes-native"]),
        (mapping, "UNSCRIPTED", "unscripted", ("extra",)),
        (t0, "REFERENCE_SYSTEMS", "reference_adapter", object),
    )
    recipe(entry)
    for module, table, field, value in replacements:
        monkeypatch.setattr(module, table, {entry["name"]: value})
        assert getattr(recipe(entry), field) == value
    monkeypatch.setattr(hp, "ENABLED", frozenset((entry["name"],)))
    assert recipe(entry).enabled


def test_absence_and_required_fields():
    resolved = recipe({"name": "absent"})
    for field in ("provider", "archive_tree", "engine", "plugin_directory", "dependency_lock",
                  "settle_threads", "write", "forget", "reference_adapter"):
        assert getattr(resolved, field) is None
        with pytest.raises(KeyError, match="absent"):
            resolved.required(field)
    assert resolved.worker_environment == {} and resolved.file_time_sites == ()
    assert resolved.unscripted == () and resolved.enabled is False


def test_forget_tuple_compatibility():
    expected = {
        "hermes-native": (None, {}, "", "", "", "", "memory", {"action": "remove", "target": "memory"}, "old_text"),
        "holographic": ("fact_store", {"action": "search"}, "query", "results", "content", "fact_id",
                        "fact_store", {"action": "remove"}, "fact_id"),
        "mem0-oss": ("mem0_search", {}, "query", "results", "memory", "id", "mem0_delete", {}, "memory_id"),
        "omega": ("omega_query", {}, "query", "results", "content", "id", "omega_delete", {}, "memory_id"),
    }
    assert plugin_host.FORGET == expected
    for name, row in plugin_host.FORGET.items():
        assert json.dumps(row) == json.dumps(expected[name])
        with pytest.raises(TypeError, match="unsupported canonical JSON type"):
            canon(row)
        assert sha256_canon(list(row)) == sha256_canon(list(expected[name]))


def raises_message(call, message):
    try:
        call()
    except ValueError as error:
        return str(error) == message
    return False


def first_write_agrees(entry):
    write = mapping.resolve_mapping(entry["name"])["write"]
    refused = raises_message(lambda: scripted.ScriptedResponder(entry),
        "scripted write arguments are not declared for this system")
    assert mapping.first_write_tool_matches(entry, write) == (not refused)


def embeddings_agree(entry):
    # Match the Call built by Director._embeddings, including role, subrole and wire.
    call = Call("embeddings", "embedding", "embeddings", {"input": "quartz"},
                "bicentennial-embeddings", None, "attempt")
    responder = scripted.ScriptedResponder(entry)
    refused = raises_message(lambda: responder.respond(call), "scripted embeddings need embedding_dim >= 2")
    assert mapping.embedding_dimension_valid(entry.get("embedding_dim")) == (not refused)


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["name"])
def test_registry_predicates_match_responder(entry):
    first_write_agrees(entry)
    embeddings_agree(entry)


@pytest.mark.parametrize("tools", [[], ["store"], ["other"], ["store", "other"]])
@pytest.mark.parametrize("write_tool", [None, "store", "other"])
def test_first_write_predicate_matches_responder(monkeypatch, tools, write_tool):
    monkeypatch.setattr(scripted, "WRITE_ARGS", {} if write_tool is None else {
        "synthetic": (write_tool, {}, "content")})
    first_write_agrees(dict(name="synthetic", write_tools=[dict(tool=t, actions=[]) for t in tools]))


@pytest.mark.parametrize("dimension", [None, 1, 2, 2.0, True])
def test_embedding_predicate_matches_responder(dimension):
    embeddings_agree(dict(name="synthetic", write_tools=[], embedding_dim=dimension))


def test_frozen_t0_routes():
    assert route_table_hash(RouteTable.load(t0.ROUTE_TABLE)) == (
        "7c34dc452feec849111831603ac6caec7521b3eb46aef7705c15d365b30b917f")
    tree = ast.parse(Path(t0.__file__).read_text())
    assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id == "ROUTE_TABLE" for t in node.targets))
    assert ast.literal_eval(assignment.value) == t0.ROUTE_TABLE


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e["name"])
def test_route_derivations(entry, monkeypatch):
    name = entry["name"]
    assert route_table_hash(RouteTable.load(life._routes(name))) == route_table_hash(RouteTable.load(t1._routes(name)))
    assert pins._routes(name)["routes"] == [t1._routes(name)["routes"][0]]
    table = t1._routes(name)
    table["routes"][0]["alias"] = "bicentennial-other"
    monkeypatch.setattr(t1, "_routes", lambda n: table if n == name else None)
    assert life._routes(name) == table
    assert pins._routes(name)["routes"] == [table["routes"][0]]
