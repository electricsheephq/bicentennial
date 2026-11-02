"""Reviewed mappings cover declarations without depending on entry identity."""

from copy import deepcopy

import pytest

from bicentennial.systems.registry import REGISTRY, load


def mapping_module():
    from bicentennial.systems import mapping
    return mapping


def declaration():
    return dict(name="custom", write_tools=[dict(tool="store", actions=["add"]),
                dict(tool="delete", actions=["remove"]), dict(tool="feedback", actions=[])],
                read_tools=["search"], own_model_routes=[], embedding_dim=None)


def resolved():
    return dict(write=dict(tool="store", fixed=dict(action="add")),
                forget=dict(search_tool="search", delete_tool="delete",
                            delete_fixed=dict(action="remove")), unscripted=("feedback",))


@pytest.mark.parametrize("tier", ["T0", "T1"])
@pytest.mark.parametrize("path", sorted(REGISTRY.glob("*.toml")), ids=lambda p: p.stem)
def test_registry_mappings_unchanged(path, tier):
    entry = load(path)
    mapping = mapping_module()
    assert mapping.check_mapping(entry, mapping.resolve_mapping(entry["name"]),
                                 require_forget=tier == "T0" or bool(entry["write_tools"])) is None


@pytest.mark.parametrize("case,code", [
    ("order", "write_mapping_missing:delete"),
    ("absent_write", "write_mapping_missing:store"),
    ("uncovered", "write_mapping_missing:extra"),
    ("unknown_delete", "write_mapping_unknown:delete"),
    ("unknown_unscripted", "write_mapping_unknown:feedback"),
    ("search", "forget_search_undeclared:search"),
    ("write_action", "write_mapping_action:store"),
    ("delete_action", "write_mapping_action:delete"),
    ("forget", "forget_mapping_missing"),
])
def test_mapping_refusals(case, code):
    entry, mapped = declaration(), resolved()
    if case == "order":
        entry["write_tools"][:2] = reversed(entry["write_tools"][:2])
    elif case == "absent_write":
        mapped["write"] = None
    elif case == "uncovered":
        entry["write_tools"] += [dict(tool="extra", actions=[]), dict(tool="later", actions=[])]
    elif case in ("unknown_delete", "unknown_unscripted"):
        entry["write_tools"].pop(1 if case == "unknown_delete" else 2)
    elif case == "search":
        entry["read_tools"] = []
    elif case in ("write_action", "delete_action"):
        entry["write_tools"][0 if case == "write_action" else 1]["actions"] = ["other"]
    elif case == "forget":
        mapped["forget"] = None
        mapped["unscripted"] += ("delete",)
    assert mapping_module().check_mapping(entry, mapped, require_forget=True) == code


def test_first_refusal_and_write_side_order():
    entry, mapped = declaration(), resolved()
    entry["write_tools"].append(dict(tool="extra", actions=[]))
    entry["read_tools"] = []
    assert mapping_module().check_mapping(entry, mapped) == "write_mapping_missing:extra"
    entry["write_tools"] = [entry["write_tools"][0]]
    assert mapping_module().check_mapping(entry, mapped) == "write_mapping_unknown:delete"


@pytest.mark.parametrize("dimension", [None, 1, 0, -1, True, 2.0, "2"])
@pytest.mark.parametrize("has_writes", [False, True])
def test_embedding_dimension_refusal(dimension, has_writes):
    entry, mapped = declaration(), resolved()
    if not has_writes:
        entry["write_tools"] = []
    entry.update(own_model_routes=[dict(role="embeddings", alias="bicentennial-embeddings")],
                 embedding_dim=dimension)
    assert mapping_module().check_mapping(entry, mapped) == "embedding_dim_invalid"


def test_mapping_valid_boundaries_and_no_mutation():
    entry, mapped = declaration(), resolved()
    entry["write_tools"][0]["actions"] = []
    entry["write_tools"][1]["actions"] = []
    entry.update(own_model_routes=[dict(role="embeddings")], embedding_dim=2)
    before = deepcopy((entry, mapped))
    assert mapping_module().check_mapping(entry, mapped) is None
    assert (entry, mapped) == before
    entry["own_model_routes"] = []
    entry["embedding_dim"] = None
    mapped["forget"] = None
    mapped["unscripted"] += ("delete",)
    assert mapping_module().check_mapping(entry, mapped, require_forget=False) is None
    entry["write_tools"] = []
    assert mapping_module().check_mapping(entry, mapped, require_forget=True) is None


@pytest.mark.parametrize("name", ["holographic", "mem0-oss"])
def test_unscripted_exceptions_are_required(name, monkeypatch):
    mapping = mapping_module()
    entry = load(REGISTRY / f"{name}.toml")
    assert mapping.check_mapping(entry, mapping.resolve_mapping(name)) is None
    monkeypatch.setattr(mapping, "UNSCRIPTED", {})
    tool = "fact_feedback" if name == "holographic" else "mem0_update"
    assert mapping.check_mapping(entry, mapping.resolve_mapping(name)) == f"write_mapping_missing:{tool}"
