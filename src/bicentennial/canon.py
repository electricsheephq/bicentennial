"""Canonical JSON bytes shared by generation, execution and scoring."""

import json
from fractions import Fraction
from hashlib import sha256


def _validate(obj: object) -> None:
    kind = type(obj)
    if kind is dict:
        for key, value in obj.items():
            if type(key) is not str:
                raise TypeError("canonical JSON requires str keys")
            _validate(value)
    elif kind in (list, tuple):
        for value in obj:
            _validate(value)
    elif kind not in (str, int, bool, type(None)):
        raise TypeError(f"unsupported canonical JSON type: {kind.__name__}")


def canon(obj: object) -> bytes:
    """Encode the supported JSON types, rejecting floats at every depth."""
    _validate(obj)
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def milli(x: int | Fraction) -> int:
    """Round an exact value to thousandths with ties to even."""
    if type(x) is not int and not isinstance(x, Fraction):
        raise TypeError("milli requires int or Fraction")
    return round(x * 1000)


def sha256_canon(obj: object) -> str:
    """Return the hexadecimal SHA-256 digest of canonical bytes."""
    return sha256(canon(obj)).hexdigest()
