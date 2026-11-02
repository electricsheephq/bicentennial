"""Exercise the release comparison command on synthetic published cards."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/compare_reference_t0.py"


def write_card(root, pack, score=1000, **changes):
    path = root / "pack" / pack / "card.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(system="reference_store", tier="T0", gate_verdict="PASS",
        run_status="COMPLETE", aggregates=[dict(stage="remember", track="Keep", score_milli=score)]) | changes))
    return path


@pytest.mark.parametrize("change", ["equal", "score", "missing_old", "missing_new", "aggregate", "verdict", "status"])
def test_comparison(tmp_path, change):
    old, new = tmp_path / "old", tmp_path / "new"
    for root in (old, new):
        write_card(root, "one")
        write_card(root, "G2/Keep/two@1/s3-d1-none/1")
    if change == "score":
        write_card(new, "G2/Keep/two@1/s3-d1-none/1", -1000)
    elif change.startswith("missing_"):
        root = old if change == "missing_old" else new
        shutil.rmtree(root / "pack/G2")
    elif change == "aggregate":
        write_card(new, "G2/Keep/two@1/s3-d1-none/1", aggregates=[])
    elif change == "verdict":
        write_card(new, "G2/Keep/two@1/s3-d1-none/1", gate_verdict="FAIL")
    elif change == "status":
        write_card(new, "G2/Keep/two@1/s3-d1-none/1", run_status="BLOCKED")
    result = subprocess.run([sys.executable, str(SCRIPT), str(old), str(new)],
                            capture_output=True, text=True)
    assert result.returncode == (0 if change == "equal" else 1), result.stderr
    assert result.stderr == ""
    if change == "equal":
        assert result.stdout == ""
    else:
        assert "pack/G2/Keep/two@1/s3-d1-none/1" in result.stdout
        assert "pack/one" not in result.stdout
        assert dict(score="/aggregates/remember/Keep: 1000 -> -1000", verdict='/gate_verdict: "PASS" -> "FAIL"',
                    status='/run_status: "COMPLETE" -> "BLOCKED"').get(change, "<missing>") in result.stdout


def test_lists_every_pack_change(tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    for index in range(86):
        pack = f"G2/Keep/fixture@1/s3-d1-none/{index}"
        write_card(old, pack)
        write_card(new, pack, -1000)
    result = subprocess.run([sys.executable, str(SCRIPT), str(old), str(new)],
                            capture_output=True, text=True)
    assert result.returncode == 1, result.stderr
    assert len(result.stdout.splitlines()) == 86
    for index in range(86):
        assert f"/{index}/aggregates/remember/Keep: 1000 -> -1000\n" in result.stdout


@pytest.mark.parametrize("invalid", ["absent", "empty", "missing_card", "json", "card", "system", "duplicate",
                                     "aggregates_dict", "aggregates_str", "verdict", "verdict_value", "status_value",
                                     "score_range", "stage_value", "track_value", "row_extra", "row_missing",
                                     "row_str"])
def test_unreadable(tmp_path, invalid):
    old, new = tmp_path / "old", tmp_path / "new"
    write_card(old, "one")
    if invalid == "empty":
        (new / "pack").mkdir(parents=True)
    elif invalid == "missing_card":
        write_card(new, "one").unlink()
    elif invalid in ("json", "card"):
        write_card(new, "one").write_text("{" if invalid == "json" else "{}")
    elif invalid == "system":
        write_card(new, "one", system="other")
    elif invalid == "duplicate":
        row = dict(stage="remember", track="Keep", score_milli=1000)
        write_card(new, "one", aggregates=[row, row])
    elif invalid.startswith("aggregates_"):
        write_card(new, "one", aggregates={} if invalid == "aggregates_dict" else "")
    elif invalid == "verdict":
        write_card(new, "one", gate_verdict=None)
    elif invalid == "verdict_value":
        write_card(new, "one", gate_verdict="MAYBE")
    elif invalid == "status_value":
        write_card(new, "one", run_status="DONE")
    elif invalid == "score_range":
        write_card(new, "one", 1001)
    elif invalid in ("stage_value", "track_value", "row_extra", "row_missing", "row_str"):
        row = dict(stage="typo" if invalid == "stage_value" else "remember",
                   track="keep" if invalid == "track_value" else "Keep", score_milli=1000)
        if invalid == "row_extra":
            row["note"] = ""
        elif invalid == "row_missing":
            del row["score_milli"]
        write_card(new, "one", aggregates=["remember/Keep" if invalid == "row_str" else row])
    result = subprocess.run([sys.executable, str(SCRIPT), str(old), str(new)],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert "unreadable T0 input:" in result.stderr
    assert result.stdout == ""
    if invalid.startswith(("stage_", "track_", "row_")):  # refused by the row check, not by a later KeyError
        assert "malformed aggregate" in result.stderr


def test_missing_schema_is_unreadable_input(tmp_path):
    # The allowed values come from the checkout's card schema; without it the script refuses (exit 2), never exit 1.
    script = tmp_path / "kit" / "scripts" / SCRIPT.name
    script.parent.mkdir(parents=True)
    shutil.copy(SCRIPT, script)
    old, new = tmp_path / "old", tmp_path / "new"
    write_card(old, "one")
    write_card(new, "one")
    result = subprocess.run([sys.executable, str(script), str(old), str(new)], capture_output=True, text=True)
    assert result.returncode == 2
    assert "unreadable T0 input:" in result.stderr and "card_ring0.schema.json" in result.stderr
    assert result.stdout == ""
