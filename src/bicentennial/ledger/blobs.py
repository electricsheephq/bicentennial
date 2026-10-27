"""Canonical, compressed, content-addressed blobs."""

import os
import re
import tempfile
from compression import zstd
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon


class BlobCorrupt(ValueError):
    """A blob is absent, unreadable, or does not match its address."""


class BlobStore:
    def __init__(self, root, guard):
        self.root, self.guard = Path(root), guard

    def _path(self, h):
        if not isinstance(h, str) or re.fullmatch(r"[0-9a-f]{64}", h) is None:
            raise BlobCorrupt("invalid blob address")
        return self.root / h[:2] / f"{h}.json.zst"

    def put(self, obj) -> str:
        data = self.guard.check(canon(obj))
        h = sha256(data).hexdigest()
        path = self._path(h)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
                tmp = Path(f.name)
                try:
                    f.write(zstd.compress(data))
                    f.flush()
                    os.fsync(f.fileno())
                    os.replace(tmp, path)
                finally:
                    tmp.unlink(missing_ok=True)
        return h

    def get(self, h) -> bytes:
        try:
            data = zstd.decompress(self._path(h).read_bytes())
        except (OSError, zstd.ZstdError) as error:
            raise BlobCorrupt("unreadable blob") from error
        if sha256(data).hexdigest() != h:
            raise BlobCorrupt("blob digest mismatch")
        return data
