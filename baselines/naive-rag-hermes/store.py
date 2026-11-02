"""Apache-2.0: atomically replaced JSONL memories and monotonic id counter."""

import json
import os
import tempfile
from pathlib import Path


class Store:
    def __init__(self, hermes_home):
        self.path = Path(hermes_home) / "plugin-data/naive-rag/store.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.counter, self.memories = 0, {}
        if self.path.exists():
            with self.path.open(encoding="utf-8") as stream:
                self.counter = json.loads(next(stream))["counter"]
                for line in stream:
                    row = json.loads(line)
                    self.memories[row["id"]] = row["content"]

    def _write(self, memories, counter):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".store-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                rows = [{"counter": counter}, *({"id": mid, "content": content}
                                               for mid, content in memories.items())]
                for row in rows:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.memories, self.counter = memories, counter

    def add(self, content):
        counter = self.counter + 1
        mid = f"m{counter:06d}"
        self._write({**self.memories, mid: content}, counter)
        return mid

    def delete(self, memory_id):
        if memory_id not in self.memories:
            return False
        self._write({mid: text for mid, text in self.memories.items() if mid != memory_id}, self.counter)
        return True
