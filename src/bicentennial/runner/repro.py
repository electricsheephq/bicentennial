"""Restore kept probe starts and compare their captured execution inputs."""

import json
import re
import shutil
import stat
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.repro_bundle import check_repro_bundle
from bicentennial.genres.g1_software.repo import workspace_hash
from bicentennial.runner.lock import attempt_id
from bicentennial.sandbox.surfaces import PORT_FILES, clone_tree, install_hash

CONTEXT_RECORDS = frozenset((
    "canonical_paths", "director_bindings", "attempt_identity", "resolved_route", "replay_segment",
    "clock_cadence", "compiled_probe", "workspace_inputs", "environment_inputs",
))
FIELDS = frozenset((
    "surface_hashes", "workspace_hash", "environment_hash", "sim_t_s", "probe_session_index",
    "probe_slot", "route_table_sha256", "probe_config_sha256", "replay_context",
))


class ReproRefused(ValueError):
    """A stable refusal code, without captured input values."""

    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _port_pattern(port):
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("port must be an int in 1..65535")
    # Keep install_hash's scope and digit boundary, including near misses.
    return rb"127\.0\.0\.1:(?<![0-9])" + str(port).encode() + rb"(?![0-9])"


def _escape(text):
    # Masks write {NAME} placeholders: doubling every literal brace first means no literal ever reads as one.
    return text.replace("{", "{{").replace("}", "}}")


def load_context(directory, fields):
    """Read exactly the nine retained records and verify their own canonical digests."""
    try:
        references = fields["replay_context"]
        if references.keys() != CONTEXT_RECORDS:
            raise ValueError("context records")
        records = {}
        for name, digest in references.items():
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("retained digest required")
            path = Path(directory) / "context" / f"{digest}.json"
            if path.is_symlink():
                raise ValueError("context symlink")
            value = json.loads(path.read_bytes())
            if not isinstance(value, dict) or sha256_canon(value) != digest:
                raise ValueError("context digest")
            records[name] = value
        bindings = records["director_bindings"]
        if (fields["probe_config_sha256"] != sha256_canon(bindings["probe_config"])
                or fields["route_table_sha256"] != sha256_canon(bindings["route_table"])):
            raise ValueError("context hash field")
        return records
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ReproRefused("bundle_invalid") from error


def rewrite_port(root, old, new):
    """Rewrite only regular top-level port files; never follow a symlink."""
    pattern = _port_pattern(old)
    _port_pattern(new)
    for name in PORT_FILES:
        path = Path(root) / name
        if path.exists() and stat.S_ISREG(path.lstat().st_mode):
            data = path.read_bytes()
            rewritten = re.sub(pattern, f"127.0.0.1:{new}".encode(), data)
            if rewritten != data:
                path.write_bytes(rewritten)


def foreign_port_refs(roots, old):
    """Return relative file locations containing an unrewritten director reference."""
    pattern, hits = _port_pattern(old), []
    for label, root in roots:
        root = Path(root)
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if relative not in PORT_FILES and stat.S_ISREG(path.lstat().st_mode):
                if re.search(pattern, path.read_bytes()):
                    hits.append(f"{label}/{relative}")
    return tuple(hits)


def _volatile(records):
    records = deepcopy(records)
    published = records["clock_cadence"]["published"]
    if type(published["rate"]) is not int or published["rate"] != 0:
        raise ReproRefused("starting_state_changed:clock_cadence")
    published.pop("wall_anchor", None)
    bindings = records["director_bindings"]
    port = int(bindings["run_values"]["director_port"])
    pattern = _port_pattern(port)
    bindings["run_values"]["director_port"] = "{DIRECTOR_PORT}"
    env = records["environment_inputs"]["worker_env"]
    for name, value in env.items():
        env[name] = re.sub(pattern, b"127.0.0.1:{DIRECTOR_PORT}", _escape(value).encode()).decode()
    return records


def _checkout_paths(records):
    checkout = records["director_bindings"]["probe_config"]["checkout"]
    paths = {checkout: "{CHECKOUT}"} if checkout else {}
    # worker_env constructs this one benchmark path; PYTHONPATH entries outside it stay exact.
    suffix = "/bicentennial/harness/hermes/clockshim"
    for value in records["environment_inputs"]["worker_env"].get("PYTHONPATH", "").split(":"):
        if value.endswith(suffix):
            paths[value[:-len(suffix)]] = "{BENCHMARK}"
    return paths


