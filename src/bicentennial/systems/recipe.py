"""Resolve per-system code tables from a registry entry at call time."""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import NamedTuple

from bicentennial.canon import sha256_canon


class WriteMapping(NamedTuple):
    tool: str
    fixed: dict
    content_key: str


@dataclass(frozen=True)
class Recipe:
    name: str
    provider: str | None
    archive_tree: tuple | None
    engine: str | None
    plugin_directory: str | None
    enabled: bool
    worker_environment: dict
    dependency_lock: str | None
    file_time_sites: tuple
    settle_threads: tuple | None
    forget: tuple | None
    write: WriteMapping | None
    unscripted: tuple
    reference_adapter: type | None

    def required(self, field):
        """Retain the strict table readers' missing-key error."""
        value = getattr(self, field)
        if value is None:
            raise KeyError(self.name)
        return value


class _ReadOnlyMapping(Mapping):
    """A detached mapping whose mutable values are copied on every read."""

    def __init__(self, values):
        self._values = deepcopy(values)

    def __getitem__(self, key):
        return deepcopy(self._values[key])

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)


def system_artifacts(entry):
    """Bind an outside system to its complete admitted declaration."""
    artifacts = [deepcopy(entry["artifact"])]
    if "recipe" in entry:
        artifacts.append(dict(name=entry["name"], version="entry", sha256=sha256_canon(entry)))
    return artifacts


def _outside(entry):
    from bicentennial.harness.hermes.plugin_host import ForgetMapping

    raw = entry["recipe"]
    tree = raw["archive_tree"]
    write, forget = raw.get("write"), raw.get("forget")
    return Recipe(
        name=entry["name"], provider=raw.get("provider"), engine=raw.get("engine"),
        plugin_directory=raw.get("plugin_directory", raw.get("provider", raw.get("engine"))),
        archive_tree=(tree["ref"],) + ((tree["subdirectory"],) if "subdirectory" in tree else ()),
        enabled=raw["enabled"], worker_environment=_ReadOnlyMapping(raw["worker_environment"]),
        dependency_lock=None, file_time_sites=tuple(raw["file_time_sites"]),
        settle_threads=tuple(raw["settle_threads"]) if "settle_threads" in raw else None,
        write=WriteMapping(write["tool"], _ReadOnlyMapping(write["fixed"]), write["content_key"])
            if write is not None else None,
        forget=ForgetMapping(*(None if k == "search_tool" and k not in forget else
            _ReadOnlyMapping(forget[k]) if k in ("search_fixed", "delete_fixed") else forget[k]
            for k in ForgetMapping._fields)) if forget is not None else None,
        unscripted=tuple(raw["unscripted"]), reference_adapter=None,
    )


def recipe(entry) -> Recipe:
    if "recipe" in entry:
        return _outside(entry)
    # These modules also consume recipes. Defer imports until their tables exist.
    from bicentennial.director import scripted
    from bicentennial.harness.hermes import plugin_host
    from bicentennial.runner import t0
    from bicentennial.systems import hermes_plugin, mapping

    name = entry["name"]
    write = scripted.WRITE_ARGS.get(name)
    return Recipe(
        name=name,
        provider=hermes_plugin.PROVIDERS.get(name),
        archive_tree=hermes_plugin.TREES.get(name),
        engine=hermes_plugin.ENGINES.get(name),
        plugin_directory=hermes_plugin.PLUGIN_DIRS.get(name,
            hermes_plugin.PROVIDERS.get(name, hermes_plugin.ENGINES.get(name))),
        enabled=name in hermes_plugin.ENABLED,
        worker_environment=hermes_plugin.WORKER_ENV.get(name, {}),
        dependency_lock=hermes_plugin.DEPENDENCIES.get(name),
        file_time_sites=hermes_plugin.FILE_TIME_SITES.get(name, ()),
        settle_threads=plugin_host.SETTLE_THREADS.get(name),
        forget=plugin_host.FORGET.get(name),
        write=WriteMapping(*write) if write is not None else None,
        unscripted=mapping.UNSCRIPTED.get(name, ()),
        reference_adapter=t0.REFERENCE_SYSTEMS.get(name),
    )
