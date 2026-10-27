"""Schema-blind streaming search, including SQLite sidecars."""

import stat
from pathlib import Path

from bicentennial.sandbox.surfaces import _directory, _walk

CHUNK_SIZE = 1024 * 1024


def span_search(root, needles: list[bytes]) -> dict[bytes, list[str]]:
    """Return relative regular-file paths only; never follow symlinks."""
    root = _directory(root)
    if any(type(n) is not bytes or not n for n in needles):
        raise ValueError("needles must be nonempty bytes")
    found = {n: [] for n in needles}
    overlap = max(map(len, found), default=1) - 1
    for directory, _, files in _walk(root):
        for name in files:
            path = Path(directory) / name
            if not stat.S_ISREG(path.lstat().st_mode):
                continue
            matches, tail = set(), b""
            with path.open("rb") as stream:
                while chunk := stream.read(CHUNK_SIZE):
                    data = tail + chunk
                    matches.update(n for n in found if n in data)
                    tail = data[-overlap:] if overlap else b""
            for needle in matches:
                found[needle].append(path.relative_to(root).as_posix())
    return {n: sorted(paths) for n, paths in found.items()}
