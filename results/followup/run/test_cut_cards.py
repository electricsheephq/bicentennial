"""Exercise the standalone cutter in isolated Python, with invented card entries."""

import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

SCRIPT = Path(__file__).with_name("cut_cards.py")


def canon(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


@pytest.mark.parametrize("fault", (None, "noncanonical", "missing", "duplicate", "substitute", "pack"))
def test_isolated_cutter(tmp_path, fault):
    keys = [dict(life=f"invented-life-{n // 5}", branch=f"B{n % 2}", item_id=f"invented-item-{n}") for n in range(50)]
    keys[1]["item_id"] = keys[0]["item_id"]
    tasks = dict(header=dict(pack="A"), rows=keys[:40], descriptive=keys[40:])
    frozen = tmp_path / "tasks.json"
    frozen.write_bytes(canon(tasks))
    card = dict(items=[dict(k, score_milli=1000) for k in keys] + [dict(life="unread", branch="B0", item_id="unread", score_milli=987654321)],
                other=dict(synthetic="preserved", count=73))
    if fault == "missing":
        card["items"].pop(0)
    elif fault == "duplicate":
        card["items"].append(card["items"][0])
    elif fault == "substitute":
        card["items"][1] = card["items"][0]
    raw = json.dumps(card).encode() if fault == "noncanonical" else canon(card)
    run = tmp_path / "run"
    run.mkdir()
    (run / "card.json").write_bytes(raw)
    out = tmp_path / "cut"
    label = "B.F1" if fault == "pack" else "A.F1"
    result = subprocess.run([sys.executable, "-I", str(SCRIPT), str(frozen), str(out), f"{label}={run}"],
                            capture_output=True, text=True)
    if fault:
        assert result.returncode != 0 and (result.stdout + result.stderr).strip() == label
        assert not out.exists() or not list(out.iterdir())
    else:
        assert result.returncode == 0
        assert json.loads(result.stdout) == {label: sha256(raw).hexdigest()}
        cut = json.loads((out / f"{label}.json").read_bytes())
        assert len(cut["items"]) == 50 and b"987654321" not in (out / f"{label}.json").read_bytes()
        assert canon(cut["other"]) == canon(card["other"])
        assert (out / f"{label}.json").read_bytes() == canon(cut)
