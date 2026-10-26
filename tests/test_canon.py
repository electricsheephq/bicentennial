from fractions import Fraction
from hashlib import sha256

import pytest

from bicentennial import __version__
from bicentennial.canon import canon, milli, sha256_canon


def test_exact_bytes():
    obj = {"z": (True, 1, False, 0, None), "a": {"é": ["雪", {"b": "c"}]}}
    expected = '{"a":{"é":["雪",{"b":"c"}]},"z":[true,1,false,0,null]}'.encode()
    assert canon(obj) == expected
    assert sha256_canon(obj) == sha256(expected).hexdigest()
    assert __version__ == "0.1.0.dev0"


def test_key_order_is_irrelevant():
    assert canon({"b": {"y": 2, "x": 1}, "a": 0}) == canon(
        {"a": 0, "b": {"x": 1, "y": 2}}
    )


@pytest.mark.parametrize("value", [1.0, float("nan"), float("inf"), -float("inf")])
def test_float_rejected_at_depth_three(value):
    with pytest.raises(TypeError):
        canon({"a": [{"b": value}]})


@pytest.mark.parametrize("value", [{1: "value"}, {True: 1}, {1.0: 1}, {"a": b"x"},
                                   {"a": {1, 2}}, Fraction(1, 2), object()])
def test_other_types_and_non_string_keys_rejected(value):
    with pytest.raises(TypeError):
        canon(value)


@pytest.mark.parametrize("value, expected", [
    (Fraction(1, 2000), 0), (Fraction(3, 2000), 2),
    (Fraction(-1, 2000), 0), (Fraction(-3, 2000), -2), (7, 7000),
])
def test_milli_half_even(value, expected):
    assert milli(value) == expected


@pytest.mark.parametrize("value", [0.5, float("nan"), True, "1"])
def test_milli_rejects_inexact_or_unsupported_types(value):
    with pytest.raises(TypeError):
        milli(value)