def _canonical_paths(records):
    paths = {v: "{CANONICAL:" + k + "}" for k, v in records["canonical_paths"].items()
             if isinstance(k, str) and isinstance(v, str) and v}
    for name, key in (("workspace_inputs", "cwd"), ("clock_cadence", "clock_path"),
                      ("environment_inputs", "envwire_root")):
        value = records[name][key]
        if isinstance(value, str):
            paths[value] = "{" + name + ":" + key + "}"
    paths[records["director_bindings"]["run_values"]["sandbox_root"]] = "{SANDBOX_ROOT}"
    return paths


def _mask_path(value, paths):
    """Mask the longest listed directory that starts the whole value; a path that only contains one stays exact."""
    for path in sorted(paths, key=len, reverse=True):
        if value == path or value.startswith(path + "/"):
            return paths[path] + _escape(value[len(path):])
    return _escape(value)


def _mask_argv(argv, paths):
    # Anything but a list of strings is compared exactly, as it was recorded.
    if not isinstance(argv, list) or not all(isinstance(arg, str) for arg in argv):
        return argv
    masked = []
    for arg in argv:
        name, equals, value = arg.partition("=")
        # An option's value after its first '=' is a path of its own; any other '=' belongs to a path.
        if arg.startswith("-") and equals:
            masked.append(_escape(name) + "=" + _mask_path(value, paths))
        else:
            masked.append(_mask_path(arg, paths))
    return masked


def compare_records(expected_fields, expected, actual_fields, actual):
    """Compare checked records, masking only volatility and the explicit relocation allowlist."""
    try:
        left, right = _volatile(expected), _volatile(actual)
        # Only the port and the wall-clock anchor may differ in an identical start: masking can explain a
        # relocation, never an identity.
        changed = sorted(name for name in CONTEXT_RECORDS if canon(left[name]) != canon(right[name]))
        reasons = set()

        def mask(a, b, key, reason):
            if key in a and key in b and isinstance(a[key], str) and isinstance(b[key], str) and a[key] != b[key]:
                reasons.add(reason)
                a[key] = b[key] = "{RELOCATED}"

        # Preserve record keys and unrecognized members: refusal remains the default.
        for key in left["canonical_paths"].keys() & right["canonical_paths"].keys():
            mask(left["canonical_paths"], right["canonical_paths"], key, "canonical_paths")
        for a, b in ((left["director_bindings"]["run_values"], right["director_bindings"]["run_values"]),):
            mask(a, b, "sandbox_root", "canonical_paths")
        for record, key in (("workspace_inputs", "cwd"), ("clock_cadence", "clock_path"),
                            ("environment_inputs", "envwire_root")):
            mask(left[record], right[record], key, "canonical_paths")
        for target, records in ((left, expected), (right, actual)):
            env = target["environment_inputs"]
            # One pass over every listed directory, so the longest one wins whichever record lists it.
            paths = _canonical_paths(records) | _checkout_paths(records)
            env["worker_argv"] = _mask_argv(env["worker_argv"], paths)
            if "PYTHONPATH" in env["worker_env"]:
                # Split the recorded value: _volatile escaped its braces, and the listed directories are raw.
                pythonpath = records["environment_inputs"]["worker_env"]["PYTHONPATH"]
                env["worker_env"]["PYTHONPATH"] = [_mask_path(p, paths) for p in pythonpath.split(":")]
        if _checkout_paths(expected) != _checkout_paths(actual):
            reasons.add("checkout")
        mask(left["director_bindings"]["probe_config"], right["director_bindings"]["probe_config"], "checkout", "checkout")
        a, b = left["environment_inputs"]["worker_env"], right["environment_inputs"]["worker_env"]
        for key in a.keys() & b.keys():
            if key in ("HERMES_HOME", "HOME", "TMPDIR", "BICENTENNIAL_CLOCK_FILE"):
                mask(a, b, key, "canonical_paths")
        # An inherited locale may be absent on one side, as well as having a different value.
        for key in list(a.keys() | b.keys()):
            if key in ("PATH", "LANG") or key.startswith("LC_"):
                if a.get(key) != b.get(key):
                    reasons.add(key)
                    a.pop(key, None)
                    b.pop(key, None)
        a, b = left["attempt_identity"], right["attempt_identity"]
        if a["lock_hash"] != b["lock_hash"]:
            for identity, fields in ((a, expected_fields), (b, actual_fields)):
                derived = attempt_id(identity["lock_hash"], "system", identity["life"], identity["branch"],
                                     fields["probe_session_index"], identity["attempt"])
                if identity["attempt_id"] != derived:
                    raise ReproRefused("starting_state_changed:attempt_identity")
            mask(a, b, "lock_hash", "lock_hash")
            mask(a, b, "attempt_id", "lock_hash")
        for name in sorted(CONTEXT_RECORDS):
            if canon(left[name]) != canon(right[name]):
                raise ReproRefused(f"starting_state_changed:{name}")
        lf, rf = deepcopy(expected_fields), deepcopy(actual_fields)
        for fields, records in ((lf, left), (rf, right)):
            fields.pop("replay_context")
            fields["probe_config_sha256"] = sha256_canon(records["director_bindings"]["probe_config"])
        for name in sorted(lf.keys() | rf.keys()):
            if name not in lf or name not in rf or canon(lf[name]) != canon(rf[name]):
                raise ReproRefused(f"starting_state_changed:{name}")
        if reasons:
            return "relocated(" + ",".join(sorted(reasons)) + ")"
        if changed:
            raise ReproRefused(f"starting_state_changed:{changed[0]}")
        return "identical"
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        if isinstance(error, ReproRefused):
            raise
        raise ReproRefused("bundle_invalid") from error


