"""Resolve per-system code tables from a registry entry at call time."""

from dataclasses import dataclass
from typing import NamedTuple


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


def recipe(entry) -> Recipe:
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
