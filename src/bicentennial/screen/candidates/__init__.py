"""Unregistered candidate roster: one independently hashed module per card."""

from dataclasses import fields
from importlib import import_module

from bicentennial.items.editions import BY_REF, EDITIONS, _swap

CANDIDATES = {}
for _tid, _cards, _cls in (("drift-config", ("K1", "K3", "K4"), "DriftActionV3"),
                           ("drift-quote", ("K1", "K3"), "DriftQuoteV3"),
                           ("drift-chain-fault", ("K1", "K3"), "DriftChainV3")):
    _v2 = BY_REF[_tid + "-v2"]
    for _card in _cards:
        _id = _tid + "-" + _card
        _type = getattr(import_module("." + _id.lower().replace("-", "_"), __name__), _cls)
        CANDIDATES[_id] = tuple(_type(**{f.name: getattr(_v2, f.name) for f in fields(_v2)} | dict(
            version=3, variant=v, decision_tables=tuple(dict(t, table_id=t["table_id"].removesuffix("-v2") + "-v3")
                                                      for t in _v2.decision_tables))) for v in range(4))


def roster(card, variant):
    if card not in CANDIDATES or type(variant) is not int or variant not in range(4):
        raise ValueError("screening candidate")
    return dict(EDITIONS[2], G1=_swap(EDITIONS[2]["G1"], (CANDIDATES[card][variant],)))
