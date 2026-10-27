"""Validated run pins and deterministic identities for session admission."""

import re
from copy import deepcopy

from bicentennial.canon import canon, sha256_canon
from bicentennial.contracts.run import validate
from bicentennial.keyed import mint_id

_TOKEN_SEGMENTS = re.compile(r"[A-Za-z0-9_+/-]+={0,2}\.[A-Za-z0-9_+/-]+={0,2}")


class LockMismatch(ValueError):
    """The current pins differ from the run's baseline; values are never exposed."""

    code = "lock_mismatch"

    def __init__(self, fields):
        self.fields = tuple(sorted(fields))
        super().__init__(f"{self.code}: {', '.join(self.fields)}")


def build_lock(**pins) -> dict:
    """Validate every K13 pin and copy it, accepting account IDs only."""
    pool = pins.get("account_pool")
    if type(pool) is not list or any(
        type(value) is not str or not value or len(value) > 64
        or _TOKEN_SEGMENTS.search(value) for value in pool
    ):
        raise ValueError("account_pool: expected IDs only")
    validate("lock", pins)
    return deepcopy(pins)


def lock_hash(lock: dict) -> str:
    """Return the SHA-256 digest of the exact canonical lock bytes."""
    return sha256_canon(lock)


def verify_lock(expected_lock: dict, lock: dict) -> None:
    """Refuse changed pins, naming only differing top-level fields."""
    baseline = build_lock(**expected_lock)
    if lock_hash(baseline) != lock_hash(lock):
        fields = [field for field in baseline.keys() | lock.keys()
                  if field not in baseline or field not in lock
                  or canon(baseline[field]) != canon(lock[field])]
        raise LockMismatch(fields)


def attempt_id(lock_hash: str, arm: str, life: str, branch: str,
               session: int, attempt: int) -> str:
    """Mint a K10 ID keyed by the run, full unit and attempt counter."""
    if type(lock_hash) is not str or re.fullmatch(r"[0-9a-f]{64}", lock_hash) is None:
        raise ValueError("invalid lock_hash")
    if any(type(value) is not str or not value for value in (arm, life, branch)):
        raise ValueError("unit labels must be nonempty strings")
    if type(session) is not int or session < 1 or type(attempt) is not int or attempt < 0:
        raise ValueError("positive session and nonnegative attempt integers required")
    run_key = canon(["session-attempt", lock_hash, [arm, life, branch, session]]).decode("utf-8")
    return mint_id(run_key, attempt)


class SessionGate:
    """Keep a detached baseline and verify it before returning ledger identities."""

    def __init__(self, expected_lock: dict):
        self._expected_lock = build_lock(**expected_lock)

    def start_session(self, current_lock: dict, arm: str, life: str, branch: str,
                      session: int, attempt: int) -> tuple[str, str]:
        verify_lock(self._expected_lock, current_lock)
        digest = lock_hash(self._expected_lock)
        return digest, attempt_id(digest, arm, life, branch, session, attempt)
