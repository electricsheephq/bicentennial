"""Offline system selection; unmeasured pins are declarations, never runnable."""

import json
import os
import re
import tomllib
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath

from bicentennial.contracts.run import SCHEMAS, _check, validate
from bicentennial.director.roles import SUMMARISER_ALIAS
from bicentennial.systems.recipe import recipe

# Provisional OSI allow-list for C-9 selection (pending), not a final roster decision.
PROVISIONAL_OSI_LICENCES = frozenset({
    "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "MPL-2.0", "ISC",
    "GPL-2.0-only", "GPL-3.0-only", "LGPL-2.1-only", "LGPL-3.0-only", "AGPL-3.0-only",
})
REGISTRY = Path(__file__).resolve().parents[3] / "systems" / "registry"
ZERO_HASH = "0" * 64
_ENV_OPERATOR = object()
_TAG = re.compile(r"v?\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?(?:\+[0-9A-Za-z.-]+)?")
_ALIAS = re.compile(r"bicentennial-[a-z0-9-]+")


class SystemRefused(ValueError):
    """A declaration failed the runner gate; reasons are stable machine labels."""

    def __init__(self, reasons):
        self.reasons = tuple(reasons)
        super().__init__(", ".join(self.reasons))


def _read(path):
    with open(path, "rb") as stream:
        entry = tomllib.load(stream)
    for key in ("recall", "embedding_dim"):
        entry.setdefault(key, None)
    return entry


def load(path) -> dict:
    """Read TOML, supply absent nullable keys, and enforce K13's system contract."""
    entry = _read(path)
    validate("system", entry)
    return entry


def load_entry(path):
    """Load an outside declaration with stable CLI refusal codes."""
    reasons = []
    try:
        entry = load(path)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        reasons.append("entry_unreadable")
    except ValueError:
        reasons.append("entry_invalid")
    else:
        if "recipe" not in entry:
            reasons.append("entry_recipe_missing")
        else:
            return entry
    raise SystemRefused(reasons)


def _recipe_error(field):
    reasons = []
    reasons.append("entry_recipe_invalid:<field>")
    return reasons[0].replace("<field>", field)


def _recipe_shape(entry):
    raw = entry["recipe"]
    schema = json.loads((SCHEMAS / "system.schema.json").read_bytes())["properties"]["recipe"]
    if not isinstance(raw, dict):
        return [_recipe_error("recipe")]
    for field in sorted(set(schema["required"]) - raw.keys()):
        return [_recipe_error(field)]
    for field in sorted(raw):
        if field not in schema["properties"]:
            return [_recipe_error(field)]
        try:
            _check(schema["properties"][field], raw[field])
        except ValueError:
            return [_recipe_error(field)]
    if ("provider" in raw) == ("engine" in raw):
        return [_recipe_error("provider")]
    if "forget" in raw:
        from bicentennial.harness.hermes.plugin_host import ForgetMapping

        if set(ForgetMapping._fields) - {"search_tool"} - raw["forget"].keys():
            return [_recipe_error("forget")]
    return []


def _selection_name(value):
    return unicodedata.normalize("NFKC", value).casefold().replace("_", "-")


def _builtin_names():
    from bicentennial.director import scripted
    from bicentennial.harness.hermes import plugin_host
    from bicentennial.runner import t0
    from bicentennial.systems import hermes_plugin, mapping

    tables = (hermes_plugin.PROVIDERS, hermes_plugin.TREES, hermes_plugin.ENGINES,
        hermes_plugin.PLUGIN_DIRS, hermes_plugin.ENABLED, hermes_plugin.WORKER_ENV,
        hermes_plugin.DEPENDENCIES, hermes_plugin.FILE_TIME_SITES, plugin_host.SETTLE_THREADS,
        plugin_host.FORGET, scripted.WRITE_ARGS, mapping.UNSCRIPTED, t0.REFERENCE_SYSTEMS)
    return {p.stem for p in REGISTRY.glob("*.toml")} | {name for table in tables for name in table} | {
        name for name, role in scripted.FORMATS}


def _operator_name(value):
    return "".join(c for c in unicodedata.normalize("NFKC", value).casefold() if c.isalnum())


