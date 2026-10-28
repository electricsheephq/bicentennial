"""Pinned plug-in trees, isolated surfaces and observed Hermes drain (R13b)."""

import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
import tarfile
import tempfile
from hashlib import sha256
from pathlib import Path, PurePosixPath

from bicentennial.canon import canon
from bicentennial.contracts.surfaces import tree_listing
from bicentennial.harness.hermes.adapter import PinMismatch
from bicentennial.harness.hermes.config import (
    _PASSED,
    _PLUGIN,
    _PROXIES,
    PLACEHOLDER_KEY,
    hermes_config,
    worker_env,
    write_config,
)
from bicentennial.sandbox.spansearch import span_search
from bicentennial.sandbox.surfaces import (
    clone_tree,
    install_hash,
    surface_hash,
    verify_empty,
    wipe_to_fresh,
)
from bicentennial.systems.settle import settle

PROVIDERS = {"holographic": "holographic", "mem0-oss": "mem0"}
TREES = {"holographic": ("HEAD",), "mem0-oss": ("HEAD", "integrations/hermes-plugin-mem0")}
ENGINES = {}  # System -> context.engine id.
PLUGIN_DIRS = {}  # System -> install directory when it differs from the slot id.
ENABLED = frozenset()  # Systems using Hermes's general plug-in manager.
WORKER_ENV = {}  # System -> reviewed extra worker environment recipe.
# Benchmark-owned hash locks, covered by benchmark_commit.
DEPENDENCIES = {"mem0-oss": "systems/locks/mem0-oss.txt"}
MARKER = ".bicentennial-sandbox"
MEM0_THREADS = ("mem0-prefetch", "mem0-sync")


def is_plugin(name):
    return name in PROVIDERS or name in ENGINES


def plugin_dir(name):
    return PLUGIN_DIRS.get(name, PROVIDERS.get(name, ENGINES.get(name)))


def validate_maps():
    for value in (*PROVIDERS.values(), *ENGINES.values(), *PLUGIN_DIRS.values()):
        if not isinstance(value, str) or not _PLUGIN.fullmatch(value):
            raise ValueError("invalid plug-in id or directory")
    if "compressor" in ENGINES.values() or (PROVIDERS.keys() | ENGINES.keys()) - TREES.keys():
        raise ValueError("invalid engine or missing tree recipe")
    for name in WORKER_ENV:
        resolve_worker_env(name)


def resolve_worker_env(name, model_cache=None):
    extra = WORKER_ENV.get(name, {})
    reserved = set(worker_env(dict.fromkeys(("hermes_home", "home", "tmp"), Path(".")), 1, ".", None))
    for key, value in extra.items():
        if (not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in reserved | set(_PASSED) | set(_PROXIES)
                or key.startswith(("BICENTENNIAL_", "HERMES_", "PYTHON"))):
            raise ValueError("reserved worker environment name")
        if not isinstance(value, str):
            raise ValueError("worker environment value must be a string")
        if value == "{model_cache}" or value.startswith("{model_cache}/"):
            suffix = value[len("{model_cache}"):].lstrip("/")
            if (".." in suffix.split("/") or "\\" in suffix or "{" in suffix
                    or value.startswith("{model_cache}//")):
                raise ValueError("invalid model cache path")
        elif any(c in value for c in "/\\{"):
            raise ValueError("invalid worker environment value")
    return {k: v.replace("{model_cache}", str(model_cache)) if model_cache is not None else v
            for k, v in extra.items()}


def cache_digest(directory, refuse):
    try:
        rows = tree_listing(directory, [])
        if any(r["kind"] == "symlink" for r in rows):
            raise ValueError("symlink in model cache")
        return sha256(b"".join(f"{r['path']}\0{r['size']}\0{r['sha256']}\n".encode()
                              for r in rows if r["kind"] == "file")).hexdigest()
    except (OSError, ValueError):
        raise refuse("model_cache_invalid") from None


