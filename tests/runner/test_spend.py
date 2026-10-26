import json
from unittest.mock import Mock

import pytest

from bicentennial.runner import spend
from bicentennial.runner.spend import Price, Spend

PRICE = Price(200_000_000, 200_000_000)


def read(path):
    return json.loads(path.read_bytes())


def test_cap_open_reservations_settlement_and_ambiguity(tmp_path):
    path = tmp_path / "spend.json"
    ledger = Spend(path, 1_000, PRICE)
    a, b = ledger.reserve(1, 1, PRICE), ledger.reserve(1, 1, PRICE)
    assert (a, b) == (1, 2)
    assert ledger.reserve(1, 1, PRICE) is None
    assert read(path)["open"] == {"1": 400, "2": 400}
    assert ledger.settle(a, {"cost": 100}) == (100, False, False)
    c = ledger.reserve(1, 1, PRICE)
    assert c == 3
    assert ledger.settle(b, {}) == (400, True, False)
    assert read(path)["settled"] == 500
    assert read(path)["open"] == {"3": 400}
    assert ledger.reserve(1, 1, PRICE) is None


def test_fake_paid_upstream_never_receives_request_after_cap(tmp_path):
    ledger = Spend(tmp_path / "spend.json", 1_000, PRICE)
    assert ledger.reserve(1, 1, PRICE) == 1
    assert ledger.reserve(1, 1, PRICE) == 2
    upstream = Mock()

    def send():
        rid = ledger.reserve(1, 1, PRICE)
        if rid is not None:
            upstream(rid)

    send()
    upstream.assert_not_called()


def test_token_fallback_reserved_prices_and_router_precedence(tmp_path):
    ledger = Spend(tmp_path / "spend.json", 1_000, PRICE)
    rid = ledger.reserve(1, 1, PRICE)
    assert ledger.settle(rid, {"prompt_tokens": 1, "completion_tokens": 0}) == (200, True, False)
    rid = ledger.reserve(1, 1, PRICE)
    assert ledger.settle(rid, {"cost": 100, "prompt_tokens": 100}) == (100, False, False)
    rid = ledger.reserve(1, 1, PRICE)
    assert ledger.settle(rid, {"cost": None, "prompt_tokens": 0}) == (400, True, False)


def test_only_provably_unsent_releases_without_usage(tmp_path):
    ledger = Spend(tmp_path / "spend.json", 1_000, PRICE)
    rid = ledger.reserve(1, 1, PRICE)
    assert ledger.settle(rid, {"refused": True}) == (400, True, False)
    rid = ledger.reserve(1, 1, PRICE)
    assert ledger.settle(rid, {}, provably_unsent=True) == (0, False, False)
    assert read(ledger.path)["settled"] == 400


def test_overage_is_charged_and_blocks_further_spend(tmp_path):
    ledger = Spend(tmp_path / "spend.json", 1_000, PRICE)
    rid = ledger.reserve(1, 1, PRICE)
    assert ledger.settle(rid, {"cost": 1_001}) == (1_001, False, True)
    assert ledger.reserve(1, 1, PRICE) is None


def test_reservation_ids_persist_across_handles(tmp_path):
    path = tmp_path / "spend.json"
    first, second = Spend(path, 1_000, PRICE), Spend(path, 1_000, PRICE)
    assert first.reserve(1, 1, PRICE) == 1
    assert second.reserve(1, 1, PRICE) == 2
    second.settle(1, {}, provably_unsent=True)
    assert Spend(path, 1_000, PRICE).reserve(1, 1, PRICE) == 3


@pytest.mark.parametrize("cap,price", [(999, PRICE), (1_000, Price(1, 2))])
def test_constructor_policy_mismatch_fails(tmp_path, cap, price):
    path = tmp_path / "spend.json"
    Spend(path, 1_000, PRICE)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="policy mismatch"):
        Spend(path, cap, price)
    assert path.read_bytes() == before


