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
    path.write_text(json.dumps(dict(system="reference_store", tier="T0", aggregates=[
        dict(stage="remember", track="Keep", score_milli=score)]) | changes))
    return path


@pytest.mark.parametrize("change", ["equal", "score", "missing_old", "missing_new", "aggregate"])
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
    result = subprocess.run([sys.executable, str(SCRIPT), str(old), str(new)],
                            capture_output=True, text=True)
    assert result.returncode == (0 if change == "equal" else 1), result.stderr
    assert result.stderr == ""
    if change == "equal":
        assert result.stdout == ""
    else:
        assert "pack/G2/Keep/two@1/s3-d1-none/1" in result.stdout
        assert "pack/one" not in result.stdout
        assert "<missing>" in result.stdout if change != "score" else "1000 -> -1000" in result.stdout


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
        assert f"/{index}/remember/Keep: 1000 -> -1000\n" in result.stdout


@pytest.mark.parametrize("invalid", ["absent", "empty", "missing_card", "json", "card", "system", "duplicate"])
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
    result = subprocess.run([sys.executable, str(SCRIPT), str(old), str(new)],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert "unreadable T0 input:" in result.stderr
    assert result.stdout == ""
