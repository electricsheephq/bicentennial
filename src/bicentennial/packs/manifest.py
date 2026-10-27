"""Byte identities and schema-derived labels for sealed packs."""

import json
import stat
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import sha256_canon
from bicentennial.contracts.run import SCHEMAS


class PinnedArtifactChanged(ValueError):
    code = "pinned_artifact_changed"

    def __init__(self, fields):
        self.fields = tuple(sorted(fields))
        super().__init__(f"{self.code}: {', '.join(self.fields)}")


def file_sha256(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def file_manifest(root):
    """Inventory regular files, refusing links and special filesystem objects."""
    root = Path(root)
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise ValueError("tree_root")
    result = {}
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        mode = path.lstat().st_mode
        rel = path.relative_to(root).as_posix()
        if stat.S_ISREG(mode):
            result[rel] = dict(size=path.stat().st_size, sha256=file_sha256(path))
        elif not stat.S_ISDIR(mode):
            raise ValueError(rel)
    return result


def tree_sha256(root):
    files = file_manifest(root)
    return sha256_canon([[rel, files[rel]["size"], files[rel]["sha256"]] for rel in sorted(files)])


def labels(tier):
    props = json.loads((SCHEMAS / "card_ring0.schema.json").read_bytes())["properties"]["labels"]["properties"]
    return {k: props[k]["enum"][0] for k in sorted(props) if k != "scripted_model" or tier == "T1"}


def boundary_hashes(life, cuts):
    return {name: sha256_canon({life: {cut.branch: {
        str(s["index"]): s["expected_state"][key] for s in cut.sessions}
        for cut in sorted(cuts, key=lambda c: c.branch)}})
        for name, key in (("environment_boundary_hash", "env_state_hash"),
                          ("repository_boundary_hash", "repo_tree_hash"))}


def leaks(files, needles):
    return [(rel, kind) for rel in sorted(files) for kind in sorted(needles)
            if any(needle in files[rel] for needle in sorted(needles[kind]))]
