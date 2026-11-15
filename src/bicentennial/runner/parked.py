"""Observe originals around a probe's complete swap/restore stack."""

import os
import stat
from contextlib import ExitStack, contextmanager
from hashlib import file_digest

from bicentennial.audit.effects import HERMES_FILES
from bicentennial.audit.source_damage import RestoreWatch
from bicentennial.canon import sha256_canon
from bicentennial.contracts.surfaces import tree_listing
from bicentennial.genres.g1_software.repo import workspace_hash


class ParkedProbe(ExitStack):
    def __init__(self, surfaces, workspace, probe, index, evidence, checkpoints, expected_hash):
        super().__init__()
        self.probe, self.index, self.evidence = probe, index, evidence
        self.checkpoints, self.expected_hash, self.failed = checkpoints, expected_hash, set()
        self.targets = [(f"{s['root']}/{s['relative']}", p, s["root"] == "HERMES_HOME" and s["relative"] == ".")
                        for s, p in surfaces] + [("workspace", workspace, False)] if probe else []

    @staticmethod
    def observe(path, rel="."):
        """Observe one target without letting evidence errors change a session."""
        try:
            if rel == ".":
                info = path.lstat()
                if not stat.S_ISDIR(info.st_mode):
                    raise ValueError("surface root must be a real directory")
                return sha256_canon([dict(path=".", kind="dir", mode=info.st_mode & 0o7777),
                                     *tree_listing(path, [])])
            target = path
            try:
                for part in rel.split("/"):
                    if not stat.S_ISDIR(target.lstat().st_mode):
                        return sha256_canon([])
                    target /= part
                info = target.lstat()
            except FileNotFoundError:
                return sha256_canon([])
            row = {"path": rel}
            if stat.S_ISLNK(info.st_mode):
                row.update(kind="symlink", target=os.readlink(target))
            elif stat.S_ISREG(info.st_mode):
                with target.open("rb") as stream:
                    digest = file_digest(stream, "sha256").hexdigest()
                row.update(kind="file", mode=info.st_mode & 0o7777, size=info.st_size, sha256=digest)
            elif stat.S_ISDIR(info.st_mode):
                row.update(kind="dir", mode=info.st_mode & 0o7777)
                return sha256_canon([row, *(dict(r, path=rel + "/" + r["path"])
                                           for r in tree_listing(target, []))])
            else:
                return "unhashable:not_regular"
            return sha256_canon([row])
        except Exception as error:
            return "unhashable:" + type(error).__name__

    @classmethod
    def hashes(cls, path, native):
        rels = (".", *(rel for _, rel in HERMES_FILES)) if native else (".",)
        return {rel: cls.observe(path, rel) for rel in rels}

    def __enter__(self):
        self.before = {p: self.hashes(p, native) for _, p, native in self.targets}
        return super().__enter__()

    @contextmanager
    def watch(self, context, path):
        failures = []
        try:
            with RestoreWatch(context, failures):
                yield
        finally:
            self.evidence.restore_failures.extend(failures)
            if failures:
                self.failed.add(path)

    def __exit__(self, *exc):
        try:
            return super().__exit__(*exc)
        finally:  # Every restore and the workspace-replacement move have finished.
            for surface, path, native in self.targets:
                if path in self.failed:
                    continue
                after = self.hashes(path, native)
                for rel, before in self.before[path].items():
                    if before != after[rel]:
                        self.evidence.parked_receipts.append(dict(session=self.index, surface=surface,
                            path=rel, before=before, after=after[rel]))
                if surface == "workspace" and self.expected_hash is not None:
                    try:
                        differs = (after["."] != self.before[path]["."] or after["."].startswith("unhashable:")
                                   or workspace_hash(path) != self.expected_hash)
                    except Exception:
                        differs = True
                    if differs:
                        self.checkpoints[:] = [cp for cp in self.checkpoints if cp != self.probe.checkpoint]