def operator_forbidden(entry):
    """Recognize operator-excluded identities without consulting the environment."""
    artifact, raw = entry.get("artifact", {}), entry.get("recipe", {})
    names = [_operator_name(value) for value in (entry.get("name"), artifact.get("name"),
        raw.get("provider"), raw.get("engine"), raw.get("plugin_directory")) if isinstance(value, str)]
    if any("lcm" in name for name in names):
        return True
    for path in sorted(REGISTRY.glob("*.toml")):
        builtin = load(path)
        if builtin["benchmark_operator_runs"] is not False:
            continue
        if set(names) & {_operator_name(builtin["name"]), _operator_name(builtin["artifact"]["name"])}:
            return True
        digest = builtin["artifact"]["sha256"]
        if digest != ZERO_HASH and digest == artifact.get("sha256"):
            return True
    return False


def outside_reasons(entry, operator=_ENV_OPERATOR):
    """Outside-only gates, also used for pin measurement without unmeasured checks."""
    if "recipe" not in entry:
        return []
    reasons = _recipe_shape(entry)
    if reasons:
        return reasons
    from bicentennial.systems.hermes_plugin import _PLUGIN, resolve_worker_env

    raw = entry["recipe"]
    # Characters a published rerun command accepts (report/t2lite_flips.py _token), starting with a letter or
    # digit so that a name is never a path such as `.` or `..`.
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", entry["name"]):
        reasons.append("entry_name_invalid")
    if _selection_name(entry["name"]) in {_selection_name(n) for n in _builtin_names()}:
        reasons.append("entry_shadows_builtin")
    for field in ("provider", "engine", "plugin_directory"):
        if field in raw and (not _PLUGIN.fullmatch(raw[field]) or field == "engine" and raw[field] == "compressor"):
            reasons.append(_recipe_error(field))
    # The life runners hash, clone and wipe the whole Hermes home and know only these two roots (runner/life.py),
    # so an outside entry declares the home as every built-in does, and its other surfaces under SANDBOX_HOME.
    declared = entry.get("surfaces")
    surfaces = [s for s in declared if isinstance(s, dict)] if isinstance(declared, list) else []
    if ([s.get("relative") for s in surfaces if s.get("root") == "HERMES_HOME"] != ["."]
            or any(s.get("root") not in ("HERMES_HOME", "SANDBOX_HOME") for s in surfaces)):
        reasons.append("entry_surfaces_unsupported")
    tree = raw["archive_tree"]
    if tree["ref"] != "HEAD" and not re.fullmatch(r"[0-9a-f]{40}", tree["ref"]):
        reasons.append(_recipe_error("archive_tree.ref"))
    if "subdirectory" in tree:
        subdir = tree["subdirectory"]
        if (not subdir or PurePosixPath(subdir).is_absolute() or PureWindowsPath(subdir).is_absolute()
                or ".." in PurePosixPath(subdir).parts or "\\" in subdir or subdir.startswith("-")):
            reasons.append(_recipe_error("archive_tree.subdirectory"))
    try:
        resolve_worker_env(entry)
    except ValueError:
        reasons.append(_recipe_error("worker_environment"))
    if entry.get("structured_formats"):
        reasons.append("entry_recipe_unsupported:structured_formats")
    if entry.get("write_tools"):
        reasons.append("entry_scripted_writes_unsupported")
    if "provider" in raw and ("write" not in raw or "forget" not in raw):
        reasons.append("t0_mapping_missing")
    if operator is _ENV_OPERATOR:
        operator = os.environ.get("BICENTENNIAL_OPERATOR")
    if operator == "benchmark" and (entry.get("benchmark_operator_runs") is False or operator_forbidden(entry)):
        reasons.append("benchmark_operator_forbidden")
    return reasons


def _placeholder(value):
    if isinstance(value, str):
        remaining = value.replace("{prompt}", "")
        return "{" in remaining or "}" in remaining
    if isinstance(value, dict):
        return any(_placeholder(k) or _placeholder(v) for k, v in value.items())
    return isinstance(value, list) and any(_placeholder(v) for v in value)