def prepare_cache(name, directory, refuse):
    extra = resolve_worker_env(name)
    needed = any("{model_cache}" in v for v in extra.values())
    if needed != (directory is not None):
        raise refuse("missing_input")
    if directory is None:
        return None, None
    digest = cache_digest(directory, refuse)
    return Path(directory).resolve(), digest


def normalise(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def validate_dependencies(repo):
    for name, value in DEPENDENCIES.items():
        path = PurePosixPath(value)
        if (name not in PROVIDERS or path.is_absolute() or ".." in path.parts or "\\" in value
                or path.parts[:2] != ("systems", "locks") or not (repo / path).is_file()):
            raise ValueError("plugin_deps_lock_invalid")


def parse_dependencies(data):
    """Read the restricted, hash-required subset of a universal requirements lock."""
    requirements, seen, pending = [], set(), ""
    for raw in data.decode("utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = re.split(r"\s+#", line, maxsplit=1)[0].rstrip()
        pending += line[:-1] + " " if line.endswith("\\") else line
        if line.endswith("\\"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)"
            r"(?:\s*;\s*(.+?))?\s+((?:--hash=sha256:[0-9a-fA-F]{64}\s*)+)", pending)
        if not match or "[" in pending:
            raise ValueError("plugin_deps_lock_invalid")
        name, version, marker, _ = match.groups()
        key = normalise(name), marker
        if key in seen:
            raise ValueError("plugin_deps_lock_invalid")
        seen.add(key)
        requirements.append([key[0], version, marker])
        pending = ""
    if pending or not requirements:
        raise ValueError("plugin_deps_lock_invalid")
    return requirements


WORKER_DISTS = r"""
import importlib.metadata as metadata
import json, re, sys
normalise = lambda name: re.sub(r"[-_.]+", "-", name).lower()
requirements = json.load(sys.stdin)
applicable, invalid = {}, False
if requirements:
    from packaging.markers import InvalidMarker, Marker, UndefinedComparison, UndefinedEnvironmentName
for name, version, marker in requirements:
    try:
        applies = marker is None or Marker(marker).evaluate()
    except (InvalidMarker, UndefinedComparison, UndefinedEnvironmentName):
        invalid = True
        continue
    if applies:
        if name in applicable and applicable[name] != version:
            invalid = True
        applicable[name] = version
installed = {}
for name in applicable:
    try:
        installed[name] = metadata.version(name)
    except metadata.PackageNotFoundError:
        installed[name] = None
dists = sorted({(normalise(d.metadata['Name']), d.version) for d in metadata.distributions()})
print(json.dumps(dict(applicable=applicable, installed=installed, dists=dists, invalid=invalid)))
"""


def worker_properties(system, checkout, repo, tier, refused, worker_argv=None):
    """Inspect only the isolated worker; injected workers have no disclosures."""
    if worker_argv is not None:
        return ()
    data, requirements = None, []
    if system in DEPENDENCIES:
        try:
            validate_dependencies(repo)
            data = (repo / DEPENDENCIES[system]).read_bytes()
            requirements = parse_dependencies(data)
        except (OSError, ValueError):
            raise refused("plugin_deps_lock_invalid") from None
    try:
        checked = subprocess.run([str(Path(checkout).resolve() / ".venv/bin/python"), "-I", "-c",
            WORKER_DISTS], input=json.dumps(requirements), capture_output=True, text=True, env={}, timeout=60)
        if checked.returncode:
            raise ValueError()
        result = json.loads(checked.stdout)
        if result.get("invalid") is True:
            raise refused("plugin_deps_lock_invalid")
        applicable, installed, dists = (result[k] for k in ("applicable", "installed", "dists"))
        if (not isinstance(applicable, dict) or not isinstance(installed, dict)
                or set(applicable) != set(installed) or not isinstance(dists, list)
                or any([name, version] not in [[n, v] for n, v, _ in requirements]
                       for name, version in applicable.items())
                or any(v is not None and not isinstance(v, str) for v in installed.values())
                or any(not isinstance(row, list) or len(row) != 2 or
                       any(not isinstance(v, str) or not v for v in row) for row in dists)):
            raise ValueError()
        dists = sorted({(normalise(n), v) for n, v in dists})
    except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, KeyError, AttributeError):
        raise refused("plugin_deps_check_failed") from None
    mismatches = sorted(n for n, v in applicable.items() if installed[n] != v)
    if mismatches:
        for name in mismatches:
            print(f"{name} locked={applicable[name]} installed={installed[name] or 'none'}", file=sys.stderr)
        raise refused("plugin_deps_missing:" + mismatches[0])
    encoded = canon(dists)
    props = [(tier + ".worker_dists", encoded.decode()),
             (tier + ".worker_dists_sha256", f"sha256:{sha256(encoded).hexdigest()} n={len(dists)}")]
    if data is not None:
        props.append((tier + ".plugin_deps", f"sha256:{sha256(data).hexdigest()} n={len(applicable)}"))
    return tuple(props)