@dataclass
class Restore:
    directory: Path
    bundle: dict
    records: dict
    foreign_port_refs: tuple = field(default=(), init=False)

    @property
    def item_id(self):
        return self.bundle["identity"]["item_id"]

    @property
    def fields(self):
        return {k: self.bundle[k] for k in FIELDS}

    @property
    def surfaces(self):
        return self.records["director_bindings"]["probe_config"]["entry"]["surfaces"]

    @property
    def old_port(self):
        return int(self.records["director_bindings"]["run_values"]["director_port"])

    def check_snapshot(self):
        """Call before the first and after the last repetition to detect kept-copy changes."""
        try:
            hashes = {f"{s['root']}/{s['relative']}": install_hash(
                self.directory / "surfaces" / str(n), s["volatile_paths"], self.old_port)
                for n, s in enumerate(self.surfaces)}
            if hashes != self.bundle["surface_hashes"] or workspace_hash(self.directory / "workspace") != self.bundle["workspace_hash"]:
                raise ValueError("snapshot hashes")
        except (OSError, ValueError) as error:
            raise ReproRefused("snapshot_changed") from error

    def check_entry(self, entry):
        """Refuse before anything runs when the entry's surfaces are not the kept copy's."""
        if entry.get("surfaces") != self.surfaces:
            raise ReproRefused("starting_state_changed:director_bindings")

    def restore(self, surfaces, workspace, new_port):
        """Replace canonical trees after materialization, before the ordinary probe clones."""
        if [s for s, _ in surfaces] != self.surfaces:
            raise ReproRefused("starting_state_changed:director_bindings")
        roots = [(f"surfaces/{n}", p) for n, (_, p) in enumerate(surfaces)] + [("workspace", workspace)]
        for relative, destination in roots:
            shutil.rmtree(destination)
            clone_tree(self.directory / relative, destination)
            rewrite_port(destination, self.old_port, new_port)
        self.foreign_port_refs = foreign_port_refs(roots, self.old_port)

    def compare_run(self, run):
        """A life without a target start is a tool failure, never a counted repetition."""
        record = (run.pre_probe or {}).get(self.item_id)
        if record is None:
            raise ReproRefused("probe_not_run")
        # Re-read both sides: digest checks apply even if a caller retained this object.
        expected = load_context(self.directory, self.fields)
        actual = load_context(record.directory, record.fields)
        return compare_records(self.fields, expected, record.fields, actual)


def load_bundle(directory):
    """Load a kept snapshot-probe directory; no CLI, credentials or leases are involved."""
    directory = Path(directory)
    try:
        bundle = json.loads((directory / "bundle.json").read_bytes())
        check_repro_bundle(bundle)
        if bundle["repro_class"] != "snapshot-probe":
            raise ValueError("snapshot-probe required")
        records = load_context(directory, bundle)
        port = records["director_bindings"]["run_values"]["director_port"]
        if not isinstance(port, str):
            raise ValueError("recorded port must be a string")
        _port_pattern(int(port))
        restore = Restore(directory, bundle, records)
        # The digests can agree on a malformed entry: check the keys the snapshot check and restore read.
        if not isinstance(restore.surfaces, list) or not all(
                isinstance(s, dict) and isinstance(s.get("root"), str) and isinstance(s.get("relative"), str)
                and isinstance(s.get("volatile_paths"), list) and all(isinstance(p, str) for p in s["volatile_paths"])
                for s in restore.surfaces):
            raise ValueError("surface metadata")
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as error:
        raise ReproRefused("bundle_invalid") from error
    restore.check_snapshot()
    return restore
