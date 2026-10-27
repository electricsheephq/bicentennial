"""Locked spend accounting. Every amount, including usage['cost'], is micro-USD."""

import contextlib
import fcntl
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from bicentennial.canon import canon


def _uint(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("non-negative integer required")
    return value


@dataclass(frozen=True)
class Price:
    """Peak input/output rates in integer micro-dollars per million tokens."""

    input_per_million: int
    output_per_million: int

    def __post_init__(self):
        _uint(self.input_per_million)
        _uint(self.output_per_million)

    def cost(self, prompt: int, output: int) -> int:
        """Round the total upward so fractional micro-dollars cannot under-reserve."""
        numerator = (_uint(prompt) * self.input_per_million
                     + _uint(output) * self.output_per_million)
        return (numerator + 999_999) // 1_000_000


class Spend:
    """One run, one immutable cap/peak-price policy, shared across processes.

    Router usage must be normalized to integer micro-dollars in 'cost' before
    settlement. Token fallback uses prompt_tokens and completion_tokens. Only
    provably_unsent=True releases a reservation at zero without usage evidence.
    """

    def __init__(self, path, cap_microdollars: int, price: Price):
        self.path = Path(path)
        self.policy = {"cap": _uint(cap_microdollars), "price": asdict(price)}
        with self.locked():
            pass

    @contextlib.contextmanager
    def locked(self):
        with os.fdopen(os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600), "r+b") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            raw = f.read()
            b = json.loads(raw) if raw else {
                "policy": self.policy, "settled": 0, "estimated": 0,
                "open": {}, "next_id": 1, "settled_calls": 0, "refused_calls": 0,
                "max_single_call": 0,
            }
            canon(b)  # Reject inexact/corrupt amounts before any budget decision.
            _uint(b["policy"]["cap"])
            Price(**b["policy"]["price"])
            if b["policy"] != self.policy:
                raise ValueError("shared spend policy mismatch")
            for key in ("settled", "estimated", "next_id", "settled_calls",
                        "refused_calls", "max_single_call"):
                _uint(b[key])
            if b["next_id"] < 1 or not isinstance(b["open"], dict):
                raise ValueError("invalid reservation state")
            for rid, cost in b["open"].items():
                if not rid.isdecimal() or not 0 < int(rid) < b["next_id"]:
                    raise ValueError("invalid reservation id")
                _uint(cost)
            yield b
            encoded = canon(b)
            f.seek(0)
            f.write(encoded)
            f.truncate()
            f.flush()
            os.fsync(f.fileno())

    def reserve(self, prompt_tokens_estimate: int, max_output_tokens: int,
                price: Price) -> int | None:
        cost = price.cost(prompt_tokens_estimate, max_output_tokens)
        with self.locked() as b:
            if asdict(price) != b["policy"]["price"]:
                raise ValueError("shared spend policy mismatch")
            if b["settled"] + sum(b["open"].values()) + cost > b["policy"]["cap"]:
                b["refused_calls"] += 1
                return None
            rid = b["next_id"]
            b["next_id"] += 1
            b["open"][str(rid)] = cost
            return rid

    def settle(self, rid: int, usage: dict, *, provably_unsent: bool = False):
        """Return (charged micro-dollars, estimated, reservation exceeded)."""
        _uint(rid)
        if type(provably_unsent) is not bool:
            raise ValueError("provably_unsent must be a boolean")
        with self.locked() as b:
            reserved = b["open"][str(rid)]
            estimated = usage.get("cost") is None
            if provably_unsent:
                if usage:
                    raise ValueError("unsent settlement cannot contain usage")
                cost, estimated = 0, False
            elif not estimated:
                cost = _uint(usage["cost"])
            elif all(k in usage for k in ("prompt_tokens", "completion_tokens")):
                cost = Price(**b["policy"]["price"]).cost(
                    usage["prompt_tokens"], usage["completion_tokens"],
                )
            else:
                cost = reserved
            del b["open"][str(rid)]
            b["settled"] += cost
            b["estimated"] += cost if estimated else 0
            b["settled_calls"] += 1
            b["max_single_call"] = max(b["max_single_call"], cost)
            return cost, estimated, cost > reserved
