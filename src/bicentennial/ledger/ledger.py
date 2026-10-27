"""Single-writer durable ledger; resume refuses torn or broken chains."""

import fcntl
import os
import re
import threading
from hashlib import sha256
from pathlib import Path

from bicentennial.canon import canon
from bicentennial.contracts.run import validate

from .blobs import BlobStore
from .verify import _scan


class LedgerBusy(RuntimeError):
    """Another writer holds the ledger."""


class TornTail(ValueError):
    """The final record lacks its newline."""


class ChainBroken(ValueError):
    """Existing ledger bytes fail chain verification."""


class Ledger:
    def __init__(self, root, guard, *, lock_hash: str, attempt_id: str):
        if not isinstance(lock_hash, str) or re.fullmatch(r"[0-9a-f]{64}", lock_hash) is None:
            raise ValueError("invalid lock_hash")
        if not isinstance(attempt_id, str) or not attempt_id or "\n" in attempt_id:
            raise ValueError("invalid attempt_id")
        self.root, self.guard = Path(root), guard
        self.lock_hash, self.attempt_id = lock_hash, attempt_id
        self._lock = threading.Lock()
        self.root.mkdir(parents=True, exist_ok=True)
        self._file = (self.root / "ledger.jsonl").open("ab")
        try:
            try:
                fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise LedgerBusy("ledger busy") from None
            counts, records, self._prev = _scan(self.root / "ledger.jsonl")
            if counts["truncated_tail"]:
                raise TornTail("torn ledger tail")
            if counts["chain_breaks"]:
                raise ChainBroken("broken ledger chain")
            self._seq = len(records)
        except BaseException:
            self._file.close()
            raise
        self._store = BlobStore(self.root / "blobs", guard)

    def append(self, rec: dict) -> dict:
        with self._lock:
            if self._file.closed:
                raise ValueError("ledger closed")
            if {"seq", "prev_hash", "lock_hash", "attempt_id", "hash"} & rec.keys():
                raise ValueError("caller supplied ledger-owned fields")
            if not isinstance(rec.get("type"), str):
                raise ValueError("record requires a string type")
            rec = dict(rec, seq=self._seq + 1, prev_hash=self._prev,
                       lock_hash=self.lock_hash, attempt_id=self.attempt_id)
            rec["hash"] = sha256(self._prev.encode() + canon(rec)).hexdigest()
            # The guard runs first: a schema error names unexpected keys, and a key can hold a credential.
            line = self.guard.check(canon(rec) + b"\n")
            if rec["type"] == "request":
                validate("ledger-record", rec)
            try:
                self._file.write(line)
                self._file.flush()
                os.fsync(self._file.fileno())
            except BaseException:
                # The bytes may be on disk; only a reopen rescans the chain and its tail.
                self._file.close()
                raise
            self._seq, self._prev = rec["seq"], rec["hash"]
            return rec

    def blob(self, obj) -> str:
        return self._store.put(obj)

    def close(self):
        with self._lock:
            self._file.close()
