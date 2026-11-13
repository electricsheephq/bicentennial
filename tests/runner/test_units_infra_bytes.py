"""Retry output bytes captured before changing unit execution."""

from test_t2lite import live_settings, scenario  # noqa: F401
from test_units_characterization import _digests

from bicentennial.runner import units
from bicentennial.runner.hermes_score import Infra

EXPECTED = {'output/card.json': '181d7ba04f115f30134281b415e7f7d2c76999760e70ee0d4b95638f601abaff',
 'output/custody.json': '862063402d605db8ca03662a5134564b123daf6c3e75076646080c33136126a8',
 'output/disclosures.json': 'ff485e70a783d58ad4d7179aa78274607fd58ce9369410900b1d1acefb3b4d06',
 'output/no_memory.json': '724d5fe8423821d0ae9d2a41e6f28354c8ce7ae7532605ddfd5c8b815d8dd620',
 'output/no_memory/t1-g1/B0/t2lite_probes.json': '86bee9ba464cfa8ba1716480c22eb870aca710fcf321bcf815b01d27579a1f98',
 'output/no_memory/t1-g1/B1/t2lite_probes.json': '99d7b92d696c238e84eb2aa9765a41882b1339ef1b765dca5c5b9121684e8257',
 'output/no_memory/t1-g2/B0/t2lite_probes.json': 'e5841ee0d3c6e7d68089eaebe377477256d70829866d1fec4072e2bcd60dc38c',
 'output/no_memory/t1-g2/B1/t2lite_probes.json': 'aa6916d5c5e923c97eb874e01cf0a8b81b1725f6669abc58ddfd130b9bf20efa',
 'output/outcomes.json': '1ff879eed343c1b8d6b3c9345a689c0037642f29eec78fc070a2027786606ad6',
 'output/receipt.json': 'd5abe6bc48fcb2ec1ffbe08e459655bdbc05ff88ede3897f52553ce734d2d006',
 'output/repetitions.json': '060f0a35d86067533b34ba579b513ddef9f099001b52d31bc1b8c5baeac682db',
 'output/repetitions/0/t1-g1/B0/t2lite_probes.json': '86bee9ba464cfa8ba1716480c22eb870aca710fcf321bcf815b01d27579a1f98',
 'output/repetitions/0/t1-g1/B1/t2lite_probes.json': '99d7b92d696c238e84eb2aa9765a41882b1339ef1b765dca5c5b9121684e8257',
 'output/repetitions/0/t1-g2/B0/t2lite_probes.json': 'e5841ee0d3c6e7d68089eaebe377477256d70829866d1fec4072e2bcd60dc38c',
 'output/repetitions/0/t1-g2/B1/t2lite_probes.json': 'aa6916d5c5e923c97eb874e01cf0a8b81b1725f6669abc58ddfd130b9bf20efa'}


def test_infra_retry_bytes_and_floor_gate(scenario, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(units, "score_item", lambda *args, **kw: Infra("synthetic"))
    cache = tmp_path / "cache"
    assert scenario.invoke(cache=cache) == 0
    assert scenario.seen == [(arm, attempt) for arm in ("no_memory", "system")
                             for _ in range(4) for attempt in range(3)]
    # All replies are live 200s; scorer-only Infra must still prohibit caching.
    assert not list(cache.glob("*"))
    actual = {"output/" + k: v for k, v in _digests(scenario.out).items()}
    actual.update({"cache/" + k: v for k, v in _digests(cache).items()})
    assert actual == EXPECTED, repr(actual)
