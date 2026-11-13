"""Output bytes captured before extracting the shared unit core."""

import json
import sys
from dataclasses import replace
from hashlib import sha256

import pytest
from test_t2lite import live_settings, runner, scenario  # noqa: F401

from bicentennial.canon import canon
from bicentennial.runner.spend import Price, Spend


def _digests(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if path.name == "receipt.json":
            receipt = json.loads(data)
            # Only these fields vary on this fake stack. Keep all other volatile fields,
            # including attempt/timing rows and token totals, to characterize partial runs.
            for field in ("wall_start_ms", "wall_end_ms", "load_milli"):
                receipt[field] = 0
            for unit in receipt["units"]:
                unit["start_ms"] = unit["end_ms"] = 0
            data = canon(receipt)
        result[path.relative_to(root).as_posix()] = sha256(data).hexdigest()
    return result


EXPECTED = {'cached': {'cache/0bd444973c2ab9f116cc791170f36cb4b42275775fb7b8675892b1a9154759f5.t2lite-floor.json': '49762fe385a1810b2543d095210217fb04e3cd027594f80ea6b1b1efb01c814a',
            'output/card.json': '9ae1bcf5e75d1e13a41ff1b3f577f79fcf2ff8c79889280864c917a8afc8406f',
            'output/custody.json': '862063402d605db8ca03662a5134564b123daf6c3e75076646080c33136126a8',
            'output/disclosures.json': 'c55bdb71cb42aa234a07dbd415c64d022d09bb2741e965960953603c46d4913d',
            'output/flips.json': 'e0bf08e3ff9782b1f1ee49657dd05b7aa31a06408bf2c3f9a93d20cde8d0b2b5',
            'output/no_memory.json': '49762fe385a1810b2543d095210217fb04e3cd027594f80ea6b1b1efb01c814a',
            'output/outcomes.json': '8de5030628e3211bbff4dfb4fcc19f079e08905992fe8fc39468b97b7e906122',
            'output/receipt.json': '0b23da4c1f0bcf6f7c7652c01339f0fc1eacb61daf1fabc9062dc32421364ff8',
            'output/repetitions.json': '3e6966ff9d1ccb6555cfaa4c389ee7dc2839b95cf3b75c2c7977bc6038e78f48',
            'output/repetitions/0/t1-g1/B0/t2lite_probes.json': 'f966e3d5725bdf907a1096f627649a623ced238e45e1ed17ab3737366e0b4097',
            'output/repetitions/0/t1-g1/B1/t2lite_probes.json': 'a195dc41e38d885dda2a085ca8e715731936cfdff08c31d64a85684a981c8206',
            'output/repetitions/0/t1-g2/B0/t2lite_probes.json': '078c5c621994218c99006ad5979c3c3b0ab8ecb36cea68412e7686d97b65ece8',
            'output/repetitions/0/t1-g2/B1/t2lite_probes.json': 'fbf79482691c6134aa7f42f302400b24558d69765ac0ad5feccfcfee47d585fe',
            'output/spend.json': '2ba978740ae96835a32fc34ef4b2de6f9f4418d97a1d3a6cdf3d6813fb2bf2ba'},
 'canary': {'output/refusal.json': '6fe83b5c08de30ce792d28758f144ad41d164a4af1438d77350e0b41c6e1e993'},
 'complete': {'cache/0bd444973c2ab9f116cc791170f36cb4b42275775fb7b8675892b1a9154759f5.t2lite-floor.json': '49762fe385a1810b2543d095210217fb04e3cd027594f80ea6b1b1efb01c814a',
              'output/card.json': '0c79ef8c58f62d13b8d02adfd2e747a24fa9f665643783aaa40cc97972f3adfa',
              'output/custody.json': '862063402d605db8ca03662a5134564b123daf6c3e75076646080c33136126a8',
              'output/disclosures.json': 'ff485e70a783d58ad4d7179aa78274607fd58ce9369410900b1d1acefb3b4d06',
              'output/no_memory.json': '49762fe385a1810b2543d095210217fb04e3cd027594f80ea6b1b1efb01c814a',
              'output/no_memory/t1-g1/B0/t2lite_probes.json': 'f966e3d5725bdf907a1096f627649a623ced238e45e1ed17ab3737366e0b4097',
              'output/no_memory/t1-g1/B1/t2lite_probes.json': 'a195dc41e38d885dda2a085ca8e715731936cfdff08c31d64a85684a981c8206',
              'output/no_memory/t1-g2/B0/t2lite_probes.json': '078c5c621994218c99006ad5979c3c3b0ab8ecb36cea68412e7686d97b65ece8',
              'output/no_memory/t1-g2/B1/t2lite_probes.json': 'fbf79482691c6134aa7f42f302400b24558d69765ac0ad5feccfcfee47d585fe',
              'output/outcomes.json': '8089e135c0a4384192a7122956a4b2a4e2ebb1830d3fa67816830bebcce69580',
              'output/receipt.json': 'e9e971031014ea353f8ce61b12367403de88a47f39f58409a4317c0550b76a18',
              'output/repetitions.json': 'db61c761a626b52d51c3847a5f7a68671da4740c96ceb32ae8840ef4437e2585',
              'output/repetitions/0/t1-g1/B0/t2lite_probes.json': 'f966e3d5725bdf907a1096f627649a623ced238e45e1ed17ab3737366e0b4097',
              'output/repetitions/0/t1-g1/B1/t2lite_probes.json': 'a195dc41e38d885dda2a085ca8e715731936cfdff08c31d64a85684a981c8206',
              'output/repetitions/0/t1-g2/B0/t2lite_probes.json': '078c5c621994218c99006ad5979c3c3b0ab8ecb36cea68412e7686d97b65ece8',
              'output/repetitions/0/t1-g2/B1/t2lite_probes.json': 'fbf79482691c6134aa7f42f302400b24558d69765ac0ad5feccfcfee47d585fe',
              'output/spend.json': '833fae63366e69451be286d98535bd4bd2c99391ca5f5f6a8e7676a5c9eec7cd'},
 'credential_scan': {'output/refusal.json': 'd7c2f8b3ca2c4b0bf9f2b36a60120596524677909670510567366523bf870d29'},
 'credential_stop': {'output/custody.json': '862063402d605db8ca03662a5134564b123daf6c3e75076646080c33136126a8',
                     'output/receipt.json': 'a6efa3130be8b4ef34cad814530eb607ca649195ede9790d502f4b6993aac494',
                     'output/refusal.json': 'd9d95e0003ac25eb2d91f7b9106159c28f8778097621c0c8173dcf33d2c4b006'},
 'gate': {'output/refusal.json': '832c9ef952d0b32daa3daae3d9bf3a9ee9ab3622580d8a9d3b4ca4768f312104'},
 'honeypot': {'output/refusal.json': '9a701d709617ef4a4af21bafbb99bdec7264c9cdb235e8dab49c57a95b54eccb'},
 'isolation': {'output/refusal.json': '4f4c73d3509b828cee875af3280c016b45ea750036f590ddba491a835edc17ea'},
 'live_stop': {'output/custody.json': '862063402d605db8ca03662a5134564b123daf6c3e75076646080c33136126a8',
               'output/receipt.json': 'a6efa3130be8b4ef34cad814530eb607ca649195ede9790d502f4b6993aac494',
               'output/refusal.json': '7e520d30c948360890420b9c35949c6b52d3bcc612bd0a3d8da20743892a7558'},
 'only_repeat': {'output/card.json': '308ff2fb34c49b290bfb21b4d2b73c3218968c58e700fbea4b2115d7863fcc0d',
                 'output/custody.json': '862063402d605db8ca03662a5134564b123daf6c3e75076646080c33136126a8',
                 'output/disclosures.json': 'ff485e70a783d58ad4d7179aa78274607fd58ce9369410900b1d1acefb3b4d06',
                 'output/no_memory.json': '49762fe385a1810b2543d095210217fb04e3cd027594f80ea6b1b1efb01c814a',
                 'output/no_memory/t1-g1/B0/t2lite_probes.json': 'f966e3d5725bdf907a1096f627649a623ced238e45e1ed17ab3737366e0b4097',
                 'output/no_memory/t1-g1/B1/t2lite_probes.json': 'a195dc41e38d885dda2a085ca8e715731936cfdff08c31d64a85684a981c8206',
                 'output/no_memory/t1-g2/B0/t2lite_probes.json': '078c5c621994218c99006ad5979c3c3b0ab8ecb36cea68412e7686d97b65ece8',
                 'output/no_memory/t1-g2/B1/t2lite_probes.json': 'fbf79482691c6134aa7f42f302400b24558d69765ac0ad5feccfcfee47d585fe',
                 'output/outcomes.json': '34446eddd3fcdafaa20a53bb76ab55cf70c231a129c5515bb5632f2b01ccfd04',
                 'output/receipt.json': 'd915f809e31fb2e9c64a0faaefca0214d876b14b9b6f56e358122921ea96552f',
                 'output/repetitions.json': 'b00b288dd79175870155af5226a211bdc37405c402c094189015e5de4003ea7c',
                 'output/repetitions/0/t1-g1/B0/t2lite_probes.json': 'f966e3d5725bdf907a1096f627649a623ced238e45e1ed17ab3737366e0b4097',
                 'output/repetitions/1/t1-g1/B0/t2lite_probes.json': 'f966e3d5725bdf907a1096f627649a623ced238e45e1ed17ab3737366e0b4097',
                 'output/spend.json': 'a5b92cc336049c08189528f7a968a4d7457160831768223f679edbfbb0f3ed6a'},
 'publication': {'output/refusal.json': '39bc7bc6d5ef6f5dd9d01db4de6c5452037b313a2dc7c2f2603b307df89aa8e1'},
 'spend_stop': {'output/custody.json': '862063402d605db8ca03662a5134564b123daf6c3e75076646080c33136126a8',
                'output/receipt.json': '5020d33f3c477251a3ea3eb72cf48064de14e2028ffac10236ca60aba16a78a3',
                'output/refusal.json': '5478d0f1454586658dae3001324e5de5ad7f39379f82fdbc4a20ca9db7ed8317'}}


@pytest.mark.parametrize("case", ["complete", "cached", "only_repeat", "canary", "honeypot",
    "isolation", "live_stop", "credential_stop", "spend_stop", "credential_scan", "publication", "gate"])
def test_output_bytes(scenario, tmp_path, monkeypatch, case):  # noqa: F811
    build = runner.build_live_stack

    def accounted_stack(spend_path, **kwargs):
        # Use the real spend file with the existing fake responder, without any transport.
        spend, stack = Spend(spend_path, 0, Price(0, 0)), build(spend_path, **kwargs)
        respond = stack.respond

        def accounted(call):
            reservation = spend.reserve(2, 1, Price(0, 0))
            reply = respond(call)
            spend.settle(reservation, {"prompt_tokens": 2, "completion_tokens": 1})
            return reply

        stack.respond = accounted
        return stack

    monkeypatch.setattr(runner, "build_live_stack", accounted_stack)
    options = {}
    if case in ("complete", "cached"):
        options["cache"] = tmp_path / "cache"
    if case == "cached":
        assert scenario.invoke("baseline", **options) == 0
        options["baseline"] = tmp_path / "baseline"
        scenario.scores["t1-g1B0"] = 0
    elif case == "only_repeat":
        options.update(only=("t1-g1", "B0", 2), repeat=2)
    elif case in ("honeypot", "publication"):
        driver = sys.modules[runner._unit.__module__]
        drive = driver.run_life

        def hit(**kw):
            return replace(drive(**kw), honeypot_hits=int(case == "honeypot"))

        monkeypatch.setattr(driver, "run_life", hit)
        if case == "publication":
            def refuse(*args, **kw):
                raise runner.t1.T1Refused("pin_mismatch", detail=("synthetic publication",))

            monkeypatch.setattr(runner, "verify", refuse)
    else:
        scenario.mode = {"isolation": "socket", "credential_stop": "credential", "spend_stop": "spend",
                         "credential_scan": "token"}.get(case, case)
    assert scenario.invoke(**options) == (0 if case in ("complete", "cached", "only_repeat") else 3)
    actual = {"output/" + k: v for k, v in _digests(scenario.out).items()}
    if options.get("cache"):
        actual.update({"cache/" + k: v for k, v in _digests(options["cache"]).items()})
    assert actual == EXPECTED.get(case), repr((case, actual))


def test_floor_then_system_stop_bytes(scenario, tmp_path, monkeypatch):  # noqa: F811
    driver = sys.modules[runner._unit.__module__]
    drive = driver.run_life

    def stop_system(**kw):
        scenario.mode = "live_stop" if kw["arm"] == "system" else None
        return drive(**kw)

    monkeypatch.setattr(driver, "run_life", stop_system)
    monkeypatch.setitem(EXPECTED, "floor_then_stop", {
        "output/custody.json": "862063402d605db8ca03662a5134564b123daf6c3e75076646080c33136126a8",
        "output/receipt.json": "f52cd6ce7f1d2e0d7724557ed4c84b1e2cd0cbceed363679faa3f0ef75337563",
        "output/refusal.json": "7e520d30c948360890420b9c35949c6b52d3bcc612bd0a3d8da20743892a7558",
    })
    test_output_bytes(scenario, tmp_path, monkeypatch, "floor_then_stop")
    assert scenario.seen == [("no_memory", 0)] * 4 + [("system", 0)]
