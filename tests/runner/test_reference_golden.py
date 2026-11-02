"""Pin published reference T0 outcomes on the whole-run fixture plus an unequal twin.

Regenerate with:
    PYTHONHASHSEED=0 BICENTENNIAL_REGEN_GOLDEN=1 PYTHONPATH=src pytest -q \
        tests/runner/test_reference_golden.py::test_reference_t0_golden

A regeneration run rewrites the file and skips, so it never reports a pass; review the diff.
A PR changing the golden file must explain why in its body.
"""

import json
import os
import runpy
from dataclasses import replace
from pathlib import Path

import pytest

from bicentennial.canon import canon
from bicentennial.items.templates.g2.keep_forget import KeepForget

ROOT = Path(__file__).resolve().parents[2]
GOLDEN = ROOT / "tests/fixtures/reference_t0.json"
shared = runpy.run_path(str(Path(__file__).with_name("test_t0.py")))
installed, synthetic_egress = (shared[k] for k in ("installed", "synthetic_egress"))
compare = runpy.run_path(str(ROOT / "scripts/compare_reference_t0.py"))


@pytest.fixture(scope="module")
def extra_rows():
    # With no word overlap, restraint passes but the action twin omits: 1000 vs 0.
    # Adapt only this additional row's input; retrieval and scoring stay untouched.
    original = KeepForget.instances

    def instances(self, db, schedule):
        values = original(self, db, schedule)
        return (tuple(replace(value, prompt="calibration_probe") for value in values)
                if schedule.seed == "2" else values)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(KeepForget, "instances", instances)
        yield ["g2-keep-forget-inv-1"]


def published(out):
    result = {}
    for path in sorted((out / "pack").rglob("card.json")):
        card = json.loads(path.read_bytes())
        assert card["system"] == "reference_store" and card["tier"] == "T0"
        result[path.parent.relative_to(out).as_posix()] = {
            "aggregates": sorted(card["aggregates"], key=lambda row: (row["stage"], row["track"])),
            "items": {item["item_id"]: {key: item[key] for key in (
                "base_verdict", "score_milli", "failure_class", "stage", "stage_attribution")}
                for item in sorted(card["items"], key=lambda item: item["item_id"])},
        }
    assert result
    return result


def test_reference_t0_golden(installed, tmp_path):
    out = tmp_path / "out"
    code = shared["run"](installed, out)
    actual = published(out)
    if os.environ.get("BICENTENNIAL_REGEN_GOLDEN") == "1":
        assert code == 0, "Only regenerate a successful reference run"
        GOLDEN.write_bytes(canon(actual))
        pytest.skip("golden regenerated; review the diff")
    golden = json.loads(GOLDEN.read_bytes())
    changes = list(compare["differences"](golden, actual))
    if changes:
        pytest.fail("reference T0 changed (pack/items/item/field: golden -> actual):\n" + "\n".join(changes))
    assert code == 0
