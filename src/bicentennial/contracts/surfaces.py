"""Canonical state-surface listings; links are recorded without traversal."""

import os
import stat
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.contracts.run import validate


def tree_listing(root, volatile_paths) -> list[dict]:
    """List descendants of root, omitting exact volatile paths and subtrees.

    Volatile paths are root-relative POSIX names, not glob patterns. The root
    itself is excluded; symlink targets are opaque strings, even if dangling.
    """
    root = Path(root)
    if not stat.S_ISDIR(root.lstat().st_mode):
        raise ValueError("surface root must be a real directory")
    volatile = list(volatile_paths)
    for path in volatile:
        validate("surfaces", [{"path": path, "kind": "dir", "mode": 0}])
    rows = []

    def visit(directory):
        with os.scandir(directory) as entries:
            for entry in sorted(entries, key=lambda item: item.name):
                path = Path(entry.path).relative_to(root).as_posix()
                if any(path == v or path.startswith(v + "/") for v in volatile):
                    continue
                info = entry.stat(follow_symlinks=False)
                row = {"path": path}
                if stat.S_ISLNK(info.st_mode):
                    row.update(kind="symlink", target=os.readlink(entry.path))
                elif stat.S_ISDIR(info.st_mode):
                    row.update(kind="dir", mode=info.st_mode & 0o7777)
                elif stat.S_ISREG(info.st_mode):
                    digest = sha256()
                    with open(entry.path, "rb") as stream:
                        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                            digest.update(chunk)
                    row.update(kind="file", mode=info.st_mode & 0o7777,
                               size=info.st_size, sha256=digest.hexdigest())
                else:
                    raise ValueError(f"unsupported surface entry: {path}")
                rows.append(row)
                if row["kind"] == "dir":
                    visit(entry.path)

    visit(root)
    rows.sort(key=lambda row: row["path"])
    validate("surfaces", rows)
    return rows


def tree_hash(listing) -> str:
    """Hash the validated listing's canonical bytes."""
    validate("surfaces", listing)
    return sha256(canon(listing)).hexdigest()
