"""Observe originals around a probe's complete swap/restore stack."""

from contextlib import ExitStack, contextmanager

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
    def hashes(path, native):
        rows = tree_listing(path, [])
        return {".": sha256_canon(rows), **({rel: sha256_canon([
            r for r in rows if r["path"] == rel or r["path"].startswith(rel + "/")])
            for _, rel in HERMES_FILES} if native else {})}

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
                if (surface == "workspace" and self.expected_hash is not None
                        and workspace_hash(path) != self.expected_hash):
                    self.checkpoints[:] = [cp for cp in self.checkpoints if cp != self.probe.checkpoint]
