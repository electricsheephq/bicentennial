"""Float-free run contracts; JSON Schema subset plus cross-field invariants.

Schemas live at the source-tree boundary. Validation returns None or raises
ValueError, including a JSON-style path for structural failures.
"""

import json
import re
from pathlib import Path

from bicentennial.canon import canon

SCHEMAS = Path(__file__).resolve().parents[3] / "schemas"
_MASK_PATH = re.compile(r"\$(?:\.\.?[A-Za-z_][A-Za-z0-9_]*|\[\*\])+")
NAMES = {"script", "ledger-record", "masks", "route-table", "fault-lite",
         "system", "surfaces", "lock"}
FORBIDDEN = {"event_id", "fact_id", "fact_ids", "gold", "gold_spans",
             "options", "manifest"}
TYPES = {"object": dict, "array": list, "string": str, "integer": int,
         "boolean": bool, "null": type(None)}


def _children(value, path="$", keys=False):
    if isinstance(value, dict):
        for key, child in value.items():
            place = f"{path}[{json.dumps(key, ensure_ascii=False)}]"
            if keys:
                yield place, key
            yield from _children(child, place, keys)
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            yield from _children(child, f"{path}[{index}]", keys)
    elif isinstance(value, str) and not keys:
        yield path, value


def scan_script(script, sealed_ids, gold_tokens) -> list[str]:
    """Return each string-value path containing any exact sealed substring."""
    tokens = tuple(sealed_ids) + tuple(gold_tokens)
    return [path for path, text in _children(script)
            if any(token in text for token in tokens)]


def _check(schema, value, path="$"):
    kinds = schema.get("type", [])
    kinds = [kinds] if isinstance(kinds, str) else kinds
    if kinds and not any(type(value) is TYPES[kind] for kind in kinds):
        raise ValueError(f"{path}: expected {kinds}")
    if "enum" in schema and not any(type(value) is type(v) and value == v
                                     for v in schema["enum"]):
        raise ValueError(f"{path}: invalid enum value")
    if isinstance(value, str) and "pattern" in schema:
        if re.search(schema["pattern"], value) is None:
            raise ValueError(f"{path}: pattern mismatch")
    if type(value) is int and value < schema.get("minimum", value):
        raise ValueError(f"{path}: below minimum")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        missing = set(schema.get("required", [])) - value.keys()
        extra = value.keys() - props.keys()
        if missing or (schema.get("additionalProperties") is False and extra):
            raise ValueError(f"{path}: missing={sorted(missing)}, extra={sorted(extra)}")
        for key in value.keys() & props.keys():
            _check(props[key], value[key], f"{path}[{json.dumps(key)}]")
    if isinstance(value, list) and "items" in schema:
        for index, child in enumerate(value):
            _check(schema["items"], child, f"{path}[{index}]")


def _unique(values, label):
    if len(values) != len(set(values)):
        raise ValueError(f"{label}: duplicate identity")


def validate(name, obj) -> None:
    """Validate a named run schema, canonical types and semantic constraints."""
    if name not in NAMES:
        raise ValueError(f"unknown contract: {name}")
    try:
        canon(obj)
    except TypeError as error:
        raise ValueError(str(error)) from error
    schema = json.loads((SCHEMAS / f"{name}.schema.json").read_bytes())
    _check(schema, obj, "$")
    if name == "script":
        for path, key in _children(obj, keys=True):
            if key in FORBIDDEN:
                raise ValueError(f"{path}: forbidden script property")
        _unique([s["index"] for s in obj["sessions"]], "sessions")
        for session in obj["sessions"]:
            _unique([t["n"] for t in session["turns"]], "turns")
            if any(t["kind"] != session["kind"] for t in session["turns"]):
                raise ValueError("session and turn kinds disagree")
    elif name == "ledger-record" and len(obj["load"]) != 3:
        raise ValueError("load: expected 1-, 5-, 15-minute values")
    elif name == "route-table":
        _unique([(r["system"], r["segment"]) for r in obj["routes"]], "routes")
    elif name == "surfaces":
        paths = [row["path"] for row in obj]
        _unique(paths, "surfaces")
        if paths != sorted(paths):
            raise ValueError("surfaces: paths must be sorted")
        shapes = {"file": {"path", "kind", "mode", "size", "sha256"},
                  "dir": {"path", "kind", "mode"},
                  "symlink": {"path", "kind", "target"}}
        for row in obj:
            if set(row) != shapes[row["kind"]] or row.get("mode", 0) > 0o7777:
                raise ValueError(f"surfaces: invalid {row['kind']} row")
    elif name == "system":
        for path, text in _children(obj["recall"]["argument_template"]):
            if re.search(r"\{[^{}]*\}", text.replace("{prompt}", "")):
                raise ValueError(f"recall{path}: only {{prompt}} is allowed")
        if obj["recall"]["tool"] not in obj["read_tools"]:
            raise ValueError("recall tool is not a declared read tool")
        roles = [route["role"] for route in obj["own_model_routes"]]
        _unique(roles, "own_model_routes")
        if set(obj["structured_formats"]) - set(roles):
            raise ValueError("structured format lacks an own-model route")
        if obj["name"].casefold().replace("_", "-") == "lcm-x":
            if obj["benchmark_operator_runs"]:
                raise ValueError("LCM-X cannot run under the benchmark operator")
    elif name == "masks":
        _unique([entry["name"] for entry in obj], "masks")
        for entry in obj:
            if entry["kind"] == "jsonpath" and not _MASK_PATH.fullmatch(entry["target"]):
                raise ValueError(f"mask {entry['name']}: only $, .name, ..name and [*] segments")