def check(entry) -> list[str]:
    """Return ordered, deduplicated policy refusals, or schema_invalid as fallback."""
    if not isinstance(entry, dict):
        return ["schema_invalid"]
    from bicentennial.systems.hermes_plugin import (
        TELEMETRY_SWITCHES,
        normalise,
    )

    reasons = []
    artifact = entry.get("artifact")
    artifact = artifact if isinstance(artifact, dict) else {}
    if not isinstance(entry.get("licence"), str) or entry["licence"] not in PROVISIONAL_OSI_LICENCES:
        reasons.append("licence_not_osi")
    version, digest = artifact.get("version"), artifact.get("sha256")
    if (not isinstance(version, str) or not _TAG.fullmatch(version)
            or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
        reasons.append("artifact_unpinned")
    routes = entry.get("own_model_routes", [])
    if isinstance(routes, list) and any(
        not isinstance(r, dict) or not isinstance(r.get("alias"), str)
        or not _ALIAS.fullmatch(r["alias"]) for r in routes
    ):
        reasons.append("route_unroutable")
    if isinstance(routes, list) and any(
        isinstance(r, dict) and r.get("role") == "compaction"
        and r.get("alias") != SUMMARISER_ALIAS for r in routes
    ):
        reasons.append("compaction_alias_mismatch")
    surfaces = entry.get("surfaces", [])
    bad_path = False
    if isinstance(surfaces, list):
        for surface in surfaces:
            path = surface.get("relative") if isinstance(surface, dict) else None
            if (not isinstance(path, str) or not path or PurePosixPath(path).is_absolute()
                    or PureWindowsPath(path).is_absolute() or "\\" in path
                    or ".." in PurePosixPath(path).parts):
                bad_path = True
    if bad_path or ((entry.get("write_tools") or routes) and not surfaces):
        reasons.append("state_path_undeclared")
    recall = entry.get("recall")
    if isinstance(recall, dict) and _placeholder(recall.get("argument_template")):
        reasons.append("recall_placeholder")
    name = entry.get("name")
    resolved = recipe(entry) if isinstance(name, str) else None
    lock = resolved.dependency_lock if resolved is not None else None
    if lock is not None:
        try:
            text = (REGISTRY.parents[1] / lock).read_text()
        except (OSError, UnicodeError):
            reasons.append("telemetry_lock_unreadable")
        else:
            pins = set()
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "--hash")):
                    continue
                pin = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)==[^\s;\\]+", line)
                if pin:
                    pins.add(normalise(pin[1]))
            for package, (switch, value) in sorted(TELEMETRY_SWITCHES.items()):
                if package in pins and resolved.worker_environment.get(switch) != value:
                    reasons.append("telemetry_switch_missing:" + package + ":" + switch + "=" + value)
    try:
        validate("system", entry)
    except ValueError:
        if not reasons:
            reasons.append("schema_invalid")
    return reasons


def unmeasured(entry) -> list[str]:
    """Name pins that still need measurement, in stable display order."""
    return [field for field, value in (
        ("artifact.sha256", entry.get("artifact", {}).get("sha256")),
        ("fresh_install_hash", entry.get("fresh_install_hash")),
    ) if value == ZERO_HASH]


def hermes_shadow_reasons(entry, hermes):
    """Hermes loads a provider or engine it bundles before an installed one of the same name, so an outside entry
    named after one would run Hermes's copy, not its archive (plugins/memory and plugins/context_engine lookups)."""
    if not isinstance(entry, dict) or not isinstance(entry.get("recipe"), dict) or hermes is None:
        return []
    raw, plugins = entry["recipe"], Path(hermes) / "plugins"
    provider, engine = raw.get("provider"), raw.get("engine")
    shadowed = (isinstance(provider, str) and (plugins / "memory" / provider / "__init__.py").is_file()
                or isinstance(engine, str) and (plugins / "context_engine" / engine).is_dir())
    return ["entry_shadows_hermes_plugin"] if shadowed else []


def admit_system(entry, operator=_ENV_OPERATOR, hermes=None) -> None:
    """Refuse before running; an omitted operator is read from the current environment."""
    if operator is _ENV_OPERATOR:
        operator = os.environ.get("BICENTENNIAL_OPERATOR")
    reasons = outside_reasons(entry, operator) + hermes_shadow_reasons(entry, hermes) if isinstance(entry, dict) else []
    if reasons:
        raise SystemRefused(reasons)
    reasons = check(entry)
    if isinstance(entry, dict):
        if entry.get("benchmark_operator_runs") is False and operator == "benchmark":
            reasons.append("benchmark_operator_forbidden")
        if "schema_invalid" not in reasons and isinstance(entry.get("artifact"), dict):
            reasons.extend("unmeasured:" + field for field in unmeasured(entry))
    if reasons:
        raise SystemRefused(reasons)