class PluginCell:
    def __init__(self, entry, adapter):
        validate_maps()
        if not is_plugin(entry["name"]) or entry["harness"] != "hermes":
            raise ValueError("unsupported Hermes plug-in")
        self.entry, self.adapter, self.surfaces = entry, adapter, []
        paths, user = adapter.paths, Path.home().resolve()
        home, root = paths["home"].resolve(), paths["root"].resolve()
        if home.is_relative_to(user) and not home.is_relative_to(root):
            raise ValueError("HOME is not isolated inside the run root")
        roots = {"HERMES_HOME": paths["hermes_home"], "SANDBOX_HOME": paths["home"]}
        for surface in entry["surfaces"]:
            if surface["root"] not in roots:
                raise ValueError("unsupported surface root")
            base = roots[surface["root"]].resolve()
            directory = (base / surface["relative"]).resolve()
            if not directory.is_relative_to(base):
                raise ValueError("surface escapes its root")
            self.surfaces.append((surface, directory))
        self.audit_roots = [paths[k] for k in ("home", "hermes_home", "workspace", "tmp")]

    def install(self, source, *, alias, context=True) -> str:
        git = ["git", "-C", str(source)]
        recipe = TREES[self.entry["name"]]
        digest = sha256()
        with tempfile.TemporaryFile() as archive:
            with subprocess.Popen([*git, "archive", "--format=tar", *recipe],
                                  stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:
                for chunk in iter(lambda: proc.stdout.read(1 << 20), b""):
                    digest.update(chunk)
                    archive.write(chunk)
            status = subprocess.run([*git, "status", "--porcelain", "--untracked-files=no"], capture_output=True)
            if proc.returncode or digest.hexdigest() != self.entry["artifact"]["sha256"]:
                raise PinMismatch("plug-in archive differs from the pin")
            if status.returncode or status.stdout.strip():
                raise PinMismatch("plug-in checkout has tracked changes")
            home = self.adapter.paths["hermes_home"]
            target = home / "plugins" / plugin_dir(self.entry["name"])
            if target.exists():
                raise ValueError("plug-in directory exists")
            target.parent.mkdir(parents=True, exist_ok=True)
            archive.seek(0)
            with tempfile.TemporaryDirectory(dir=target.parent) as unpacked:
                with tarfile.open(fileobj=archive) as tree:
                    tree.extractall(unpacked, filter="data")
                (Path(unpacked) / (recipe[1] if len(recipe) > 1 else ".")).rename(target)
        port = int(self.adapter.director.run_values["director_port"])
        name = self.entry["name"]
        write_config(home, hermes_config(port, alias, plugin=PROVIDERS.get(name),
            context_engine=ENGINES.get(name) if context else None,
            plugins_enabled=(plugin_dir(name),) if name in ENABLED else ()))
        if self.entry["name"] == "mem0-oss":
            base = f"http://127.0.0.1:{port}/mem0/v1"
            llm = {"model": "bicentennial-extraction", "api_key": PLACEHOLDER_KEY, "openai_base_url": base,
                   "is_reasoning_model": True}
            embed = {"model": "bicentennial-embeddings", "api_key": PLACEHOLDER_KEY, "openai_base_url": base,
                     "embedding_dims": 1536}
            cfg = {"mode": "oss", "user_id": "hermes-user", "agent_id": "hermes", "rerank": False,
                   "oss": {"llm": {"provider": "openai", "config": llm},
                           "embedder": {"provider": "openai", "config": embed},
                           "vector_store": {"provider": "qdrant", "config": {
                               "path": "~/.mem0/qdrant", "collection_name": "mem0"}}}}
            pending = home / ".mem0.json.pending"
            pending.write_bytes(canon(cfg) + b"\n")
            os.replace(pending, home / "mem0.json")
            (home / ".env").write_bytes(b"MEM0_TELEMETRY=false\n")
        self.snapshots = []
        for i, (surface, directory) in enumerate(self.surfaces):
            directory.mkdir(parents=True, exist_ok=True)
            (directory / MARKER).write_bytes(b"")
            snapshot = self.adapter.paths["root"] / "fresh" / str(i)
            snapshot.parent.mkdir(exist_ok=True)
            clone_tree(directory, snapshot)
            self.snapshots.append((snapshot, surface_hash(directory, surface["volatile_paths"])))
        hashes = [{"relative": s["relative"], "root": s["root"],
                   "tree_hash": install_hash(d, s["volatile_paths"], port)} for s, d in self.surfaces]
        self.fresh_install_hash = hashes[0]["tree_hash"] if len(hashes) == 1 else sha256(canon(hashes)).hexdigest()
        self.baseline = self._listing()
        return self.surface_hash()

    def _idle(self):
        worker = getattr(self.adapter, "_worker", None)
        if worker is not None and worker.proc.poll() is None:
            raise ValueError("worker must exit before accessing surfaces")

    def checkpoint(self):
        self._idle()
        checkpoint_sqlite(d for _, d in self.surfaces)

    def surface_hash(self) -> str:
        self.checkpoint()
        hashes = [{"relative": s["relative"], "root": s["root"],
                   "tree_hash": surface_hash(d, s["volatile_paths"])} for s, d in self.surfaces]
        return hashes[0]["tree_hash"] if len(hashes) == 1 else sha256(canon(hashes)).hexdigest()

    def wipe(self):
        self._idle()
        for (surface, directory), (snapshot, digest) in zip(self.surfaces, self.snapshots, strict=True):
            wipe_to_fresh(directory, snapshot)
            verify_empty(directory, surface["volatile_paths"], digest)
        return True  # R12 writes the current route's config after this hook

    def _listing(self):
        return {f"{root.name}/{row['path']}": row for root in self.audit_roots for row in tree_listing(root, [])
                if not any((root / row["path"]).is_relative_to(d) for _, d in self.surfaces)}

    def audit(self) -> list[str]:
        current = self._listing()
        return sorted(p for p in current.keys() | self.baseline.keys() if current.get(p) != self.baseline.get(p))

    def store_contains(self, needle: bytes) -> list[str]:
        self.checkpoint()
        return sorted(f"{s['root']}/{s['relative']}/{p}" for s, d in self.surfaces
                      for p in span_search(d, [needle])[needle])

    def settle(self):
        self._idle()
        from bicentennial.harness.hermes.plugin_host import SETTLE_THREADS
        def observed():
            threads = getattr(self.adapter, "end_threads", None)
            return (isinstance(threads, tuple) and not any(t in SETTLE_THREADS[self.entry["name"]] for t in threads)
                    and self.adapter.director.control()["inflight"] == 0)
        return settle(self.entry, observed if self.entry["settle"]["kind"] == "hook" else None)


def checkpoint_sqlite(directories):
    """Truncate SQLite WALs before hashing closed surfaces."""
    for directory in directories:
        for path in directory.rglob("*"):
            if not stat.S_ISREG(path.lstat().st_mode) or not path.with_name(path.name + "-wal").exists():
                continue
            with path.open("rb") as stream:
                sqlite = stream.read(16) == b"SQLite format 3\x00"
            if sqlite:
                con = sqlite3.connect(path)
                try:
                    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                finally:
                    con.close()