def test_reservation_price_mismatch_fails_without_write(tmp_path):
    ledger = Spend(tmp_path / "spend.json", 1_000, PRICE)
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError, match="policy mismatch"):
        ledger.reserve(1, 1, Price(1, 2))
    assert ledger.path.read_bytes() == before


@pytest.mark.parametrize("usage,kwargs", [
    ({"cost": -1}, {}), ({"cost": 1.0}, {}), ({"cost": True}, {}),
    ({"prompt_tokens": 1.0, "completion_tokens": 1}, {}),
    ({"cost": 100}, {"provably_unsent": True}), ({}, {"provably_unsent": 1}),
])
def test_invalid_settlement_leaves_reservation_intact(tmp_path, usage, kwargs):
    ledger = Spend(tmp_path / "spend.json", 1_000, PRICE)
    rid = ledger.reserve(1, 1, PRICE)
    before = ledger.path.read_bytes()
    with pytest.raises(ValueError):
        ledger.settle(rid, usage, **kwargs)
    assert ledger.path.read_bytes() == before


def test_double_or_unknown_settlement_fails(tmp_path):
    ledger = Spend(tmp_path / "spend.json", 1_000, PRICE)
    rid = ledger.reserve(1, 1, PRICE)
    ledger.settle(rid, {"cost": 0})
    with pytest.raises(KeyError):
        ledger.settle(rid, {})
    with pytest.raises(KeyError):
        ledger.settle(999, {})


@pytest.mark.parametrize("bad", [-1, True, 0.5])
def test_invalid_cap_prices_and_tokens_rejected(tmp_path, bad):
    with pytest.raises(ValueError):
        Spend(tmp_path / "bad.json", bad, PRICE)
    with pytest.raises(ValueError):
        Price(bad, 0)
    ledger = Spend(tmp_path / "spend.json", 1_000, PRICE)
    with pytest.raises(ValueError):
        ledger.reserve(bad, 1, PRICE)
    with pytest.raises(ValueError):
        ledger.reserve(1, bad, PRICE)


def test_microdollar_rounding_and_exact_cap(tmp_path):
    price = Price(1, 1)
    assert price.cost(1, 1) == 1
    ledger = Spend(tmp_path / "spend.json", 2, price)
    assert ledger.reserve(1_000_000, 1_000_000, price) == 1
    assert ledger.reserve(1, 0, price) is None


def test_no_floats_anywhere_in_file(tmp_path):
    path = tmp_path / "spend.json"
    ledger = Spend(path, 1_000, PRICE)
    ledger.settle(ledger.reserve(1, 1, PRICE), {"cost": 100})
    ledger.reserve(1, 1, PRICE)

    def walk(value):
        assert not isinstance(value, float)
        if isinstance(value, dict):
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(read(path))
    assert path.read_bytes() == spend.canon(read(path))


def test_each_operation_locks_and_fsyncs(tmp_path, monkeypatch):
    lock = Mock(wraps=spend.fcntl.flock)
    sync = Mock(wraps=spend.os.fsync)
    monkeypatch.setattr(spend.fcntl, "flock", lock)
    monkeypatch.setattr(spend.os, "fsync", sync)
    ledger = Spend(tmp_path / "spend.json", 400, PRICE)
    rid = ledger.reserve(1, 1, PRICE)
    assert ledger.reserve(1, 1, PRICE) is None
    ledger.settle(rid, {})
    assert lock.call_count == sync.call_count == 4
    assert all(call.args[1] == spend.fcntl.LOCK_EX for call in lock.call_args_list)


@pytest.mark.parametrize("field,value", [("settled", -1), ("settled", 1.0),
                                        ("next_id", 0), ("open", {"1": -400})])
def test_corrupt_state_fails_closed(tmp_path, field, value):
    ledger = Spend(tmp_path / "spend.json", 1_000, PRICE)
    state = read(ledger.path)
    state[field] = value
    ledger.path.write_text(json.dumps(state))
    before = ledger.path.read_bytes()
    with pytest.raises((TypeError, ValueError)):
        ledger.reserve(1, 1, PRICE)
    assert ledger.path.read_bytes() == before
