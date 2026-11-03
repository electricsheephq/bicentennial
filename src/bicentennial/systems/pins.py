"""Measure registry pins through the T0 host without starting its worker."""

import re
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from copy import deepcopy
from hashlib import sha256

from bicentennial.director.routes import RouteTable
from bicentennial.director.scripted import ScriptedResponder
from bicentennial.gitenv import git_env
from bicentennial.harness.hermes.adapter import PinMismatch
from bicentennial.harness.hermes.plugin_host import HermesMemoryHost
from bicentennial.runtime.clock import SimClock
from bicentennial.sandbox import fixedroot
from bicentennial.systems.hermes_plugin import TREES, is_plugin
from bicentennial.systems.registry import (
    REGISTRY,
    ZERO_HASH,
    SystemRefused,
    check,
    load,
)


class PinsRefused(ValueError):
    def __init__(self, code, *, detail=()):
        self.code, self.detail = code, tuple(detail)
        super().__init__(code)


def archive_hash(source, recipe):
    """Hash the exact archive bytes, including Git's commit and path headers."""
    digest = sha256()
    with subprocess.Popen(["git", "-C", str(source), "archive", "--format=tar", *recipe],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=git_env()) as proc:
        for chunk in iter(lambda: proc.stdout.read(1 << 20), b""):
            digest.update(chunk)
    if proc.returncode:
        raise PinsRefused("pin_mismatch")
    return digest.hexdigest()


def _validate(entry, hermes, plugin_source, worker_argv):
    reasons = check(entry)
    if reasons:
        raise SystemRefused(reasons)
    if entry["harness"] != "hermes":
        raise PinsRefused("harness_not_hermes")
    plugin = is_plugin(entry["name"])
    if (hermes is None and worker_argv is None) or plugin != (plugin_source is not None):
        raise PinsRefused("missing_input")
    if any(fixedroot.overlaps(path) for path in (hermes, plugin_source) if path is not None):
        raise PinsRefused("sandbox_overlap")


def measure(entry, *, hermes=None, plugin_source=None, recipe=None, sandbox_slot=0):
    """Measure two samples under a private lease, ignoring the old declaration."""
    _validate(entry, hermes, plugin_source, None)
    with fixedroot.lease(sandbox_slot, PinsRefused) as sandbox:
        return _measure(entry, sandbox, hermes=hermes, plugin_source=plugin_source, recipe=recipe)


def measure_once(entry, sandbox, *, hermes=None, plugin_source=None, worker_argv=None):
    """Measure one install in the caller's leased sandbox, preserving its declarations."""
    _validate(entry, hermes, plugin_source, worker_argv)
    return _measure(entry, sandbox, hermes=hermes, plugin_source=plugin_source,
                    samples=1, verify_declared=True, worker_argv=worker_argv)


def _measure(entry, sandbox, *, hermes=None, plugin_source=None, recipe=None,
             samples=2, verify_declared=False, worker_argv=None):
    plugin = is_plugin(entry["name"])
    measured = deepcopy(entry)
    if not verify_declared:
        measured["fresh_install_hash"] = ZERO_HASH
    with ExitStack() as cleanup:
        # The existing installer uses tempfile for its archive. Keep that scratch in the lease too.
        temporary = sandbox / "tmp"
        temporary.mkdir()
        previous = tempfile.tempdir
        tempfile.tempdir = str(temporary)
        cleanup.callback(setattr, tempfile, "tempdir", previous)
        if plugin:
            recipe = tuple(recipe or TREES[entry["name"]])
            if recipe[1:] != TREES[entry["name"]][1:]:
                raise PinsRefused("pin_mismatch")
            if not verify_declared:
                measured["artifact"]["sha256"] = archive_hash(plugin_source, recipe)
        routes = RouteTable.load({"routes": [dict(system=entry["name"], segment="seg0",
            probe_model="probe-model", alias="bicentennial-main", summariser="summary-model",
            vision=None, served_by="scripted")]})
        hosts = []
        for index in range(samples):
            root = sandbox / f"pins-{index}"
            root.mkdir()
            host = HermesMemoryHost(measured, route_table=routes, responder=ScriptedResponder(measured),
                clock=SimClock(root / "clock.json", 0, 60), root=root, scratch=sandbox,
                life="pins", branch="B0", run="pins", lock_hash="0" * 64, sim_epoch_s=0,
                checkout=hermes, harness_pin=load(REGISTRY / "hermes-native.toml")["artifact"],
                plugin_source=plugin_source, worker_argv=worker_argv)
            cleanup.callback(host.close)
            # Both servers remain bound until both measurements finish: port 0 cannot be reused.
            hosts.append(host)
        first = hosts[0].fresh_install_hash
        if any(host.fresh_install_hash != first for host in hosts[1:]):
            raise PinsRefused("pins_unstable", detail=tuple(host.fresh_install_hash for host in hosts))
        return {"fresh_install_hash": first, "artifact.sha256": measured["artifact"]["sha256"]}


def run_pins(*, system, hermes=None, plugin_source=None, sandbox_slot=0):
    try:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", system):
            raise PinsRefused("unknown_system")
        path = REGISTRY / f"{system}.toml"
        if not path.is_file():
            raise PinsRefused("unknown_system")
        entry = load(path)
        if entry["name"] != system:
            raise PinsRefused("unknown_system")
        recipe = None
        if is_plugin(system):
            # Registry comments supply the catalog commit and optional archive subdirectory.
            match = re.search(r"git archive --format=tar ([0-9a-f]{40})([^|\n]*) \|", path.read_text())
            if match is None:
                raise PinsRefused("pin_mismatch")
            recipe = (match[1], *match[2].split())
        pins = measure(entry, hermes=hermes, plugin_source=plugin_source,
                       recipe=recipe, sandbox_slot=sandbox_slot)
    except PinsRefused as error:
        print(error.code, *error.detail, file=sys.stderr)
        return 3
    except SystemRefused as error:
        print(*error.reasons, file=sys.stderr)
        return 3
    except PinMismatch:
        print("pin_mismatch", file=sys.stderr)
        return 3
    except (OSError, ValueError) as error:  # the text names the cause, for example "no T0 mapping"
        print(f"refused {error}".rstrip(), file=sys.stderr)
        return 3
    for field, value in pins.items():
        print(field, value)
    print("entry", system)
    return 0
