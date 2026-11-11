"""Live control arms for T2: one probe-only arm, with a pinned control's text placed in the probe turn."""

import json
from hashlib import sha256

from test_t2 import t2_scenario  # noqa: F401
from test_t2lite import live_settings, scenario  # noqa: F401

from bicentennial.canon import canon


def _digests(out):
    """Every file a run writes, with only its wall-clock and monotonic timing fields zeroed."""
    result = {}
    for path in sorted(out.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if path.suffix == ".json":
            value = json.loads(data)
            def zero(obj):
                if isinstance(obj, dict):
                    return {k: 0 if k in TIMING else zero(v) for k, v in obj.items()}
                if isinstance(obj, list):
                    return [zero(v) for v in obj]
                return obj
            data = canon(zero(value))
        result[path.relative_to(out).as_posix()] = sha256(data).hexdigest()
    return result


TIMING = {"wall_start_ms", "wall_end_ms", "load_milli", "start_ms", "end_ms", "t_start_ms", "t_end_ms",
          "pre_probe_ms", "keep_ms", "latency_ms", "runtime_by_role", "arm_time", "t_ms"}


# Captured on main 5e09bbe, before control arms existed: a T2 fixture run without a control arm.
BASE_DIGESTS = {
    "card.json": "9b91b3deeacbc197a99ce34260dc4d28ea6d2bed7ab4e09ca63a47a254872ca7",
    "custody.json": "862063402d605db8ca03662a5134564b123daf6c3e75076646080c33136126a8",
    "disclosures.json": "6ad998c00551198376590a7d8cc613354e089213d2a4b3a1931bd0801e76543f",
    "kept/index.json": "5b59eae9a6b8274f8ed0c10d55ac7d8628dd048eeccd52a6b142c2fede1286dc",
    "kept/t1-g1/B0/t1-g1-shared/bundle.json": "6206c1011972b02f22995a0439dc0dbabbaa1854ae9e469d7d9a9e9352f93d8a",
    "kept/t1-g1/B0/t1-g1-shared/surfaces/0/state": "c81c3c7eb75c5cd6d79f8b690177d08de6f7bba5e5755abb4cd39d0504b66316",
    "kept/t1-g1/B1/t1-g1-shared/bundle.json": "a6e1dcb0703620216014943564ed90e85a857b633ce12b6bbaa6c11cdfedc34a",
    "kept/t1-g1/B1/t1-g1-shared/surfaces/0/state": "c81c3c7eb75c5cd6d79f8b690177d08de6f7bba5e5755abb4cd39d0504b66316",
    "no_memory.json": "6ca9132126b57f05845ed90385aa12f23ce8408a0d776d826228bb33ddbbc4b9",
    "no_memory/t1-g1/B0/t2lite_probes.json": "e41f92e60f5a7607de3cafb8effdcbcba4ad19b737a19cc64ee5c7b56c42f214",
    "no_memory/t1-g1/B1/t2lite_probes.json": "e41f92e60f5a7607de3cafb8effdcbcba4ad19b737a19cc64ee5c7b56c42f214",
    "no_memory/t1-g2/B0/t2lite_probes.json": "02cc16ac52b08fc5b4a4a409f28a743d70c1292f7e236cd55c46679a3e67114d",
    "no_memory/t1-g2/B1/t2lite_probes.json": "02cc16ac52b08fc5b4a4a409f28a743d70c1292f7e236cd55c46679a3e67114d",
    "outcomes.json": "504e3c271052e0496079f182d79c448da4160c4a95d135c08af4e177af6b0cf0",
    "receipt.json": "f8823d658a4bae7d8b3abf12eaa6429d9f7325eaaf7d9a356158840fb2c97006",
    "receipts/no_memory.json": "ec2d5472054ac717a64ff80f2169083206e4b75503b93b852bbb4955d4f7d86a",
    "receipts/system.json": "d5a65a0c156b33d2633dba32af5d4b23629d4ac63d62685287e5e973d8f96ea7",
    "spend.json": "d5487556beab2972871ade7dd07e3fa048fb1964cc65bbee635a95e5793849ea",
    "system/t1-g1/B0/t2lite_probes.json": "e41f92e60f5a7607de3cafb8effdcbcba4ad19b737a19cc64ee5c7b56c42f214",
    "system/t1-g1/B1/t2lite_probes.json": "e41f92e60f5a7607de3cafb8effdcbcba4ad19b737a19cc64ee5c7b56c42f214",
    "system/t1-g2/B0/t2lite_probes.json": "8f8cf8b93836aeede6d5523917ef4905d05850a2ec6f31f1e025f0cae6c3d8c7",
    "system/t1-g2/B1/t2lite_probes.json": "8f8cf8b93836aeede6d5523917ef4905d05850a2ec6f31f1e025f0cae6c3d8c7",
    "units.json": "edef413e1537f926db2dcc50bad095d3a0d158a7aad2de4923848561d59fe237",
}


def test_f_run_without_a_control_arm_keeps_base_bytes(t2_scenario, tmp_path):
    # Acceptance F: with no control arm requested, a T2 fixture run writes the bytes it wrote before control arms
    # existed, for every file, and a floor cache entry is still read and written as before.
    s = t2_scenario
    assert s.invoke(slots=1) == 0
    assert _digests(s.out) == BASE_DIGESTS
