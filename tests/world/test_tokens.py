"""Offline estimate fixtures and keyed Unicode properties (no model calls)."""

import pytest

from bicentennial.canon import canon
from bicentennial.director.wire.chat import usage_estimate
from bicentennial.keyed import uniform_int
from bicentennial.world import unit
from bicentennial.world.tokens import (
    ESTIMATOR,
    estimate_tokens,
    meets_sprint,
    sprint_floor,
)


@pytest.mark.parametrize("text,expected", [
    ("", 0), ("a", 1), ("abcd", 1), ("abcde", 2), ("é", 1), ("猫猫", 2), ("😀" * 3, 3),
])
def test_estimate_examples(text, expected):
    assert estimate_tokens(text) == expected


def test_estimate_refusals_and_identity():
    assert ESTIMATOR == {"name": "utf8-bytes-div4", "sha256": None}
    with pytest.raises(ValueError):
        estimate_tokens("\ud800")
    with pytest.raises(TypeError):
        estimate_tokens(b"a")


def test_keyed_unicode_matches_r03_byte_rule():
    for case in range(200):
        seed = f"g02-unicode-{case}"
        key = unit("life-a", "tokens", "unicode")
        size = uniform_int(seed, key, 0, "length", 0, 100)
        points = [uniform_int(seed, key, 0, f"point-{i}", 0, 0x10F7FF) for i in range(size)]
        text = "".join(chr(p if p < 0xD800 else p + 0x800) for p in points)
        assert estimate_tokens(text) == (len(text.encode("utf-8")) + 3) // 4
        # R03 sizes compact JSON. Compare the exact same JSON bytes as well.
        message = {"role": "assistant", "content": text}
        usage = usage_estimate({}, {"choices": [{"message": message}]})
        assert usage["estimated"] is True
        assert estimate_tokens(canon(message).decode()) == usage["completion_tokens"]


@pytest.mark.parametrize("window,floor", [(16_384, 20_480), (131_072, 163_840)])
def test_sprint_boundary(window, floor):
    assert sprint_floor(window) == floor
    assert estimate_tokens("a" * (4 * floor)) == floor
    assert meets_sprint(floor, window)
    assert not meets_sprint(floor - 1, window)


def test_sprint_ceiling_for_200_integer_windows():
    for case in range(200):
        window = uniform_int(f"g02-window-{case}", ("window",), 0, "size", 1, 200_000)
        floor = sprint_floor(window)
        assert 4 * (floor - 1) < 5 * window <= 4 * floor
