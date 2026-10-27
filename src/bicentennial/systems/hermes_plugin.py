"""Pinned plug-in trees, isolated surfaces and observed Hermes drain (R13b)."""

import os
import sqlite3
import stat
import subprocess
import tarfile
import tempfile
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.contracts.surfaces import tree_listing
from bicentennial.harness.hermes.adapter import PinMismatch
from bicentennial.harness.hermes.config import (
    PLACEHOLDER_KEY,
    hermes_config,
    write_config,
)
from bicentennial.sandbox.spansearch import span_search
from bicentennial.sandbox.surfaces import (
    clone_tree,
    surface_hash,
    verify_empty,
    wipe_to_fresh,
)
from bicentennial.systems.settle import settle

PROVIDERS = {"holographic": "holographic", "mem0-oss": "mem0"}
TREES = {"holographic": ("HEAD",), "mem0-oss": ("HEAD", "integrations/hermes-plugin-mem0")}
MARKER = ".bicentennial-sandbox"
MEM0_THREADS = ("mem0-prefetch", "mem0-sync")


class PluginCell:
    def __init__(self, entry, adapter):
        if entry["name"] not in PROVIDERS or entry["harness"] != "hermes":
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

    def install(self, source, *, alias) -> str:
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
            target = home / "plugins" / PROVIDERS[self.entry["name"]]
            if target.exists():
                raise ValueError("plug-in directory exists")
            target.parent.mkdir(parents=True, exist_ok=True)
            archive.seek(0)
            with tempfile.TemporaryDirectory(dir=target.parent) as unpacked:
                with tarfile.open(fileobj=archive) as tree:
                    tree.extractall(unpacked, filter="data")
                (Path(unpacked) / (recipe[1] if len(recipe) > 1 else ".")).rename(target)
        port = int(self.adapter.director.run_values["director_port"])
        write_config(home, hermes_config(port, alias, plugin=PROVIDERS[self.entry["name"]]))
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
        self.baseline = self._listing()
        return self.surface_hash()

    def _idle(self):
        worker = getattr(self.adapter, "_worker", None)
        if worker is not None and worker.proc.poll() is None:
            raise ValueError("worker must exit before accessing surfaces")

    def checkpoint(self):
        self._idle()
        for _, directory in self.surfaces:
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
        def observed():
            threads = getattr(self.adapter, "end_threads", None)
            return (isinstance(threads, tuple) and not any(t in MEM0_THREADS for t in threads)
                    and self.adapter.director.control()["inflight"] == 0)
        return settle(self.entry, observed if self.entry["settle"]["kind"] == "hook" else None)
