"""Stateless, independently keyed draws for reproducible benchmark work."""

import os
from collections.abc import Sequence
from hashlib import sha256
from typing import TypeVar

from .canon import canon

T = TypeVar("T")


def assert_hashseed() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise SystemExit(70)


def draw(seed: str, unit: tuple[str, ...], attempt: int, name: str) -> int:
    return int.from_bytes(
        sha256(canon([seed, list(unit), attempt, name])).digest()[:8], "big"
    )


def uniform_int(
    seed: str, unit: tuple[str, ...], attempt: int, name: str, lo: int, hi: int,
) -> int:
    """Draw inclusively, rejecting the incomplete residue block.

    The first word uses name unchanged. Retries use name#retryN and extra
    words (for ranges wider than 64 bits) append #wordN. The attempt key
    remains unchanged, so rejection never consumes another attempt's draw.
    """
    if type(lo) is not int or type(hi) is not int:
        raise TypeError("integer bounds required")
    if lo > hi:
        raise ValueError("lo must be <= hi")
    span = hi - lo + 1
    words = max(1, ((span - 1).bit_length() + 63) // 64)
    space = 1 << (64 * words)
    limit = space - space % span
    retry = 0
    while True:
        prefix = name if retry == 0 else f"{name}#retry{retry}"
        value = 0
        for word in range(words):
            word_name = prefix if word == 0 else f"{prefix}#word{word}"
            value = (value << 64) | draw(seed, unit, attempt, word_name)
        if value < limit:
            return lo + value % span
        retry += 1


def choice(
    seed: str, unit: tuple[str, ...], attempt: int, name: str, seq: Sequence[T],
) -> T:
    if not seq:
        raise IndexError("cannot choose from an empty sequence")
    return seq[uniform_int(seed, unit, attempt, name, 0, len(seq) - 1)]


def shuffle(
    seed: str, unit: tuple[str, ...], attempt: int, name: str, seq: Sequence[T],
) -> list[T]:
    result = list(seq)
    for i in range(len(result) - 1, 0, -1):
        j = uniform_int(seed, unit, attempt, f"{name}#{i}", 0, i)
        result[i], result[j] = result[j], result[i]
    return result


def mint_id(run_key: str, counter: int) -> str:
    return "bcw-" + sha256(canon([run_key, counter])).hexdigest()[:16]
