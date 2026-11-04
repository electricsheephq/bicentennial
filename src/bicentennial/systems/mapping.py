"""Preflight coverage of declared tools by the reviewed scripted mappings."""

from bicentennial.systems.recipe import recipe

UNSCRIPTED = {"holographic": ("fact_feedback",), "mem0-oss": ("mem0_update",)}


def resolve_mapping(name):
    """Adapt the built-in tables to the mapping accepted by check_mapping."""
    resolved = recipe({"name": name} if isinstance(name, str) else name)
    write, forget = resolved.write, resolved.forget
    return dict(write=None if write is None else dict(tool=write.tool, fixed=write.fixed),
                forget=None if forget is None else dict(search_tool=forget.search_tool,
                    delete_tool=forget.delete_tool, delete_fixed=forget.delete_fixed),
                unscripted=resolved.unscripted)


def first_write_tool_matches(entry, write):
    """Whether the first declared write tool can use the scripted write mapping."""
    writes = entry.get("write_tools", [])
    return not writes or write is not None and write["tool"] == writes[0]["tool"]


def embedding_dimension_valid(dimension):
    """Whether the scripted embeddings responder can construct a vector."""
    return type(dimension) is int and dimension >= 2


def check_mapping(entry, mapping, *, require_forget=True):
    """Return the first D7 refusal, or None, for an admitted entry and resolved mapping.

    Mapping keys are write (tool, fixed), forget (search_tool, delete_tool,
    delete_fixed), and unscripted (tool names). Write and forget may be None.
    The caller selects whether its execution path needs a forget mapping.
    """
    writes = entry["write_tools"]
    if writes:
        write, forget = mapping.get("write"), mapping.get("forget")
        first = writes[0]["tool"]
        if not first_write_tool_matches(entry, write):
            return f"write_mapping_missing:{first}"
        tools = {row["tool"]: row for row in writes}
        named = [write["tool"]]
        if forget is not None:
            named.append(forget["delete_tool"])
        named.extend(mapping.get("unscripted", ()))
        for row in writes:
            if row["tool"] not in named:
                return f"write_mapping_missing:{row['tool']}"
        for tool in named:
            if tool not in tools:
                return f"write_mapping_unknown:{tool}"
        if forget is not None and forget.get("search_tool") is not None:
            search = forget["search_tool"]
            if search not in entry["read_tools"]:
                return f"forget_search_undeclared:{search}"
        calls = [(write["tool"], write.get("fixed", {}))]
        if forget is not None:
            calls.append((forget["delete_tool"], forget.get("delete_fixed", {})))
        for tool, fixed in calls:
            actions = tools[tool]["actions"]
            if "action" in fixed and actions and fixed["action"] not in actions:
                return f"write_mapping_action:{tool}"
        if require_forget and forget is None:
            return "forget_mapping_missing"
    if any(route["role"] == "embeddings" for route in entry["own_model_routes"]):
        dimension = entry.get("embedding_dim")
        if not embedding_dimension_valid(dimension):
            return "embedding_dim_invalid"
    return None
