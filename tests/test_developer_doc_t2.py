"""Keep the T2 guide aligned with parser flags, refusal vocabulary and outputs."""

import ast
import re
import runpy
import shlex
import sys
from pathlib import Path

import pytest

from bicentennial import cli
from bicentennial.runner.units import T2_ONLY_REFUSALS

REPO = Path(__file__).resolve().parents[1]
LITE = runpy.run_path(str(REPO / "tests/test_developer_doc_t2lite.py"))
SHARED = LITE["SHARED"]
# The runner fixtures use sibling imports, just as their ordinary pytest collection does.
sys.path.insert(0, str(REPO / "tests/runner"))
try:
    RUNNER = runpy.run_path(str(REPO / "tests/runner/test_t2.py"))
finally:
    sys.path.pop(0)
scenario, live_settings, t2_scenario = (RUNNER[k] for k in ("scenario", "live_settings", "t2_scenario"))
GUIDE = REPO / "docs/developers/t2.md"

# Only the vocabulary introduced by T2-lite's reference and rerun flags is removed.
LITE_ONLY = {
    "<field>", "aa_of:<field>", "aa_of_items", "aa_prime:<field>", "aa_prime:flag",
    "aa_prime:no_card", "aa_prime:no_outcomes", "aa_prime_items", "baseline_invalid",
    "baseline_items", "baseline_unreadable", "invalid_card:<side>", "invalid_card:aa_of",
    "invalid_card:aa_prime", "items:<side>", "only", "rerun_arguments",
}


def _code_refusals():
    codes = LITE["_code_refusals"]()
    assert LITE_ONLY <= codes
    codes -= LITE_ONLY
    tree = ast.parse((REPO / "src/bicentennial/runner/t2.py").read_text())
    for call in LITE["_calls"](tree, "T1Refused"):
        if isinstance(call.args[0], ast.Constant):
            codes.add(call.args[0].value)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "code" for t in node.targets):
            codes.update(LITE["_mapped_literals"](node.value))
        if isinstance(node, ast.keyword) and node.arg == "code" and isinstance(node.value, ast.Constant):
            codes.add(node.value.value)
    kept = ast.parse((REPO / "src/bicentennial/runner/kept.py").read_text())
    codes.update(c.args[0].value for c in LITE["_calls"](kept, "KeptRefused"))
    return codes | T2_ONLY_REFUSALS


def test_doc_commands_exist(monkeypatch, capsys):
    text = GUIDE.read_text()
    flags = [s.split()[0] for s in re.findall(r"`([^`\n]+)`", text) if s.startswith("--")]
    SHARED["_flags_in_help"](cli.main, "t2", flags, capsys)
    seen = []
    monkeypatch.setattr(cli, "reexec_niced", lambda argv: None)
    monkeypatch.setattr(cli, "run_t2", lambda **kw: seen.append(kw) or 0)
    for line in SHARED["_shell_lines"](text):
        tokens = shlex.split(line)
        if tokens[:2] == ["bicentennial", "t2"]:
            assert cli.main(tokens[1:]) == 0
    assert len(seen) == 1


def test_doc_codes():
    table = GUIDE.read_text().split("| Code | Cause |\n|---|---|\n", 1)[1].split("\n\n", 1)[0]
    rows = re.findall(r"^\| `([^`]+)` \|", table, re.MULTILINE)
    assert len(rows) == len(set(rows))
    assert set(rows) == _code_refusals()


@pytest.mark.parametrize("mode", [None, "credential"])
def test_doc_outputs(t2_scenario, mode):
    s = t2_scenario
    s.mode = mode
    assert s.invoke() == (0 if mode is None else 3)
    section = "Complete" if mode is None else "Credential stop"
    table = GUIDE.read_text().split(f"### {section}\n", 1)[1].strip().split("\n\n", 1)[0]
    listed = set(re.findall(r"^\| `([^`]+)` \|", table, re.MULTILINE))
    actual = set()
    for p in s.out.rglob("*"):
        if not p.is_file():
            continue
        parts = p.relative_to(s.out).parts
        if parts[0] == "kept" and parts[1] != "index.json":
            actual.add("kept/<life>/<branch>/<item_id>/")
        else:
            actual.add(re.sub(r"/(t1-g[12])/B[01]/", "/<life>/<branch>/", "/".join(parts)))
    assert listed == actual


def test_doc_public_text():
    paths = runpy.run_path(str(REPO / "scripts/public_check.py"))["PATHS"]
    assert not paths.search(GUIDE.read_text())
    assert "ci-block" not in GUIDE.read_text()


def test_doc_arm_time_rule():
    text = GUIDE.read_text()
    assert all(name in text for name in ("pre_probe_ms", "keep_ms", "floor_replay_ms"))
    assert "admission order (largest predicted time first, ties in card order)" in text
    assert "no-memory floor counts in no arm's time" in text
